"""User settings, persisted as JSON next to the project root."""

import json

from . import config

DEFAULTS = {
    "theme": "dark",
    "lang": "zh",
    # when the client shows up, inject by itself (nothing is launched here)
    "watch_client": True,
}

_cache = None


def load():
    global _cache
    if _cache is not None:
        return _cache
    data = dict(DEFAULTS)
    try:
        # utf-8-sig: tolerate a BOM, hand edited files get one easily
        with open(config.SETTINGS_PATH, "r", encoding="utf-8-sig") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    _cache = data
    return _cache


def reload():
    """Drop the cache so the next read comes from the current settings path."""
    global _cache
    _cache = None
    return load()


def get(key, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def save():
    try:
        with open(config.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(load(), fh, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def update(**values):
    load().update(values)
    return save()


