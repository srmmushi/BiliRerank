"""biliRerank - the rerank scoring engine.

This module turns a raw Bilibili feed response into a re-ordered feed. Every
video is scored on **eight independent dimensions**, each returning a value in
``[0, 1]`` plus a small breakdown dict that explains *why* the score landed
where it did. The per-dimension scores are blended with tunable weights into a
single final score; items are then filtered (ads / vertical / empty), de-duplicated
per uploader and by title, and the surviving list is written back.

Design goals
------------
* **No denylist.** Nothing is thrown away for being "bad"; every item is scored
  from what the feed already returns (engagement ratios, duration, publish time,
  author stats, title wording, growth, category and diversity). Low scores simply
  sink to the bottom.
* **Explainable.** Each dimension returns a breakdown so the UI can later show
  *why* a video ranked where it did (not implemented in the UI yet, but the data
  is there).
* **Robust to API shape.** Bilibili ships the same logical feed through several
  different JSON envelopes (the app, the web ``index`` feed, the ``rcmd`` by
  index). The extraction layer normalises all of them into a single
  :class:`Features` structure before any scoring happens.
* **Tunable in one place.** Weights and thresholds come from :mod:`core.config`
  with sane in-module fallbacks, so the algorithm never crashes if a knob is
  missing.

The eight dimensions
---------------------
1. ``engagement``   互动质量  - weighted like/coin/fav/share/danmaku/reply vs views
2. ``duration``     时长契合  - closeness of length to a "sweet spot" window
3. ``recency``      新鲜度    - exponential decay of publish age
4. ``authority``    作者权威  - follower proxy + share-of-voice inside the feed
5. ``title``        标题质量  - clickbait / spam penalties, length & info density
6. ``momentum``     增长动量  - views-per-hour and acceleration
7. ``interest``     兴趣匹配  - category / keyword match against the user profile
8. ``diversity``    多样性    - per-uploader / per-category saturation penalty

Public API (stable, used by the backends)
-----------------------------------------
* :func:`apply`           - raw feed JSON string -> ``(new_json, cards, report)``
* :func:`rank`            - already-parsed feed list -> ``(items, cards, report)``
* :func:`is_feed_url`     - does a request URL look like a feed fetch?
* :func:`is_refresh_url`  - is this the client pulling a fresh first page?
* :func:`looks_like_feed`- does a response body look like a feed payload?
"""

from __future__ import annotations

import json
import math
import re
import time
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .. import config, store
from . import ALGORITHM_NAMES, get_algorithm, set_algorithm, rerank as algo_rerank
from ._util import set_debug as algo_set_debug

# Terminal debug verbosity (0 = quiet, 1..7 as in core.log.Console). The CLI sets
# this via set_debug(); the reranker emits per-video algorithm dumps at v>=6/7.
DEBUG_LEVEL = 0


def set_debug(level):
    global DEBUG_LEVEL
    try:
        DEBUG_LEVEL = int(level)
    except (TypeError, ValueError):
        DEBUG_LEVEL = 0
    try:
        algo_set_debug(DEBUG_LEVEL)
    except Exception:
        pass


# BVid of the video the user is currently watching, pushed in by the CDP backend
# (read from the page's location). When it matches a feed item, that item is used
# as an extra signal by the algorithms (GNN seed, sequence prefix, ...). See
# :func:`rank` and the algorithm modules.
_PLAYING_BVID = None


def set_playing(bvid):
    """Tell the engine which video is currently playing (None clears it)."""
    global _PLAYING_BVID
    _PLAYING_BVID = bvid or None


# =============================================================================
# Tunables
# -----------------------------------------------------------------------------
# Every knob has a fallback here so the engine is self-contained. ``core.config``
# wins when the attribute exists, which keeps all the "real" tuning in one file.
# =============================================================================
def _cfg(name: str, default):
    """Read a tuning knob from core.config, falling back to a local default."""
    return getattr(config, name, default)


# Final score is a base plus the weighted, zero-centred dimensions.
BASE_SCORE = float(_cfg("BASE_SCORE", 50.0))

# Dimension weights (in final-score points). Because each dimension is mapped to
# the range [-1, 1] (neutral = 0), a weight is "how many points this dimension
# can swing the final score in either direction".
WEIGHTS: Dict[str, float] = {
    "engagement": float(_cfg("W_ENGAGEMENT", 22.0)),
    "duration":   float(_cfg("W_DURATION", 10.0)),
    "recency":    float(_cfg("W_RECENCY", 8.0)),
    "authority":  float(_cfg("W_AUTHORITY", 14.0)),
    "title":      float(_cfg("W_TITLE", 12.0)),
    "momentum":   float(_cfg("W_MOMENTUM", 12.0)),
    "interest":   float(_cfg("W_INTEREST", 10.0)),
    "diversity":  float(_cfg("W_DIVERSITY", 12.0)),
}

@dataclass
class WeightProfile:
    """A named set of dimension weights - inspectable and overridable."""

    engagement: float = WEIGHTS["engagement"]
    duration: float = WEIGHTS["duration"]
    recency: float = WEIGHTS["recency"]
    authority: float = WEIGHTS["authority"]
    title: float = WEIGHTS["title"]
    momentum: float = WEIGHTS["momentum"]
    interest: float = WEIGHTS["interest"]
    diversity: float = WEIGHTS["diversity"]

    def as_dict(self) -> Dict[str, float]:
        return {
            "engagement": self.engagement, "duration": self.duration,
            "recency": self.recency, "authority": self.authority,
            "title": self.title, "momentum": self.momentum,
            "interest": self.interest, "diversity": self.diversity,
        }

    def total(self) -> float:
        return sum(self.as_dict().values())


_PROFILE: Optional[WeightProfile] = None


def current_profile() -> WeightProfile:
    """Return the active weight profile, rebuilt from core.config exactly once."""
    global _PROFILE
    if _PROFILE is None:
        p = WeightProfile()
        p.engagement = float(_cfg("W_ENGAGEMENT", p.engagement))
        p.duration = float(_cfg("W_DURATION", p.duration))
        p.recency = float(_cfg("W_RECENCY", p.recency))
        p.authority = float(_cfg("W_AUTHORITY", p.authority))
        p.title = float(_cfg("W_TITLE", p.title))
        p.momentum = float(_cfg("W_MOMENTUM", p.momentum))
        p.interest = float(_cfg("W_INTEREST", p.interest))
        p.diversity = float(_cfg("W_DIVERSITY", p.diversity))
        _PROFILE = p
    return _PROFILE


def explain_weights() -> str:
    """One-line description of the active weights, handy for logs / debugging."""
    p = current_profile()
    parts = ["%s=%.1f" % (k, v) for k, v in p.as_dict().items()]
    return "weights(total=%.1f) %s" % (p.total(), " ".join(parts))


