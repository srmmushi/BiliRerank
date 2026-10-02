"""Shared state between the transport threads and the GUI thread.

Log entries carry a translation key plus its arguments, never finished text, so
the GUI can render the whole history in either language.
"""

import threading
import time

from . import config

logs = []
items = []
scripts = {}                 # script name -> running, mirrored by the tools page
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


def add_log(level, key, args=None, source=None):
    """`source` is the script a line belongs to (None for tool wide lines):
    the log page filters on it, the tools page uses it to pick a script."""
    global version
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        logs.append({"time": stamp, "level": level, "key": key, "args": args,
                     "source": source})
        if len(logs) > config.MAX_LOGS:
            del logs[:-config.MAX_LOGS]
        version += 1
    print("[%s] %-7s %s %s" % (stamp, level, key, args or ""))


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


def set_script_state(name, running):
    with _lock:
        if running:
            scripts[name] = True
        else:
            scripts.pop(name, None)


def running_scripts():
    with _lock:
        return sorted(scripts)


def snapshot():
    """(logs, items, version, runtime, scripts) - copies, safe for the UI loop."""
    with _lock:
        return list(logs), list(items), version, dict(runtime), sorted(scripts)
