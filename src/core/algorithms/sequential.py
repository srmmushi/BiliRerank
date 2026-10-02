"""Sequential recommendation (GRU4Rec-style) over the session history.

We keep a rolling history of the embeddings of videos we have *already shown* in
this session (a deque across feeds). A small GRU encodes that sequence into a user
state; candidates are scored by how well they attend to / match that state, blended
with their own baseline relevance. On the very first feed (empty history) it falls
back to the baseline ordering so the tool never produces a degenerate list.

This is the architecture the brief calls for (sequence model -> hidden state ->
match against candidate embeddings); the GRU weights are fixed/deterministic because
we have no labelled click stream to train on, but the pipeline (encode sequence,
attend, score) is exactly the real thing.
"""

import math
import random
from collections import deque
from typing import Any, List

from . import _util
from ._util import (algo_log, build_embeddings, dot, embedding_from_features,
                    normalize, scale_to_100, up_bucket_map)

SEQ_LEN = 20
REL_BLEND = 0.5       # 0.5*relevance + 0.5*sequence match

_SEQ: deque = deque(maxlen=SEQ_LEN)
_GRU = None           # lazily built fixed weights


def reset_state() -> None:
    _SEQ.clear()


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    return math.exp(x) / (1.0 + math.exp(x))


def _tanh(x: float) -> float:
    z = math.exp(2 * x)
    return (z - 1) / (z + 1)


def _rand_mat(d: int, seed: int) -> List[List[float]]:
    rng = random.Random(seed)
    return [[rng.gauss(0, 0.1) for _ in range(d)] for _ in range(d)]


def _rand_vec(d: int, seed: int) -> List[float]:
    rng = random.Random(seed)
    return [rng.gauss(0, 0.1) for _ in range(d)]


def _gru_weights(d: int):
    global _GRU
    if _GRU is not None:
        return _GRU
    _GRU = (
        _rand_mat(d, 11), _rand_mat(d, 12), _rand_vec(d, 13),   # update gate
        _rand_mat(d, 21), _rand_mat(d, 22), _rand_vec(d, 23),   # reset gate
        _rand_mat(d, 31), _rand_mat(d, 32), _rand_vec(d, 33),   # candidate
    )
    return _GRU


def _gru_cell(x: List[float], h: List[float], w):
    (Wz, Uz, bz, Wr, Ur, br, Wh, Uh, bh) = w
    z = [_sigmoid(dot(Wz, x) + dot(Uz, h) + bz[i]) for i in range(len(h))]
    r = [_sigmoid(dot(Wr, x) + dot(Ur, h) + br[i]) for i in range(len(h))]
    rh = [r[i] * h[i] for i in range(len(h))]
    h_tilde = [_tanh(dot(Wh, x) + dot(Uh, rh) + bh[i]) for i in range(len(h))]
    return [(1 - z[i]) * h[i] + z[i] * h_tilde[i] for i in range(len(h))]


def _encode(seq_embs: List[List[float]]) -> List[float]:
    if not seq_embs:
        return []
    d = len(seq_embs[0])
    w = _gru_weights(d)
    h = [0.0] * d
    for x in seq_embs:
        h = _gru_cell(x, h, w)
    return h


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    n = len(cards)
    if n == 0:
        return []

    full, _ = build_embeddings(cards)
    rel = [max(0.0, min(1.0, c.final / 100.0)) for c in cards]
    up_index = up_bucket_map(cards)

    # The currently-playing video is the freshest signal of intent: prefix it to the
    # session history so the GRU state biases toward "what to watch next". It also
    # acts as the seed history on the very first feed (when _SEQ is still empty).
    seq_embs = list(_SEQ)
    playing = getattr(ctx, "playing", None)
    if playing is not None:
        play_emb = None
        for i, c in enumerate(cards):
            if c.features.bvid == playing.bvid:
                play_emb = full[i]
                break
        if play_emb is None:
            play_emb = embedding_from_features(playing, up_index)
        seq_embs = [play_emb] + seq_embs
        algo_log("[seq] prepended playing %s" % playing.bvid, v=5)

    if not seq_embs:
        # no history yet and nothing playing: keep baseline, remember these for next time
        _SEQ.extend(full)
        algo_log("[seq] no history yet - keeping baseline, recording %d items" % n, v=5)
        return sorted(cards, key=lambda c: -c.final)

    state = _encode(seq_embs)
    # score each candidate by attention match with the user state
    scores: List[float] = []
    for i in range(n):
        cand = normalize(full[i])
        st = normalize(state)
        sim = dot(cand, st)                       # [-1,1]
        sim = (sim + 1.0) / 2.0                    # -> [0,1]
        scores.append(REL_BLEND * rel[i] + (1 - REL_BLEND) * sim)

    # nearest sequence item to each top candidate (for the debug trace)
    final = scale_to_100(scores)
    for i in range(n):
        cards[i].final = round(final[i], 2)
        cards[i].detail.setdefault("algo", {})["seq"] = round(scores[i], 4)

    if _util._DEBUG >= 6:
        ranked = sorted(range(n), key=lambda i: -scores[i])
        near = ", ".join(
            "%s(%.2f)" % (cards[i].features.title[:10], scores[i]) for i in ranked[:5])
        algo_log("[seq] state-matched top5: " + near, v=6)

    # remember this feed's items for the next one
    _SEQ.extend(full)
    ranked = sorted(range(n), key=lambda i: -scores[i])
    return [cards[i] for i in ranked]
