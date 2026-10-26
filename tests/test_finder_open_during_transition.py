"""A .jser opened from the Finder while an open, an import or a quit runs.

An open, a new series, an import, a Save As and a quit each show dialogs, and
every dialog runs the event loop, where macOS delivers a Finder open
(run.FileOpenWatcher). Opening that series there changed which series the
window held under the running transition. What is pinned here, against a real
window and the watcher as the app installs it:

  * the Finder open is refused with a notice naming the file, not queued
  * the running transition finishes on the series it started with, and an
    import writes into the series it started on
  * the unsaved work of the series the Finder asked for is still on disk
"""
import os
import shutil

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def finder(qapp, main_window, monkeypatch):
    """Send the event a Finder open sends, routed as the app routes it.

    Opening C would take its unsaved work.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent

    from PyReconstruct.modules.gui.main import main_window as mw
    from PyReconstruct.run import FileOpenWatcher
    watcher = FileOpenWatcher()
    watcher.main_window = main_window
    qapp.installEventFilter(watcher)
    monkeypatch.setattr(mw, "unsavedNotify", lambda *a, **k: True)
    yield lambda fp: qapp.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile(fp)))
    qapp.removeEventFilter(watcher)


def _two_more_series(window, tmp_path):
    """Series B, and series C with work left unsaved in its working folder.

    Returns B's file, C's file, and C's unsaved section file with its bytes.
    """
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.trace import Trace
    first = window.series

    def copy(name):
        fp = tmp_path / name / f"{name}.jser"
        fp.parent.mkdir()
        shutil.copyfile(first.jser_fp, fp)
        return str(fp)

    b_fp, c_fp = copy("series_b"), copy("series_c")
    # as a crash leaves it
    c = Series.openJser(c_fp, progress=NullProgressReporter)
    snum = sorted(c.sections)[0]
    section = c.loadSection(snum)
    trace = Trace("unsaved", (255, 0, 0), closed=True)
    trace.points = [(0, 0), (1, 0), (1, 1)]
    section.addTrace(trace, log_event=False)
    section.save()
    unsaved_fp = os.path.join(c.hidden_dir, c.sections[snum])
    with open(unsaved_fp, "rb") as f:
        return b_fp, c_fp, unsaved_fp, f.read()


def _holds(fp, data):
    if not os.path.isfile(fp):
        return False
    with open(fp, "rb") as f:
        return f.read() == data


def test_a_finder_open_under_the_open_dialog_keeps_its_unsaved_work(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    from PyReconstruct.modules.gui.dialog import FileDialog
    window = main_window
    b_fp, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def choose_b(*args, **kwargs):
        # the file dialog runs its own event loop, after the first series
        # closed and before B opens: C is opened from the Finder in it
        finder(c_fp)
        return b_fp

    monkeypatch.setattr(FileDialog, "get", staticmethod(choose_b))
    window.open_act.trigger()

    assert _holds(unsaved_fp, unsaved)
    assert window.series.jser_fp == b_fp and not window.series.closed
    assert any(c_fp in n for n in main_window_dialogs.notices)
    # refused, not queued: nothing opens C once the open of B is over
    assert not window.seriesTransitionRunning()


def test_a_finder_open_under_the_quit_prompt_keeps_its_unsaved_work(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    from PySide6.QtGui import QCloseEvent

    from PyReconstruct.modules.gui.main import main_window as mw
    window = main_window
    first = window.series
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    window.seriesModified(True)

    def dont_save(*args, **kwargs):
        # the save prompt runs its own event loop: C is opened from the
        # Finder while it is up, then the first series is not saved
        main_window_dialogs.save_prompts += 1
        if main_window_dialogs.save_prompts == 1:
            finder(c_fp)
        return "no"

    monkeypatch.setattr(mw, "saveNotify", dont_save)
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert _holds(unsaved_fp, unsaved)
    # the quit closed the series it was asked about, and asked only once
    assert window.series is first and first.closed
    assert main_window_dialogs.save_prompts == 1
    assert any(c_fp in n for n in main_window_dialogs.notices)


def test_a_finder_open_under_the_import_series_dialog_imports_into_the_first(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.gui.main import main_window as mw
    window = main_window
    first = window.series
    b_fp, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    # B, the series imported from, has an object group the first lacks
    b = Series.openJser(b_fp, progress=NullProgressReporter)
    obj = next(iter(b.data["objects"]))
    b.object_groups.add("from_b", obj)
    b.save()
    b.saveJser()
    b.close()
    assert "from_b" not in first.object_groups.getGroupList()

    def choose_groups(dialog):
        # the import dialog runs its own event loop: C is opened from the
        # Finder while it is up, then object groups are imported
        finder(c_fp)
        return {"attributes": [[
            ("groups", True), ("hosts", False), ("cols", False),
            ("zgroups", False), ("attrs", False),
        ]]}, True

    monkeypatch.setattr(mw.FileDialog, "get", staticmethod(lambda *a, **k: b_fp))
    monkeypatch.setattr(mw.ImportSeriesDialog, "exec", choose_groups)
    window.importFromSeries()

    assert window.series is first and not first.closed
    assert first.object_groups.getGroupObjects("from_b") == {obj}
    assert _holds(unsaved_fp, unsaved)
    assert any(c_fp in n for n in main_window_dialogs.notices)
    assert not window.seriesTransitionRunning()


def _labels_zarr(tmp_path, window, snum):
    """A zarr whose labels_x group holds label 123456 on section snum."""
    import numpy as np
    import zarr
    fp = str(tmp_path / "labels.zarr")
    zg = zarr.open(fp, mode="w")
    mag = window.field.section.mag
    raw = zg.create_dataset("raw", shape=(1, 100, 100), dtype=np.uint8)
    raw.attrs.update({
        "alignment": {str(snum): [1, 0, 0, 0, 1, 0]},
        "window": [0, 0, 100 * mag, 100 * mag], "offset": [0, 0, 0],
        "sections": [snum], "true_mag": mag,
        "voxel_size": [50, mag * 1000, mag * 1000],
    })
    labels = zg.create_dataset("labels_x", shape=(1, 100, 100), dtype=np.uint64)
    labels[0, 20:80, 20:80] = 123456
    labels.attrs.update({
        "offset": [0, 0, 0], "voxel_size": [50, mag * 1000, mag * 1000],
    })
    return fp


def test_a_finder_open_under_the_zarr_label_import_imports_into_the_first(
    qapp, main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtGui import QFileOpenEvent

    from PyReconstruct.modules.backend.autoseg import conversions
    from PyReconstruct.modules.gui.main import main_window as mw
    window = main_window
    first = window.series
    snum = first.current_section
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    zarr_fp = _labels_zarr(tmp_path, window, snum)
    name = conversions.AUTOSEG_TRACE_PREFIX + "123456"

    def choose_labels(*args, **kwargs):
        # the label dialog runs its own event loop: C is opened from the
        # Finder while it is up
        finder(c_fp)
        return [["labels_x"]], True

    import_section = conversions.importSection

    def import_section_then_finder_open(*args, **kwargs):
        # the workers run under the progress bar's event loop: C is opened
        # from the Finder again while they write
        QCoreApplication.postEvent(
            qapp, QFileOpenEvent(QUrl.fromLocalFile(c_fp))
        )
        return import_section(*args, **kwargs)

    monkeypatch.setattr(mw.FileDialog, "get", staticmethod(lambda *a, **k: zarr_fp))
    monkeypatch.setattr(mw.QuickDialog, "get", staticmethod(choose_labels))
    monkeypatch.setattr(conversions, "importSection", import_section_then_finder_open)
    window.importFromZarrLabels()
    qapp.processEvents()

    assert window.series is first and not first.closed
    assert name in first.loadSection(snum).contours
    # and none in C's working folder
    c_section_fp = os.path.join(
        os.path.dirname(unsaved_fp), first.sections[snum]
    )
    if os.path.isfile(c_section_fp):
        with open(c_section_fp) as f:
            assert name not in f.read()
    assert _holds(unsaved_fp, unsaved)
    assert sum(c_fp in n for n in main_window_dialogs.notices) == 2
    assert not window.seriesTransitionRunning()
