"""DevTools protocol backend.

The current client is Electron based, so the feed is fetched and parsed in JS and
there is no native export worth hooking. This backend drives the client over CDP:
it makes sure the client runs with --remote-debugging-port, attaches to every
page target, intercepts the feed response, swaps in the reranked JSON and lets
the app render it as usual.

Runs in its own thread with its own event loop; the GUI only reads core.store.
"""

import asyncio
import base64
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

from ..core import config, rerank, store

try:
    import websockets
except ImportError:          # reported in the log panel instead of crashing the GUI
    websockets = None

BASE = "http://%s:%d" % (config.HOST, config.DEBUG_PORT)

_thread = None
_stop = threading.Event()


def is_running():
    return _thread is not None and _thread.is_alive()


def start():
    global _thread
    if is_running():
        # a previous session may still be unwinding: signal it and give it a moment
        _stop.set()
        _thread.join(timeout=3)
        if is_running():
            store.add_log("warn", "cdp.already")
            return False
    if websockets is None:
        store.add_log("error", "cdp.no_websockets")
        return False
    _stop.clear()
    _thread = threading.Thread(target=_serve, daemon=True, name="biliRerank-cdp")
    _thread.start()
    return True


def stop():
    # the attach loops poll this flag once a second and unwind on their own
    _stop.set()
    store.set_runtime(connecting=False, running=False, backend="")


