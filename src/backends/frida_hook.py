"""frida backend.

Attaches to the client once and loads hook scripts from the config folder
(<config dir>/script/). The bundled scripts are released there on first run and
never rewritten afterwards - this app does not modify hook scripts.

Each script gets its own message channel, so every log line can say which script
reported it and the tools page can drive one script at a time.

frida can only observe: its callbacks are asynchronous, so a modified body would
arrive after the caller already consumed the original. Rewriting the feed is the
devtools backend's job - both can run at the same time, feeds captured twice are
de-duplicated by bvid in core.store.
"""

import os
import threading

from ..core import config, rerank, store

try:
    import frida
except ImportError:          # the GUI stays importable so the failure shows up in the log panel
    frida = None

_lock = threading.Lock()
_session = None
_scripts = {}                # name -> frida script object


def ensure_dir():
    """Script folder next to the settings file, seeded with the bundled scripts."""
    target = config.script_dir()
    os.makedirs(target, exist_ok=True)
    released = config.release_scripts()
    if released:
        store.add_log("success", "py.script_released", {"names": ", ".join(released)})
    return target


def list_scripts():
    ensure_dir()
    names = [n for n in os.listdir(config.script_dir()) if n.lower().endswith(".js")]
    return sorted(names, key=lambda n: (n != "rcmd.js", n.lower()))


def path_of(name):
    return os.path.join(config.script_dir(), os.path.basename(name))


