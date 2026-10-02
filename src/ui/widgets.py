"""Small building blocks: cards, rows, the log console, feed cards.

Silicon covers the interactive controls (buttons, switches, inputs); the pieces
here are plain Qt because they exist in bulk - one per log line, one per feed
item - and custom-painted widgets are far too expensive at that scale.

Fonts always come from theme.ui_font / theme.mono_font: the Qt default on a
Chinese Windows is SimSun, which renders visibly rougher than a smooth face.
"""

from PyQt5.QtCore import QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QTextCursor
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                             QVBoxLayout, QWidget)

from . import icons, theme as _theme


def label(text="", role="", mono=False, parent=None):
    item = QLabel(text, parent)
    if role:
        item.setProperty("role", role)
    item.setFont(_theme.mono_font(10) if mono else _theme.ui_font(12))
    item.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    item.setWordWrap(False)
    return item


def section(text="", parent=None):
    return label(text, "section", parent=parent)


def row(*widgets, spacing=8, margins=(0, 0, 0, 0)):
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for item in widgets:
        if item == "stretch":
            layout.addStretch(1)
        elif item is not None:
            layout.addWidget(item)
    return box


class Card(QFrame):
    def __init__(self, parent=None, padding=16, spacing=10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("cardStyle", True)     # theme.restyle paints these
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def add(self, widget):
        self.body.addWidget(widget)
        return widget

    def set_palette(self, palette):
        """Cards built after the theme pass (the script rows) paint themselves."""
        self.setStyleSheet(_theme.card_sheet(palette))


class ToolButton(QPushButton):
    """Header/page button. Plain Qt + an inline sheet so both themes stay under
    our control; the glyph is painted (see icons.py) so it stays sharp when the
    display is scaled; icon-only when there is no label."""

    HEIGHT = 24
    ICON_ONLY_WIDTH = 24
    ICON_BOX = QRect(7, 0, 14, HEIGHT)
    ICON_PX = 13

    def __init__(self, icon_key=None, text="", tone="ghost", parent=None):
        super().__init__(text, parent)
        self.icon_key = icon_key
        self.icon_color = _theme.get("dark")["text"]
        self.tone = tone
        self.palette = _theme.get("dark")
        self.setFixedHeight(self.HEIGHT)
        self.setFont(_theme.ui_font(8.5))
        self.setCursor(Qt.PointingHandCursor)
        if icon_key and not text:
            self.setFixedWidth(self.ICON_ONLY_WIDTH)
        self.set_palette(self.palette)

    def set_palette(self, palette):
        self.palette = palette
        p = palette
        if self.tone == "primary":
            bg, fg, bd = p["accent"], p["on_accent"], p["accent"]
        elif self.tone == "danger":
            bg, fg, bd = "transparent", p["danger"], p["border"]
        else:
            bg, fg, bd = p["raised"], p["text"], p["border"]
        self.icon_color = fg
        # the label sits after the glyph slot, so the glyph never touches the border
        if self.icon_key and self.text():
            pad = "0 8px 0 24px"
            align = "text-align: left;"
        elif self.icon_key:
            pad = "0px"
            align = ""
        else:
            pad = "0 8px"
            align = ""
        self.setStyleSheet(
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 6px; padding: %s; %s }"
            "QPushButton:hover { background: %s; }"
            % (bg, fg, bd, pad, align,
               p["accent"] if self.tone == "primary" else p["hover"]))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.icon_key:
            return
        painter = QPainter(self)
        if self.text():
            icons.paint(painter, self.ICON_BOX, self.icon_key, self.icon_color,
                        self.ICON_PX, align_left=True)
        else:
            icons.paint(painter, self.rect(), self.icon_key, self.icon_color, self.ICON_PX)

    def retranslate(self, text):
        self.setText(text)
        if text:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
        else:
            self.setFixedWidth(self.ICON_ONLY_WIDTH)
        self.set_palette(self.palette)
        self.updateGeometry()


class SettingsRow(QWidget):
    """Title on the left, control on the right."""

    def __init__(self, title="", control=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.title = label(title, "field")
        layout.addWidget(self.title)
        layout.addStretch(1)
        if control is not None:
            layout.addWidget(control)

    def retranslate(self, text):
        self.title.setText(text)


class ChoicePair(QWidget):
    """Two exclusive pills - theme and language."""

    changed = pyqtSignal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = list(options)           # [(value, text), ...]
        self.current = None
        self.palette = _theme.get("dark")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.buttons = {}
        for value, text in self.options:
            button = QPushButton(text, self)
            button.setFont(_theme.ui_font(8.5))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, v=value: self.changed.emit(v))
            layout.addWidget(button)
            self.buttons[value] = button

    def set_palette(self, palette):
        self.palette = palette
        self.set_current(self.current)

    def set_current(self, value):
        self.current = value
        p = self.palette
        for key, button in self.buttons.items():
            on = key == value
            button.setStyleSheet(
                "QPushButton { background: %s; color: %s; border: 1px solid %s;"
                " border-radius: 6px; padding: 2px 10px; }"
                % ((p["accent"], p["on_accent"], p["accent"]) if on
                   else (p["raised"], p["text"], p["border"])))

    def retranslate(self, texts):
        for (value, _), text in zip(self.options, texts):
            self.buttons[value].setText(text)