# --- client discovery -------------------------------------------------------
def _client_pids():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq " + config.PROCESS, "/FO", "CSV", "/NH"],
            capture_output=True, timeout=20,
        ).stdout
    except Exception:
        return []

    text = out.decode("utf-8", "replace")
    if "\ufffd" in text:
        text = out.decode("gbk", "replace")

    pids = []
    for line in text.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def _proc_path(pid):
    """Full image path of a running process - ctypes, no extra dependency."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)      # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
    except OSError:
        pass
    finally:
        kernel32.CloseHandle(handle)
    return None


def _scan_dir(path):
    try:
        for name in os.listdir(path):
            low = name.lower()
            if low.endswith(".exe") and any(h in low for h in ("哔哩哔哩", "bilibili")):
                return os.path.join(path, name)
    except OSError:
        pass
    return None


def find_client_exe():
    """The path of a running client first - that is the install actually in use -
    then uninstall registry entries and the usual install dirs."""
    for pid in _client_pids():
        path = _proc_path(pid)
        if path and os.path.exists(path):
            return path

    local = os.environ.get("LOCALAPPDATA", "")
    for guess in (
        os.path.join(local, "Programs", "bilibili"),
        os.path.join(local, "哔哩哔哩"),
        os.path.join(local, "Programs", "哔哩哔哩"),
        r"C:\Program Files\哔哩哔哩",
        r"C:\Program Files (x86)\哔哩哔哩",
        r"C:\Program Files\bilibili",
    ):
        hit = _scan_dir(guess)
        if hit:
            return hit

    try:
        import winreg
    except ImportError:
        return None

    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, root in roots:
        try:
            key = winreg.OpenKey(hive, root)
        except OSError:
            continue
        with key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, index)) as sub:
                        display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        if not any(h in display.lower() for h in ("哔哩哔哩", "bilibili")):
                            continue
                        for value in ("DisplayIcon", "InstallLocation"):
                            try:
                                raw = str(winreg.QueryValueEx(sub, value)[0])
                            except OSError:
                                continue
                            raw = raw.strip('"').split(",")[0]
                            if raw.lower().endswith(".exe") and os.path.exists(raw):
                                return raw
                            hit = _scan_dir(raw)
                            if hit:
                                return hit
                except OSError:
                    continue
    return None


def _http(path, timeout=1.5):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _process_running():
    # name matching on tasklist output is codepage dependent, the pid column is not
    return bool(_client_pids())


def _kill_client():
    try:
        subprocess.run(["taskkill", "/IM", config.PROCESS, "/F"], capture_output=True, timeout=20)
        time.sleep(1.5)
        return True
    except Exception as exc:
        store.add_log("warn", "cdp.kill_failed", {"err": str(exc)})
        return False


def _wait_port(secs):
    deadline = time.time() + secs
    while time.time() < deadline and not _stop.is_set():
        if _http("/json/version") is not None:
            return True
        time.sleep(0.7)
    return _http("/json/version") is not None


def ensure_client():
    """The client is expected to be running here - nothing is launched for the
    user. Without the debug port there is nothing to attach to, so explain how
    to get one instead of quietly restarting their client."""
    if _http("/json/version") is not None:
        store.add_log("info", "cdp.port_open", {"port": config.DEBUG_PORT})
        return True
    if _process_running():
        store.add_log("error", "cdp.no_port", {"port": config.DEBUG_PORT})
    else:
        store.add_log("error", "cdp.not_running", {"process": config.PROCESS})
    return False


def restart_client():
    """Manual action: restart the client with the debug port so CDP can attach.
    The watcher never does this by itself."""
    exe = find_client_exe()
    if exe is None:
        store.add_log("error", "cdp.no_exe")
        return False
    if _process_running():
        store.add_log("warn", "cdp.restarting", {"port": config.DEBUG_PORT})
        _kill_client()
    store.add_log("info", "cdp.launching", {"exe": exe, "port": config.DEBUG_PORT})
    try:
        subprocess.Popen([exe, "--remote-debugging-port=%d" % config.DEBUG_PORT], close_fds=True)
    except Exception as exc:
        store.add_log("error", "cdp.launch_failed", {"err": str(exc)})
        return False
    if not _wait_port(config.PORT_WAIT):
        store.add_log("error", "cdp.port_timeout",
                      {"port": config.DEBUG_PORT, "secs": config.PORT_WAIT})
        return False
    store.add_log("success", "cdp.port_ready", {"port": config.DEBUG_PORT})
    return True


# --- CDP session ------------------------------------------------------------
class Session:
    """Request/response wrapper; incoming events land on a queue."""

    def __init__(self, ws):
        self.ws = ws
        self.pending = {}
        self.events = asyncio.Queue()
        self.seq = 0

    async def reader(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self.pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"].get("message", "cdp error")))
                    else:
                        fut.set_result(msg.get("result", {}))
            else:
                await self.events.put(msg)

    async def send(self, method, params=None):
        self.seq += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.seq] = fut
        await self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        return await fut


def _short(url):
    return url.split("?")[0][-70:]


async def _continue(session, request_id, state):
    if not state["continue"]:
        try:
            await session.send("Fetch.continueResponse", {"requestId": request_id})
            return
        except Exception:
            state["continue"] = "request"
    method = "Fetch.continueRequest" if state["continue"] == "request" else "Fetch.continueResponse"
    try:
        await session.send(method, {"requestId": request_id})
    except Exception as exc:
        store.add_log("warn", "cdp.continue_failed", {"err": str(exc)})


async def _handle_pause(session, params, state):
    request_id = params.get("requestId")
    url = (params.get("request") or {}).get("url", "")

    if not rerank.is_feed_url(url) or params.get("responseStatusCode") != 200:
        await _continue(session, request_id, state)
        return

    try:
        body = await session.send("Fetch.getResponseBody", {"requestId": request_id})
    except Exception as exc:
        store.add_log("warn", "cdp.body_failed", {"err": str(exc)})
        await _continue(session, request_id, state)
        return

    raw = body.get("body", "")
    if body.get("base64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8", "replace")
        except Exception:
            await _continue(session, request_id, state)
            return

    if len(raw) > config.BODY_LIMIT or not rerank.looks_like_feed(raw):
        state["seen"] += 1
        if state["seen"] <= 6:
            store.add_log("info", "cdp.not_feed", {"url": _short(url)})
        await _continue(session, request_id, state)
        return

    result = rerank.apply(raw)
    if result is None:
        await _continue(session, request_id, state)
        return

    new_body, cards, report = result
    headers = [h for h in (params.get("responseHeaders") or [])
               if h.get("name", "").lower() not in config.DROP_HEADERS]
    try:
        await session.send("Fetch.fulfillRequest", {
            "requestId": request_id,
            "responseCode": params.get("responseStatusCode", 200),
            "responseHeaders": headers,
            "body": base64.b64encode(new_body.encode("utf-8")).decode("ascii"),
        })
    except Exception as exc:
        store.add_log("error", "cdp.fulfill_failed", {"err": str(exc)})
        return

    if rerank.is_refresh_url(url):
        # the client pulled to refresh: the old list is stale, but keep it so
        # the Back button in the header can bring it back
        store.push_history()
        store.clear_items()
        store.add_log("info", "rr.cleared")

    added = store.append_items(cards)
    store.bump(feeds=1, ads=report["ads"], vertical=report["vertical"],
               deferred=report["deferred"], rewritten=1, added=added)
    store.set_runtime(top=report["top"])
    store.add_log("success", "rr.done", {
        "seen": report["seen"], "kept": report["kept"], "ads": report["ads"],
        "vertical": report["vertical"], "deferred": report["deferred"], "top": report["top"],
    })
    store.add_log("info", "rr.added", {"added": added, "total": len(store.items)})
    store.add_log("info", "rr.head", {"list": ", ".join(report["head"]) or "-"})


async def _attach(target):
    state = {"continue": "", "seen": 0}
    try:
        async with websockets.connect(target["webSocketDebuggerUrl"],
                                      max_size=16 * 1024 * 1024) as ws:
            session = Session(ws)
            reader = asyncio.create_task(session.reader())
            await session.send("Fetch.enable", {
                "patterns": [{"urlPattern": "*", "requestStage": "Response"}]
            })
            store.add_log("success", "cdp.attached", {"title": (target.get("title") or "")[:40]})
            try:
                while not _stop.is_set():
                    try:
                        msg = await asyncio.wait_for(session.events.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if msg.get("method") == "Fetch.requestPaused":
                        await _handle_pause(session, msg.get("params") or {}, state)
            finally:
                reader.cancel()
    except Exception as exc:
        store.add_log("error", "cdp.error", {"err": str(exc)})


def _serve():
    try:
        asyncio.run(_async_main())
    except Exception as exc:
        store.add_log("error", "cdp.error", {"err": str(exc)})
    finally:
        store.set_runtime(connecting=False, running=False, backend="")
        store.add_log("warn", "cdp.closed")


async def _async_main():
    store.add_log("info", "cdp.connecting", {"port": config.DEBUG_PORT})
    if not await asyncio.to_thread(ensure_client):
        return

    tabs = _http("/json/list", timeout=3) or []
    targets = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not targets:
        store.add_log("error", "cdp.no_target")
        return

    store.set_runtime(running=True, connecting=False, backend="cdp",
                      target="%s:%d" % (config.HOST, config.DEBUG_PORT))
    store.add_log("success", "cdp.intercepting",
                  {"n": len(targets), "port": config.DEBUG_PORT})
    await asyncio.gather(*[_attach(t) for t in targets])
