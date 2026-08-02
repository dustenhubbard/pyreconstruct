"""Validate a restored main-window geometry against the current screens.

Qt's ``restoreGeometry`` can leave the window unusable when the display setup
changed since the geometry was saved -- most commonly moving a laptop between a
1x external monitor and a 2x (HiDPI/Retina) internal panel, which can restore a
window that is tiny or parked off every connected screen ("window opens very
tiny"). This module holds the Qt-free decision so it can be unit-tested without
a display; the GUI passes plain ``(x, y, w, h)`` rects in device-independent
pixels.
"""


# Fraction of the primary screen the window falls back to when there is no
# usable saved geometry. It is LINEAR: applied to width and to height
# separately, so the window covers roughly `fraction ** 2` of the screen by
# area. It was 0.5 -- a quarter of the screen -- until he said:
#
#     "i think 50% is a tad small."
#
# 0.7 linear is about half the screen by area, still comfortably short of
# near-maximized, which the centered fallback was deliberately chosen to avoid.
# This number is his to tune: change it here and both the first-launch fallback
# and View > Reset window follow.
DEFAULT_SCREEN_FRACTION = 0.7


def default_window_rect(
    screen_w: int,
    screen_h: int,
    fraction: float = DEFAULT_SCREEN_FRACTION,
) -> tuple:
    """The centered default window rect for a screen, as ``(x, y, w, h)``.

    Depends on nothing but the screen, which is the whole point: it is also the
    answer for a window whose current geometry is garbage (tiny, or parked off
    every display), where reading the window would only propagate the problem.

    ``round`` rather than ``int``: binary floating point makes ``720 * 0.7``
    come out at 503.999..., and truncating that to 503 is an arithmetic
    artifact rather than a decision.

        Params:
            screen_w (int): screen width in device-independent pixels
            screen_h (int): screen height in device-independent pixels
            fraction (float): linear fraction of the screen to occupy
        Returns:
            (tuple): (x, y, w, h) in the same coordinate space
    """
    w = round(screen_w * fraction)
    h = round(screen_h * fraction)
    return ((screen_w - w) // 2, (screen_h - h) // 2, w, h)


def _intersection_area(a, b) -> int:
    """Area of the overlap between two ``(x, y, w, h)`` rects (0 if disjoint)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left   = max(ax, bx)
    top    = max(ay, by)
    right  = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def window_geometry_is_usable(
    window_rect,
    screen_rects,
    min_w: int = 480,
    min_h: int = 360,
    min_visible: float = 0.30,
) -> bool:
    """Whether a restored window rect is usable on the current screens.

    ``window_rect`` and every rect in ``screen_rects`` are ``(x, y, w, h)``
    tuples in the same device-independent coordinate space (e.g. Qt's
    ``availableGeometry``). Usable means BOTH:

      * the window meets a minimum size (``min_w`` x ``min_h``), and
      * at least ``min_visible`` of its area lands on the connected screens.

    Screen rects tile the virtual desktop without overlapping, so summing the
    per-screen intersections gives the total visible fraction -- a window
    straddling two monitors is still counted as visible.
    """
    x, y, w, h = window_rect
    if w < min_w or h < min_h:
        return False
    area = w * h
    if area <= 0:
        return False
    if not screen_rects:
        return False
    visible = sum(_intersection_area(window_rect, s) for s in screen_rects)
    return (visible / area) >= min_visible
