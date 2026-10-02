"""Script editing: a modal editor for one hook script.

Qt ships a real incremental highlighter, so only the changed block is re-lexed
and even a long script stays responsive.
"""

from PyQt5.QtCore import QRegExp, Qt
from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                             QVBoxLayout)

from . import theme as _theme

RULES = (
    (QRegExp(r"//[^\n]*"), "comment"),
    (QRegExp(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/"), "comment"),
    (QRegExp(r"'(?:\\.|[^'\\])*'"), "string"),
    (QRegExp(r'"(?:\\.|[^"\\])*"'), "string"),
    (QRegExp(r"`(?:\\.|[^`\\])*`"), "string"),
    (QRegExp(r"\b(?:const|let|var|function|return|if|else|for|while|do|new|try|catch|finally"
             r"|throw|typeof|instanceof|null|undefined|true|false|this|class|of|in|delete"
             r"|break|continue|switch|case|default|await|async)\b"), "keyword"),
    (QRegExp(r"\b(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?)\b"), "number"),
    (QRegExp(r"[A-Za-z_$][A-Za-z0-9_$]*(?=\s*\()"), "function"),
)


class JsHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.formats = {}

    def set_theme(self, palette):
        self.formats = {}
        for name, color in palette["code"].items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if name == "keyword":
                fmt.setFontWeight(QFont.Bold)
            self.formats[name] = fmt
        self.rehighlight()

    def highlightBlock(self, text):
        if not self.formats:
            return
        for pattern, name in RULES:
            fmt = self.formats.get(name)
            if fmt is None:
                continue
            index = pattern.indexIn(text)
            while index >= 0:
                length = pattern.matchedLength()
                if length <= 0:
                    break
                self.setFormat(index, length, fmt)
                index = pattern.indexIn(text, index + length)


class ScriptDialog(QDialog):
    """Edit one script: Save writes the file (and the backend reloads it)."""

    def __init__(self, name, source, palette, translate, parent=None):
        super().__init__(parent)
        self.palette = palette
        self.translate = translate
        self.setWindowTitle(translate("ui.dlg.title", {"name": name}))
        self.resize(720, 520)
        self.setStyleSheet(
            "QDialog { background: %s; }" % palette["bg"])

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        title = QLabel(name)
        title.setFont(_theme.ui_font(13))
        title.setStyleSheet("color: %s; font-weight: 600;" % palette["text"])
        outer.addWidget(title)

        self.editor = QPlainTextEdit(self)
        self.editor.setObjectName("Editor")
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setFont(_theme.mono_font(10.5))
        self.editor.setStyleSheet(
            "QPlainTextEdit { background: %s; color: %s; border: 1px solid %s;"
            " border-radius: 10px; selection-background-color: %s; }"
            % (palette["console"], palette["text"], palette["border"], palette["raised"]))
        self.editor.setPlainText(source or "")
        self.highlighter = JsHighlighter(self.editor.document())
        self.highlighter.set_theme(palette)
        outer.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel = QPushButton(translate("ui.dlg.cancel"), self)
        self.save = QPushButton(translate("ui.dlg.save"), self)
        for item in (self.cancel, self.save):
            item.setFont(_theme.ui_font(8.5))
            item.setFixedHeight(24)
            item.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(item)
        outer.addLayout(buttons)

        self.cancel.clicked.connect(self.reject)
        self.save.clicked.connect(self.accept)

    def source(self):
        return self.editor.toPlainText()
