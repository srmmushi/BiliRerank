"""The three pages: feed, log, settings.

Injection scripts are read-only files on disk - the UI never shows or edits
them, so there is no script page and nothing here can change a hook.

No page repeats its own name or counters: the window header owns the title and
the per-page counter, the footer owns the stats.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from siui.components.button import SiSwitchRefactor
from siui.components.slider_ import SiScrollAreaRefactor

from . import theme as _theme, widgets
from .widgets import Card, ChoicePair, FeedCard, LogConsole, SettingsRow, ToolButton


class Page(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.palette = _theme.get("dark")

    def set_palette(self, palette):
        self.palette = palette
        for item in self.findChildren(ToolButton) + self.findChildren(ChoicePair):
            item.set_palette(palette)

    def retranslate(self, t):
        pass


class FeedPage(Page):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drawn = 0
        self._empty = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)

        self.scroll = SiScrollAreaRefactor(self)
        self.scroll.setWidgetResizable(True)
        canvas = QWidget()
        self.list = QVBoxLayout(canvas)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(6)
        self.list.addStretch(1)
        self.scroll.setWidget(canvas)
        outer.addWidget(self.scroll, 1)

    def set_items(self, items, translate):
        if len(items) < self._drawn:
            self.clear()
        if not items:
            if self._empty is None:
                self._empty = widgets.EmptyState(self.palette)
                self.list.insertWidget(0, self._empty)
            return
        if self._empty is not None:
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None
        for index in range(self._drawn, len(items)):
            self.list.insertWidget(self.list.count() - 1,
                                   FeedCard(items[index], index, self.palette, translate))
        self._drawn = len(items)

    def clear(self):
        while self.list.count() > 1:
            widget = self.list.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._drawn = 0
        self._empty = None

    def retranslate(self, t, refresh=True):
        if self._empty is not None:
            self._empty.retranslate(t("ui.feed_empty"))


class ToolsPage(Page):
    """Every hook script with its own inject / stop / log buttons."""

    script_action = pyqtSignal(str, str)      # (script name, "inject" | "stop" | "log")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signature = None
        self._rows = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(6)

        self.scroll = SiScrollAreaRefactor(self)
        self.scroll.setWidgetResizable(True)
        canvas = QWidget()
        self.list = QVBoxLayout(canvas)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(6)
        self.list.addStretch(1)
        self.scroll.setWidget(canvas)
        outer.addWidget(self.scroll, 1)

        self.empty = widgets.label("", "faint")
        self.empty.setAlignment(Qt.AlignCenter)
        outer.insertWidget(0, self.empty)      # above the list, hidden when it has rows

    def set_scripts(self, names, running, t):
        signature = tuple((name, name in running) for name in names)
        self.empty.setVisible(not names)
        if signature == self._signature:
            return
        self._signature = signature

        while self.list.count() > 1:
            widget = self.list.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for name, is_on in signature:
            card = Card(self, padding=12, spacing=8)
            card.set_palette(self.palette)
            dot = widgets.StatusDot(card)
            dot.set_color(_theme.GREEN if is_on else self.palette["faint"])

            buttons = []
            # the three the user drives most keep their label, edit/delete are
            # icon-only with a tooltip so the row stays short
            for key, text, enabled in (("inject", t("ui.tools.inject"), not is_on),
                                       ("stop", t("ui.tools.stop"), is_on),
                                       ("log", t("ui.tools.log"), True),
                                       ("edit", "", True),
                                       ("delete", "", True)):
                button = ToolButton(key, text, "ghost", parent=card)
                button.setEnabled(enabled)
                button.setToolTip(t("ui.tools." + key))
                button.clicked.connect(lambda _, n=name, k=key: self.script_action.emit(n, k))
                buttons.append(button)
            card.body.addWidget(widgets.row(
                dot, widgets.label(name, "field"), "stretch", *buttons, spacing=8))
            self.list.insertWidget(self.list.count() - 1, card)
    def retranslate(self, t):
        self.empty.setText(t("ui.tools.empty"))


class LogPage(Page):
    filter_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(8)

        self.chip = QWidget(self)
        chip_layout = QHBoxLayout(self.chip)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(6)
        self.chip_name = widgets.label("", "field")
        self.chip_all = ToolButton("reload", "", tone="ghost", parent=self.chip)
        self.chip_all.clicked.connect(self.filter_cleared.emit)
        chip_layout.addWidget(self.chip_name)
        chip_layout.addWidget(self.chip_all)
        chip_layout.addStretch(1)
        self.chip.setVisible(False)
        outer.addWidget(self.chip)

        self.console = LogConsole(self)
        outer.addWidget(self.console, 1)

    def set_filter(self, name, t):
        self.chip_name.setText(name)
        self.chip_name.setStyleSheet("color: %s; font-weight: 600;" % _theme.PINK)
        self.chip_all.retranslate(t("ui.log_all"))
        self.chip.setVisible(bool(name))

    def retranslate(self, t):
        self.chip_all.retranslate(t("ui.log_all"))


class SettingsPage(Page):
    theme_changed = pyqtSignal(str)
    lang_changed = pyqtSignal(str)
    watch_toggled = pyqtSignal(bool)
    restart_requested = pyqtSignal()
    config_change_requested = pyqtSignal()
    config_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)

        self.scroll = SiScrollAreaRefactor(self)
        self.scroll.setWidgetResizable(True)
        canvas = QWidget()
        self.body = QVBoxLayout(canvas)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)

        self.appearance = Card(canvas)
        self.appearance_title = widgets.section("")
        self.theme_pair = ChoicePair([("dark", ""), ("light", "")])
        self.theme_row = SettingsRow("", self.theme_pair)
        self.lang_pair = ChoicePair([("zh", ""), ("en", "")])
        self.lang_row = SettingsRow("", self.lang_pair)
        self.appearance.add(self.appearance_title)
        self.appearance.add(self.theme_row)
        self.appearance.add(self.lang_row)
        self.theme_pair.changed.connect(self.theme_changed.emit)
        self.lang_pair.changed.connect(self.lang_changed.emit)

        self.client = Card(canvas)
        self.client_title = widgets.section("")
        self.watch = SiSwitchRefactor()
        self.watch.setFixedSize(40, 20)
        self.watch.clicked.connect(lambda: self.watch_toggled.emit(self.watch.isChecked()))
        self.watch_row = SettingsRow("", self.watch)
        self.restart_button = ToolButton("client", tone="ghost", parent=self.client)
        self.restart_button.clicked.connect(self.restart_requested.emit)
        self.client.add(self.client_title)
        self.client.add(self.watch_row)
        self.client.add(widgets.row(self.restart_button, "stretch"))

        self.config = Card(canvas)
        self.config_title = widgets.section("")
        self.config_change = ToolButton("folder", tone="ghost", parent=self.config)
        self.config_default = ToolButton("reload", tone="ghost", parent=self.config)
        self.config_change.clicked.connect(self.config_change_requested.emit)
        self.config_default.clicked.connect(self.config_reset_requested.emit)
        self.config_row = SettingsRow("", widgets.row(self.config_change,
                                                      self.config_default, "stretch"))
        self.config_value = widgets.label("", "faint")
        self.config_value.setWordWrap(True)
        self.config.add(self.config_title)
        self.config.add(self.config_row)
        self.config.add(self.config_value)

        self.about = Card(canvas)
        self.about_title = widgets.section("")
        self.about_text = widgets.label("", "faint")
        self.about.add(self.about_title)
        self.about.add(self.about_text)

        for card in (self.appearance, self.client, self.config, self.about):
            self.body.addWidget(card)
        self.body.addStretch(1)
        self.scroll.setWidget(canvas)
        outer.addWidget(self.scroll, 1)

    def set_theme_choice(self, theme):
        self.theme_pair.set_current(theme)

    def set_lang_choice(self, lang):
        self.lang_pair.set_current(lang)

    def set_watch(self, on):
        self.watch.setChecked(bool(on))

    def set_config_path(self, path):
        self.config_value.setText(path)
        self.config_value.setToolTip(path)

    def retranslate(self, t, values=None):
        values = values or {}
        self.appearance_title.setText(t("ui.set.appearance"))
        self.theme_row.retranslate(t("ui.set.theme"))
        self.lang_row.retranslate(t("ui.set.lang"))
        self.theme_pair.retranslate([t("ui.dark"), t("ui.light")])
        self.lang_pair.retranslate([t("ui.zh"), t("ui.en")])
        self.client_title.setText(t("ui.set.client"))
        self.watch_row.retranslate(t("ui.set.watch_client"))
        self.restart_button.retranslate(t("ui.set.restart_client"))
        self.config_title.setText(t("ui.set.config"))
        self.config_row.retranslate(t("ui.set.config_where"))
        self.config_change.retranslate(t("ui.set.config_change"))
        self.config_default.retranslate(t("ui.set.config_default"))
        self.config_value.setText(values.get("config", ""))
        self.config_value.setToolTip(values.get("config", ""))
        self.about_title.setText(t("ui.set.about"))
        self.about_text.setText(values.get("about", ""))