# --- duration sweet-spot (seconds) -------------------------------------------
SHORT_SECONDS = float(_cfg("SHORT_SECONDS", 75))
LONG_SECONDS = float(_cfg("LONG_SECONDS", 1800))
SWEET_SECONDS = tuple(_cfg("SWEET_SECONDS", (180, 900)))

# --- recency ----------------------------------------------------------------
FRESH_DAYS = float(_cfg("FRESH_DAYS", 7))

# --- momentum ---------------------------------------------------------------
# A young video with an unusually high engagement ratio is treated as "accelerating".
MOMENTUM_RATIO = float(_cfg("MOMENTUM_RATIO", 0.06))           # engagement ratio that reads as hot
MOMENTUM_YOUNG_HOURS = float(_cfg("MOMENTUM_YOUNG_HOURS", 72)) # only younger-than-this (h) gets the boost
MOMENTUM_BOOST = float(_cfg("MOMENTUM_BOOST", 0.1))            # points added for accelerating young video

# --- diversity caps ---------------------------------------------------------
MAX_PER_UP = int(_cfg("MAX_PER_UP", 2))
DIVERSITY_PENALTY = float(_cfg("DIVERSITY_PENALTY", 12.0))

# --- interest profile keys (read from settings, optional) --------------------
DEFAULT_FAV_CATEGORIES = list(_cfg("FAV_CATEGORIES", []))
DEFAULT_KEYWORDS = list(_cfg("INTEREST_KEYWORDS", []))

# --- output ----------------------------------------------------------------
UI_LIMIT = int(_cfg("UI_LIMIT", 60))

# --- lexicons (kept here so the scoring module is self-describing) -----------
# Clickbait phrases: sensationalist wording that correlates with low-signal content.
CLICKBAIT_WORDS = (
    "震惊", "必看", "你还不知道", "速看", "不看后悔", "史上最", "揭秘", "真相",
    "居然", "没想到", "惊呆", "炸裂", "封神", "绝了", "偷偷", "重磅", "突发",
    "万万没想到", "细思极恐", "全程高能", "燃爆", "泪目", "破防", "逆天", "离谱",
)
# Spam / hard-sell wording: the feed sometimes leaks commercial or promo cards.
SPAM_WORDS = (
    "优惠券", "领券", "低价", "包邮", "私信", "加群", "限时", "点击链接",
    "带货", "下单", "抢购", "秒杀", "福利", "免费领", "扫码", "代理", "加盟",
)
# Words that signal *useful* specificity in a title (rewards informative titles).
SIGNAL_WORDS = (
    "教程", "实测", "对比", "评测", "拆解", "原理", "攻略", "盘点", "科普",
    "详解", "手把手", "复盘", "案例", "数据", "报告", "分析", "速通", "思路",
)

# Bilibili category id -> human name (a useful but non-exhaustive map; we also
# accept the category name directly from the payload).
# A *curated* id -> name map. Bilibili's real category ids are sparse and stable,
# so we keep only plausible entries; extract_category() prefers the raw `tname`
# from the payload anyway, and this table is just a fallback when that is absent.
# (The old 100-155 = "生活" run was fabricated and has been dropped.)
CATEGORY_NAMES = {
    "0": "未知", "1": "动画", "3": "音乐", "4": "游戏", "5": "娱乐", "11": "电视剧",
    "13": "番剧", "14": "电影", "15": "纪录片", "17": "时尚", "19": "科技",
    "20": "数码", "21": "生活", "22": "美食", "23": "动物圈", "24": "鬼畜",
    "25": "舞蹈", "26": "影视", "27": "影视", "28": "娱乐", "29": "娱乐",
    "30": "游戏", "31": "动画", "36": "知识", "39": "知识", "42": "手机摄影",
    "43": "运动", "44": "汽车", "45": "生活", "46": "手游", "47": "舞蹈",
    "48": "资讯", "49": "搞笑", "51": "旅游", "54": "绘画", "55": "舞蹈",
    "56": "国创", "59": "生活", "60": "生活", "64": "动物圈", "66": "虚拟主播",
    "70": "美食", "71": "美食", "75": "知识", "80": "电子竞技", "86": "知识",
    "88": "动物圈", "95": "资讯", "96": "日常", "98": "公益", "99": "时尚",
}

# Group fine categories into coarse buckets so the diversity / interest dimensions
# can reason about "genre" rather than individual ids. Keyed by bucket name.
CATEGORY_GROUPS = {
    "动画番剧": {"动画", "1", "31", "番剧", "13", "国创", "56", "影视", "26", "27", "11", "电视剧", "电影", "14", "纪录片", "15"},
    "游戏": {"游戏", "4", "30", "手游", "46", "电子竞技", "80"},
    "知识科技": {"科技", "19", "数码", "20", "知识", "36", "39", "75", "86"},
    "生活美食": {"生活", "21", "美食", "22", "70", "71", "旅游", "51", "日常", "96"},
    "音乐舞蹈": {"音乐", "3", "舞蹈", "25", "47", "55", "绘画", "54"},
    "娱乐鬼畜": {"娱乐", "5", "28", "29", "鬼畜", "24", "搞笑", "49"},
    "资讯": {"资讯", "48", "95", "新闻", "社会"},
    "动物萌宠": {"动物圈", "23", "64", "88"},
    "时尚运动": {"时尚", "17", "99", "运动", "43", "汽车", "44", "手机摄影", "42", "虚拟主播", "66", "公益", "98"},
}


def category_group(name: str) -> str:
    """Map a category name/id to a coarse genre bucket (``"其他"`` fallback)."""
    if not name or name == "未知":
        return "其他"
    for group, members in CATEGORY_GROUPS.items():
        if name in members:
            return group
    return name


# Categories that usually benefit from being seen soon (time-sensitive).
TIME_SENSITIVE = {
    "资讯", "48", "95", "110", "新闻", "影视", "13", "11", "26", "56",
}


