"""BiliHook - entry point.

    C:\\app\\Python313\\python.exe main.py

Importing src.ui pulls in PyQt-SiliconUI first (it pins QT_SCALE_FACTOR from the
system DPI), then everything else lives under src/: core (config, settings,
store, algorithm), backends (devtools / frida) and ui (Qt window, pages, theme).
"""

import sys

from src.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
