"""Progress bars that show up and say how long (fork issue #421).

Kristen's report: rename, 3D and other long tasks sat with no bar, or a bar
with no estimate. Three changes, each pinned here:

  * Every operation's section pass asks its progress bar for a time estimate.
    Opening a series does not (his call, 2026-09-14).
  * The 3D export pass (export meshes, export 3D data) shows a bar with an
    estimate and loads only the sections that hold the objects. It ran silently
    over every section before.
  * The 3D scene's worker reports a percent while it runs. A lone reporting
    worker turns the status-bar spinner into a real bar with an estimate.
"""
import os
import shutil

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStatusBar, QWidget, QProgressDialog

from PyReconstruct.modules.backend.progress import NullProgressReporter

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)


class Capturing(NullProgressReporter):
    made = []

    def __init__(self, text="", cancel=True, eta=False):
        super().__init__(text, cancel, eta)
        Capturing.made.append((text, eta))


def _open(tmp_path, name="shapes1.jser"):
    src = os.path.join(FIXTURE_DIR, name)
    if not os.path.exists(src):
        pytest.skip(f"fixture {name} not found")
    fp = str(tmp_path / name)
    shutil.copyfile(src, fp)
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    return Series.openJser(fp)


# ---------------------------------------------------------------------------
# estimates on operation bars, none on open
# ---------------------------------------------------------------------------

def test_operations_ask_for_an_estimate_and_opening_does_not(series_jser):
    from PyReconstruct.modules.datatypes import Series
    Capturing.made = []
    s = Series.openJser(str(series_jser), progress=Capturing)
    try:
        assert Capturing.made, "opening showed no bar at all"
        assert all(eta is False for _, eta in Capturing.made), Capturing.made
        Capturing.made = []
        s.setProgressReporter(Capturing)
        # the series-data rebuild is the open pass; it must stay estimate-free
        s.data.refresh()
        assert Capturing.made == [("Loading series data...", False)]
        Capturing.made = []
        name = sorted(s.data["objects"].keys())[0]
        s.deleteObjects([name])
        assert Capturing.made == [("Deleting object(s)...", True)]
    finally:
        s.close()


def test_series_iterator_defaults_to_an_estimate():
    import inspect
    from PyReconstruct.modules.datatypes.series import Series, SeriesIterator
    assert inspect.signature(Series.enumerateSections).parameters["eta"].default is True
    assert inspect.signature(SeriesIterator.__init__).parameters["eta"].default is True


# ---------------------------------------------------------------------------
# the 3D export pass
# ---------------------------------------------------------------------------

def test_3d_export_pass_shows_a_bar_and_loads_only_holding_sections(series_jser, monkeypatch):
    from PyReconstruct.modules.backend.volume.export_volumes import get_3D_meshes
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.datatypes import series as series_mod

    QApplication.instance() or QApplication(["test"])
    s = Series.openJser(str(series_jser))
    try:
        Capturing.made = []
        s.setProgressReporter(Capturing)
        # d03 is on 182 of the 198 fixture sections
        name = "d03"
        holding = s.getObjectSections([name])
        assert holding and holding != set(s.sections), (
            "fixture premise: the object must be on some but not all sections"
        )

        seen = []
        real = series_mod.Series.loadSection

        def spy(self, snum, *a, **k):
            seen.append(snum)
            return real(self, snum, *a, **k)

        monkeypatch.setattr(series_mod.Series, "loadSection", spy)
        meshes = get_3D_meshes(s, [name])

        assert set(meshes) == {name}
        assert Capturing.made == [("Building 3D meshes...", True)]
        assert set(seen) == holding, f"loaded {sorted(seen)}, object is on {sorted(holding)}"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# the 3D scene worker reports a percent
# ---------------------------------------------------------------------------

def test_generate_volumes_reports_percent_from_zero_to_a_hundred(tmp_path):
    from PyReconstruct.modules.backend.volume.generate_volumes import generateVolumes

    s = _open(tmp_path)
    try:
        s.setProgressReporter(NullProgressReporter)
        name = sorted(s.data["objects"].keys())[0]
        reports = []
        meshes, _ = generateVolumes(
            s, [{"name": name}], [], progress=reports.append
        )
        assert len(meshes) == 1
        assert reports[0] == 0 and reports[-1] == 100
        assert reports == sorted(reports), "percent went backwards"
        # both phases spoke: the section pass under 80, the meshing at or over
        assert any(0 < r < 80 for r in reports)
        assert any(80 <= r < 100 for r in reports)
    finally:
        s.close()