class NavButton(QPushButton):
    """One entry of the left rail."""

    def __init__(self, page, text="", icon_key=None, parent=None):
        super().__init__(text, parent)
        self.page = page
        self.icon_key = icon_key
        self.setFixedHeight(28)
        self.setFont(_theme.ui_font(9))
        self.setCursor(Qt.PointingHandCursor)
        self.icon_color = _theme.get("dark")["dim"]
        self.set_palette(_theme.get("dark"), False)

    def set_palette(self, palette, active=False):
        p = palette
        self.icon_color = p["on_accent"] if active else p["dim"]
        if active:
            sheet = ("QPushButton { text-align: left; padding-left: 30px; border: none;"
                     " border-radius: 6px; background: %s; color: %s; }"
                     % (p["accent"], p["on_accent"]))
        else:
            sheet = ("QPushButton { text-align: left; padding-left: 30px; border: none;"
                     " border-radius: 6px; background: transparent; color: %s; }"
                     "QPushButton:hover { background: %s; color: %s; }"
                     % (p["dim"], p["raised"], p["text"]))
        self.setStyleSheet(sheet)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.icon_key:
            icons.paint(QPainter(self), QRect(8, 0, 14, self.height()),
                        self.icon_key, self.icon_color, 14, align_left=True)

    def retranslate(self, text):
        self.setText(text)


class StatusDot(QWidget):
    """A painted circle - a glyph would be clipped by its own font metrics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.color = QColor(_theme.get("dark")["faint"])

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(self.rect())


class LogConsole(QPlainTextEdit):
    """Read-only console: Qt trims old lines, colour carries the level."""

    def __init__(self, parent=None, max_lines=300):
        super().__init__(parent)
        self.setObjectName("Console")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setFont(_theme.mono_font(10.5))
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

    def append_line(self, time_text, message, color, faint):
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        self.appendHtml('<span style="color:%s">%s </span><span style="color:%s">%s</span>'
                        % (faint, time_text, color, _escape(message)))
        if at_bottom:
            self.moveCursor(QTextCursor.End)
            bar.setValue(bar.maximum())


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))


class FeedCard(QFrame):
    """One reranked item: rank, title, uploader, score."""

    def __init__(self, item, index, palette, translate, parent=None):
        super().__init__(parent)
        top = index < 3
        self.setObjectName("Card")
        self.setStyleSheet(
            "QFrame#Card { background: %s; border: 1px solid %s; border-radius: 10px; }"
            % (palette["surface"], palette["accent"] if top else palette["border"]))
        tags = item.get("tags") or []
        if tags:
            self.setToolTip(" / ".join(translate(key) for key in tags))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(12)

        rank = QLabel(str(index + 1))
        rank.setFixedWidth(16)
        rank.setAlignment(Qt.AlignCenter)
        rank.setFont(_theme.ui_font(11, bold=True))
        rank.setStyleSheet("color: %s;" % (palette["accent"] if top else palette["faint"]))
        layout.addWidget(rank)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        title = QLabel(item.get("title") or "-")
        title.setWordWrap(True)
        title.setFont(_theme.ui_font(12))
        title.setStyleSheet("color: %s;" % palette["text"])
        text.addWidget(title)
        meta = QLabel("%s   %s" % (item.get("up") or translate("ui.unknown_up"),
                                   item.get("mid") or "-"))
        meta.setFont(_theme.mono_font(9))
        meta.setStyleSheet("color: %s;" % palette["faint"])
        text.addWidget(meta)
        layout.addLayout(text, 1)

        score = QLabel(str(int(round(item.get("score", 0)))))
        score.setFont(_theme.mono_font(10, bold=True))
        score.setStyleSheet("color: %s;" % (palette["accent"] if top else palette["faint"]))
        layout.addWidget(score)


class EmptyState(QWidget):
    def __init__(self, palette, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 80, 0, 0)
        layout.setSpacing(12)
        glyph = QLabel(icons.char("feed"))
        glyph.setAlignment(Qt.AlignCenter)
        glyph.setFont(icons.font(30))
        glyph.setStyleSheet("color: %s;" % palette["faint"])
        layout.addWidget(glyph)
        self.text = QLabel("")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setFont(_theme.ui_font(12))
        self.text.setStyleSheet("color: %s;" % palette["faint"])
        layout.addWidget(self.text)
        layout.addStretch(1)

    def retranslate(self, text):
        self.text.setText(text)
