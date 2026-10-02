"""Transport layer.

`inject()` is what the CLI calls: devtools takes the feed over (it is the only
backend - it intercepts the response, reranks and writes it back). `stop_all()`
tears it down.

`start_watcher()` watches the client process and injects when it appears - the
tool never launches the client itself.
"""

import threading
import time

from ..core import config, settings, store
from . import devtools

__all__ = ["devtools", "inject", "stop_all", "restart_client",
           "start_watcher", "stop_watcher", "back", "CDP_GRACE"]

CDP_GRACE = 40               # polls of 0.5s while the devtools backend settles

_watch_thread = None
_watch_stop = threading.Event()
_seen = False


def inject():
    """DevTools for the feed (the only backend)."""
    store.add_log("info", "inject.start")
    store.set_runtime(connecting=True, backend="")

    if devtools.start():
        for _ in range(CDP_GRACE):
            time.sleep(0.5)
            if store.runtime["running"] or not devtools.is_running():
                break
        if store.runtime["running"]:
            store.add_log("success", "inject.cdp_ok")
            return True
    store.set_runtime(connecting=False)

    store.add_log("warn", "inject.fallback")
    return False


def stop_all():
    devtools.stop()
    store.set_runtime(connecting=False, running=False, backend="")


def back():
    """Back button: bring back the list from before the last client refresh."""
    rows = store.pop_history()
    if not rows:
        store.add_log("warn", "py.back_empty")
        return False
    store.set_items(rows)
    store.add_log("success", "py.back_done", {"n": len(rows)})
    return True


def restart_client():
    return devtools.restart_client()


# --- client watcher ---------------------------------------------------------
def start_watcher():
    """Inject when the client shows up, stand down when it quits."""
    global _watch_thread
    if _watch_thread is not None and _watch_thread.is_alive():
        return
    _watch_stop.clear()
    _watch_thread = threading.Thread(target=_watch, daemon=True, name="biliRerank-watch")
    _watch_thread.start()


def stop_watcher():
    _watch_stop.set()


def _watch():
    global _seen
    while not _watch_stop.is_set():
        try:
            running = devtools._process_running()
            if running and not _seen:
                _seen = True
                store.add_log("success", "watch.up", {"process": config.PROCESS})
                if settings.get("watch_client"):
                    inject()
            elif not running and _seen:
                _seen = False
                store.add_log("warn", "watch.down", {"process": config.PROCESS})
                if store.runtime["running"]:
                    stop_all()
        except Exception as exc:
            store.add_log("error", "watch.error", {"err": str(exc)})
        _watch_stop.wait(config.WATCH_INTERVAL)
