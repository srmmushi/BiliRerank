"""Palette, stylesheet and the "restyle silicon widgets" pass.

PyQt-SiliconUI's refactored widgets keep their colours in a per-widget
`style_data` object (GlobalStyleManager fills it once, dark values only), so a
theme switch means: overwrite the global colour group for the token-based
widgets, then walk our own tree and push the palette into every siui widget's
style data.
"""

from PyQt5.QtGui import QColor

from siui.components.button import (    # noqa: F401  (imported for the type checks below)
    ABCButton,
    SiCheckBoxRefactor,
    SiPushButtonRefactor,
    SiSwitchRefactor,
    SiToggleButtonRefactor,
)
from siui.components.combobox_ import SiCapsuleComboBox
from siui.components.container import SiPanelCard, SiRowCard, SiTriSectionPanelCard
from siui.components.editbox import SiCapsuleLineEdit, SiLabeledLineEdit
from siui.components.label import SiLabelRefactor
from siui.components.progress_bar_ import SiProgressBarRefactor
from siui.components.slider_ import SiScrollAreaRefactor
from siui.core import SiGlobal

PINK = "#FB7299"        # one accent for the whole UI
ACCENT = PINK
GREEN = "#6FBF8B"
RED = "#F2707F"

THEMES = {
    "dark": {
        "bg": "#1E161C",
        "surface": "#2C2028",
        "raised": "#3A2A34",
        "hover": "#48343F",
        "border": "#452F3A",
        "text": "#F3E7EC",
        "dim": "#B7A0AA",
        "faint": "#826B76",
        "accent": ACCENT,
        "on_accent": "#FFFFFF",
        "ok": GREEN,
        "danger": RED,
        "console": "#191217",
        "code": {
            "comment": "#826B76",
            "string": "#8FBF7F",
            "keyword": "#F58EAE",
            "number": "#EFC07A",
            "function": "#9CC8F0",
        },
        "level": {"info": "#E8DCE2", "success": "#8ED3A5", "warn": "#EFC07A", "error": "#F58E9B"},
    },
    "light": {
        "bg": "#FFF4F7",
        "surface": "#FFFFFF",
        "raised": "#FCE9EF",
        "hover": "#F9DCE5",
        "border": "#F4D2DC",
        "text": "#2E2126",
        "dim": "#7A6068",
        "faint": "#A88E97",
        "accent": ACCENT,
        "on_accent": "#FFFFFF",
        "ok": "#2F8F4E",
        "danger": "#C4384A",
        "console": "#FFF9FB",
        "code": {
            "comment": "#A88E97",
            "string": "#2F7D46",
            "keyword": "#C2276B",
            "number": "#B26A00",
            "function": "#1F63C8",
        },
        "level": {"info": "#4A3A40", "success": "#2F8F4E", "warn": "#A96A00", "error": "#C4384A"},
    },
}

LEVEL_TAG = {"info": "INFO", "success": "OK", "warn": "WARN", "error": "ERR"}

# Qt's default on a Chinese Windows is SimSun, which renders rough and unhinted,
# so the whole UI is pinned to a smooth family with antialiasing enabled.
UI_FAMILIES = ("Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", "Noto Sans SC")
MONO_FAMILIES = ("Cascadia Mono", "JetBrains Mono", "Consolas")

_families = {}


def _pick(candidates):
    key = candidates[0]
    if key not in _families:
        from PyQt5.QtGui import QFontDatabase

        installed = set(QFontDatabase().families())
        _families[key] = next((name for name in candidates if name in installed), candidates[-1])
    return _families[key]


def ui_family():
    return _pick(UI_FAMILIES)


def mono_family():
    return _pick(MONO_FAMILIES)


def ui_font(size=10, bold=False):
    return _smooth(ui_family(), size, bold)


def mono_font(size=10, bold=False):
    return _smooth(mono_family(), size, bold)


def _smooth(family, size, bold):
    from PyQt5.QtGui import QFont

    font = QFont(family)
    font.setPointSizeF(float(size))
    font.setBold(bool(bold))
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setHintingPreference(QFont.PreferVerticalHinting)
    return font


def get(theme):
    return THEMES.get(theme, THEMES["dark"])


def rgba(hex_color, alpha=0.55):
    """#RRGGBB + alpha -> rgba() for rich text and stylesheets."""
    try:
        value = hex_color.lstrip("#")
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return hex_color
    return "rgba(%d, %d, %d, %.2f)" % (red, green, blue, alpha)


