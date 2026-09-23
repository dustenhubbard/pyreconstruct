"""A command's progress indicator is painted before its work starts."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QProgressDialog, QPushButton, QWidget

from PyReconstruct.modules.backend.progress import QtProgressReporter
from PyReconstruct.modules.gui.utils import utils

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("maximum", [0, 100])
@pytest.mark.parametrize("cancel", [False, True])
def test_progress_is_visible_and_painted_before_return(qtbot, monkeypatch, maximum, cancel):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    monkeypatch.setattr(utils, "mainwindow", parent)
    paints = []

    class PaintedProgress(QProgressDialog):
        def paintEvent(self, event):
            paints.append(True)
            super().paintEvent(event)

    monkeypatch.setattr(utils, "QProgressDialog", PaintedProgress)
    bar = utils.getProgbar("Working...", cancel=cancel, maximum=maximum)
    try:
        # Deliberately no wait/processEvents here: the next line in a command
        # may perform blocking work before it can report the first increment.
        assert bar.isVisible()
        assert paints, "show() alone may leave the first frame waiting on the work"
        assert bar.minimumDuration() == 0
        assert bar.maximum() == maximum
        buttons = bar.findChildren(QPushButton)
        assert bool(buttons) == cancel
        if maximum:
            assert bar.value() == 0
            bar.setValue(maximum)
            assert not bar.isVisible()
        else:
            assert bar.isVisible(), "indeterminate progress must not auto-reset"
    finally:
        bar.close()


def test_series_reporter_shows_without_a_first_update(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    monkeypatch.setattr(utils, "mainwindow", parent)
    reporter = QtProgressReporter("Editing sections...", cancel=False)
    try:
        assert reporter._progbar.isVisible()
    finally:
        reporter.finish()
    assert not reporter._progbar.isVisible()


def test_finishing_an_already_completed_reporter_does_not_flash_again(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    monkeypatch.setattr(utils, "mainwindow", parent)
    shows = []

    class ObservedProgress(QProgressDialog):
        def showEvent(self, event):
            shows.append(self.value())
            super().showEvent(event)

    monkeypatch.setattr(utils, "QProgressDialog", ObservedProgress)
    reporter = QtProgressReporter("Saving series...", cancel=False)
    try:
        reporter.set_progress(100)
        reporter.finish()
        reporter.finish()
        assert len(shows) == 1, "cleanup reopened the completed dialog"
        assert not reporter._progbar.isVisible()
    finally:
        reporter._progbar.close()


def test_console_progress_still_works_without_qt(monkeypatch, capsys):
    monkeypatch.setattr(utils.QApplication, "instance", lambda: None)
    bar = utils.getProgbar("Working...", cancel=False)
    assert isinstance(bar, utils.BasicProgbar)
    bar.setValue(100)
    assert "100.0%" in capsys.readouterr().out


@pytest.mark.parametrize("count", [1, 4])
def test_workers_start_with_visible_application_modal_progress(qtbot, monkeypatch, count):
    from PyReconstruct.modules.backend.threading.threading import ThreadPoolProgBar

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    monkeypatch.setattr(utils, "mainwindow", parent)
    pool = ThreadPoolProgBar()
    started = []

    def start(worker):
        visible = [bar for bar in parent.findChildren(QProgressDialog) if bar.isVisible()]
        assert len(visible) == 1
        assert visible[0].windowModality() == Qt.ApplicationModal
        started.append(worker)
        worker.run()

    monkeypatch.setattr(pool, "start", start)
    for _ in range(count):
        pool.createWorker(lambda: None)
    assert pool.startAll("Working...")
    assert len(started) == count
    assert all(not bar.isVisible() for bar in parent.findChildren(QProgressDialog))


def test_qt_progress_without_registered_window(qtbot, monkeypatch):
    monkeypatch.setattr(utils, "mainwindow", None)
    bar = utils.getProgbar("Opening series...", cancel=False)
    try:
        assert isinstance(bar, QProgressDialog)
        assert bar.isVisible()
        assert bar.parent() is None
    finally:
        bar.close()
