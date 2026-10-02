"""Counterfactual rerank (IPS + Doubly Robust correction).

The feed we see is the result of the *original* (B站) ranking, so the click/engage
signal it carries is biased by position: videos shown near the top were seen by far
more people, so they accumulate more clicks regardless of quality. Counterfactual
methods correct that selection bias.

We model the *propensity* ``P(shown at position i)`` as a position-driven softmax
(higher positions -> higher propensity), treat each video's baseline score as the
(observed, biased) reward ``r``, and a content-quality model ``mu`` (independent of
position) as the prediction. Then:

  * IPS estimate          :  r / p            (inverse-propensity weighting)
  * Doubly Robust estimate:  mu + (r - mu) / p  (model + residual correction)

Both are clipped for stability and the feed is reranked by the de-biased score, which
pulls *under-shown, high-content* videos up and cools off *over-shown* ones. With a
real click stream you would plug the observed click in for ``r`` and a trained
propensity for ``p``; the structure is identical.
"""

import math
from typing import Any, List

from . import _util
from ._util import (algo_log, build_embeddings, cosine, playing_context, softmax,
                    up_bucket_map)

TAU = 0.34           # position temperature (fraction of n); smaller = sharper bias
P_MIN = 0.05         # clip propensity floor
CLIP = 2.0           # clip the IPS / DR correction term
PLAY_BONUS = 0.2     # quality-model bonus for videos similar to the one playing


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    n = len(cards)
    if n == 0:
        return []

    # original feed position == current index (rank() scores in feed order)
    pos = list(range(n))
    tau = max(1.0, TAU * n)
    pos_scores = [math.exp(-p / tau) for p in pos]
    p = softmax(pos_scores)
    p = [max(P_MIN, x) for x in p]            # propensity floor

    r = [max(0.0, min(1.0, c.final / 100.0)) for c in cards]
    # content-quality model: position-independent (engagement/authority/title/interest)
    mu = []
    for c in cards:
        d = c.dims
        mu.append((d.get("engagement", 0.5) + d.get("authority", 0.5)
                   + d.get("title", 0.5) + d.get("interest", 0.5)) / 4.0)

    # The video currently playing is itself a strong relevance cue: nudge the quality
    # model up for videos that resemble it (this is the de-biased estimate mu, so the
    # residual correction then flows through Doubly Robust as usual).
    full, _ = build_embeddings(cards)
    up_index = up_bucket_map(cards)
    play_emb, _ = playing_context(cards, full, up_index, ctx)
    if play_emb is not None:
        for i in range(n):
            mu[i] += PLAY_BONUS * max(0.0, cosine(full[i], play_emb))
        algo_log("[cf] playing similarity bonus applied", v=5)

    dr: List[float] = []
    ips: List[float] = []
    for i in range(n):
        inv = 1.0 / p[i]
        ips_i = r[i] * inv
        dr_i = mu[i] + max(-CLIP, min(CLIP, (r[i] - mu[i]) * inv))
        ips.append(ips_i)
        dr.append(dr_i)

    # min-max normalise the DR score into [0,100] so the report stays readable
    lo, hi = min(dr), max(dr)
    span = (hi - lo) or 1.0
    finals = [100.0 * (x - lo) / span for x in dr]

    # original -> new rank mapping for the debug trace
    new_order = sorted(range(n), key=lambda i: -dr[i])
    if _util._DEBUG >= 5:
        moved = []
        for new_pos, i in enumerate(new_order[:5]):
            if abs(i - new_pos) >= 2:
                moved.append("%s:%d->%d" % (cards[i].features.title[:8], i, new_pos))
        algo_log("[cf] DR rerank: " + (", ".join(moved) if moved else "stable"), v=5)
        algo_log("[cf] mean propensity=%.3f  max=%.3f" % (sum(p) / n, max(p)), v=6)

    for i in range(n):
        cards[i].final = round(finals[i], 2)
        cards[i].detail.setdefault("algo", {})["dr"] = round(dr[i], 4)
        cards[i].detail["algo"]["ips"] = round(ips[i], 4)

    return [cards[i] for i in new_order]