# --------------------------------------------------------------------- QSS
def stylesheet(p):
    return ("""
QMainWindow, QWidget#Root, QWidget#Page { background: %(bg)s; }
QWidget, QLabel { font-family: "%(ui)s"; }
QWidget#Sidebar { background: %(surface)s; border-right: 1px solid %(border)s; }
QWidget#Header  { background: %(surface)s; border-bottom: 1px solid %(border)s; }
QWidget#Footer  { background: %(bg)s; border-top: 1px solid %(border)s; }
QLabel { color: %(text)s; background: transparent; font-size: 11px; }
QLabel[role="title"]  { font-size: 13px; font-weight: 600; }
QLabel[role="meta"]   { color: %(dim)s; font-size: 10px; }
QLabel[role="faint"]  { color: %(faint)s; font-size: 10px; }
QLabel[role="section"]{ color: %(dim)s; font-size: 10px; font-weight: 600; }
QLabel[role="field"]  { color: %(text)s; font-size: 12px; }
QWidget#Card, QFrame#Card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
QFrame#Divider { background: %(border)s; border: none; }
QPlainTextEdit#Console {
    background: %(console)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 10px;
    font-family: "%(mono)s"; font-size: 11px;
    selection-background-color: %(raised)s;
}

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(raised)s; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(hover)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(raised)s; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent; border: none; width: 0; height: 0;
}
QComboBox QAbstractItemView {
    background: %(surface)s; color: %(text)s; border: 1px solid %(border)s;
    selection-background-color: %(raised)s; outline: none; padding: 4px;
}
QMenu { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: %(raised)s; }
QToolTip { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px; }
QMessageBox, QInputDialog, QFileDialog { background: %(bg)s; color: %(text)s; }
QComboBox {
    background: %(raised)s; color: %(text)s; border: 1px solid %(border)s;
    border-radius: 8px; padding: 4px 10px;
}
QComboBox:hover { background: %(hover)s; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow {
    image: none; width: 0; height: 0; margin-right: 6px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid %(dim)s;
}
""" % {
        "bg": p["bg"], "surface": p["surface"], "raised": p["raised"], "hover": p["hover"],
        "border": p["border"], "text": p["text"], "dim": p["dim"], "faint": p["faint"],
        "accent": p["accent"], "on_accent": p["on_accent"], "console": p["console"],
        "mono": mono_family(), "ui": ui_family(),
    })


def apply_global(theme):
    """Token-based silicon widgets (pages, old containers, labels) follow this."""
    from siui.core import SiColor
    from siui.gui import BrightColorGroup, DarkColorGroup

    group = DarkColorGroup() if theme == "dark" else BrightColorGroup()
    try:    # silicon's own theme token is purple - pin it to the pink accent
        group.assign(SiColor.THEME, ACCENT)
    except Exception:
        pass
    SiGlobal.siui.colors.overwrite(group)
    SiGlobal.siui.reloadAllWindowsStyleSheet()


# ------------------------------------------------------- silicon widget restyle
def _style(widget, qss_color=None, qss_checked=None, **values):
    data = getattr(widget, "style_data", None)
    if qss_color:
        sheet = "QPushButton { color: %s; }" % qss_color
        if qss_checked:
            sheet += " QPushButton:checked { color: %s; }" % qss_checked
        widget.setStyleSheet(sheet)
    if data is None:
        return
    for key, value in values.items():
        if hasattr(data, key):
            setattr(data, key, value)
    # silicon buttons cache the colours in python properties, so push them again:
    # otherwise the repaint depends on reloadStyleData() succeeding for every type
    for prop, key in (("textColor", "text_color"), ("buttonRectColor", "button_color"),
                      ("backgroundRectColor", "background_color"),
                      ("highlightRectColor", "hover_color")):
        if hasattr(data, key) and hasattr(widget, prop):
            try:
                setattr(widget, prop, getattr(data, key))
            except Exception:
                pass
    reload_ = getattr(widget, "reloadStyleData", None)
    if callable(reload_):
        try:
            reload_()
        except Exception:
            pass
    widget.update()


def card_sheet(p):
    return ("QFrame#Card { background: %s; border: 1px solid %s; border-radius: 10px; }"
            % (p["surface"], p["border"]))


