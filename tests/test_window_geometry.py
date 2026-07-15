"""The Qt-free guard behind cross-DPI window-geometry restore.

``restoreGeometry`` can leave the main window tiny or parked off every screen
after the display setup changes (moving a laptop between a 1x external monitor
and a 2x Retina panel). ``window_geometry_is_usable`` decides whether to keep
the restored rect or fall back to the centered default; these tests pin that
decision without needing a display.
"""
from PyReconstruct.modules.backend.func.window_geometry import (
    window_geometry_is_usable,
)

# A single 1920x1080 screen at the origin, unless a test says otherwise.
ONE_SCREEN = [(0, 0, 1920, 1080)]


def test_fully_on_screen_and_large_is_usable():
    assert window_geometry_is_usable((100, 100, 1000, 700), ONE_SCREEN)


def test_too_small_is_not_usable():
    # the "opens very tiny" symptom
    assert not window_geometry_is_usable((100, 100, 200, 150), ONE_SCREEN)


def test_below_only_one_dimension_is_not_usable():
    assert not window_geometry_is_usable((0, 0, 1000, 100), ONE_SCREEN)   # short
    assert not window_geometry_is_usable((0, 0, 100, 1000), ONE_SCREEN)   # narrow


def test_completely_off_screen_is_not_usable():
    # parked far past the right edge -- no overlap at all
    assert not window_geometry_is_usable((5000, 5000, 1000, 700), ONE_SCREEN)


def test_barely_visible_sliver_is_not_usable():
    # only a thin strip pokes onto the screen -> below the 30% threshold
    assert not window_geometry_is_usable((1870, 100, 1000, 700), ONE_SCREEN)


def test_mostly_visible_is_usable():
    # hangs off the right edge but well over half its area is on screen
    assert window_geometry_is_usable((1100, 100, 1000, 700), ONE_SCREEN)


def test_spanning_two_screens_counts_total_visible():
    # a window straddling two side-by-side monitors is fully visible even
    # though neither screen alone holds 30% of it
    screens = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
    assert window_geometry_is_usable((1420, 100, 1000, 700), screens)


def test_no_screens_is_not_usable():
    assert not window_geometry_is_usable((100, 100, 1000, 700), [])


def test_zero_area_is_not_usable():
    assert not window_geometry_is_usable((0, 0, 0, 0), ONE_SCREEN)


def test_custom_thresholds_are_honored():
    rect = (0, 0, 300, 250)
    assert not window_geometry_is_usable(rect, ONE_SCREEN)               # default min
    assert window_geometry_is_usable(rect, ONE_SCREEN, min_w=200, min_h=200)
