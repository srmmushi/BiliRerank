"""Terminal entry point.

Replaces the old Qt GUI: it parses the command line, starts the client watcher
(which injects into the Bilibili desktop client as soon as it appears), streams
colored, i18n-aware logs to the terminal, and always cancels the injection on
exit (Ctrl+C or process end).

    python main.py [--debug [N]] [--lang zh|en] [--algorithm NAME]
                   [--start-on-boot {enable|disable}]

Flags
-----
--debug [N]    verbosity 1..7 (default 1; bare ``--debug`` = 7, which dumps the
               algorithm trace for every single video). Levels 1..4 add incremental
               detail; 5 = per-feed dimension averages, 6 = one line per video,
               7 = the full per-video breakdown.
--lang zh|en   switch UI/log language (persisted to settings.json).
--algorithm NAME
               rerank algorithm: weighted/gnn/bandit/mmr/sequential/pareto/
               counterfactual (persisted to settings.json, default gnn).
--start-on-boot {enable|disable}
               enable  = register a background logon task (next sign-in auto
                         injects), then exit.
               disable = remove that task, then exit. Bare ``--start-on-boot``
                         defaults to enable.
"""

import argparse
import atexit
import os
import subprocess
import sys
import time

from .core import config, log, rerank, settings
from .core.log import console
from .backends import start_watcher, stop_watcher, stop_all

# Stop child processes (tasklist / taskkill / client launch) popping their own
# console window when we are running without one of our own.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _build_parser():
    p = argparse.ArgumentParser(
        prog="BiliRerank",
        description="B站推荐流本地重排 · 终端模式 (Bilibili feed rerank, terminal mode)")
    p.add_argument("--debug", nargs="?", const=7, type=int, default=1,
                   help="调试等级 1-7（默认 1；--debug 不带数字=7，显示每个视频的算法过程）")
    p.add_argument("--lang", choices=["zh", "en"], default=None,
                   help="界面/日志语言 language")
    p.add_argument("--algorithm", choices=rerank.ALGORITHM_NAMES, default=None,
                   help="重排算法：weighted/gnn/bandit/mmr/sequential/pareto/counterfactual")
    p.add_argument("--start-on-boot", nargs="?", const="enable",
                   choices=["enable", "disable"],
                   help="开机自启（随后退出）：enable=开启后台自启，disable=关闭；省略参数默认 enable")
    p.add_argument("--boot", action="store_true",
                   help="(内部) 被计划任务调用的后台实例标记")
    return p


def _pythonw():
    """Interpreter to use for the background (no-console) auto-start task."""
    if getattr(sys, "frozen", False):
        return sys.executable
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def _register_boot():
    main_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    cmd = '"%s" "%s" --boot' % (_pythonw(), main_py)
    try:
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", "BiliRerank", "/TR", cmd,
             "/SC", "ONLOGON", "/F"],
            capture_output=True, text=True, creationflags=_NO_WINDOW)
    except Exception as exc:  # pragma: no cover - environment dependent
        console.emit(time.strftime("%H:%M:%S"), "error", "cli.boot_failed",
                     {"err": str(exc)}, None, 0)
        return False
    if r.returncode != 0:
        console.emit(time.strftime("%H:%M:%S"), "error", "cli.boot_failed",
                     {"err": (r.stderr or r.stdout or "").strip()}, None, 0)
        return False
    return True


def _unregister_boot():
    try:
        r = subprocess.run(["schtasks", "/Delete", "/TN", "BiliRerank", "/F"],
                           capture_output=True, text=True, creationflags=_NO_WINDOW)
    except Exception as exc:  # pragma: no cover - environment dependent
        console.emit(time.strftime("%H:%M:%S"), "error", "cli.boot_failed",
                     {"err": str(exc)}, None, 0)
        return False
    if r.returncode == 0:
        return True
    # already removed is fine - the goal (no auto-start) is achieved
    msg = (r.stderr or r.stdout or "").strip().lower()
    if "cannot find" in msg or "does not exist" in msg or "找不到" in msg:
        return True
    console.emit(time.strftime("%H:%M:%S"), "error", "cli.boot_failed",
                 {"err": (r.stderr or r.stdout or "").strip()}, None, 0)
    return False


def _client_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq " + config.PROCESS, "/FO", "CSV", "/NH"],
            capture_output=True, timeout=20, creationflags=_NO_WINDOW).stdout
        text = out.decode("utf-8", "replace")
        if "\ufffd" in text:
            text = out.decode("gbk", "replace")
        return config.PROCESS.lower() in text.lower()
    except Exception:
        return False


def main(argv=None):
    args = _build_parser().parse_args(argv)

    lang = args.lang or settings.get("lang", "zh")
    settings.update(lang=lang)
    console.configure(lang, args.debug)
    rerank.set_debug(args.debug or 0)

    algorithm = args.algorithm or settings.get("algorithm", "gnn")
    rerank.set_algorithm(algorithm)
    settings.update(algorithm=algorithm)

    console.emit(time.strftime("%H:%M:%S"), "info", "cli.banner",
                 {"version": config.VERSION}, None, 1)
    console.emit(time.strftime("%H:%M:%S"), "info", "cli.lang", {"lang": lang}, None, 1)
    console.emit(time.strftime("%H:%M:%S"), "info", "cli.debug",
                 {"level": console.debug}, None, 1)
    console.emit(time.strftime("%H:%M:%S"), "info", "cli.algorithm",
                 {"name": rerank.get_algorithm()}, None, 1)

    if args.start_on_boot:
        if args.start_on_boot == "disable":
            if _unregister_boot():
                console.emit(time.strftime("%H:%M:%S"), "success", "cli.boot_disabled", {}, None, 0)
        else:
            if _register_boot():
                console.emit(time.strftime("%H:%M:%S"), "success", "cli.boot_enabled", {}, None, 0)
        return 0

    console.emit(time.strftime("%H:%M:%S"), "info", "cli.starting", {}, None, 1)
    if not _client_running():
        console.emit(time.strftime("%H:%M:%S"), "info", "cli.client_missing", {}, None, 1)

    def _cleanup():
        console.emit(time.strftime("%H:%M:%S"), "info", "cli.stop", {}, None, 1)
        try:
            stop_all()
        except Exception:
            pass
        try:
            stop_watcher()
        except Exception:
            pass
    atexit.register(_cleanup)

    start_watcher()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0
