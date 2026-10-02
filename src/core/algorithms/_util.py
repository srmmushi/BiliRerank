"""Shared math + feature-embedding helpers for the rerank algorithms.

Everything here is pure Python (no numpy) so the tool keeps its tiny dependency
footprint. The embedding is a fixed-length vector built from the eight dimension
scores plus a coarse category bucket, a hashed bag-of-words of the title/tags
(cheap "semantic" signal), and an uploader bucket. It is deliberately small and
deterministic - enough to drive cosine similarity, graphs, attention and linear
bandits without any external model.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any, Dict, List, Tuple

# layout of the embedding vector
DIM_SCORES = 8        # the eight [0,1] dimension scores
GROUP_BUCKETS = 9     # coarse category buckets
HASH_DIM = 32         # hashed bag-of-words of title + tags
UP_BUCKETS = 12       # top uploaders + one "other" bucket
EMBED_DIM = DIM_SCORES + GROUP_BUCKETS + HASH_DIM + UP_BUCKETS
# the context vector used by the linear bandit / pareto (stable + interpretable)
CTX_DIM = DIM_SCORES + GROUP_BUCKETS


# --------------------------------------------------------------------------- #
# scalar / vector math
# --------------------------------------------------------------------------- #
def dot(a: List[float], b: List[float]) -> float:
    s = 0.0
    for x, y in zip(a, b):
        s += x * y
    return s


def norm(v: List[float]) -> float:
    return math.sqrt(dot(v, v))


def normalize(v: List[float]) -> List[float]:
    n = norm(v)
    if n <= 1e-12:
        return [0.0] * len(v)
    return [x / n for x in v]


def cosine(a: List[float], b: List[float]) -> float:
    na, nb = norm(a), norm(b)
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot(a, b) / (na * nb)


def softmax(values: List[float], temperature: float = 1.0) -> List[float]:
    if not values:
        return []
    m = max(values)
    exps = [math.exp((v - m) / max(temperature, 1e-6)) for v in values]
    s = sum(exps) or 1.0
    return [e / s for e in exps]


def mat_vec(m: List[List[float]], v: List[float]) -> List[float]:
    return [dot(row, v) for row in m]


def mat_identity(d: int, scale: float = 1.0) -> List[List[float]]:
    return [[scale if i == j else 0.0 for j in range(d)] for i in range(d)]


def outer(a: List[float], b: List[float]) -> List[List[float]]:
    return [[a[i] * b[j] for j in range(len(b))] for i in range(len(a))]


def mat_add(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    return [[a[i][j] + b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def mat_inverse(m: List[List[float]]) -> List[List[float]]:
    """Gaussian-elimination inverse of a small square matrix (d <= ~32)."""
    n = len(m)
    # augment with identity
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        # partial pivot
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            continue  # singular-ish; leave row
        aug[col], aug[pivot] = aug[pivot], aug[col]
        piv = aug[col][col]
        aug[col] = [x / piv for x in aug[col]]
        for r in range(n):
            if r != col and aug[r][col] != 0.0:
                factor = aug[r][col]
                aug[r] = [aug[r][k] - factor * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


# --------------------------------------------------------------------------- #
# embeddings
# --------------------------------------------------------------------------- #
def _hash_token(token: str, buckets: int) -> int:
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "little") % buckets


def _tokenize(text: str) -> List[str]:
    """Char-level for CJK, word-level for latin; good enough for similarity."""
    tokens: List[str] = []
    buf = ""
    for ch in text:
        if "一" <= ch <= "鿿":
            if buf:
                tokens.append(buf.lower())
                buf = ""
            tokens.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            if buf:
                tokens.append(buf.lower())
                buf = ""
    if buf:
        tokens.append(buf.lower())
    return tokens


def _group_index(group: str) -> int:
    """Lazily use engine.category_group so there is no import cycle at load time."""
    from . import engine
    order = ["动画番剧", "游戏", "知识科技", "生活美食", "音乐舞蹈",
             "娱乐鬼畜", "资讯", "动物萌宠", "时尚运动"]
    try:
        g = engine.category_group(group)
    except Exception:
        g = "其他"
    return order.index(g) if g in order else len(order)  # 9 -> "其他"


def build_embedding(card: Any, up_index: Dict[Any, int]) -> List[float]:
    """Build the fixed-layout embedding for one scored card."""
    f = card.features
    d = card.dims
    vec: List[float] = [0.0] * EMBED_DIM

    # 1) the eight dimension scores (already in [0,1])
    for i, name in enumerate((
        "engagement", "duration", "recency", "authority",
        "title", "momentum", "interest", "diversity",
    )):
        vec[i] = float(d.get(name, 0.5))

    # 2) coarse category bucket (one-hot)
    gi = _group_index(f.category)
    if 0 <= gi < GROUP_BUCKETS:
        vec[DIM_SCORES + gi] = 1.0

    # 3) hashed bag-of-words of title + tags (semantic-ish)
    base = DIM_SCORES + GROUP_BUCKETS
    for tok in _tokenize(f.title):
        vec[base + _hash_token(tok, HASH_DIM)] += 1.0
    for tag in (f.tags or []):
        for tok in _tokenize(tag):
            vec[base + _hash_token(tok, HASH_DIM)] += 1.0
    # L2-normalise the hash block so title length does not dominate
    block = vec[base:base + HASH_DIM]
    nb = norm(block)
    if nb > 1e-12:
        for k in range(HASH_DIM):
            vec[base + k] /= nb

    # 4) uploader bucket (one-hot over the top uploaders in the feed)
    ub = DIM_SCORES + GROUP_BUCKETS + HASH_DIM
    idx = up_index.get(f.mid, UP_BUCKETS - 1)
    if 0 <= idx < UP_BUCKETS:
        vec[ub + idx] = 1.0
    return vec


def build_embeddings(cards: List[Any]) -> Tuple[List[List[float]], List[List[float]]]:
    """Return (full_embeddings, context_vectors) for every card, plus the up map."""
    # rank uploaders by frequency so the most common ones get their own bucket
    counts: Counter = Counter(c.features.mid for c in cards)
    top_ups = [mid for mid, _ in counts.most_common(UP_BUCKETS - 1)]
    up_index = {mid: i for i, mid in enumerate(top_ups)}
    full = [build_embedding(c, up_index) for c in cards]
    ctx = [vec[:CTX_DIM] for vec in full]
    return full, ctx


def context_vector(card: Any, up_index: Dict[Any, int]) -> List[float]:
    return build_embedding(card, up_index)[:CTX_DIM]


def embedding_from_features(features: Any, up_index: Dict[Any, int]) -> List[float]:
    """Build an embedding from a bare Features object (the currently-playing video
    is not a scored card, so its 8 dimension scores default to 0.5)."""
    class _Stub:
        pass
    s = _Stub()
    s.features = features
    s.dims = {}
    return build_embedding(s, up_index)


def playing_context(cards: List[Any], full: List[List[float]],
                    up_index: Dict[Any, int], ctx: Any):
    """Return ``(embedding, index_in_cards)`` for the currently-playing video, or
    ``(None, None)`` when none is known. The embedding comes from the card when the
    video is in this feed, else is reconstructed from its bare Features."""
    playing = getattr(ctx, "playing", None)
    if playing is None:
        return None, None
    idx = None
    for i, c in enumerate(cards):
        if c.features.bvid == playing.bvid:
            idx = i
            break
    emb = full[idx] if idx is not None else embedding_from_features(playing, up_index)
    return emb, idx


def up_bucket_map(cards: List[Any]) -> Dict[Any, int]:
    counts: Counter = Counter(c.features.mid for c in cards)
    top_ups = [mid for mid, _ in counts.most_common(UP_BUCKETS - 1)]
    return {mid: i for i, mid in enumerate(top_ups)}


# --------------------------------------------------------------------------- #
# logging (respects the running debug level)
# --------------------------------------------------------------------------- #
_DEBUG = 0


def set_debug(level: int) -> None:
    global _DEBUG
    try:
        _DEBUG = int(level)
    except (TypeError, ValueError):
        _DEBUG = 0


def algo_log(text: str, v: int = 5, level: str = "info") -> None:
    """Emit an algorithm-process line; only shown when v <= active debug level."""
    if v > _DEBUG:
        return
    try:
        from .. import store
        store.add_log(level, "raw", {"text": text}, v=v)
    except Exception:
        pass


def scale_to_100(values: List[float]) -> List[float]:
    """Map arbitrary scores to [0,100] by dividing by the max (keeps report tidy)."""
    mx = max(values) if values else 0.0
    if mx <= 1e-9:
        return [0.0 for _ in values]
    return [100.0 * v / mx for v in values]
