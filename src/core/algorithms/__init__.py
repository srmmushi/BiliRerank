"""Rerank algorithms.

The active algorithm is fixed to GNN (Personalized PageRank over a similarity
graph) - there is no runtime switching anymore. The other modules in this folder
stay as a library of the algorithms that were built, but only GNN is wired in.
"""

from typing import Any, List

from .. import store
from . import gnn
from ._util import set_debug

ALGORITHM = "gnn"


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    """Run the fixed GNN algorithm; never let a ranking failure crash the feed."""
    store.add_log("info", "algo.gnn.on", v=2)
    try:
        return gnn.rerank(cards, ctx)
    except Exception as exc:
        store.add_log("error", "algo.fail", {"name": ALGORITHM, "err": str(exc)}, v=0)
        return sorted(cards, key=lambda c: -c.final)