def restyle(widget, p):
    """Push the palette into every silicon widget under `widget`."""
    from PyQt5.QtWidgets import QWidget

    face = ui_font(10)
    sheet = card_sheet(p)
    targets = [widget] + widget.findChildren(QWidget)
    for item in targets:
        # cards take an inline sheet: an application sheet alone does not always
        # paint the background of a plain container
        if item.property("cardStyle"):
            item.setStyleSheet(sheet)
        # silicon paints its own text and ignores the application font
        if hasattr(item, "style_data"):
            try:
                item.style_data.font = face
            except Exception:
                pass
        if isinstance(item, SiPushButtonRefactor) and not isinstance(item, SiSwitchRefactor):
            primary = item.property("tone") == "primary"
            danger = item.property("tone") == "danger"
            if primary:
                _style(item, qss_color=p["on_accent"],
                       text_color=QColor(p["on_accent"]), button_color=QColor(p["accent"]),
                       hover_color=QColor(255, 255, 255, 40), click_color=QColor(255, 255, 255, 70),
                       idle_color=QColor(0, 0, 0, 0), background_color=QColor(p["accent"]))
            elif danger:
                _style(item, qss_color=p["danger"],
                       text_color=QColor(p["danger"]), button_color=QColor(0, 0, 0, 0),
                       hover_color=QColor(p["raised"]), idle_color=QColor(0, 0, 0, 0),
                       click_color=QColor(p["hover"]), background_color=QColor(0, 0, 0, 0))
            else:
                _style(item, qss_color=p["text"],
                       text_color=QColor(p["text"]), button_color=QColor(p["raised"]),
                       hover_color=QColor(p["hover"]), click_color=QColor(p["hover"]),
                       idle_color=QColor(0, 0, 0, 0), background_color=QColor(0, 0, 0, 0))
        elif isinstance(item, SiToggleButtonRefactor):
            _style(item, qss_color=p["dim"], qss_checked=p["on_accent"],
                   text_color=QColor(p["dim"]),
                   button_color=QColor(0, 0, 0, 0),
                   toggled_text_color=QColor(p["on_accent"]),
                   toggled_button_color=QColor(p["accent"]),
                   hover_color=QColor(p["hover"]), click_color=QColor(p["hover"]),
                   idle_color=QColor(0, 0, 0, 0), background_color=QColor(0, 0, 0, 0),
                   border_radius=8, border_inner_radius=6)
        elif isinstance(item, SiSwitchRefactor):
            _style(item, button_color=QColor(p["accent"]), complete_color=QColor(p["accent"]),
                   background_color=QColor(p["idle"] if "idle" in p else p["border"]),
                   text_color=QColor(p["text"]))
        elif isinstance(item, SiCheckBoxRefactor):
            _style(item, text_color=QColor(p["text"]), button_color=QColor(p["accent"]),
                   background_color=QColor(p["border"]), complete_color=QColor(p["accent"]))
        elif isinstance(item, (SiPanelCard, SiTriSectionPanelCard, SiRowCard)):
            _style(item, color=QColor(p["surface"]), panel_color=QColor(p["surface"]),
                   background_color=QColor(p["surface"]), border_color=QColor(p["border"]))
        elif isinstance(item, SiLabelRefactor):
            _style(item, text_color=QColor(p["text"]), background_color=QColor(0, 0, 0, 0))
        elif isinstance(item, (SiCapsuleLineEdit, SiLabeledLineEdit)):
            _style(item, text_color=QColor(p["text"]), background_color=QColor(p["surface"]),
                   border_color=QColor(p["border"]), indicator_color=QColor(p["accent"]))
        elif isinstance(item, SiCapsuleComboBox):
            _style(item, background_color=QColor(p["raised"]), button_color=QColor(p["raised"]),
                   capsule_color=QColor(p["raised"]), text_color=QColor(p["text"]),
                   title_text_color=QColor(p["dim"]), hover_color=QColor(p["hover"]))
        elif isinstance(item, SiScrollAreaRefactor):
            _style(item, background_color=QColor(p["bg"]))
        elif isinstance(item, SiProgressBarRefactor):
            _style(item, progress_color=QColor(p["accent"]), background_color=QColor(p["raised"]))
        elif getattr(item, "style_data", None) is not None:
            # anything else silicon paints itself (combo box, scrollbars, ...)
            _style(item, text_color=QColor(p["text"]), background_color=QColor(p["surface"]),
                   button_color=QColor(p["raised"]), hover_color=QColor(p["hover"]),
                   border_color=QColor(p["border"]))


def apply_palette(app, p):
    """Silicon draws button text through the application palette, not through
    style_data, so the palette has to follow the theme too."""
    from PyQt5.QtGui import QPalette

    pal = app.palette()
    pairs = (
        (QPalette.Window, p["bg"]), (QPalette.WindowText, p["text"]),
        (QPalette.Base, p["surface"]), (QPalette.AlternateBase, p["raised"]),
        (QPalette.Text, p["text"]), (QPalette.Button, p["raised"]),
        (QPalette.ButtonText, p["text"]), (QPalette.Highlight, p["accent"]),
        (QPalette.HighlightedText, p["on_accent"]), (QPalette.ToolTipBase, p["surface"]),
        (QPalette.ToolTipText, p["text"]), (QPalette.PlaceholderText, p["faint"]),
    )
    for role, value in pairs:
        pal.setColor(role, QColor(value))
    app.setPalette(pal)


def apply_theme(app, theme):
    """Everything at once: font, palette, silicon tokens, our QSS, the repaint."""
    p = get(theme)
    app.setFont(ui_font(10))     # beats the SimSun default on a Chinese Windows
    apply_palette(app, p)
    apply_global(theme)
    app.setStyleSheet(stylesheet(p))
    for window in app.topLevelWidgets():
        restyle(window, p)
