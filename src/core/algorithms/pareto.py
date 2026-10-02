"""Multi-objective Pareto rerank via NSGA-II (policy weight selection).

The eight dimensions can be grouped into four competing goals: relevance, diversity,
freshness and quality. A single weighted sum assumes they trade off linearly, which
they do not - pushing relevance often crushes diversity. So instead of picking one
weighting by hand, we evolve a *population of weightings* with NSGA-II:

  * each individual is a 4-vector of goal weights (relevance, diversity, freshness,
    quality) summing to 1;
  * decoding a weighting ranks the feed by the weighted objective sum and we read off
    the objective vector of the items it places at the top (the "fitness");
  * NSGA-II sorts the population by non-domination + crowding distance and evolves it.

After the run we pick the most *balanced* individual on the final front (max-min over
the normalised objectives - the knee), and use its ranking. This is the "choose a
solution that balances all goals" step from the brief, and it is computed offline per
feed (the method is too heavy for true real-time, as the brief notes).
"""

import random
from typing import Any, List, Tuple

from . import _util
from ._util import algo_log, scale_to_100

POPSIZE = 24
GENERATIONS = 20
TOP_K = 12            # objectives measured on the top-K items a policy places
MUTATE = 0.3


def _objectives(cards: List[Any]) -> List[List[float]]:
    """Per-item objective vector [relevance, diversity, freshness, quality]."""
    objs = []
    for c in cards:
        rel = max(0.0, min(1.0, c.final / 100.0))
        div = c.dims.get("diversity", 0.5)
        fresh = c.dims.get("recency", 0.5)
        qual = (c.dims.get("engagement", 0.5) + c.dims.get("authority", 0.5)) / 2.0
        objs.append([rel, div, fresh, qual])
    return objs


def _decode(w: List[float], objs: List[List[float]]) -> List[int]:
    n = len(objs)
    scored = [(sum(w[k] * objs[i][k] for k in range(4)), i) for i in range(n)]
    scored.sort(key=lambda t: -t[0])
    return [i for _, i in scored]


def _fitness(order: List[int], objs: List[List[float]]) -> List[float]:
    k = min(TOP_K, len(order))
    acc = [0.0, 0.0, 0.0, 0.0]
    for idx in order[:k]:
        for j in range(4):
            acc[j] += objs[idx][j]
    return [a / k for a in acc]


def _dominates(a: List[float], b: List[float]) -> bool:
    better = any(a[j] > b[j] for j in range(4))
    worse = any(a[j] < b[j] for j in range(4))
    return better and not worse


def _non_dominated_sort(fits: List[List[float]]) -> List[List[int]]:
    """Standard fast non-dominated sort (maximising all four objectives)."""
    n = len(fits)
    S = [[] for _ in range(n)]
    dominated_by = [0] * n
    fronts: List[List[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if _dominates(fits[p], fits[q]):
                S[p].append(q)
            elif _dominates(fits[q], fits[p]):
                dominated_by[p] += 1
        if dominated_by[p] == 0:
            fronts[0].append(p)
    fi = 0
    while fronts[fi]:
        nxt: List[int] = []
        for p in fronts[fi]:
            for q in S[p]:
                dominated_by[q] -= 1
                if dominated_by[q] == 0:
                    nxt.append(q)
        fi += 1
        fronts.append(nxt)
    return [f for f in fronts if f]


def _crowding(fits: List[List[float]], front: List[int]) -> List[float]:
    m = len(front)
    cd = [0.0] * m
    for obj in range(4):
        order = sorted(range(m), key=lambda r: fits[front[r]][obj])
        cd[order[0]] = cd[order[-1]] = float("inf")
        lo = fits[front[order[0]]][obj]
        hi = fits[front[order[-1]]][obj]
        rng = hi - lo or 1.0
        for r in range(1, m - 1):
            cd[order[r]] += (fits[front[order[r + 1]]][obj]
                             - fits[front[order[r - 1]]][obj]) / rng
    return cd


def _normalize(w: List[float]) -> List[float]:
    s = sum(w) or 1.0
    return [x / s for x in w]


def _mate(a: List[float], b: List[float]) -> List[float]:
    c = [(a[i] + b[i]) / 2.0 for i in range(4)]
    if random.random() < MUTATE:
        for i in range(4):
            c[i] += random.gauss(0, 0.15)
        c = [max(0.0, x) for x in c]
    return _normalize(c)


def rerank(cards: List[Any], ctx: Any) -> List[Any]:
    n = len(cards)
    if n == 0:
        return []
    objs = _objectives(cards)

    rng = random.Random(12345)
    pop = []
    for _ in range(POPSIZE):
        w = [rng.random() for _ in range(4)]
        pop.append(_normalize(w))

    for _ in range(GENERATIONS):
        fits = [_fitness(_decode(w, objs), objs) for w in pop]
        fronts = _non_dominated_sort(fits)
        next_pop: List[List[float]] = []
        fi = 0
        while fi < len(fronts) and len(next_pop) + len(fronts[fi]) <= POPSIZE:
            next_pop.extend(pop[i] for i in fronts[fi])
            fi += 1
        # fill the rest by crowding distance within the next front
        if len(next_pop) < POPSIZE and fi < len(fronts):
            front = fronts[fi]
            cd = _crowding(fits, front)
            order = sorted(front, key=lambda i: -cd[front.index(i)])
            for i in order:
                if len(next_pop) >= POPSIZE:
                    break
                next_pop.append(pop[i])
        # breed
        children = []
        for _ in range(POPSIZE - len(next_pop)):
            a, b = rng.choice(next_pop), rng.choice(next_pop)
            children.append(_mate(a, b))
        pop = next_pop + children

    fits = [_fitness(_decode(w, objs), objs) for w in pop]
    fronts = _non_dominated_sort(fits)
    front = fronts[0]

    # knee: most balanced individual on the front (max of the min objective)
    best = max(front, key=lambda i: min(fits[i]))
    order = _decode(pop[best], objs)

    if _util._DEBUG >= 5:
        algo_log("[pareto] front size=%d  chosen weights=%.2f/%.2f/%.2f/%.2f" % (
            len(front), pop[best][0], pop[best][1], pop[best][2], pop[best][3]), v=5)
        algo_log("[pareto] front fitness(top): " + ", ".join(
            "%.2f" % min(fits[i]) for i in front[:5]), v=6)

    # assign final scores by the chosen (balanced) weighting so downstream numbers
    # stay coherent with the ordering NSGA-II settled on
    chosen_w = pop[best]
    finals = [sum(chosen_w[k] * objs[i][k] for k in range(4)) for i in order]
    scaled = scale_to_100(finals)
    for rank_pos, i in enumerate(order):
        cards[i].final = round(scaled[rank_pos], 2)
        cards[i].detail.setdefault("algo", {})["pareto"] = round(finals[rank_pos], 4)

    return [cards[i] for i in order]
