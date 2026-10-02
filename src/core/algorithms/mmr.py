"""MMR + Submodular rerank.

MMR is reimplemented as a greedy maximisation of a *submodular* objective, which is
what the brief asks for: MMR (``relevance - lambda * max_similarity``) is just one
special case, but a proper submodular facility-coverage function gives the same
intuition with a theoretical guarantee - greedy achieves at least (1 - 1/e) ≈ 63%
of the optimal set (Nemhauser 1978).

The objective is a sum of a modular relevance term and monotone submodular coverage
terms (category-group coverage, tag coverage, quality coverage, freshness coverage).
At each step we add the item with the largest *marginal gain* ``f(S∪{i}) - f(S)``.
We also compute the classic MMR ordering for comparison and log both.
"""

from collections import Counter
from typing import Any, List

from . import _util
from ._util import (algo_log, build_embeddings, cosine, playing_context, scale_to_100,
                    up_bucket_map)

LAMBDA_REL = 0.6       # weight of the (modular) relevance term
LAMBDA_DIV = 0.4       # weight of the (submodular) diversity/coverage term
W_GROUP, W_TAG, W_QUAL, W_FRESH = 0.3, 0.2, 0.25, 0.25   # weights inside the coverage
MMR_LAMBDA = 0.7       # classic MMR trade-off (relevance vs diversity)
PLAY_BONUS = 0.2       # relevance bonus for videos similar to the one playing


def _group_index(group: str) -> int:
    from . import engine
    order = ["动画番剧", "游戏", "知识科技", "生活美食", "音乐舞蹈",
             "娱乐鬼畜", "资讯", "动物萌宠", "时尚运动"]
    try:
        g = engine.category_group(group)
    except Exception:
        g = "其他"
    return order.index(g) if g in order else len(order)


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    n = len(cards)
    if n == 0:
        return []

    full, _ = build_embeddings(cards)
    up_index = up_bucket_map(cards)
    rel = [max(0.0, min(1.0, c.final / 100.0)) for c in cards]

    # reward videos similar to what the user is currently watching (blended into rel)
    play_emb, _ = playing_context(cards, full, up_index, ctx)
    if play_emb is not None:
        for i in range(n):
            rel[i] += PLAY_BONUS * max(0.0, cosine(full[i], play_emb))
        algo_log("[mmr] playing similarity bonus applied", v=5)

    qual = [c.dims.get("authority", 0.5) for c in cards]
    fresh = [c.dims.get("recency", 0.5) for c in cards]
    groups = [_group_index(c.features.category) for c in cards]

    # tag facets: top-K frequent tags across the feed
    tag_counter: Counter = Counter()
    for c in cards:
        for t in (c.features.tags or []):
            tag_counter[t] += 1
    top_tags = [t for t, _ in tag_counter.most_common(8)]
    tag_index = {t: i for i, t in enumerate(top_tags)}
    item_tags = []
    for c in cards:
        s = set()
        for t in (c.features.tags or []):
            if t in tag_index:
                s.add(tag_index[t])
        item_tags.append(s)

    # --- submodular greedy -----------------------------------------------------
    G = len(set(groups))            # number of distinct group facets present
    T = len(top_tags)
    covered_groups = set()
    covered_tags = set()
    max_qual = 0.0
    max_fresh = 0.0
    selected: List[int] = []
    remaining = set(range(n))
    gains: List[float] = []

    def marginal(i: int) -> float:
        new_g = sum(1 for g in (groups[i],) if g not in covered_groups and g < G)
        new_t = sum(1 for t in item_tags[i] if t not in covered_tags)
        dq = max(0.0, qual[i] - max_qual)
        df = max(0.0, fresh[i] - max_fresh)
        cov = (W_GROUP * new_g + W_TAG * new_t
               + W_QUAL * dq + W_FRESH * df)
        return LAMBDA_REL * rel[i] + LAMBDA_DIV * cov

    while remaining:
        best = max(remaining, key=marginal)
        g = marginal(best)
        gains.append(g)
        for grp in (groups[best],):
            if grp < G:
                covered_groups.add(grp)
        covered_tags |= item_tags[best]
        max_qual = max(max_qual, qual[best])
        max_fresh = max(max_fresh, fresh[best])
        selected.append(best)
        remaining.discard(best)

    # --- classic MMR for comparison -------------------------------------------
    mmr_order: List[int] = []
    rem2 = set(range(n))
    while rem2:
        def mmr_score(i: int) -> float:
            if not mmr_order:
                return MMR_LAMBDA * rel[i]
            sim = max(cosine(full[i], full[j]) for j in mmr_order)
            return MMR_LAMBDA * rel[i] - (1 - MMR_LAMBDA) * max(0.0, sim)
        best = max(rem2, key=mmr_score)
        mmr_order.append(best)
        rem2.discard(best)

    # blend the selection score (relevance already inside) into the final score
    final = scale_to_100(gains)
    for rank_pos, i in enumerate(selected):
        cards[i].final = round(final[rank_pos], 2)
        cards[i].detail.setdefault("algo", {})["mmr_gain"] = round(gains[rank_pos], 4)

    if _util._DEBUG >= 5:
        sub = ", ".join(cards[i].features.title[:10] for i in selected[:5])
        mmr = ", ".join(cards[i].features.title[:10] for i in mmr_order[:5])
        algo_log("[submodular] greedy top5: " + sub, v=5)
        algo_log("[mmr]       top5: " + mmr, v=5)

    return [cards[i] for i in selected]
