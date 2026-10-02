"""Rerank algorithms.

Each algorithm takes the already-eight-dimension-scored cards (a list of
``ScoreCard``) plus the feed ``Context`` and returns them in the order it wants,
having rewritten ``card.final`` to its own ranking score. ``rerank()`` is what
:func:`core.algorithms.engine.rank` calls after scoring; it logs which algorithm
is active and falls back to the baseline on anything it does not recognise or
that raises.

Switch the active algorithm with ``--algorithm NAME`` (persisted to settings) or
:func:`set_algorithm`.
"""

from typing import Any, List

from .. import store
from . import (bandit, counterfactual, gnn, mmr, pareto, sequential, weighted)
from ._util import set_debug

REGISTRY = {
    "weighted": weighted.rerank,       # 八维加权（基线）
    "gnn": gnn.rerank,                 # 图神经网络重排 (Personalized PageRank)
    "bandit": bandit.rerank,           # 上下文老虎机 (LinUCB)
    "mmr": mmr.rerank,                 # MMR + 子模优化
    "sequential": sequential.rerank,   # 序列建模 (GRU4Rec 式)
    "pareto": pareto.rerank,           # 多目标帕累托优化 (NSGA-II)
    "counterfactual": counterfactual.rerank,  # 反事实推断 (IPS / Doubly Robust)
}
ALGORITHM_NAMES = list(REGISTRY.keys())

_current = "gnn"


def set_algorithm(name: str) -> str:
    global _current
    if name in REGISTRY:
        _current = name
    return _current


def get_algorithm() -> str:
    return _current


def reset_state() -> None:
    """Clear any cross-feed session state (bandit parameters, sequence history)."""
    try:
        bandit.reset_state()
    except Exception:
        pass
    try:
        sequential.reset_state()
    except Exception:
        pass


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    """Run the chosen algorithm; fall back to the baseline on unknown/error."""
    algo = _current
    if algo not in REGISTRY:
        store.add_log("warn", "algo.unknown.on", {"name": algo}, v=2)
        algo = "weighted"
    store.add_log("info", "algo.%s.on" % algo, v=2)
    try:
        return REGISTRY[algo](cards, ctx)
    except Exception as exc:  # never let a ranking method crash the feed
        store.add_log("error", "algo.fail", {"name": algo, "err": str(exc)}, v=0)
        return sorted(cards, key=lambda c: -c.final)
