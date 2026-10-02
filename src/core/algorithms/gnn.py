"""GNN rerank: treat the feed as a graph, run Personalized PageRank over it.

Builds a k-NN similarity graph from per-video embeddings (cosine similarity of the
vector in :mod:`_util`), adds explicit edges for "same uploader" and "same category"
(the structural signals the brief asks for), then propagates preference from the
videos you already liked (here, the top-scored items by the baseline model, standing
in for the user's click history) using Personalized PageRank. The resulting stationary
distribution is the new ranking score.

Why a GNN-style PPR and not just k-means: the brief explicitly wants node embeddings
+ a similarity graph + iterative propagation with a convergence check, which is exactly
PPR on a similarity graph.
"""

from typing import Any, Dict, List, Tuple

from . import _util
from ._util import (algo_log, build_embeddings, cosine, scale_to_100)

K = 8                 # neighbours per node (k in k-NN)
ALPHA = 0.85          # PPR teleport probability
MAX_ITER = 100
TOL = 1e-6


def _build_graph(full: List[List[float]], cards: List[Any]) -> List[List[float]]:
    """Return a column-normalised (stochastic) adjacency matrix of edge weights."""
    n = len(full)
    # raw weighted edges
    raw: List[Dict[int, float]] = [{} for _ in range(n)]
    k = min(K, n - 1) if n > 1 else 0
    for i in range(n):
        if k > 0:
            sims = [(j, cosine(full[i], full[j])) for j in range(n) if j != i]
            sims.sort(key=lambda t: -t[1])
            for j, s in sims[:k]:
                if s > 0:
                    raw[i][j] = max(s, 0.05)   # keep a sliver so the graph is connected
        # structural edges: same uploader / same coarse category
        fi = cards[i].features
        for j in range(n):
            if j == i:
                continue
            fj = cards[j].features
            if fi.mid and fi.mid == fj.mid:
                raw[i][j] = raw[i].get(j, 0.0) + 0.6
            if fi.category and fi.category == fj.category:
                raw[i][j] = raw[i].get(j, 0.0) + 0.2

    # symmetrise + column-normalise so each column sums to 1 (outgoing stochastic)
    w: List[List[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j, v in raw[i].items():
            w[i][j] += v
            w[j][i] += v
    col_sum = [sum(w[r][c] for r in range(n)) for c in range(n)]
    M = [[0.0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            M[r][c] = w[r][c] / col_sum[c] if col_sum[c] > 1e-12 else 0.0
    return M


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    n = len(cards)
    if n <= 1:
        return list(cards)

    full, _ = build_embeddings(cards)
    M = _build_graph(full, cards)

    # seed vector: top ~20% by baseline score = "videos you already liked"
    order = sorted(range(n), key=lambda i: -cards[i].final)
    n_seeds = max(1, n // 5)
    seeds = set(order[:n_seeds])
    p = [1.0 / n_seeds if i in seeds else 0.0 for i in range(n)]

    # The video the user is currently watching is the strongest "liked" signal we
    # have - if it is in this feed, give it a guaranteed, dominant teleport weight
    # so its neighbourhood (same UP / category / topic) propagates to the top.
    playing_idx = None
    playing = getattr(ctx, "playing", None)
    if playing is not None:
        for i in range(n):
            if cards[i].features.bvid == playing.bvid:
                playing_idx = i
                break
    if playing_idx is not None:
        seeds.add(playing_idx)
        p[playing_idx] = max(p[playing_idx], 0.5)
        s = sum(p) or 1.0
        p = [x / s for x in p]
        algo_log("[gnn] seed+playing %s" % playing.bvid, v=5)

    algo_log("[gnn] seeds=%d/%d  K=%d  alpha=%.2f" % (len(seeds), n, K, ALPHA), v=5)

    # power iteration: p = (1-alpha)*p0 + alpha * M p
    p0 = list(p)
    it = 0
    for it in range(MAX_ITER):
        nxt = [0.0] * n
        for r in range(n):
            for c in range(n):
                nxt[r] += M[r][c] * p[c]
        nxt = [(1 - ALPHA) * p0[r] + ALPHA * nxt[r] for r in range(n)]
        diff = sum(abs(nxt[r] - p[r]) for r in range(n))
        p = nxt
        if diff < TOL:
            break
    algo_log("[gnn] PPR converged in %d iters (L1=%g)" % (it + 1, diff), v=6)

    final = scale_to_100(p)
    for i in range(n):
        cards[i].final = round(final[i], 2)
        cards[i].detail.setdefault("algo", {})["ppr"] = round(p[i], 5)

    ranked = sorted(range(n), key=lambda i: -p[i])
    if _util._DEBUG >= 7:
        top = ", ".join("%s(%.3f)" % (cards[i].features.title[:10], p[i])
                        for i in ranked[:5])
        algo_log("[gnn] top PPR: " + top, v=7)
    return [cards[i] for i in ranked]
