"""Draw the dmg window background: light gray with one dark chevron.

Writes dmg-background.png (1x) and dmg-background@2x.png next to this file.
dmgbuild finds the @2x file and joins both into one HiDPI image. The sizes
and the chevron position must match dmg_settings.py.

    python packaging/macos/make_dmg_background.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 640, 560          # points; covers the tallest window (with the guide)
BACKGROUND = (236, 236, 236)
CHEVRON = (60, 60, 64)
CENTER = (320, 160)               # between the two icons, at their center line
HALF_WIDTH, HALF_HEIGHT = 14, 28  # the chevron's arms, in points
STROKE = 6                        # points

SUPERSAMPLE = 4                   # drawn large, then scaled down for smooth edges


def draw(scale):
    s = scale * SUPERSAMPLE
    img = Image.new("RGB", (WIDTH * s, HEIGHT * s), BACKGROUND)
    cx, cy = CENTER[0] * s, CENTER[1] * s
    points = [(cx - HALF_WIDTH * s, cy - HALF_HEIGHT * s),
              (cx + HALF_WIDTH * s, cy),
              (cx - HALF_WIDTH * s, cy + HALF_HEIGHT * s)]
    width = STROKE * s
    pen = ImageDraw.Draw(img)
    pen.line(points, fill=CHEVRON, width=width, joint="curve")
    r = width / 2                 # round caps on both ends
    for x, y in (points[0], points[-1]):
        pen.ellipse((x - r, y - r, x + r, y + r), fill=CHEVRON)
    return img.resize((WIDTH * scale, HEIGHT * scale), Image.LANCZOS)


def main():
    here = Path(__file__).resolve().parent
    draw(1).save(here / "dmg-background.png", dpi=(72, 72), optimize=True)
    draw(2).save(here / "dmg-background@2x.png", dpi=(144, 144), optimize=True)


if __name__ == "__main__":
    main()