# =============================================================================
# Math helpers
# =============================================================================
def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``value`` into ``[lo, hi]`` without raising."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def sigmoid(x: float) -> float:
    """Numerically stable logistic sigmoid."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def softplus(x: float, beta: float = 1.0) -> float:
    """Smooth, always-positive ReLU. Useful for turning a raw signal into a score."""
    return math.log1p(math.exp(min(beta * x, 40.0))) / beta


def normalize_log(value: float, midpoint: float, scale: float) -> float:
    """Map a positive, heavy-tailed quantity (views, likes...) onto ``[0, 1]``.

    ``midpoint`` is the value that should score exactly 0.5; ``scale`` controls
    how fast the curve saturates. We operate in log space because these metrics
    span many orders of magnitude.
    """
    if value <= 0:
        return 0.0
    return clamp(sigmoid((math.log1p(value) - math.log1p(midpoint)) / scale))


def minmax(value: float, lo: float, hi: float) -> float:
    """Normalise ``value`` to ``[0, 1]`` between ``lo`` and ``hi``."""
    if hi <= lo:
        return 0.0 if value < lo else 1.0
    return clamp((value - lo) / (hi - lo))


def gaussian(value: float, center: float, width: float) -> float:
    """A bell curve centred on ``center`` with the given ``width`` (std-dev-ish)."""
    if width <= 0:
        return 0.0
    return clamp(math.exp(-((value - center) ** 2) / (2.0 * width * width)))


def safe_div(num: float, den: float, default: float = 0.0) -> float:
    """Divide without ZeroDivisionError."""
    return num / den if den else default


def percentile(sorted_values: List[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list (q in ``[0, 1]``)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = clamp(q, 0.0, 1.0) * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def geometric_mean(values: List[float]) -> float:
    """Geometric mean; returns 0 if any value is <= 0 (so penalties compound)."""
    if not values:
        return 0.0
    prod = 1.0
    for v in values:
        if v <= 0:
            return 0.0
        prod *= v
    return prod ** (1.0 / len(values))


def blend(weights: Dict[str, float], scores: Dict[str, float]) -> float:
    """Weighted average of dimension scores, ignoring missing dimensions."""
    total = 0.0
    mass = 0.0
    for key, score in scores.items():
        w = weights.get(key)
        if w is None:
            continue
        total += w * score
        mass += w
    return safe_div(total, mass, 0.0)


def triangular(value: float, lo: float, peak: float, hi: float) -> float:
    """A triangle bump that rises from ``lo`` to ``peak`` and falls to ``hi``.

    Unlike a Gaussian it has compact support (exactly zero outside ``[lo, hi]``),
    which is handy for "sweet spot" windows where anything far outside should score
    zero rather than a long thin tail.
    """
    if value <= lo or value >= hi or hi <= lo:
        return 0.0
    if value <= peak:
        return clamp(safe_div(value - lo, peak - lo, 0.0))
    return clamp(safe_div(hi - value, hi - peak, 0.0))


def rank_in_feed(value: float, sorted_values: List[float]) -> float:
    """Position of ``value`` within an ascending sorted list, as ``[0, 1]``."""
    if not sorted_values:
        return 0.5
    lo, hi = sorted_values[0], sorted_values[-1]
    if hi <= lo:
        return 0.5
    return clamp((value - lo) / (hi - lo))


# =============================================================================
# Field extraction (robust across several Bilibili JSON envelopes)
# =============================================================================
def dig(item: Any, path: str, default: Any = 0) -> Any:
    """Walk a dotted path through nested dicts, returning ``default`` on any miss."""
    cur = item
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def first(item: Any, *paths: str, default: Any = 0) -> Any:
    """Return the first of several dotted paths that holds a non-empty value."""
    for path in paths:
        value = dig(item, path, None)
        if value not in (None, "", [], {}):
            return value
    return default


def to_number(value: Any) -> float:
    """Best-effort numeric coercion; strips thousands separators and units."""
    try:
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d.]", "", value)
            if not cleaned:
                return 0.0
            return float(cleaned)
        if isinstance(value, (int, float)):
            return float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def parse_duration(value: Any) -> float:
    """Parse a duration that may be seconds (int) or ``HH:MM:SS`` / ``MM:SS``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return 0.0
    parts = [to_number(p) for p in value.strip().split(":")]
    if not parts:
        return 0.0
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60.0 + part
    return seconds


def parse_pubdate(value: Any) -> float:
    """Parse a publish timestamp that may be in seconds or milliseconds."""
    num = to_number(value)
    if num > 1e11:           # milliseconds
        return num / 1000.0
    return num


def title_of(item: Any) -> str:
    return str(first(item, "title", "name", "title_render", default="")).strip()


def up_of(item: Any) -> str:
    return str(dig(item, "owner.name", "") or item.get("author") or "").strip()


def mid_of(item: Any) -> Any:
    return dig(item, "owner.mid", 0) or item.get("mid") or 0


def goto_of(item: Any) -> str:
    return str(item.get("goto") or item.get("card_type") or "").strip()


def bvid_of(item: Any) -> str:
    return str(first(item, "bvid", "args.bvid", "bvid_", "aid", default="")).strip()


def fingerprint(text: str) -> str:
    """A loose title key used to catch near-duplicate cards."""
    return re.sub(r"[\s\W_]+", "", text)[:14]


def is_ad(item: Any) -> bool:
    if goto_of(item) in ("ad", "cm"):
        return True
    ad = item.get("ad_info")
    return isinstance(ad, dict) and len(ad) > 0


def is_vertical(item: Any) -> bool:
    """Portrait / short-form clips (not a normal landscape video card)."""
    return goto_of(item) in ("vertical_av", "vertical")


def is_live(item: Any) -> bool:
    """Live-streaming entries - excluded from the reranked VOD feed."""
    return goto_of(item) in ("live", "vertical_live")


def extract_stats(item: Any) -> Dict[str, float]:
    """Pull the engagement counters, trying every known envelope shape."""
    stat = item.get("stat") if isinstance(item.get("stat"), dict) else {}
    args = item.get("args") if isinstance(item.get("args"), dict) else {}
    return {
        "view":     to_number(first(item, "stat.view", "view", "cnt_info.play", "args.stat.view", "play", default=0)),
        "like":     to_number(first(item, "stat.like", "like", "cnt_info.like", "args.stat.like", default=0)),
        "danmaku":  to_number(first(item, "stat.danmaku", "danmaku", "cnt_info.danmaku", "args.stat.danmaku", default=0)),
        "reply":    to_number(first(item, "stat.reply", "reply", "cnt_info.reply", "args.stat.reply", default=0)),
        "coin":     to_number(first(item, "stat.coin", "coin", "cnt_info.coin", "args.stat.coin", default=0)),
        "favorite": to_number(first(item, "stat.favorite", "favorite", "cnt_info.favorite", "args.stat.favorite", default=0)),
        "share":    to_number(first(item, "stat.share", "share", "cnt_info.share", "args.stat.share", default=0)),
    }


def extract_owner(item: Any) -> Dict[str, Any]:
    """Pull uploader-level stats; follower/level are not always present."""
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    return {
        "name": up_of(item),
        "mid": mid_of(item),
        "follower": to_number(first(item, "owner.fans", "owner.follower", "follower", "fans", default=0)),
        "level": to_number(first(item, "owner.level", "level", "level_info.current_level", default=0)),
        "official": bool(
            item.get("official") or owner.get("official") or item.get("owner", {}).get("official", {})
        ),
    }


