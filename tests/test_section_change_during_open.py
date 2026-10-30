"""A section change asked for from the event loop of a running open.

The progress window of an open runs the event loop while sections load, and a
queued slot there can call FieldWidget.changeSection. The outgoing series is
already closed by then, so the change read its section from a working folder
that was gone and raised FileNotFoundError. What is pinned here, on a real
window and the real progress window:

  * the section change is dropped and raises nothing
  * the canceled outer open leaves the first series open on its section
  * outside a transition the same change still runs
"""
import shutil

import pytest

pytestmark = pytest.mark.gui


def test_a_section_change_queued_during_an_open_is_dropped(
    qapp, main_window, main_window_dialogs, monkeypatch, tmp_path
):
    from PySide6.QtCore import QObject, Qt, Signal

    from PyReconstruct.modules.backend.progress import QtProgressReporter
    from PyReconstruct.modules.datatypes import section_rows as sr
    from PyReconstruct.modules.datatypes import series as sm

    window = main_window
    first = window.series
    start = first.current_section
    target = next(n for n in sorted(first.sections) if n != start)
    incoming_fp = str(tmp_path / "incoming.jser")
    shutil.copyfile(first.jser_fp, incoming_fp)

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
                window.field.changeSection(target)
            except Exception as exc:
                seen["error"] = repr(exc)
            finally:
                outer._progbar.cancel()

    sender = Sender()
    real_load = sr.loadForOpen

    def load(series, n):
        rows = real_load(series, n)
        if series.filepath.endswith("incoming.ser") and not seen:
            seen["queued"] = True
            sender.request.emit()
        return rows

    monkeypatch.setattr(sm, "_PROGRESS_REPORTER_FACTORY", Reporter)
    monkeypatch.setattr(sr, "PARALLEL_MIN_BYTES", float("inf"))
    monkeypatch.setattr(sr, "loadForOpen", load)

    window.openSeries(jser_fp=incoming_fp, query_prev=False)

    assert seen.get("transition") is True
    assert "error" not in seen
    assert window.series.jser_fp == first.jser_fp
    assert not window.series.closed
    assert window.series.current_section == start
    assert window.field.section.n == start

    # outside a transition the same change runs
    window.field.changeSection(target)
    assert window.series.current_section == target
    assert window.field.section.n == target