def read_script(name):
    try:
        with open(path_of(name), "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        store.add_log("error", "py.script_read_failed", {"err": str(exc)}, source=name)
        return ""


def write_script(name, source):
    """The edit dialog saves here - the app never rewrites a script on its own."""
    ensure_dir()
    try:
        with open(path_of(name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source if source.endswith("\n") else source + "\n")
    except OSError as exc:
        store.add_log("error", "py.script_write_failed", {"err": str(exc)}, source=name)
        return False
    if name in running_scripts():          # an edited running script is stale now
        return reload(name)
    store.add_log("success", "py.script_saved", {"path": name}, source=name)
    return True


def delete_script(name):
    """Delete a script file. The bundled ones come back on the next start."""
    try:
        os.remove(path_of(name))
    except OSError:
        return False
    unload(name)
    store.add_log("success", "py.script_deleted", {"path": name}, source=name)
    return True


def is_running():
    with _lock:
        return _session is not None


def running_scripts():
    with _lock:
        return sorted(_scripts)


def _find_process():
    try:
        procs = frida.get_local_device().enumerate_processes()
    except Exception:
        return None
    for proc in procs:
        if proc.name == config.PROCESS:
            return proc
    for proc in procs:
        low = proc.name.lower()
        if any(hint in low for hint in config.NAME_HINTS):
            return proc
    return None


def _on_message(name, message, data):
    if message.get("type") == "error":
        store.add_log("error", "raw", {"text": "%s: %s" % (
            name, message.get("description", "script error"))}, source=name)
        stack = (message.get("stack") or "").strip().splitlines()[:1]
        if stack:
            store.add_log("error", "raw", {"text": stack[0]}, source=name)
        return

    payload = message.get("payload") or {}
    kind = payload.get("type")

    if kind == "log":
        level = payload.get("level", "info")
        args = payload.get("args") or {}
        if "key" in payload:
            if payload["key"] in ("js.loaded", "js.installed"):
                args["script"] = name
            store.add_log(level, payload["key"], args, source=name)
        else:
            store.add_log(level, "raw", {"text": payload.get("msg", "")}, source=name)
    elif kind == "feed":
        _report(payload.get("raw", ""), name)
    elif kind == "items":                      # older script shape
        store.append_items(payload.get("data") or [])


def _report(text, name):
    result = rerank.apply(text)
    if result is None:
        return
    _, cards, report = result
    added = store.append_items(cards)
    store.bump(feeds=1, ads=report["ads"], vertical=report["vertical"],
               deferred=report["deferred"], added=added)
    store.set_runtime(top=report["top"])
    store.add_log("success", "rr.done", {
        "seen": report["seen"], "kept": report["kept"], "ads": report["ads"],
        "vertical": report["vertical"], "deferred": report["deferred"], "top": report["top"],
    }, source=name)
    store.add_log("info", "rr.added", {"added": added, "total": len(store.items),
                                       "script": name}, source=name)


def _destroyed(name):
    def handler():
        with _lock:
            _scripts.pop(name, None)
            alive = bool(_scripts)
        store.set_script_state(name, False)
        if not alive:
            store.set_runtime(connecting=False, running=False, backend="")
        store.add_log("warn", "py.destroyed", {"script": name}, source=name)
    return handler


def attach():
    """Attach to the client - the session is what `running` means here."""
    global _session
    if _session is not None:
        return True
    if frida is None:
        store.add_log("error", "py.frida_missing")
        return False

    proc = _find_process()
    if proc is None:
        store.add_log("error", "py.not_running", {"process": config.PROCESS})
        return False

    store.add_log("info", "py.attaching", {"process": config.PROCESS})
    try:
        _session = frida.attach(proc.pid)
    except Exception as exc:
        store.add_log("error", "py.attach_failed", {"err": str(exc)})
        store.add_log("info", "py.attach_hint")
        _session = None
        return False

    store.add_log("success", "py.attached",
                  {"target": "%s (pid %d)" % (proc.name, proc.pid)})
    return True


def load(name):
    """Load one script into the current session."""
    if _session is None:
        return False
    source = read_script(name)
    if not source.strip():
        store.add_log("warn", "py.script_empty", {"path": name}, source=name)
        return False
    try:
        script = _session.create_script(source)
        script.on("message", lambda message, data, n=name: _on_message(n, message, data))
        script.on("destroyed", _destroyed(name))
        script.load()
    except Exception as exc:
        store.add_log("error", "py.script_failed", {"err": str(exc), "script": name}, source=name)
        return False
    with _lock:
        _scripts[name] = script
    store.set_script_state(name, True)
    store.add_log("success", "py.script_loaded", {"script": name}, source=name)
    return True


def unload(name):
    with _lock:
        script = _scripts.pop(name, None)
    if script is None:
        return False
    try:
        script.unload()
    except Exception as exc:
        store.add_log("warn", "py.unload_failed", {"err": str(exc), "script": name}, source=name)
    store.set_script_state(name, False)
    store.add_log("info", "py.script_unloaded", {"script": name}, source=name)
    return True


def start(only=None):
    """Attach, then load every script in the folder (or just `only`).

    Anything already loaded is dropped first: the Inject button means "inject
    them all", including the scripts that were stopped by hand.
    """
    if not attach():
        return False
    names = list_scripts()
    if not names:
        store.add_log("warn", "py.no_scripts")
        return False
    if only is None:
        for name in running_scripts():
            unload(name)
    for name in ([only] if only else names):
        load(name)
    active = bool(running_scripts())
    store.set_runtime(running=active, connecting=False, backend="frida",
                      target="%s +%d" % (config.PROCESS, len(running_scripts())))
    return active


def start_script(name):
    """Tools page: attach if needed, then load this one script."""
    if not os.path.exists(path_of(name)):
        store.add_log("error", "py.script_missing", {"script": name})
        return False
    if name in running_scripts():
        store.add_log("info", "py.script_already", {"script": name}, source=name)
        return True
    if not attach():
        return False
    loaded = load(name)
    if loaded:
        store.set_runtime(running=True, connecting=False, backend="frida",
                          target="%s +%d" % (config.PROCESS, len(running_scripts())))
    return loaded


def stop_script(name):
    """Tools page: drop one script, keep the rest (and the session) alive."""
    if not unload(name):
        return False
    store.set_runtime(target="%s +%d" % (config.PROCESS, len(running_scripts())),
                      running=bool(running_scripts()))
    return True


def reload(name):
    """Drop and re-load one script - used after it was edited."""
    if name not in running_scripts():
        return start(only=name)
    unload(name)
    return load(name)


def stop():
    global _session
    names = running_scripts()
    for name in names:
        unload(name)
    if _session is not None:
        try:
            _session.detach()
        except Exception:
            pass
        _session = None
    store.set_runtime(connecting=False, running=False, backend="")
    if names:
        store.add_log("info", "py.stopped")
    else:
        # no script was loaded, so stop had nothing to do - say so instead of
        # leaving the log untouched
        store.add_log("info", "py.nothing_running")
