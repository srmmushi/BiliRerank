"""Baseline: the original eight-dimension weighted-sum ranking.

This is the default / fallback algorithm. It does not reorder - it just keeps the
score that :func:`core.algorithms.engine.score_item` already produced - so the behaviour the
user had before the algorithm switch is preserved under ``--algorithm weighted``.
"""

from typing import Any, List

# the baseline leaves the final score untouched, so the order is by that score
def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    return sorted(cards, key=lambda c: -c.final)
