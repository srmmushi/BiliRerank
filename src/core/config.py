"""All the knobs in one place: client, transport, paths and scoring weights."""

import os
import shutil
import sys

APP_NAME = "BiliHook"
VERSION = "0.5.0"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
if getattr(sys, "frozen", False):
    # packaged with PyInstaller: the code and the bundled assets live in the
    # temp extraction dir, everything writable has to sit next to the exe
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(SRC)

BUNDLED_SCRIPTS = os.path.join(SRC, "assets", "scripts")   # shipped with the code
SCRIPT_DIR_NAME = "script"                                 # released into the config folder
ICON_NAME = "icon.ico"     # taskbar icon, sits next to the settings file:
                           # drop your own icon.ico there to replace the generated one

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


def script_dir():
    """Hook scripts sit next to the settings file: moving the config moves them."""
    return os.path.join(os.path.dirname(SETTINGS_PATH), SCRIPT_DIR_NAME)


def icon_path():
    """Taskbar icon, in the config folder so it can be swapped by the user."""
    return os.path.join(os.path.dirname(SETTINGS_PATH), ICON_NAME)


def user_icon():
    """An icon the user dropped in (ico or png), if there is one."""
    folder = os.path.dirname(SETTINGS_PATH)
    for name in (ICON_NAME, "icon.png", "icon.ico"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return None


def release_scripts():
    """Copy the scripts that ship with the code into the config folder at startup.

    Existing files are never overwritten - the app does not modify hook scripts,
    so a locally edited one stays as it is. Returns the names written.
    """
    target_dir = script_dir()
    released = []
    try:
        os.makedirs(target_dir, exist_ok=True)
        names = sorted(n for n in os.listdir(BUNDLED_SCRIPTS) if n.lower().endswith(".js"))
    except OSError:
        return released
    for name in names:
        target = os.path.join(target_dir, name)
        if os.path.exists(target):
            continue
        try:
            shutil.copyfile(os.path.join(BUNDLED_SCRIPTS, name), target)
        except OSError:
            continue
        released.append(name)
    return released

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

# --- algorithm --------------------------------------------------------------
BASE_SCORE = 50.0
MAX_PER_UP = 2
DIVERSITY_PENALTY = 12.0
SHORT_SECONDS = 75
LONG_SECONDS = 7200
SWEET_SECONDS = (180, 1800)
FRESH_DAYS = 7

W_ENGAGEMENT = 20.0
W_LENGTH = 9.0
W_FRESH = 5.0
W_VOD = 3.0
W_LIVE = -5.0
W_SHORT = -11.0
W_LONG = -6.0
W_CLICKBAIT = -6.0
W_CLICKBAIT_CAP = -18.0
W_SPAM = -15.0
W_TINY_TITLE = -9.0
W_LOW_ENGAGEMENT = -8.0
LOW_ENG_VIEWS = 5000
LOW_ENG_RATIO = 0.015

CLICKBAIT_WORDS = (
    "震惊", "必看", "你还不知道", "速看", "不看后悔", "史上最", "揭秘", "真相",
    "居然", "没想到", "惊呆", "炸裂", "封神", "绝了", "偷偷", "重磅", "突发",
)
SPAM_WORDS = (
    "优惠券", "领券", "低价", "包邮", "私信", "加群", "限时", "点击链接",
    "带货", "下单", "抢购", "秒杀",
)
