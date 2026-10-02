"""BiliRerank - terminal entry point.

    C:\\app\\Python313\\python.exe main.py [--debug [N]] [--lang zh|en] [--start-on-boot]

The program injects into the Bilibili desktop client, reranks its feed with a
hardcoded GNN algorithm, streams colored logs to the terminal, and cancels the
injection on exit.
"""

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
