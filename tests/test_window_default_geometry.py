"""The centered default window size, and View > Reset window.

Two halves, deliberately split:

  * the arithmetic (``default_window_rect``), which is Qt-free and pinned
    without a display -- including the tight case, a logical 1280x720 screen;
  * the action (``MainWindow.resetWindowGeometry``), driven on a real offscreen
    main window from a deliberately unusable geometry, because recovering an
    off-screen or too-small window is the only reason the action exists.

Settings note. ``resetWindowGeometry`` writes ``window/geometry``, which lives
in the machine-wide ``QSettings("KHLab", "PyReconstruct")`` domain alongside the
developer's real preferences. Every test here that lets that write happen first
redirects it, by monkeypatching ``main_window.windowGeometrySettings`` to a
``QSettings`` bound to an explicit file under ``tmp_path``. The explicit
``QSettings(fileName, IniFormat)`` constructor is used rather than
``setDefaultFormat``, which on PySide6 6.5.2 reports success and still resolves
the two-argument organization/application constructor to the native domain.
"""
import pytest

from conftest import menu_action

from PyReconstruct.modules.backend.func.window_geometry import (
    DEFAULT_SCREEN_FRACTION,
    default_window_rect,
    window_geometry_is_usable,
)


# --------------------------------------------------------------------------- #
# 1. the arithmetic
# --------------------------------------------------------------------------- #
def test_default_fraction_is_seventy_percent_linear():
    """0.5 was "a tad small"; 0.7 linear is about half the screen by area."""
    assert DEFAULT_SCREEN_FRACTION == 0.7
    assert 0.48 < DEFAULT_SCREEN_FRACTION ** 2 < 0.50


@pytest.mark.parametrize(
    "screen_w, screen_h, expected",
    [
        # the tight case: the smallest screen anyone plausibly runs this on
        (1280, 720, (192, 108, 896, 504)),
        (1440, 900, (216, 135, 1008, 630)),
        (1920, 1080, (288, 162, 1344, 756)),
        (2560, 1440, (384, 216, 1792, 1008)),
        (3840, 2160, (576, 324, 2688, 1512)),
    ],
)
def test_default_rect_is_seventy_percent_centered(screen_w, screen_h, expected):
    assert default_window_rect(screen_w, screen_h) == expected


@pytest.mark.parametrize(
    "screen_w, screen_h", [(1280, 720), (1440, 900), (1920, 1080), (3840, 2160)]
)
def test_default_rect_is_centered_to_within_a_pixel(screen_w, screen_h):
    """Stated as a property rather than a number: equal margins either side."""
    x, y, w, h = default_window_rect(screen_w, screen_h)
    assert abs((screen_w - (x + w)) - x) <= 1
    assert abs((screen_h - (y + h)) - y) <= 1


def test_default_rect_rounds_rather_than_truncates():
    """``720 * 0.7`` is 503.999... in binary floating point, not 504."""
    assert int(720 * 0.7) == 503          # what truncation would have given
    assert default_window_rect(1280, 720)[3] == 504


def test_the_fraction_is_a_parameter_so_it_stays_tunable():
    assert default_window_rect(1000, 1000, fraction=0.5) == (250, 250, 500, 500)
    assert default_window_rect(1000, 1000, fraction=0.9) == (50, 50, 900, 900)


# --------------------------------------------------------------------------- #
# 2. the interaction with the restore guard, which must not change
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "screen_w, screen_h", [(1280, 720), (1440, 900), (1920, 1080), (3840, 2160)]
)
def test_the_default_is_always_a_usable_geometry(screen_w, screen_h):
    """The fallback can never itself trip the guard that produced it.

    ``window_geometry_is_usable`` demands 480x360 and 30% visibility; the
    centered default is fully on screen and, at 1280x720, is 896x504.
    """
    rect = default_window_rect(screen_w, screen_h)
    assert window_geometry_is_usable(rect, [(0, 0, screen_w, screen_h)])


def test_the_guard_still_rejects_what_it_rejected_before():
    """The two shapes the fallback exists for are unchanged by this work."""
    screens = [(0, 0, 1920, 1080)]
    assert not window_geometry_is_usable((5000, 5000, 1000, 700), screens)  # off
    assert not window_geometry_is_usable((100, 100, 200, 150), screens)     # tiny


# --------------------------------------------------------------------------- #
# 3. the action
# --------------------------------------------------------------------------- #
# A geometry that is both too small and parked off every screen -- the state the
# action exists to escape, and one the guard rejects on either count alone.
BAD_GEOMETRY = (9000, 9000, 120, 90)


@pytest.fixture
def isolated_geometry_settings(monkeypatch, tmp_path):
    """Point `window/geometry` at a scratch ini file for the duration.

    Yields a zero-argument callable returning a fresh `QSettings` on that file,
    so a test can read back what the action wrote.
    """
    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.main import main_window as main_window_module

    path = str(tmp_path / "scratch-settings.ini")

    def scratch():
        return QSettings(path, QSettings.IniFormat)

    monkeypatch.setattr(main_window_module, "windowGeometrySettings", scratch)
    return scratch


def _expected_default(window):
    """The rect the action should produce, read from the live primary screen."""
    from PySide6.QtWidgets import QApplication

    from PyReconstruct.modules.gui.utils import get_screen_info

    info = get_screen_info(QApplication.primaryScreen())
    return default_window_rect(info["width"], info["height"])


