"""A .jser opened from the Finder while the first window is being built.

The window gets Finder opens once it is built. An open under a dialog it
shows on the way is skipped with a notice once the window is up; one with no
dialog up opens in the window then. Neither is left waiting.
"""
import shutil

import pytest

from conftest import SERIES_FIXTURE

pytestmark = pytest.mark.gui


@pytest.fixture
def watcher(qapp):
    """The Finder open filter as runPyReconstruct installs it, with no window yet."""
    from PyReconstruct.run import FileOpenWatcher
    w = FileOpenWatcher()
    qapp.installEventFilter(w)
    yield w
    qapp.removeEventFilter(w)


@pytest.fixture
def other_jser(tmp_path):
    """A second series for the Finder to open."""
    fp = tmp_path / "other" / "other.jser"
    fp.parent.mkdir()
    shutil.copyfile(SERIES_FIXTURE, fp)
    return str(fp)


def _send_open(qapp, fp):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent
    qapp.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile(fp)))


@pytest.fixture
def open_during_construction(qapp, watcher, other_jser, monkeypatch, request):
    """Send the Finder open from a step of MainWindow.__init__.

    With request.param "dialog" it arrives under a modal dialog that step
    shows; with "none" it arrives with no dialog up. Returns a list that
    holds whether a modal dialog was up when it arrived.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog
    from PyReconstruct.modules.gui.main import main_window as mw
    seen = []
    real = mw.MainWindow.resolveUsernameStartup

    def step(self):
        if request.param == "dialog":
            dialog = QDialog(self)
            dialog.setModal(True)

            def arrive():
                seen.append(QApplication.activeModalWidget() is dialog)
                _send_open(qapp, other_jser)
                dialog.accept()

            QTimer.singleShot(0, arrive)
            dialog.exec()
        else:
            seen.append(QApplication.activeModalWidget() is not None)
            _send_open(qapp, other_jser)
        return real(self)

    monkeypatch.setattr(mw.MainWindow, "resolveUsernameStartup", step)
    return seen


def _settle(qapp):
    from PySide6.QtCore import QEventLoop
    for _ in range(5):
        qapp.processEvents(QEventLoop.AllEvents, 50)


@pytest.mark.parametrize("open_during_construction", ["dialog"], indirect=True)
def test_an_open_under_a_startup_dialog_is_refused_once_the_window_is_up(
    qapp, watcher, open_during_construction, main_window, main_window_dialogs,
    other_jser, series_jser
):
    assert open_during_construction == [True]
    assert not any(other_jser in n for n in main_window_dialogs.notices)

    watcher.main_window = main_window
    _settle(qapp)

    assert sum(other_jser in n for n in main_window_dialogs.notices) == 1
    assert main_window.series.jser_fp == str(series_jser)
    assert watcher.pending is None and not watcher.refused


@pytest.mark.parametrize("open_during_construction", ["none"], indirect=True)
def test_an_open_with_no_startup_dialog_up_opens_once_the_window_is_up(
    qapp, watcher, open_during_construction, main_window, main_window_dialogs,
    other_jser
):
    assert open_during_construction == [False]

    watcher.main_window = main_window
    _settle(qapp)

    assert main_window.series.jser_fp == other_jser
    assert not any(other_jser in n for n in main_window_dialogs.notices)
    assert watcher.pending is None and not watcher.refused


@pytest.mark.parametrize("open_during_construction", ["dialog"], indirect=True)
def test_an_open_left_by_a_window_closed_before_its_first_pass_goes_to_the_next(
    qapp, watcher, open_during_construction, main_window, main_window_dialogs,
    other_jser
):
    watcher.main_window = main_window
    watcher.main_window = None
    _settle(qapp)
    assert len(watcher.refused) == 1
    assert not any(other_jser in n for n in main_window_dialogs.notices)

    watcher.main_window = main_window
    _settle(qapp)
    assert sum(other_jser in n for n in main_window_dialogs.notices) == 1
    assert not watcher.refused
