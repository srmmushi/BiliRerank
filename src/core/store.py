"""Shared state between the transport threads and the GUI thread.

Log entries carry a translation key plus its arguments, never finished text, so
the GUI can render the whole history in either language.
"""

import threading
import time

from . import config, log

logs = []
items = []
history = []                 # lists from before a client refresh, oldest first
version = 0
HISTORY_LIMIT = 5
runtime = {
    "running": False,
    "connecting": False,
    "backend": "",
    "target": "",
    "can_back": False,
    "feeds": 0,
    "added": 0,
    "ads": 0,
    "vertical": 0,
    "deferred": 0,
    "rewritten": 0,
    "top": 0.0,
}

_lock = threading.Lock()


def add_log(level, key, args=None, source=None, v=None):
    """`source` is the script a line belongs to (None for tool wide lines).

    `v` is the verbosity (1 = most important ... 7 = deepest); core.log compares
    it against the running debug level. When omitted it is derived from severity:
    errors/warnings always show, success/info at v=2, debug at v=7.
    """
    global version
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        logs.append({"time": stamp, "level": level, "key": key, "args": args,
                     "source": source})
        if len(logs) > config.MAX_LOGS:
            del logs[:-config.MAX_LOGS]
        version += 1
    if v is None:
        v = {"error": 0, "warn": 0, "success": 2, "info": 2, "debug": 7}.get(level, 2)
    try:
        log.console.emit(stamp, level, key, args, source, v)
    except Exception:
        pass


def set_items(rows):
    with _lock:
        items[:] = rows


def append_items(rows):
    """The list only grows: scrolling the client keeps adding cards, and only a
    manual refresh clears it. Items already seen are refreshed in place (their
    score can change between feeds). Returns how many were new."""
    with _lock:
        known = {(row.get("bvid") or row.get("title")): index for index, row in enumerate(items)}
        added = 0
        for row in rows:
            key = row.get("bvid") or row.get("title")
            if key in known:
                items[known[key]] = row
                continue
            if len(items) >= config.MAX_FEED:
                break
            known[key] = len(items)
            items.append(row)
            added += 1
        return added


def clear_items():
    with _lock:
        items.clear()


def push_history():
    """Keep the current list so the Back button can bring it back after the
    client pulled to refresh. Nothing to remember when the list is empty."""
    with _lock:
        if not items:
            return False
        history.append(list(items))
        del history[:-HISTORY_LIMIT]
        runtime["can_back"] = True
        return True


def pop_history():
    with _lock:
        snapshot = history.pop() if history else None
        runtime["can_back"] = bool(history)
        return snapshot


def set_runtime(**kw):
    with _lock:
        runtime.update(kw)


def bump(**kw):
    with _lock:
        for key, delta in kw.items():
            runtime[key] = runtime.get(key, 0) + delta