def extract_category(item: Any) -> str:
    """Return a normalised category name; falls back through several fields."""
    raw = first(item, "tname", "category", "args.area", "typename", default="")
    raw = str(raw).strip()
    if raw and raw in CATEGORY_NAMES.values():
        return raw
    if raw in CATEGORY_NAMES:
        return CATEGORY_NAMES[raw]
    # sometimes category is an id inside a nested dict
    cid = str(dig(item, "tag.category_id", "") or dig(item, "category_id", "") or "")
    if cid in CATEGORY_NAMES:
        return CATEGORY_NAMES[cid]
    return raw or "未知"


def extract_tags(item: Any) -> List[str]:
    """Collect tag-like tokens from the payload for interest matching."""
    tags: List[str] = []
    raw = item.get("tag")
    if isinstance(raw, str) and raw:
        tags.extend(t.strip() for t in raw.split(",") if t.strip())
    elif isinstance(raw, list):
        for t in raw:
            if isinstance(t, dict):
                txt = t.get("name") or t.get("tag_name") or t.get("text")
                if txt:
                    tags.append(str(txt).strip())
            elif t:
                tags.append(str(t).strip())
    # rcmd feeds sometimes carry a list of reason tags
    reasons = item.get("rcmd_reason")
    if isinstance(reasons, dict):
        tag = reasons.get("content")
        if tag:
            tags.append(str(tag).strip())
    return [t for t in tags if t]


# =============================================================================
# Normalised feature record
# =============================================================================
@dataclass
class Features:
    """Everything a dimension needs, normalised away from the raw envelope."""

    title: str = ""
    up: str = ""
    mid: Any = 0
    bvid: str = ""
    goto: str = ""
    view: float = 0.0
    like: float = 0.0
    danmaku: float = 0.0
    reply: float = 0.0
    coin: float = 0.0
    favorite: float = 0.0
    share: float = 0.0
    duration: float = 0.0
    pubdate: float = 0.0
    follower: float = 0.0
    level: float = 0.0
    official: bool = False
    category: str = "未知"
    tags: List[str] = field(default_factory=list)
    description: str = ""
    raw: Any = None

    # --- derived convenience ------------------------------------------------
    @property
    def engagement_total(self) -> float:
        return (self.like + self.coin * 1.5 + self.favorite * 1.5
                + self.share * 2.0 + self.danmaku * 2.0 + self.reply * 1.5)

    @property
    def engagement_ratio(self) -> float:
        return safe_div(self.engagement_total, self.view)


def make_features(item: Any) -> Features:
    """Build a :class:`Features` record from whichever envelope shape we got."""
    stats = extract_stats(item)
    owner = extract_owner(item)
    desc = str(first(item, "desc", "description", "args.desc", default="")).strip()
    return Features(
        title=title_of(item),
        up=owner["name"],
        mid=owner["mid"],
        bvid=bvid_of(item),
        goto=goto_of(item),
        view=stats["view"],
        like=stats["like"],
        danmaku=stats["danmaku"],
        reply=stats["reply"],
        coin=stats["coin"],
        favorite=stats["favorite"],
        share=stats["share"],
        duration=parse_duration(first(item, "duration", "args.duration", default=0)),
        pubdate=parse_pubdate(first(item, "pubdate", "ctime", "args.pubdate", "pub_time", default=0)),
        follower=owner["follower"],
        level=owner["level"],
        official=owner["official"],
        category=extract_category(item),
        tags=extract_tags(item),
        description=desc,
        raw=item,
    )


# =============================================================================
# Interest profile (user preferences, read from settings when available)
# =============================================================================
# Cache the parsed interest profile so a feed with many items doesn't re-read and
# re-parse settings for every card. The cache is invalidated by the settings file's
# mtime, so an edited settings file is picked up on the next feed automatically.
_interest_cache: Optional["InterestProfile"] = None
_interest_mtime: float = -1.0


def _settings_mtime() -> float:
    try:
        return os.path.getmtime(config.SETTINGS_PATH)
    except OSError:
        return -1.0


def _load_interest_profile(cls) -> "InterestProfile":
    """Read settings once and return a cached InterestProfile (mtime-gated)."""
    global _interest_cache, _interest_mtime
    mtime = _settings_mtime()
    if _interest_cache is not None and mtime == _interest_mtime:
        return _interest_cache
    cats: List[str] = []
    kws: List[str] = []
    try:
        from . import settings
        data = settings.load()
        cats = list(data.get("fav_categories", DEFAULT_FAV_CATEGORIES) or [])
        kws = list(data.get("interest_keywords", DEFAULT_KEYWORDS) or [])
    except Exception:
        cats, kws = list(DEFAULT_FAV_CATEGORIES), list(DEFAULT_KEYWORDS)
    profile = cls(
        categories={str(c).strip() for c in cats if str(c).strip()},
        keywords={str(k).strip().lower() for k in kws if str(k).strip()},
    )
    _interest_cache, _interest_mtime = profile, mtime
    return profile


@dataclass
class InterestProfile:
    """What the user is (optionally) interested in, used by dimension 7."""

    categories: set = field(default_factory=set)
    keywords: set = field(default_factory=set)

    @classmethod
    def from_settings(cls) -> "InterestProfile":
        """Build the profile from persisted settings (cached; best-effort, never fails)."""
        return _load_interest_profile(cls)

    @property
    def configured(self) -> bool:
        return bool(self.categories or self.keywords)


# =============================================================================
# Feed-wide context
# =============================================================================
@dataclass
class Context:
    """Statistics computed once across the whole feed, shared by every dimension."""

    now: float = 0.0
    max_view: float = 1.0
    median_view: float = 1.0
    view_values: List[float] = field(default_factory=list)
    category_counts: Counter = field(default_factory=Counter)
    up_counts: Counter = field(default_factory=Counter)
    total: int = 0
    interest: InterestProfile = field(default_factory=InterestProfile)
    # the video the user is currently watching (a Features in the feed, or None)
    playing: Any = None

    def view_rank(self, view: float) -> float:
        """Where this video's view count sits in the feed (0=lowest, 1=highest)."""
        if not self.view_values:
            return 0.5
        return minmax(view, self.view_values[0], self.view_values[-1])


def build_context(features_list: List[Features]) -> Context:
    """Aggregate the statistics every dimension needs."""
    ctx = Context(now=time.time())
    views = sorted(f.view for f in features_list if f.view > 0)
    ctx.view_values = views
    ctx.max_view = max(views) if views else 1.0
    ctx.median_view = percentile(views, 0.5) or 1.0
    ctx.total = len(features_list)
    for f in features_list:
        if f.category:
            ctx.category_counts[f.category] += 1
        if f.mid:
            ctx.up_counts[f.mid] += 1
    ctx.interest = InterestProfile.from_settings()
    return ctx


