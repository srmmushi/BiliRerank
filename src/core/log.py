"""Colored terminal logging with adjustable verbosity and i18n.

Log entries carry a translation key plus its arguments (never finished text),
exactly like the old GUI path, so they are rendered here in the active language.
Each line has a verbosity ``v`` (1 = most important ... 7 = deepest) compared
against the running debug level:

    debug level 1 -> errors + warnings only
    debug level 2 -> + normal operation (the default)
    debug level 3..6 -> progressively more detail
    debug level 7 -> everything, including per-video algorithm dumps
"""

import os
import sys

from .i18n import Translator

_COLORS = {
    "reset": "\033[0m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "gray": "\033[90m",
}

_LEVEL_COLOR = {
    "error": "red",
    "warn": "yellow",
    "success": "green",
    "info": "cyan",
    "debug": "gray",
}

# default verbosity by severity when a call does not pass `v` explicitly
_SEVERITY_V = {"error": 0, "warn": 0, "success": 2, "info": 2, "debug": 7}


def _enable_vt():
    """Turn on ANSI escape processing in the Windows console (no extra deps)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32(0)
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


class Console:
    def __init__(self):
        self.lang = "zh"
        self.debug = 2
        self.translator = Translator("zh")
        self._file = None
        _enable_vt()

    def configure(self, lang, debug):
        if lang in ("zh", "en"):
            self.lang = lang
        try:
            self.debug = max(1, min(7, int(debug)))
        except (TypeError, ValueError):
            self.debug = 2
        self.translator.set(self.lang)

    def _stream(self):
        """Return None for the live terminal, else an open file for background runs."""
        if sys.stdout is not None:
            return None
        if self._file is None:
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                path = os.path.join(here, "..", "..", "bilirerank.log")
                self._file = open(os.path.abspath(path), "a", encoding="utf-8")
            except OSError:
                self._file = False
        return self._file if self._file is not False else None

    def emit(self, stamp, level, key, args, source, v):
        if level in ("error", "warn"):
            show = True
        else:
            show = v is not None and v <= self.debug
        if not show:
            return

        if key == "raw":
            text = (args or {}).get("text", "")
        else:
            text = self.translator.t(key, args)

        head = ("%s %s" % (stamp, level.upper().ljust(7)))
        if source:
            head += " [%s]" % source

        color = _COLORS.get(_LEVEL_COLOR.get(level, "white"), "")
        reset = _COLORS["reset"]
        line = "%s%s%s %s" % (color, head, reset, text)

        stream = self._stream()
        if stream is None:
            try:
                print(line)
            except Exception:
                pass
        else:
            try:
                stream.write(line + "\n")
                stream.flush()
            except Exception:
                pass


console = Console()
