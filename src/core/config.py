"""All the knobs in one place: client, transport, paths and scoring weights."""

import os
import sys

APP_NAME = "BiliRerank"
VERSION = "1.0.1"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
if getattr(sys, "frozen", False):
    # packaged with PyInstaller: the code and the bundled assets live in the
    # temp extraction dir, everything writable has to sit next to the exe
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(SRC)

# The settings file can live anywhere; this tiny file next to the code remembers
# where, so the choice survives a restart without needing the settings themselves.
SETTINGS_NAME = "settings.json"
DEFAULT_SETTINGS_PATH = os.path.join(ROOT, SETTINGS_NAME)
POINTER_PATH = os.path.join(ROOT, ".settings-path")


def _read_pointer():
    try:
        with open(POINTER_PATH, "r", encoding="utf-8-sig") as fh:
            pointed = fh.read().strip()
    except OSError:
        return None
    return pointed or None


def apply_settings_path(path):
    """Point the app at another settings file. None goes back to the default."""
    global SETTINGS_PATH
    target = os.path.abspath(path) if path else DEFAULT_SETTINGS_PATH
    try:
        if os.path.abspath(target) == os.path.abspath(DEFAULT_SETTINGS_PATH):
            if os.path.exists(POINTER_PATH):
                os.remove(POINTER_PATH)
        else:
            with open(POINTER_PATH, "w", encoding="utf-8") as fh:
                fh.write(target)
    except OSError:
        return False
    SETTINGS_PATH = target
    return True


SETTINGS_PATH = _read_pointer() or DEFAULT_SETTINGS_PATH


# --- client -----------------------------------------------------------------
PROCESS = "哔哩哔哩.exe"
NAME_HINTS = ("哔哩哔哩", "bilibili", "bili")
WATCH_INTERVAL = 2.0         # seconds between client liveness checks

# --- transport --------------------------------------------------------------
DEBUG_PORT = 9222
HOST = "127.0.0.1"
PORT_WAIT = 25               # seconds to wait for the debug port
BODY_LIMIT = 4 * 1024 * 1024
DROP_HEADERS = ("content-encoding", "content-length", "transfer-encoding")

FEED_URL_HINTS = (
    "feed/rcmd",
    "feed/index",
    "rcmd_reason",
    "index/top/feed",
    "recommend",
    "/x/v2/feed",
)
# A pull-to-refresh in the client asks for the first page again: that is the
# signal to drop the accumulated list and start over.
REFRESH_URL_HINTS = (
    "refresh",
    "pull=true",
    "pull=1",
    "fresh_type=3",
    "idx=0",
    "idx=1",
)
FEED_MARKERS = ('"rcmd_reason"', '"items":[', '"item":[', '"goto":"av"')
FEED_KEY = "items"           # app feed
FEED_KEY_ALT = "item"        # web feed (rcmd by index)

# --- ui ---------------------------------------------------------------------
MAX_LOGS = 500
LOG_ROWS = 60
MAX_FEED = 200               # accumulated cards kept in memory
UI_LIMIT = 60                # cards a single feed response contributes

# --- algorithm (8-dimension scoring) -----------------------------------------
# Final score = BASE + sum(weight_i * (dim_i * 2 - 1)); each dimension returns
# [0,1] (neutral 0.5), so a weight is the points that dimension can swing the
# score in either direction. All knobs are read by core.algorithms.engine.
BASE_SCORE = 50.0

W_ENGAGEMENT = 20.0   # 互动质量
W_DURATION = 10.0     # 时长契合
W_RECENCY = 8.0       # 新鲜度
W_AUTHORITY = 14.0    # 作者权威
W_TITLE = 16.0        # 标题质量
W_MOMENTUM = 12.0     # 增长动量
W_INTEREST = 10.0     # 兴趣匹配
W_DIVERSITY = 12.0    # 多样性

SHORT_SECONDS = 75      # below this reads as a filler clip
LONG_SECONDS = 1800     # above this competes poorly for attention
SWEET_SECONDS = (180, 900)   # duration sweet-spot window (seconds)
FRESH_DAYS = 7          # recency half-life-ish constant

# Growth-momentum boost: a young video with a high engagement ratio is treated as
# "accelerating". All three knobs live here so tuning never means hunting in code.
MOMENTUM_RATIO = 0.06        # engagement ratio that reads as hot word-of-mouth
MOMENTUM_YOUNG_HOURS = 72    # only videos younger than this (hours) get the boost
MOMENTUM_BOOST = 0.1         # points added to an accelerating young video

MAX_PER_UP = 2              # hard cap on videos kept per uploader
DIVERSITY_PENALTY = 12.0   # score knocked off de-duplicated items

# Optional user interest profile, read by engine.InterestProfile.from_settings().
# Leave empty for a neutral interest dimension.
FAV_CATEGORIES = []        # e.g. ["知识", "科技", "游戏"]
INTEREST_KEYWORDS = []     # e.g. ["python", "机器学习"]
