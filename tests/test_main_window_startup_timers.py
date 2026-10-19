"""A main window's startup timers stay with the window that armed them.

``MainWindow.__init__`` arms two single-shot timers: What's new at 750 ms and
the launch update check at 2500 ms. They used to be bare ``QTimer.singleShot``
calls, which belong to no window, so a window closed before they fired left
them pending and the handlers ran on the closed window while something else
was on screen. In this suite every ``main_window`` fixture window is closed
and only queued for deletion, so each test's timers came due during the next
test, and two tests had grown their own guards against it
(``test_update_notice.py``, ``test_whats_new_popup_reset.py``). The window
now owns both timers and ``closeEvent`` stops them.

The first test asserts the state a fixture window is torn down in: both
timers still pending. The second builds a window first and closes it the way
the fixture's teardown does, then builds its own; it finds the closed window's
timers stopped, processes events past the later deadline, and sees only its
own window reach the two handlers. It needs no other test to have run first.
The handlers are wrapped on the class before either window is
built, so the timers connect to the wrappers and a run on the closed window is
recorded whenever it happens, during the next window's construction included.
"""
import shutil
import sys

import pytest
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.gui.main import main_window as MW

# (handler name, window) for every run of a startup handler on a window built
# in this module, in order. Module level so a run after the test that built
# the window has ended is still recorded.
CALLS = []

# Past the later of the two timers, with room for a slow machine.
PAST_BOTH_TIMERS_MS = 3000

HANDLERS = ("showWhatsNewStartup", "checkForUpdatesStartup")


@pytest.fixture
def recorded_startup_handlers(monkeypatch):
    """Wrap both startup handlers on the class, recording the window each
    runs on. Listed before ``main_window`` in a test's signature so the
    wrappers are in place when ``__init__`` binds the handlers to the timers;
    the connections keep the wrappers after the patch is undone."""
    for name in HANDLERS:
        real = getattr(MW.MainWindow, name)

        def wrapper(self, _name=name, _real=real):
            CALLS.append((_name, self))
            return _real(self)

        monkeypatch.setattr(MW.MainWindow, name, wrapper)


@pytest.mark.gui
def test_a_window_ends_its_test_with_both_timers_pending(
    recorded_startup_handlers, main_window
):
    """The state a fixture window is torn down in, asserted rather than
    assumed: the timers are live, and nothing has run yet."""
    assert main_window.whats_new_timer.isActive()
    assert main_window.update_check_timer.isActive()
    assert not [window for _, window in CALLS if window is main_window]


@pytest.fixture
def spent_window(recorded_startup_handlers, main_window_dialogs, tmp_path):
    """A window built and closed before the test's own, as the previous
    test's fixture window is: closed with both timers pending and only queued
    for deletion. Listed before ``main_window`` so it is built first.

    The reference keeps the Python wrapper alive; the C++ window may or may
    not still exist by the time the test looks."""
    from conftest import SERIES_FIXTURE

    copy = tmp_path / "spent" / "series.jser"
    copy.parent.mkdir()
    shutil.copy(SERIES_FIXTURE, copy)
    previous_excepthook = sys.excepthook
    window = MW.MainWindow(str(copy))
    window._captureListLayout = lambda: None
    sys.excepthook = previous_excepthook
    assert window.whats_new_timer.isActive()
    assert window.update_check_timer.isActive()
    window.series.modified = False
    window.close()
    window.deleteLater()
    return window, len(CALLS)


@pytest.mark.gui
def test_a_finished_test_s_window_fires_nothing_in_this_one(
    recorded_startup_handlers, spent_window, main_window, qtbot
):
    spent, since = spent_window
    # the closed window: both timers stopped. A timer whose C++ object is gone
    # went with its window and cannot fire.
    for timer in (spent.whats_new_timer, spent.update_check_timer):
        assert not (isValid(timer) and timer.isActive())

    # past both deadlines, the handlers hear from this window and no other
    mark = len(CALLS)
    qtbot.wait(PAST_BOTH_TIMERS_MS)
    assert CALLS[mark:] == [(name, main_window) for name in HANDLERS]
    assert QApplication.activeWindow() is main_window

    # and no handler ran on the closed window after it closed, whenever that
    # would have been
    assert not [name for name, window in CALLS[since:] if window is spent]