def _rect(window):
    g = window.geometry()
    return (g.x(), g.y(), g.width(), g.height())


@pytest.mark.gui
def test_first_launch_falls_back_to_the_centered_default(
    qapp, series_jser, qsettings_snapshot, main_window_dialogs,
    isolated_geometry_settings,
):
    """The constructor's own fallback, not just the helper it calls.

    Built here rather than through the `main_window` fixture because the
    geometry store has to be empty *before* `MainWindow.__init__` reads it, and
    the fixture builds the window itself. The teardown mirrors that fixture's.
    """
    import sys as _sys

    from PyReconstruct.modules.gui.main import MainWindow

    assert isolated_geometry_settings().value("window/geometry") is None

    previous_excepthook = _sys.excepthook
    window = MainWindow(str(series_jser))
    try:
        assert _rect(window) == _expected_default(window)
        assert window._restoredGeometryIsUsable()
    finally:
        _sys.excepthook = previous_excepthook
        window.series.modified = False
        window.close()
        window.deleteLater()


@pytest.mark.gui
def test_reset_recovers_a_window_that_is_off_screen_and_tiny(
    main_window, isolated_geometry_settings
):
    main_window.setGeometry(*BAD_GEOMETRY)
    assert not main_window._restoredGeometryIsUsable()

    main_window.resetWindowGeometry()

    assert _rect(main_window) == _expected_default(main_window)
    assert main_window._restoredGeometryIsUsable()


@pytest.mark.gui
def test_reset_reads_nothing_from_the_broken_geometry(
    main_window, isolated_geometry_settings
):
    """Two different garbage rects have to land on the same answer."""
    main_window.setGeometry(*BAD_GEOMETRY)
    main_window.resetWindowGeometry()
    first = _rect(main_window)

    main_window.setGeometry(-8000, -8000, 1, 1)
    main_window.resetWindowGeometry()

    assert _rect(main_window) == first == _expected_default(main_window)


@pytest.mark.gui
def test_reset_overwrites_the_saved_geometry(
    main_window, isolated_geometry_settings
):
    """The reset has to survive a restart, not just the session."""
    settings = isolated_geometry_settings()
    settings.setValue("window/geometry", b"not a real geometry blob")
    settings.sync()

    main_window.setGeometry(*BAD_GEOMETRY)
    main_window.resetWindowGeometry()

    saved = isolated_geometry_settings().value("window/geometry")
    assert saved is not None
    assert bytes(saved) != b"not a real geometry blob"

    # and it round-trips: restoring it puts a window back at the default
    from PySide6.QtWidgets import QMainWindow

    revived = QMainWindow()
    try:
        assert revived.restoreGeometry(saved)
        g = revived.geometry()
        assert (g.x(), g.y(), g.width(), g.height()) == _expected_default(main_window)
    finally:
        revived.deleteLater()


@pytest.mark.gui
def test_reset_leaves_maximized_before_resizing(
    main_window, isolated_geometry_settings
):
    """`setGeometry` on a maximized window moves nothing the user can see.

    The bad rect is set *before* maximizing, so `showNormal` alone cannot
    produce the answer: it restores the window to the rect it was maximized
    from, which here is the broken one.
    """
    main_window.setGeometry(*BAD_GEOMETRY)
    main_window.showMaximized()
    assert main_window.isMaximized()

    main_window.resetWindowGeometry()

    assert not main_window.isMaximized()
    assert _rect(main_window) == _expected_default(main_window)


@pytest.mark.gui
def test_reset_calls_show_normal_before_setting_the_geometry(
    main_window, isolated_geometry_settings, monkeypatch
):
    """The `showNormal` call is asserted directly, because offscreen it is a
    no-op difference: with no window manager, `setGeometry` on a maximized
    window moves it anyway, so the end state alone cannot prove the guard is
    there. On a real platform `setGeometry` would change only the stored normal
    geometry and the window would stay maximized -- verified by removing the
    call, which the assertion above does not notice and this one does.
    """
    main_window.setGeometry(*BAD_GEOMETRY)
    main_window.showMaximized()
    assert main_window.isMaximized()

    calls = []
    real_show_normal = main_window.showNormal

    def spy():
        calls.append(_rect(main_window))
        real_show_normal()

    monkeypatch.setattr(main_window, "showNormal", spy)

    main_window.resetWindowGeometry()

    # called exactly once, and before the geometry was set
    assert len(calls) == 1
    assert calls[0] != _expected_default(main_window)


@pytest.mark.gui
def test_the_view_menu_action_is_wired_to_the_reset(
    main_window, isolated_geometry_settings
):
    """The menu item, not just the method: triggering it does the reset.

    Looked up through the live menubar rather than through
    ``main_window.viewmenu``, which is not the menubar's View menu: the field
    context menu declares a ``viewmenu`` of its own and ``createContextMenus``
    runs after ``createMenuBar``, so the attribute holds the context menu.
    """
    action = menu_action(main_window.menubar, "View > Reset window")
    assert action is not None
    assert action is main_window.resetwindow_act
    assert action.shortcut().toString() == ""

    main_window.setGeometry(*BAD_GEOMETRY)
    action.trigger()

    assert _rect(main_window) == _expected_default(main_window)
