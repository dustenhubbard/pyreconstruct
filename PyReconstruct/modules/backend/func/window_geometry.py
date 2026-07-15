"""Validate a restored main-window geometry against the current screens.

Qt's ``restoreGeometry`` can leave the window unusable when the display setup
changed since the geometry was saved -- most commonly moving a laptop between a
1x external monitor and a 2x (HiDPI/Retina) internal panel, which can restore a
window that is tiny or parked off every connected screen ("window opens very
tiny"). This module holds the Qt-free decision so it can be unit-tested without
a display; the GUI passes plain ``(x, y, w, h)`` rects in device-independent
pixels.
"""


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
