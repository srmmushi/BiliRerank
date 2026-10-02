"""The taskbar icon: a bilibili style little TV with a hook.

Drawn with Pillow once, into the config folder (next to settings.json), so it
can be replaced by dropping an icon.ico / icon.png there.

The TV is the recognisable part at 16px: white body, two antennae, a face. The
hook sits to its right - thick strokes only, nothing that survives downscaling.
"""

TILE_TOP = (255, 154, 184)
TILE_BOTTOM = (226, 84, 130)
WHITE = (255, 255, 255)
PINK = (238, 62, 109)


def render(path):
    """Write the icon and return True on success."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    _tile(draw, size)
    _tv(draw, size)
    _hook(draw, size)

    # round the corners of the whole tile
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8, 8, size - 8, size - 8], radius=54, fill=255)
    image.putalpha(mask)

    try:
        image.save(path, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    except OSError:
        return False
    return True


def _tile(draw, size):
    for y in range(size):
        mix = y / float(size - 1)
        draw.line([(0, y), (size, y)],
                  fill=tuple(int(TILE_TOP[i] + (TILE_BOTTOM[i] - TILE_TOP[i]) * mix)
                             for i in range(3)))


def _tv(draw, size):
    left, right, top, bottom = 40, 176, 96, 186
    white = WHITE

    # antennae: a line out of each top corner with a tip
    for start, end in (((84, top), (62, 62)), ((132, top), (154, 62))):
        draw.line([start, end], fill=white, width=11)
        x, y = end
        draw.ellipse([x - 11, y - 11, x + 11, y + 11], fill=white)

    draw.rounded_rectangle([left, top, right, bottom], radius=22, fill=white)

    # face: two eyes and a smile
    for cx in (78, 138):
        draw.ellipse([cx - 9, 126, cx + 9, 148], fill=PINK)
    draw.arc([84, 140, 132, 172], start=20, end=160, fill=PINK, width=9)


def _hook(draw, size):
    """A thick hook to the right of the TV: eyelet, shaft, then the curve."""
    white = WHITE
    x = 206

    draw.ellipse([x - 13, 74, x + 13, 100], outline=white, width=10)
    draw.line([(x, 96), (x, 150)], fill=white, width=13)
    draw.arc([x - 44, 122, x + 12, 178], start=0, end=180, fill=white, width=13)