# =============================================================================
# Dimension 1 - engagement quality (互动质量)
# -----------------------------------------------------------------------------
# Weighted engagement actions (like / coin / favourite / share / danmaku / reply)
# relative to view count. We use a log-normalised ratio so both a tiny viral clip
# and a massive mainstream video can score well.
# =============================================================================
def dim_engagement(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    if f.view <= 0:
        return 0.5, {"reason": "no_views", "ratio": 0.0}
    ratio = f.engagement_ratio
    score = normalize_log(ratio, midpoint=0.03, scale=0.9)
    detail = {
        "ratio": round(ratio, 5),
        "view": int(f.view),
        "like": int(f.like),
        "coin": int(f.coin),
        "favorite": int(f.favorite),
        "share": int(f.share),
        "danmaku": int(f.danmaku),
        "reply": int(f.reply),
    }
    # A genuinely popular video (high absolute actions) gets a small floor so it
    # is never buried purely for having a large denominator.
    if f.like >= 1000 or f.coin >= 500 or f.favorite >= 500:
        score = max(score, 0.45)
    return clamp(score), detail


# =============================================================================
# Dimension 2 - duration fit (时长契合)
# -----------------------------------------------------------------------------
# Videos near the "sweet spot" (a few minutes) score highest. Too short reads as
# a filler clip; too long competes poorly for attention in a scroll feed.
# =============================================================================
def dim_duration(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    lo, hi = SWEET_SECONDS
    center = (lo + hi) / 2.0
    width = (hi - lo) / 3.0
    if f.duration <= 0:
        return 0.5, {"reason": "unknown_duration", "seconds": 0}
    if f.duration < SHORT_SECONDS:
        # linear ramp from 0.2 (very short) up to 0.7 at the short threshold
        score = 0.2 + 0.5 * minmax(f.duration, 5.0, SHORT_SECONDS)
        tag = "short"
    elif f.duration > LONG_SECONDS:
        # gentle decay past the long threshold
        score = 0.6 * gaussian(f.duration, LONG_SECONDS, LONG_SECONDS * 0.8)
        tag = "long"
    else:
        score = 0.6 + 0.4 * triangular(f.duration, lo, center, hi)
        tag = "sweet"
    return clamp(score), {"seconds": int(f.duration), "zone": tag}


# =============================================================================
# Dimension 3 - recency (新鲜度)
# -----------------------------------------------------------------------------
# Exponential decay of publish age. Fresh content is rewarded; very old content
# still gets a small floor so evergreen videos are not erased.
# =============================================================================
def dim_recency(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    if f.pubdate <= 0:
        return 0.5, {"reason": "unknown_date"}
    age_days = (ctx.now - f.pubdate) / 86400.0
    if age_days < 0:
        age_days = 0.0
    tau = FRESH_DAYS            # half-life-ish constant
    decay = math.exp(-age_days / tau)
    score = 0.35 + 0.65 * decay
    return clamp(score), {"age_days": round(age_days, 2)}


# =============================================================================
# Dimension 4 - uploader authority (作者权威)
# -----------------------------------------------------------------------------
# Bilibili rarely ships follower counts in the feed, so we blend two signals:
#   * an explicit follower count when present (log-normalised), and
#   * a "share of voice" proxy: how this video's views compare to the rest of the
#     feed (a channel that out-performs its peers is authoritative in context).
# =============================================================================
def dim_authority(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    """Authority = explicit credentials blended with in-feed share-of-voice.

    The explicit signals (follower count, account level, official badge) are hard,
    trustworthy credentials. The contextual "voice" (where this video's views rank
    inside the current feed) is a softer proxy - a channel that out-performs its
    peers reads as authoritative even without follower data - but it must not
    dominate, otherwise any popular-in-feed clip would look like a big UP.
    """
    detail: Dict[str, Any] = {}
    explicit: List[float] = []

    if f.follower > 0:
        explicit.append(normalize_log(f.follower, midpoint=50000, scale=1.0))
        detail["follower"] = int(f.follower)
    if f.level >= 5:
        explicit.append(minmax(f.level, 0, 6))
        detail["level"] = int(f.level)
    if f.official:
        explicit.append(0.9)
        detail["official"] = True

    voice = rank_in_feed(f.view, ctx.view_values)
    detail["voice"] = round(voice, 3)

    # Explicit credentials own 65% of the score; in-feed voice owns 35%. When no
    # explicit signal is present we fall back to a neutral 0.5 so stat-less feeds
    # are not unfairly crushed or inflated.
    explicit_score = sum(explicit) / len(explicit) if explicit else 0.5
    score = 0.65 * explicit_score + 0.35 * voice
    return clamp(score), detail


# =============================================================================
# Dimension 5 - title quality (标题质量)
# -----------------------------------------------------------------------------
# Rewards informative, well-formed titles and penalises clickbait and hard-sell
# wording. Combines: clickbait count, spam count, length fit, and "signal" words
# that indicate a substantive video.
# =============================================================================
def _count_words(title: str, words) -> int:
    return sum(1 for w in words if w in title)


def dim_title(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    title = f.title
    n = len(title)
    if not title:
        return 0.3, {"reason": "empty"}

    clickbait = _count_words(title, CLICKBAIT_WORDS)
    spam = _count_words(title, SPAM_WORDS)
    signal = _count_words(title, SIGNAL_WORDS)

    # length fit: best around 8-24 characters
    if n < 6:
        length_fit = 0.25
    elif n <= 24:
        length_fit = 1.0
    elif n <= 36:
        length_fit = 0.7
    else:
        length_fit = 0.45

    score = 0.55 + 0.25 * (length_fit - 0.5) * 2.0
    score += 0.12 * min(signal, 2)            # reward substantive wording
    score -= 0.25 * min(clickbait, 3)         # punish clickbait (capped)
    score -= 0.42 * min(spam, 3)              # punish hard-sell (capped)
    score = clamp(score)

    detail = {
        "len": n,
        "clickbait": clickbait,
        "spam": spam,
        "signal": signal,
        "length_fit": round(length_fit, 2),
    }
    return score, detail


# =============================================================================
# Dimension 6 - momentum (增长动量)
# -----------------------------------------------------------------------------
# How fast the video is gaining traction right now: views per hour since publish,
# plus a mild acceleration proxy from engagement ratio. Catches "rising" content
# that has not yet accumulated huge raw numbers.
# =============================================================================
def dim_momentum(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    if f.pubdate <= 0 or f.view <= 0:
        return 0.5, {"reason": "no_baseline"}
    age_hours = max((ctx.now - f.pubdate) / 3600.0, 0.5)
    views_per_hour = f.view / age_hours
    # normalise: 500 v/h -> ~0.5, 50k v/h -> near 1
    score = normalize_log(views_per_hour, midpoint=2000, scale=1.1)
    detail = {
        "views_per_hour": int(views_per_hour),
        "age_hours": round(age_hours, 1),
    }
    # acceleration proxy: a young video with an unusually high engagement ratio
    # hints at strong word-of-mouth momentum (knobs live in core.config).
    if f.engagement_ratio > MOMENTUM_RATIO and age_hours < MOMENTUM_YOUNG_HOURS:
        score = min(1.0, score + MOMENTUM_BOOST)
        detail["boost"] = "high_engagement_young"
    return clamp(score), detail


# =============================================================================
# Dimension 7 - interest match (兴趣匹配)
# -----------------------------------------------------------------------------
# Matches the video's category and tags/title keywords against the user profile.
# When no profile is configured the dimension is neutral (so it neither helps nor
# hurts); once the user picks favourite categories / keywords it becomes a real
# signal. We also give a small bonus to time-sensitive categories that are usually
# better consumed fresh.
# =============================================================================
def dim_interest(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    profile = ctx.interest
    detail = {"configured": profile.configured, "category": f.category}

    if not profile.configured:
        return 0.5, detail

    score = 0.5
    hits = 0

    if f.category in profile.categories:
        score += 0.3
        hits += 1
        detail["category_hit"] = True

    haystack = " ".join(f.tags).lower() + " " + f.title.lower()
    kw_hits = [k for k in profile.keywords if k and k in haystack]
    if kw_hits:
        score += min(0.3, 0.1 * len(kw_hits))
        hits += len(kw_hits)
        detail["keyword_hits"] = kw_hits[:5]

    if f.category in TIME_SENSITIVE:
        # freshness already rewards newness; this nudges timely topics up a touch
        score += 0.05

    detail["hits"] = hits
    return clamp(score), detail


# =============================================================================
# Dimension 8 - diversity (多样性)
# -----------------------------------------------------------------------------
# Soft penalty for categories / uploaders that already dominate the feed, so a
# single viral UP or genre does not crowd everything out. The *hard* caps (max per
# UP, title de-dup) are applied later in :func:`rank`, this dimension only shades
# the score. Computed against the feed-wide frequencies in ``ctx``.
# =============================================================================
def dim_diversity(f: Features, ctx: Context) -> Tuple[float, Dict[str, Any]]:
    if ctx.total <= 1:
        return 0.8, {"reason": "single_item"}

    cat_share = safe_div(ctx.category_counts.get(f.category, 0), ctx.total)
    up_share = safe_div(ctx.up_counts.get(f.mid, 0), ctx.total)

    # more common -> lower diversity score (with a floor so nothing hits zero)
    cat_score = clamp(1.0 - 1.6 * cat_share)
    up_score = clamp(1.0 - 1.6 * up_share)
    score = 0.6 * cat_score + 0.4 * up_score
    return clamp(score), {
        "group": category_group(f.category),
        "category_share": round(cat_share, 3),
        "up_share": round(up_share, 3),
    }


# =============================================================================
# Aggregation
# =============================================================================
DIMENSIONS = {
    "engagement": dim_engagement,
    "duration": dim_duration,
    "recency": dim_recency,
    "authority": dim_authority,
    "title": dim_title,
    "momentum": dim_momentum,
    "interest": dim_interest,
    "diversity": dim_diversity,
}


@dataclass
class ScoreCard:
    """The full result for one video: final score, per-dimension breakdown, tags.

    ``final`` is the true blended score (used for primary ranking and relative
    comparison). ``display_score`` is what the UI shows and what places an item in
    the list; for de-duplicated ("deferred") items it is pushed below the primary
    tail so the number the user sees matches the position.
    """

    features: Features
    final: float = 0.0
    dims: Dict[str, float] = field(default_factory=dict)
    detail: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    display_score: Optional[float] = None


def _tags_for(f: Features, dims: Dict[str, float]) -> List[str]:
    """Translate strong dimension signals into UI chip keys (must exist in i18n)."""
    tags: List[str] = []
    if dims.get("engagement", 0) >= 0.7:
        tags.append("tag.hot")
    elif dims.get("engagement", 0) <= 0.3:
        tags.append("tag.low_eng")
    if dims.get("duration", 0) >= 0.85:
        tags.append("tag.length")
    elif dims.get("duration", 0) <= 0.3:
        tags.append("tag.short")
    if dims.get("recency", 0) >= 0.8:
        tags.append("tag.fresh")
    if dims.get("authority", 0) >= 0.75:
        tags.append("tag.authority")
    if dims.get("title", 0) >= 0.8 and dims.get("title", 1) > 0.4:
        tags.append("tag.title_good")
    if _count_words(f.title, CLICKBAIT_WORDS) >= 1:
        tags.append("tag.clickbait")
    if _count_words(f.title, SPAM_WORDS) >= 1:
        tags.append("tag.spam")
    if dims.get("momentum", 0) >= 0.75:
        tags.append("tag.trending")
    if dims.get("interest", 0) >= 0.8:
        tags.append("tag.interest")
    return tags


def apply_quality_gate(card: ScoreCard) -> ScoreCard:
    """Decisive but bounded demotion for low-trust titles (clickbait / hard-sell).

    The per-dimension scores already penalise these, but a viral clip can still
    score high on engagement/momentum. This gate makes the editorial call
    explicit and predictable instead of leaking it into every dimension.
    """
    tags = set(card.tags)
    if "tag.spam" in tags:
        card.final = round(clamp(card.final * 0.80, 0.0, 100.0), 1)
        card.detail["gate"] = "spam x0.80"
    elif "tag.clickbait" in tags:
        card.final = round(clamp(card.final * 0.90, 0.0, 100.0), 1)
        card.detail["gate"] = "clickbait x0.90"
    return card


def score_item(f: Features, ctx: Context) -> ScoreCard:
    """Run all eight dimensions and blend them into a final score."""
    dims: Dict[str, float] = {}
    detail: Dict[str, Dict[str, Any]] = {}
    for name, fn in DIMENSIONS.items():
        s, d = fn(f, ctx)
        dims[name] = s
        detail[name] = d

    # Map each [0,1] dimension to [-1,1] (neutral = 0) and apply its weight.
    profile = current_profile()
    swing = 0.0
    mass = 0.0
    for name, s in dims.items():
        w = getattr(profile, name, 0.0)
        swing += w * (s * 2.0 - 1.0)
        mass += w
    final = clamp(BASE_SCORE + swing, 0.0, 100.0) if mass else BASE_SCORE

    card = ScoreCard(features=f, final=round(final, 1), dims=dims,
                     detail=detail, tags=_tags_for(f, dims))
    return apply_quality_gate(card)


# =============================================================================
# Ranking, filtering and diversity enforcement
# =============================================================================
def _clip(text: str, n: int) -> str:
    s = text or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _debug_dump(ordered: List[Tuple[float, ScoreCard]], ctx: Context,
                report: Dict[str, Any]) -> None:
    """Emit per-feed / per-video algorithm traces at high debug levels (v>=5)."""
    if DEBUG_LEVEL <= 0:
        return
    try:
        if DEBUG_LEVEL >= 5:
            dims = report.get("dims", {})
            line = "[debug] feed dim avg: " + ", ".join(
                "%s=%.3f" % (k, dims[k]) for k in dims)
            store.add_log("info", "raw", {"text": line}, v=5)
        if DEBUG_LEVEL >= 6:
            for i, (score, card) in enumerate(ordered[:config.UI_LIMIT]):
                f = card.features
                line = "[debug] #%02d  %.1f  %s  UP=%s  tags=%s" % (
                    i + 1, score, _clip(f.title, 32), f.up or "?",
                    ",".join(card.tags))
                store.add_log("debug", "raw", {"text": line}, v=6)
        if DEBUG_LEVEL >= 7:
            for i, (score, card) in enumerate(ordered):
                f = card.features
                d = card.dims
                age_days = (ctx.now - f.pubdate) / 86400.0 if f.pubdate > 0 else 0.0
                disp = card.display_score if card.display_score is not None else card.final
                line = (
                    "[debug] #%02d  %s\n"
                    "        bvid=%s up=%s(mid=%s) view=%.0f like=%.0f coin=%.0f fav=%.0f "
                    "dur=%.0fs age=%.1fd\n"
                    "        final=%.2f display=%.2f gate=%s\n"
                    "        dims: eng=%.2f dur=%.2f rec=%.2f auth=%.2f title=%.2f "
                    "mom=%.2f intr=%.2f div=%.2f\n"
                    "        tags=%s"
                ) % (i + 1, _clip(f.title, 48), f.bvid, f.up or "?", f.mid,
                     f.view, f.like, f.coin, f.favorite, f.duration, age_days,
                     card.final, disp, card.detail.get("gate", "-"),
                     d.get("engagement", 0), d.get("duration", 0), d.get("recency", 0),
                     d.get("authority", 0), d.get("title", 0), d.get("momentum", 0),
                     d.get("interest", 0), d.get("diversity", 0),
                     ",".join(card.tags))
                store.add_log("debug", "raw", {"text": line}, v=7)
    except Exception:
        pass


def rank(feed: List[Any]) -> Tuple[List[Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Filter, score on eight dimensions, de-duplicate, and order the feed.

    Returns ``(ordered_raw_items, cards, report)`` where ``cards`` is the UI-shaped
    list and ``report`` is the summary the backends log.
    """
    kept: List[Any] = []
    ads = excluded = empty = 0
    features_list: List[Features] = []

    for item in feed:
        if not isinstance(item, dict):
            continue
        if is_ad(item):
            ads += 1
            continue
        # portrait short-clips and live rooms are not normal VOD cards to rerank
        if is_vertical(item) or is_live(item):
            excluded += 1
            continue
        if not title_of(item):
            empty += 1
            continue
        feat = make_features(item)
        features_list.append(feat)
        kept.append(item)

    if not features_list:
        return [], [], {"seen": len(feed), "kept": 0, "ads": ads,
                        "vertical": excluded, "deferred": 0, "top": 0.0,
                        "empty": empty, "head": []}

    ctx = build_context(features_list)

    # Resolve the currently-playing video (if the backend reported one) to a feed
    # item; the algorithms then use it as an extra signal (seed / sequence prefix).
    playing = None
    if _PLAYING_BVID:
        for f in features_list:
            if f.bvid == _PLAYING_BVID:
                playing = f
                break
    ctx.playing = playing
    if DEBUG_LEVEL >= 1 and playing:
        store.add_log("info", "play.now",
                      {"title": _clip(playing.title, 30), "bvid": playing.bvid}, v=1)

    cards_all = [score_item(f, ctx) for f in features_list]

    # Run the selected rerank algorithm. It returns the cards in the order it wants
    # (each card.final rewritten to its own ranking score); the de-dup below then
    # hands out the scarce "primary" slots in that order.
    cards_all = algo_rerank(cards_all, ctx)

    per_up: Counter = Counter()
    seen: set = set()
    primary: List[ScoreCard] = []
    deferred: List[Tuple[float, ScoreCard]] = []

    for card in cards_all:
        mid = card.features.mid
        key = fingerprint(card.features.title)
        is_dup_up = per_up.get(mid, 0) >= MAX_PER_UP
        is_dup_title = bool(key and key in seen)
        if is_dup_up or is_dup_title:
            # duplicates are demoted by a flat penalty and pushed below the primary tail
            deferred.append((card.final - DIVERSITY_PENALTY, card))
            continue
        per_up[mid] = per_up.get(mid, 0) + 1
        if key:
            seen.add(key)
        card.display_score = card.final
        primary.append(card)

    # Deferred items keep the tail. Their visible score is the demoted value, further
    # stepped down per position so the number shown always sits below the lowest
    # primary - fixing the old bug where a high `final` was shown but ranked last.
    deferred.sort(key=lambda pair: -pair[0])
    if primary:
        floor = primary[-1].final
        for i, (base, card) in enumerate(deferred):
            card.display_score = round(min(base, floor - 0.5 - i * 0.1), 1)
    else:
        for base, card in deferred:
            card.display_score = round(base, 1)

    ordered: List[Tuple[float, ScoreCard]] = (
        [(c.final, c) for c in primary] + [(c.display_score, c) for _, c in deferred]
    )
    ordered_items = [card.features.raw for _, card in ordered]

    cards = [_card_to_ui(card) for _, card in ordered[:UI_LIMIT]]
    report = {
        "seen": len(feed),
        "kept": len(ordered_items),
        "ads": ads,
        "vertical": excluded,
        "deferred": len(deferred),
        "top": round(ordered[0][0], 1) if ordered else 0.0,
        "empty": empty,
        "algorithm": get_algorithm(),
        "playing": playing.bvid if playing else None,
        "head": [c["title"][:22] for c in cards[:3]],
        "titles": [_clip(card.features.title, 40) for _, card in ordered],
        "avg_engagement": round(_avg_dim(ordered, "engagement"), 3),
        "avg_recency": round(_avg_dim(ordered, "recency"), 3),
        "dims": summarize_dimensions(ordered),
    }
    _debug_dump(ordered, ctx, report)
    return ordered_items, cards, report


def _avg_dim(ordered: List[Tuple[float, ScoreCard]], dim: str) -> float:
    if not ordered:
        return 0.0
    return sum(c.dims.get(dim, 0.0) for _, c in ordered) / len(ordered)


def summarize_dimensions(ordered: List[Tuple[float, ScoreCard]]) -> Dict[str, float]:
    """Average of every dimension across the final ordered list (for the report)."""
    out: Dict[str, float] = {}
    for name in DIMENSIONS:
        vals = [c.dims.get(name, 0.0) for _, c in ordered]
        out[name] = round(sum(vals) / len(vals), 3) if vals else 0.0
    return out


def _card_to_ui(card: ScoreCard) -> Dict[str, Any]:
    f = card.features
    return {
        "title": f.title,
        "up": f.up or "?",
        "mid": f.mid,
        "bvid": f.bvid,
        "score": card.display_score if card.display_score is not None else card.final,
        "tags": card.tags,
    }


# =============================================================================
# Feed payload detection (stable API used by the backends)
# =============================================================================
def is_feed_url(url: str) -> bool:
    low = (url or "").lower()
    return any(hint in low for hint in config.FEED_URL_HINTS)


def is_refresh_url(url: str) -> bool:
    """The client asked for a fresh first page (pull to refresh / re-entering the
    home tab): the accumulated list is dropped before the new items land."""
    low = (url or "").lower()
    return any(hint in low for hint in config.REFRESH_URL_HINTS)


def looks_like_feed(text: str) -> bool:
    return any(marker in text for marker in config.FEED_MARKERS)


def _feed_list(body: Dict[str, Any]):
    """Find the list of items inside a parsed feed body, or return None."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    for candidate in (config.FEED_KEY, config.FEED_KEY_ALT):
        value = data.get(candidate)
        if isinstance(value, list) and value:
            return value
    return None


def apply(text: str):
    """Raw feed JSON in, ``(new_json, cards, report)`` out - ``None`` when the
    payload is not a feed."""
    try:
        body = json.loads(text)
    except ValueError:
        return None

    items = _feed_list(body)
    if items is None:
        return None

    ordered, cards, report = rank(items)
    if not ordered:
        return None

    # write the re-ordered list back into the original envelope
    data = body["data"]
    key = config.FEED_KEY if isinstance(data.get(config.FEED_KEY), list) else config.FEED_KEY_ALT
    data[key] = ordered
    new_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return new_json, cards, report


# =============================================================================
# Optional: human-readable explanation for a single ScoreCard (for debugging /
# future UI). Kept tiny so it does not bloat the hot path.
# =============================================================================
def explain(card: ScoreCard) -> str:
    parts = []
    for name in DIMENSIONS:
        s = card.dims.get(name, 0.0)
        parts.append("%s=%.2f" % (name, s))
    return "final=%.1f [%s]" % (card.final, " ".join(parts))


# =============================================================================
# Self-test / demonstration (run: python -m src.core.algorithms.engine)
# =============================================================================
def _demo():
    now = time.time()
    sample = [
        {"title": "震惊！这视频居然这么牛，不看后悔", "owner": {"name": "BigUP", "mid": 1},
         "bvid": "BV1", "goto": "av", "duration": "3:20", "pubdate": now - 3600,
         "stat": {"view": 50000, "like": 8000, "coin": 2000, "favorite": 1500,
                  "share": 600, "danmaku": 400, "reply": 300}, "tname": "知识"},
        {"title": "Python 教程：从零手把手讲解装饰器原理", "owner": {"name": "Teacher", "mid": 2},
         "bvid": "BV2", "goto": "av", "duration": "12:05", "pubdate": now - 86400 * 2,
         "stat": {"view": 20000, "like": 3000, "coin": 1200, "favorite": 900,
                  "share": 200, "danmaku": 150, "reply": 120}, "tname": "科技"},
        {"title": "直播回放", "owner": {"name": "Streamer", "mid": 3},
         "bvid": "BV3", "goto": "av", "duration": "7200", "pubdate": now - 86400 * 30,
         "stat": {"view": 5000, "like": 20, "coin": 5, "favorite": 4,
                  "share": 1, "danmaku": 10, "reply": 5}, "tname": "游戏"},
    ]
    items, cards, report = rank(sample)
    print("weights:", explain_weights())
    print("report:", json.dumps(report, ensure_ascii=False))
    for c in cards:
        print(" -", c["title"], "->", c["score"], c["tags"])

    # a synthetic stress feed: 40 items, mixed shapes, a couple of duplicates
    stress = []
    for i in range(40):
        stress.append({
            "title": "第 %d 期 干货盘点：%s" % (i, "原理" if i % 3 == 0 else "趣闻"),
            "owner": {"name": "UP%d" % (i % 5), "mid": i % 5},
            "bvid": "BV%d" % i, "goto": "av",
            "duration": str(60 + (i * 37) % 1800),
            "pubdate": now - (i % 20) * 86400,
            "stat": {"view": 1000 * (i + 1), "like": 100 * (i + 1),
                     "coin": 30 * (i + 1), "favorite": 20 * (i + 1),
                     "share": 5 * (i + 1), "danmaku": 10 * (i + 1),
                     "reply": 8 * (i + 1)},
            "tname": ["科技", "游戏", "生活", "知识"][i % 4],
        })
    stress_items, stress_cards, stress_report = rank(stress)
    assert len(stress_items) == 40, "every item should survive filtering"
    assert stress_report["kept"] == 40
    # diversity: no single UP may own more than MAX_PER_UP of the *primary* slots.
    # With 5 UPs each capped at 2, exactly 10 items are primary and 30 deferred.
    primary_count = stress_report["kept"] - stress_report["deferred"]
    up_freq = Counter(f.get("owner", {}).get("mid") for f in stress_items[:primary_count])
    assert max(up_freq.values()) <= MAX_PER_UP, "a UP exceeds the primary cap"
    print("stress kept:", stress_report["kept"], "primary:", primary_count,
          "max_per_up:", max(up_freq.values()), "dims:", stress_report["dims"])

    # sanity: a clickbait title must rank below an equally-engaged clean title
    clean = {"title": "React 性能优化实战教程", "owner": {"name": "X", "mid": 9},
             "bvid": "BVc", "goto": "av", "duration": "600", "pubdate": now - 7200,
             "stat": {"view": 50000, "like": 8000, "coin": 2000, "favorite": 1500,
                      "share": 600, "danmaku": 400, "reply": 300}, "tname": "科技"}
    bait = dict(clean)
    bait["title"] = "震惊！React 居然还能这样优化，不看后悔"
    bait["bvid"] = "BVb"
    bait["mid"] = 10
    rc, _, _ = rank([clean, bait])
    assert rc[0]["bvid"] == "BVc", "clean title should outrank clickbait"
    print("quality-gate OK: clean beats clickbait")


if __name__ == "__main__":
    _demo()
