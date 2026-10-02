"""Main window.

PyQt-SiliconUI has no application template we would want to use (its README is
explicit about that), so the shell is a plain QMainWindow: rail on the left,
header + QStackedWidget on the right, one QTimer polling core.store. Transport
threads never touch widgets, they only write to the store.

Four pages: the reranked feed, the tools page (one row per hook script with its
own inject / stop / log buttons) and the log and settings pages. Hook scripts
live in the config folder's script directory and this UI never writes them.

Text budget: the header owns the page name and the per-page counter, the footer
owns the stats, the rail owns nothing but navigation.
"""

import os
import threading

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QMainWindow,
                             QMessageBox, QStackedWidget, QVBoxLayout, QWidget)

from ..backends import (back, frida_hook, inject, restart_client, start_script,
                        start_watcher, stop_all, stop_script, stop_watcher)
from ..core import config, settings, store
from . import pages, theme as _theme, widgets
from .i18n import Translator

TICK_MS = 200
PAGE_ORDER = ("feed", "tools", "log", "settings")


def ensure_icon():
    """Taskbar icon: whatever the user dropped next to the settings file wins,
    otherwise draw the little TV + hook once."""
    custom = config.user_icon()
    if custom:
        return custom
    from .icon import render

    path = config.icon_path()
    return path if render(path) else None


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.tr = Translator(settings.get("lang"))
        self.theme = settings.get("theme")
        self.palette = _theme.get(self.theme)
        self.page = "feed"

        self._log_drawn = 0
        self._cards_drawn = 0
        self._labels = None
        self._scripts = None
        self._script_names = []
        self.log_filter = None

        self.setWindowTitle(config.APP_NAME)
        icon_file = ensure_icon()
        if icon_file:
            self.setWindowIcon(QIcon(icon_file))
        self.resize(1180, 780)
        self.setMinimumSize(940, 600)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_rail())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.page_feed = pages.FeedPage()
        self.page_tools = pages.ToolsPage()
        self.page_log = pages.LogPage()
        self.page_settings = pages.SettingsPage()
        for name in PAGE_ORDER:
            self.stack.addWidget(getattr(self, "page_" + name))
        right_layout.addWidget(self.stack, 1)
        right_layout.addWidget(self._build_footer())
        layout.addWidget(right, 1)

        self._wire()
        self.refresh_scripts()
        self.apply_theme(self.theme)
        self.retranslate()
        self.show_page("feed")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        self._refresh()

    # ------------------------------------------------------------- building
    def _build_rail(self):
        rail = QWidget()
        rail.setObjectName("Sidebar")
        rail.setFixedWidth(168)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(3)

        self.brand = widgets.label(config.APP_NAME, "title")
        self.brand.setStyleSheet("font-size: 15px; font-weight: 700; color: %s;" % _theme.PINK)
        layout.addWidget(self.brand)
        layout.addSpacing(16)

        self.nav = {}
        for key in PAGE_ORDER:
            button = widgets.NavButton(key, "", key, rail)
            button.clicked.connect(lambda _, p=key: self.show_page(p))
            layout.addWidget(button)
            self.nav[key] = button

        layout.addStretch(1)
        return rail

    def _build_header(self):
        header = QWidget()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)
        header.setFixedHeight(44)

        self.page_title = widgets.label("", "title")
        self.page_meta = widgets.label("", "faint")
        layout.addWidget(self.page_title)
        layout.addWidget(self.page_meta)
        layout.addStretch(1)

        self.dot = widgets.StatusDot()
        self.back_button = widgets.ToolButton("back", "", tone="ghost", parent=header)
        self.inject_button = widgets.ToolButton("inject", "", tone="primary", parent=header)
        self.stop_button = widgets.ToolButton("stop", "", tone="ghost", parent=header)
        layout.addWidget(self.dot)
        layout.addSpacing(4)
        # only offered once a refresh actually pushed a list into the history
        self.back_button.setVisible(False)
        for item in (self.back_button, self.inject_button, self.stop_button):
            layout.addWidget(item)
        return header

    def _build_footer(self):
        footer = QWidget()
        footer.setObjectName("Footer")
        footer.setFixedHeight(26)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 0, 16, 0)
        self.footer_stats = widgets.label("", "faint")
        layout.addStretch(1)
        layout.addWidget(self.footer_stats)
        return footer

    def _wire(self):
        self.inject_button.clicked.connect(self.on_inject)
        self.stop_button.clicked.connect(self.on_stop)
        self.back_button.clicked.connect(self.on_back)
        self.page_tools.script_action.connect(self.on_script_action)
        self.page_log.filter_cleared.connect(self.clear_log_filter)
        self.page_settings.theme_changed.connect(lambda t: self.apply_theme(t))
        self.page_settings.lang_changed.connect(self.set_language)
        self.page_settings.watch_toggled.connect(
            lambda on: settings.update(watch_client=bool(on)))
        self.page_settings.restart_requested.connect(
            lambda: threading.Thread(target=restart_client, daemon=True).start())
        self.page_settings.config_change_requested.connect(self.on_config_change)
        self.page_settings.config_reset_requested.connect(self.on_config_reset)

    # ------------------------------------------------------------------ pages
    def show_page(self, page):
        self.page = page if page in PAGE_ORDER else "feed"
        self.stack.setCurrentIndex(PAGE_ORDER.index(self.page))
        for key, button in self.nav.items():
            button.set_palette(self.palette, key == self.page)
        self.refresh_scripts()
        self._labels = None
        self._refresh()

    # ------------------------------------------------------------- transport
    def on_inject(self):
        self.show_page("log")
        threading.Thread(target=inject, daemon=True).start()

    def on_stop(self):
        threading.Thread(target=stop_all, daemon=True).start()

    def on_back(self):
        self.show_page("feed")
        threading.Thread(target=back, daemon=True).start()

    # --------------------------------------------------------------- scripts
    def refresh_scripts(self):
        names = frida_hook.list_scripts()
        if names != self._script_names:
            self._script_names = names
            self._scripts = None

    def on_script_action(self, name, action):
        if action == "log":
            self.set_log_filter(name)
            return
        if action == "edit":
            self.edit_script(name)
            return
        if action == "delete":
            question = "%s\n%s" % (self.tr.t("ui.tools.delete"), name)
            if QMessageBox.question(self, config.APP_NAME, question) != QMessageBox.Yes:
                return
            frida_hook.delete_script(name)
            self.refresh_scripts()
            self._scripts = None
            self._labels = None
            self._refresh()
            return
        target = start_script if action == "inject" else stop_script
        threading.Thread(target=target, args=(name,), daemon=True).start()

    def edit_script(self, name):
        from .editor import ScriptDialog

        dialog = ScriptDialog(name, frida_hook.read_script(name), self.palette,
                              self.tr.t, self)
        if dialog.exec_() != dialog.Accepted:
            return
        source = dialog.source()
        if source.strip() == frida_hook.read_script(name).strip():
            return
        frida_hook.write_script(name, source)     # reloads it if it was running
        self._labels = None
        self._refresh()

    def set_log_filter(self, name):
        self.log_filter = name
        self._log_drawn = 0
        self.page_log.console.clear()
        self.page_log.set_filter(name or "", self.tr.t)
        if name:
            self.show_page("log")

    def clear_log_filter(self):
        self.log_filter = None
        self._log_drawn = 0
        self.page_log.console.clear()
        self.page_log.set_filter("", self.tr.t)
        self._labels = None
        self._refresh()

    # ----------------------------------------------------------- config file
    def on_config_change(self):
        start = os.path.dirname(config.SETTINGS_PATH) or config.ROOT
        folder = QFileDialog.getExistingDirectory(self, self.tr.t("ui.set.config_pick"), start)
        if folder:
            self._move_config(os.path.join(folder, config.SETTINGS_NAME))

    def on_config_reset(self):
        self._move_config(config.DEFAULT_SETTINGS_PATH)

    def _move_config(self, target):
        """Switch the settings file. An existing file at the target wins,
        otherwise the values in use are written there."""
        if os.path.abspath(target) == os.path.abspath(config.SETTINGS_PATH):
            return
        current = dict(settings.load())
        if not config.apply_settings_path(target):
            store.add_log("error", "py.config_failed", {"path": target})
            return
        if os.path.exists(target):
            settings.reload()
        else:
            settings.update(**current)
        store.add_log("success", "py.config_moved", {"path": config.SETTINGS_PATH})
        # the script folder follows the config file
        frida_hook.ensure_dir()
        store.add_log("info", "py.script_dir", {"path": config.script_dir()})
        self.refresh_scripts()
        self.apply_from_settings()

    def apply_from_settings(self):
        lang = settings.get("lang")
        self.page_settings.set_watch(settings.get("watch_client", True))
        if lang != self.tr.lang:
            self.set_language(lang)
        self.apply_theme(settings.get("theme"))
        self.page_settings.set_config_path(config.SETTINGS_PATH)
        self._labels = None
        self._refresh()

    # ---------------------------------------------------------------- theme
    def apply_theme(self, theme):
        self.theme = theme
        self.palette = _theme.get(theme)
        settings.update(theme=theme)
        _theme.apply_theme(self.app, theme)

        for page in (self.page_feed, self.page_tools, self.page_log, self.page_settings):
            page.set_palette(self.palette)
        for button in (self.inject_button, self.stop_button, self.back_button):
            button.set_palette(self.palette)
        for key, button in self.nav.items():
            button.set_palette(self.palette, key == self.page)
        self.page_settings.set_theme_choice(theme)
        self.page_log.set_filter(self.log_filter or "", self.tr.t)

        self._log_drawn = 0
        self._cards_drawn = 0
        self._scripts = None
        self.page_log.console.clear()
        self.page_feed.clear()
        self._labels = None
        self._refresh()

    def set_language(self, lang):
        self.tr.set(lang)
        settings.update(lang=lang)
        self.page_settings.set_lang_choice(lang)
        self._log_drawn = 0
        self.page_log.console.clear()
        self.retranslate()
        self._labels = None
        self._refresh()

    # ----------------------------------------------------------- translation
    def retranslate(self):
        t = self.tr.t
        for key in PAGE_ORDER:
            self.nav[key].retranslate(t("ui.nav." + key))
        self.inject_button.retranslate(t("ui.inject"))
        self.stop_button.retranslate(t("ui.stop"))
        self.back_button.retranslate(t("ui.back"))
        self.page_feed.retranslate(t)
        self.page_tools.retranslate(t)
        self.page_log.set_filter(self.log_filter or "", t)
        self.page_settings.retranslate(t, {
            "about": t("ui.set.about_text", {"name": config.APP_NAME,
                                             "version": config.VERSION}),
            "config": config.SETTINGS_PATH,
        })
        self._scripts = None
        self._labels = None
        self._refresh()

    # --------------------------------------------------------------- render
    def _filtered(self, logs):
        if not self.log_filter:
            return logs
        return [entry for entry in logs if entry.get("source") == self.log_filter]

    def _render_logs(self, logs):
        console = self.page_log.console
        if len(logs) < self._log_drawn:
            console.clear()
            self._log_drawn = 0
        if self._log_drawn == 0 and len(logs) > config.LOG_ROWS:
            console.clear()
            self._log_drawn = len(logs) - config.LOG_ROWS
        fresh = logs[self._log_drawn:]
        if not fresh:
            return
        p = self.palette
        for entry in fresh:
            level = entry["level"] if entry["level"] in p["level"] else "info"
            console.append_line(entry["time"], self.tr.t(entry["key"], entry["args"]),
                                p["level"][level], p["faint"])
        self._log_drawn = len(logs)

    def _render_feed(self, feed):
        if len(feed) < self._cards_drawn:
            self.page_feed.clear()
            self._cards_drawn = 0
        self.page_feed.set_items(feed, self.tr.t)
        self._cards_drawn = len(feed)

    def _render_tools(self, running):
        signature = (tuple(self._script_names), tuple(running))
        if signature != self._scripts:
            self._scripts = signature
            self.page_tools.set_scripts(self._script_names, running, self.tr.t)

    def _render_labels(self, shown, feed, runtime, running):
        t = self.tr.t
        state = (t("ui.state_connecting") if runtime["connecting"]
                 else (t("ui.state_up") if runtime["running"] else t("ui.state_down")))
        tooltip = (t("ui.status_run", {"process": config.PROCESS,
                                       "backend": runtime["backend"].upper() or "-",
                                       "target": runtime["target"] or "-"})
                   if runtime["running"] else state)
        stats = t("ui.stats", {"feeds": runtime["feeds"], "added": runtime["added"],
                               "ads": runtime["ads"], "vertical": runtime["vertical"],
                               "rewritten": runtime["rewritten"]})
        if self.page == "feed":
            meta = t("ui.count", {"n": len(feed)})
        elif self.page == "log":
            meta = t("ui.logged", {"n": len(shown)})
        elif self.page == "tools":
            meta = t("ui.tools.count", {"n": len(self._script_names),
                                        "on": len(running)})
        else:
            meta = ""
        can_back = bool(runtime.get("can_back"))
        cache = (state, tooltip, stats, meta, len(shown), len(feed), len(running), can_back)
        if cache == self._labels:
            return
        self._labels = cache
        self.back_button.setVisible(can_back)
        self.dot.set_color(_theme.GREEN if runtime["running"] else
                           (_theme.PINK if runtime["connecting"] else self.palette["faint"]))
        self.dot.setToolTip(tooltip)
        self.footer_stats.setText(stats)
        self.page_meta.setText(meta)

    def _refresh(self):
        logs, feed, _, runtime, running = store.snapshot()
        shown = self._filtered(logs)
        self._render_logs(shown)
        self._render_feed(feed)
        self._render_tools(running)
        self._render_labels(shown, feed, runtime, running)
        self.page_title.setText(self.tr.t("ui.nav." + self.page))

    def tick(self):
        try:
            self._refresh()
        except Exception as exc:
            store.add_log("error", "py.ui_error", {"err": str(exc)})

    def closeEvent(self, event):
        self.timer.stop()
        stop_watcher()
        stop_all()
        super().closeEvent(event)


def _pin_app_id():
    """Without this Windows shows the python interpreter's taskbar icon."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "%s.Desktop" % config.APP_NAME)
    except Exception:
        pass


def main():
    app = QApplication.instance() or QApplication([])
    _pin_app_id()               # before any window exists
    app.setStyle("Fusion")      # the native Windows style ignores palettes
    app.setApplicationName(config.APP_NAME)
    icon_path = ensure_icon()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    frida_hook.ensure_dir()     # release bundled scripts, log what was written
    store.add_log("info", "py.script_dir", {"path": config.script_dir()})

    window = MainWindow(app)
    window.show()
    threading.Thread(target=start_watcher, daemon=True).start()
    return app.exec_()
