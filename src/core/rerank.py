"""The rerank algorithm.

No whitelist: every item is scored from what the feed already returns (duration,
engagement ratios, publish time, title wording), filtered, de-duplicated per UP
and by title, then the whole thing is written back. Pure functions, no state.
"""

import json
import re
import time

from . import config


# --- item accessors ---------------------------------------------------------
def dig(item, path, default=0):
    cur = item
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def first(item, *paths, default=0):
    for path in paths:
        value = dig(item, path, None)
        if value not in (None, "", [], {}):
            return value
    return default


def num(value):
    try:
        if isinstance(value, str):
            value = re.sub(r"[^\d.]", "", value)
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def title_of(item):
    return str(item.get("title") or item.get("name") or "").strip()


def up_of(item):
    return dig(item, "owner.name", "") or item.get("author") or ""


def mid_of(item):
    return dig(item, "owner.mid", 0) or item.get("mid") or 0


def goto_of(item):
    return str(item.get("goto") or "")


def fingerprint(text):
    return re.sub(r"[\s\W_]+", "", text)[:14]


def is_ad(item):
    if goto_of(item) in ("ad", "cm"):
        return True
    ad = item.get("ad_info")
    return isinstance(ad, dict) and len(ad) > 0


def is_vertical(item):
    return goto_of(item) in ("vertical_av", "vertical_live")


# --- scoring ---------------------------------------------------------------
def score(item):
    tags = []
    total = config.BASE_SCORE

    title = title_of(item)
    view = num(first(item, "stat.view", "view", "args.stat.view", "cnt_info.play", "play"))
    like = num(first(item, "stat.like", "like", "args.stat.like", "cnt_info.like"))
    danmaku = num(first(item, "stat.danmaku", "danmaku", "args.stat.danmaku", "cnt_info.danmaku"))
    reply = num(first(item, "stat.reply", "reply", "args.stat.reply", "cnt_info.reply"))
    duration = num(first(item, "duration", "args.duration"))
    pubdate = num(first(item, "pubdate", "ctime", "args.pubdate", "pub_time"))

    if view > 0:
        engagement = (like + danmaku * 2.0 + reply * 3.0) / view
        total += min(engagement / 0.08, 1.0) * config.W_ENGAGEMENT
        if engagement >= 0.05:
            tags.append("tag.hot")
        elif view >= config.LOW_ENG_VIEWS and engagement < config.LOW_ENG_RATIO:
            total += config.W_LOW_ENGAGEMENT
            tags.append("tag.low_eng")

    if duration > 0:
        if config.SWEET_SECONDS[0] <= duration <= config.SWEET_SECONDS[1]:
            total += config.W_LENGTH
            tags.append("tag.length")
        elif duration < config.SHORT_SECONDS:
            total += config.W_SHORT
            tags.append("tag.short")
        elif duration > config.LONG_SECONDS:
            total += config.W_LONG

    if pubdate > 0:
        seconds = pubdate / 1000.0 if pubdate > 1e11 else pubdate
        age = (time.time() - seconds) / 86400.0
        if 0 <= age <= config.FRESH_DAYS:
            total += config.W_FRESH
            tags.append("tag.fresh")

    goto = goto_of(item)
    if goto == "av":
        total += config.W_VOD
    elif goto == "live":
        total += config.W_LIVE

    hits = sum(1 for word in config.CLICKBAIT_WORDS if word in title)
    if hits:
        total += max(config.W_CLICKBAIT * hits, config.W_CLICKBAIT_CAP)
        tags.append("tag.clickbait")

    if any(word in title for word in config.SPAM_WORDS):
        total += config.W_SPAM
        tags.append("tag.spam")

    if len(title) < 6:
        total += config.W_TINY_TITLE

    return total, tags


def rank(feed):
    """Filter, score, keep the top diverse, defer the rest. Returns
    (ordered_items, cards, report)."""
    kept = []
    ads = vertical = 0
    for item in feed:
        if is_ad(item):
            ads += 1
            continue
        if is_vertical(item):
            vertical += 1
            continue
        if not title_of(item):
            continue
        kept.append(item)

    scored = sorted(((score(item), item) for item in kept), key=lambda pair: -pair[0][0])

    per_up = {}
    seen = set()
    primary = []
    deferred = []

    for (value, tags), item in scored:
        key = fingerprint(title_of(item))
        if per_up.get(mid_of(item), 0) >= config.MAX_PER_UP:
            deferred.append((value - config.DIVERSITY_PENALTY, tags + ["tag.dup"], item))
            continue
        if key and key in seen:
            deferred.append((value - config.DIVERSITY_PENALTY, tags + ["tag.same_title"], item))
            continue
        per_up[mid_of(item)] = per_up.get(mid_of(item), 0) + 1
        if key:
            seen.add(key)
        primary.append((value, tags, item))

    # deferred items keep the tail; cap their score so the shown numbers
    # never look out of order
    if primary and deferred:
        floor = primary[-1][0]
        deferred = [
            (min(value, floor - 0.5 - index * 0.1), tags, item)
            for index, (value, tags, item) in enumerate(deferred)
        ]

    ordered = primary + deferred
    cards = [
        {
            "title": title_of(item),
            "up": up_of(item) or "?",
            "mid": mid_of(item),
            "bvid": str(first(item, "bvid", "args.bvid", "bvid_", default="")),
            "score": round(value, 1),
            "tags": tags,
        }
        for value, tags, item in ordered[:config.UI_LIMIT]
    ]
    report = {
        "seen": len(feed),
        "kept": len(ordered),
        "ads": ads,
        "vertical": vertical,
        "deferred": len(deferred),
        "top": round(ordered[0][0], 1) if ordered else 0.0,
        "head": [title_of(item)[:22] for _, _, item in ordered[:3]],
    }
    return [item for _, _, item in ordered], cards, report


# --- feed payloads ---------------------------------------------------------
def is_feed_url(url):
    low = url.lower()
    return any(hint in low for hint in config.FEED_URL_HINTS)


def is_refresh_url(url):
    """The client asked for a fresh first page (pull to refresh / re-entering the
    home tab): the accumulated list is dropped before the new items land."""
    low = url.lower()
    return any(hint in low for hint in config.REFRESH_URL_HINTS)


def looks_like_feed(text):
    return any(marker in text for marker in config.FEED_MARKERS)


def apply(text):
    """Raw feed JSON in, (new_json, cards, report) out - None when the payload
    is not a feed."""
    try:
        body = json.loads(text)
    except ValueError:
        return None

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None

    key = None
    for candidate in (config.FEED_KEY, config.FEED_KEY_ALT):
        if isinstance(data.get(candidate), list) and data[candidate]:
            key = candidate
            break
    if key is None:
        return None

    ordered, cards, report = rank(data[key])
    if not ordered:
        return None

    data[key] = ordered
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")), cards, report
