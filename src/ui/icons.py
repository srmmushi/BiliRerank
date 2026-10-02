"""Icons from a system glyph font.

Windows 11 ships Segoe Fluent Icons (Windows 10: Segoe MDL2 Assets); one glyph
per action.

Glyphs are *painted*, not turned into QIcon pixmaps: a pixmap is rasterised at
one size and then rescaled by the screen scale factor (1.6 on a 160% display),
which is what made the icons look soft. Text goes through the font engine, so it
is rendered at the real physical resolution and stays sharp at any DPI.
"""

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter

GLYPHS = {
    "feed": 0xE714,      # video
    "tools": 0xE90F,     # repair/wrench
    "log": 0xE7C3,       # page
    "settings": 0xE713,
    "inject": 0xE768,    # play
    "back": 0xE72B,      # back arrow
    "stop": 0xE71A,
    "reload": 0xE72C,
    "delete": 0xE74D,
    "folder": 0xE8B7,
    "client": 0xE7F4,
    "dark": 0xE708,
    "light": 0xE706,
    "lang": 0xE774,
}

FAMILIES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
_family = None


def family():
    global _family
    if _family is None:
        installed = set(QFontDatabase().families())
        _family = next((name for name in FAMILIES if name in installed), FAMILIES[-1])
    return _family


def font(size=14):
    item = QFont(family(), size)
    item.setStyleStrategy(QFont.PreferAntialias)
    return item


FALLBACK = 0xE9D9       # unknown glyph: still something, never a KeyError


def char(key):
    return chr(GLYPHS.get(key, FALLBACK))


def glyph_font(key, px):
    """A face whose ink for this glyph is about `px` pixels tall.

    These fonts sit on a ~2em em box, so the point size has to come from a
    measurement rather than being used directly.
    """
    base = font(100)
    ink = QFontMetrics(base).tightBoundingRect(char(key))
    extent = max(ink.width(), ink.height())
    if extent <= 0:
        return font(max(6, int(px)))
    return font(max(6, int(round(100.0 * px / extent))))


def paint(painter, rect, key, color, px, align_left=False):
    """Draw one glyph, about `px` pixels tall, inside `rect`."""
    glyph = char(key)
    face = glyph_font(key, px)
    ink = QFontMetrics(face).tightBoundingRect(glyph)
    if ink.isEmpty():
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setPen(QColor(color))
    painter.setFont(face)
    if align_left:
        x = rect.left() + (rect.width() - ink.width()) / 2.0 - ink.x()
    else:
        x = rect.center().x() - ink.width() / 2.0 - ink.x()
    y = rect.center().y() - ink.height() / 2.0 - ink.y()
    painter.drawText(int(x), int(y), glyph)
    painter.restore()