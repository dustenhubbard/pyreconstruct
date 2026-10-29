"""An open asked for from the event loop of a running open.

The progress window of an open runs the event loop while sections load, and a
queued slot there can call MainWindow.openSeries. That open used to run inside
the outer one: the nested series opened, a cancel of the outer open put the
first series back, and the nested series' working folder stayed on disk with
no series holding it. What is pinned here, on a real window and the real
progress window:

  * the nested open is refused with a notice and opens nothing
  * a series object handed to the refused open is left as it is: its owner,
    the caller or another live window, still holds its working folder
  * the canceled outer open leaves the first series open, as before
"""
import os
import shutil

import pytest

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("handed", ["file", "series"])
def test_an_open_queued_during_an_open_leaves_nothing_behind(
    qapp, main_window, main_window_dialogs, monkeypatch, tmp_path, handed
):
    from PySide6.QtCore import QObject, Qt, Signal

    from PyReconstruct.modules.backend.progress import (
        NullProgressReporter,
        QtProgressReporter,
    )
    from PyReconstruct.modules.datatypes import section_rows as sr
    from PyReconstruct.modules.datatypes import series as sm
    from PyReconstruct.modules.datatypes.series import Series

    window = main_window
    first = window.series
    incoming_fp = str(tmp_path / "incoming.jser")
    other_fp = str(tmp_path / "other.jser")
    for fp in (incoming_fp, other_fp):
        shutil.copyfile(first.jser_fp, fp)
    other_folder = os.path.join(str(tmp_path), ".other")
    if handed == "series":
        other = Series.openJser(other_fp, progress=NullProgressReporter)
        assert os.path.isdir(other.hidden_dir)

    reporters = []

    class Reporter(QtProgressReporter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            reporters.append(self)

    seen = {}

    class Sender(QObject):
        request = Signal()

        def __init__(self):
            super().__init__()
            self.request.connect(self.run, Qt.QueuedConnection)

        def run(self):
            # delivered by the progress window of the open of incoming
            outer = reporters[-1]
            seen["transition"] = window.seriesTransitionRunning()
            try:
                if handed == "series":
                    window.openSeries(other, query_prev=False)
                else:
                    window.openSeries(jser_fp=other_fp, query_prev=False)
            finally:
                outer._progbar.cancel()

    sender = Sender()
    real_load = sr.loadForOpen

    def load(series, n):
        rows = real_load(series, n)
        if os.path.basename(series.filepath) == "incoming.ser" and not seen:
            seen["queued"] = True
            sender.request.emit()
        return rows

    monkeypatch.setattr(sm, "_PROGRESS_REPORTER_FACTORY", Reporter)
    monkeypatch.setattr(sr, "PARALLEL_MIN_BYTES", float("inf"))
    monkeypatch.setattr(sr, "loadForOpen", load)

    window.openSeries(jser_fp=incoming_fp, query_prev=False)

    assert seen.get("transition") is True
    assert window.series.jser_fp == first.jser_fp
    assert not window.series.closed
    assert not window.seriesTransitionRunning()
    assert not os.path.exists(os.path.join(str(tmp_path), ".incoming"))
    if handed == "series":
        # the caller still owns the series it handed over
        assert not other.closed
        assert os.path.isdir(other_folder)
        other.close()
    assert not os.path.exists(other_folder)
    assert any(
        n.startswith("Open skipped") and other_fp in n
        for n in main_window_dialogs.notices
    )


def test_a_refused_open_leaves_another_windows_series_alone(
    main_window, main_window_dialogs, tmp_path
):
    """A series that another live window holds, with a section saved to its
    working folder and not to the .jser, survives a refused open of it."""
    import hashlib
    import sys

    from PyReconstruct.modules.datatypes import Trace
    from PyReconstruct.modules.gui.main import MainWindow

    window = main_window
    other_fp = tmp_path / "other-window.jser"
    shutil.copyfile(window.series.jser_fp, other_fp)
    hook = sys.excepthook
    other_window = MainWindow(str(other_fp))
    other = other_window.series
    other_window._captureListLayout = lambda: None
    folder = other.hidden_dir
    section = other_window.field.section
    trace = Trace("only-in-working-folder", (255, 0, 0), closed=True)
    trace.points = [(0, 0), (1, 0), (1, 1)]
    section.addTrace(trace, log_event=False)
    section.save()
    other.modified = True
    digest = hashlib.sha256(other_fp.read_bytes()).hexdigest()
    try:
        with window.seriesTransition():
            window.openSeries(other, query_prev=False)
        assert window.series is not other
        assert not other.closed
        assert os.path.isdir(folder)
        assert "only-in-working-folder" in other.loadSection(section.n).contours
        assert hashlib.sha256(other_fp.read_bytes()).hexdigest() == digest
        assert any(
            n.startswith("Open skipped") for n in main_window_dialogs.notices
        )
    finally:
        other.modified = False
        other.unsaved_series_data = False
        other_window.close()
        other_window.deleteLater()
        sys.excepthook = hook