def test_generate_volumes_without_a_callback_is_unchanged(tmp_path):
    from PyReconstruct.modules.backend.volume.generate_volumes import generateVolumes

    s = _open(tmp_path)
    try:
        s.setProgressReporter(NullProgressReporter)
        name = sorted(s.data["objects"].keys())[0]
        meshes, _ = generateVolumes(s, [{"name": name}], [])
        assert len(meshes) == 1
    finally:
        s.close()


def test_worker_passes_progress_only_when_asked():
    from PyReconstruct.modules.backend.threading.threading import Worker
    QApplication.instance() or QApplication(["test"])

    got = {}

    def plain(a, b):
        got["plain"] = (a, b)

    def reporting(a, progress):
        got["reporting"] = a
        progress(42.7)

    Worker(plain, 1, 2).run()
    assert got["plain"] == (1, 2)

    w = Worker(reporting, 5, progress=True)
    emitted = []
    w.signals.progress.connect(emitted.append, Qt.DirectConnection)
    w.run()
    assert got["reporting"] == 5
    assert emitted == [42], "percent is emitted as an int"


def _run_pool(pool, status_bar):
    """Drive startAll with the worker run inline, delivering its queued signals."""
    def start(worker):
        worker.run()
        QApplication.processEvents()

    pool.start = start
    return pool.startAll("Generating 3D...", status_bar=status_bar)


def test_lone_reporting_worker_turns_the_spinner_into_a_bar(qtbot, monkeypatch):
    from PyReconstruct.modules.backend.threading import threading as th

    parent = QWidget()
    qtbot.addWidget(parent)
    bar = QStatusBar(parent)
    parent.show()

    # a fixed estimate, so the label text is deterministic
    monkeypatch.setattr(th, "estimate_remaining", lambda elapsed, pct: 40.0)

    seen = []

    def job(progress):
        for pct in (0, 50, 90):
            progress(pct)
            QApplication.processEvents()
            widgets = bar.findChildren(th.QProgressBar)
            labels = bar.findChildren(th.QLabel)
            seen.append((
                widgets[0].maximum(), widgets[0].value(),
                labels[0].text(),
            ))

    pool = th.ThreadPoolProgBar()
    pool.createWorker(job, progress=True)
    assert _run_pool(pool, bar)

    assert seen == [
        (100, 0, "Generating 3D... about 40 seconds left"),
        (100, 50, "Generating 3D... about 40 seconds left"),
        (100, 90, "Generating 3D... about 40 seconds left"),
    ], seen
    assert all(not w.isVisible() for w in bar.findChildren(th.QProgressBar)), (
        "the bar was not torn down"
    )


def test_lone_reporting_worker_in_dialog_mode_gets_percent_and_label(qtbot, monkeypatch):
    from PyReconstruct.modules.backend.threading import threading as th
    from PyReconstruct.modules.gui.utils import utils

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    monkeypatch.setattr(utils, "mainwindow", parent)
    monkeypatch.setattr(th, "estimate_remaining", lambda elapsed, pct: 90.0)

    seen = []

    def job(progress):
        progress(25)
        QApplication.processEvents()
        dlg = [d for d in parent.findChildren(QProgressDialog) if d.isVisible()][0]
        seen.append((dlg.maximum(), dlg.value(), dlg.labelText()))

    pool = th.ThreadPoolProgBar()
    pool.createWorker(job, progress=True)
    assert _run_pool(pool, None)
    assert seen == [(100, 25, "Generating 3D... about 2 minutes left")], seen


def test_several_workers_keep_the_per_worker_count(qtbot):
    """Two reporting workers would fight over one bar, so the count stays."""
    from PyReconstruct.modules.backend.threading import threading as th

    parent = QWidget()
    qtbot.addWidget(parent)
    bar = QStatusBar(parent)
    parent.show()

    maxima = []

    def job(progress):
        progress(50)
        QApplication.processEvents()
        maxima.append(bar.findChildren(th.QProgressBar)[0].maximum())

    pool = th.ThreadPoolProgBar()
    pool.createWorker(job, progress=True)
    pool.createWorker(job, progress=True)
    assert _run_pool(pool, bar)
    assert maxima == [0, 0], "a percent from one of two workers moved the bar"
