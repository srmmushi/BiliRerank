"""Contextual Bandit rerank via LinUCB.

LinUCB models each *arm* (here: a coarse content bucket) with a linear payoff
``r = x^T theta_a + noise`` and maintains a running confidence ellipsoid
``A_a = I + sum x x^T, b_a = sum r x``. For every candidate we compute the
Upper-Confidence-Bound score ``x^T A_a^-1 b_a + alpha * sqrt(x^T A_a^-1 x)`` and
rank by it - this balances *exploitation* (arms that paid off) with *exploration*
(arms whose estimate is still uncertain).

We have no live click stream, so the "reward" for a candidate is its baseline
score (a stand-in for "the user would have engaged"), and we warm-start each arm
with the baseline statistics so the first ranking is sensible rather than random.
The model then keeps updating across feeds (session state below), which is exactly
how online bandits adapt as preferences drift.
"""

import math
from typing import Any, Dict, List

from . import _util
from ._util import (algo_log, build_embeddings, dot, mat_add, mat_identity,
                    mat_inverse, mat_vec, outer, playing_context, scale_to_100)

ALPHA = 1.5          # exploration strength
PRIOR = 2.0          # ridge added to A (regularisation)
PLAY_BIAS = 2.0      # extra prior weight given to the category of the video playing
GROUP_ORDER = ["动画番剧", "游戏", "知识科技", "生活美食", "音乐舞蹈",
               "娱乐鬼畜", "资讯", "动物萌宠", "时尚运动", "其他"]
N_ARMS = len(GROUP_ORDER)

_state: Dict[str, Any] = {"init": False, "A": None, "b": None}


def reset_state() -> None:
    """Drop the learned bandit parameters (used on a fresh session)."""
    _state["init"] = False
    _state["A"] = None
    _state["b"] = None


def _group_index(group: str) -> int:
    from . import engine
    try:
        g = engine.category_group(group)
    except Exception:
        g = "其他"
    return GROUP_ORDER.index(g) if g in GROUP_ORDER else N_ARMS - 1


def _ensure_state(d: int) -> None:
    if _state["init"]:
        return
    _state["A"] = [mat_identity(d, PRIOR) for _ in range(N_ARMS)]
    _state["b"] = [[0.0] * d for _ in range(N_ARMS)]
    _state["init"] = True


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    n = len(cards)
    if n == 0:
        return []

    _, ctx_vecs = build_embeddings(cards)
    d = len(ctx_vecs[0])
    _ensure_state(d)
    A = _state["A"]
    b = _state["b"]

    # warm-start: seed each arm with the baseline relevance (reward proxy = final/100)
    for i, c in enumerate(cards):
        arm = _group_index(c.features.category)
        x = ctx_vecs[i]
        r = max(0.0, min(1.0, c.final / 100.0))
        A[arm] = mat_add(A[arm], outer(x, x))
        b[arm] = [b[arm][k] + r * x[k] for k in range(d)]

    # The currently-playing video is a strong, fresh reward signal: bias its content
    # bucket (arm) so the bandit favours "more like what you are watching".
    play_emb, play_idx = playing_context(cards, ctx_vecs, {}, ctx)
    if play_emb is not None:
        xp = ctx_vecs[play_idx] if play_idx is not None else play_emb[:d]
        parm = _group_index(cards[play_idx].features.category) if play_idx is not None \
            else _group_index(getattr(ctx.playing, "category", ""))
        A[parm] = mat_add(A[parm], outer(xp, xp))
        b[parm] = [b[parm][k] + PLAY_BIAS * xp[k] for k in range(d)]
        algo_log("[bandit] playing arm bias -> %s" % GROUP_ORDER[parm], v=5)

    # inverse + theta per arm
    Ainv = [mat_inverse(A[a]) for a in range(N_ARMS)]
    theta = [mat_vec(Ainv[a], b[a]) for a in range(N_ARMS)]

    ucb: List[float] = []
    for i, c in enumerate(cards):
        arm = _group_index(c.features.category)
        x = ctx_vecs[i]
        xAinv = mat_vec(Ainv[arm], x)
        mean = dot(x, theta[arm])
        unc = math.sqrt(max(dot(x, xAinv), 0.0))
        ucb.append(mean + ALPHA * unc)

    final = scale_to_100(ucb)
    for i in range(n):
        cards[i].final = round(final[i], 2)
        cards[i].detail.setdefault("algo", {})["ucb"] = round(ucb[i], 4)

    if _util._DEBUG >= 5:
        chosen = [GROUP_ORDER[_group_index(c.features.category)] for c in cards]
        from collections import Counter
        dist = Counter(chosen)
        algo_log("[bandit] arm counts: " + ", ".join(
            "%s=%d" % (k, dist[k]) for k in GROUP_ORDER if dist[k]), v=5)

    ranked = sorted(range(n), key=lambda i: -ucb[i])
    return [cards[i] for i in ranked]
