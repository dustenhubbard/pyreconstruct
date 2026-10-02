"""Actions that reload the field keep a trace drawn just before them.

`field.reload()` reads each section from its file. A trace drawn since the
section was last written exists only in memory, so an action that reloads
without writing first loses it, and the next save writes the section without
it. Switching the series alignment did this, and so did both label imports,
which also rewrite the sections they import into.
"""
import shutil
import types

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "reload_keep_obj"


class _InlinePool:
    """ThreadPoolProgBar, run in this thread."""

    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _draw(window):
    series, field = window.series, window.field
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.4, wy + wh * 0.4
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(
        [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)],
        field.tracing_trace, points_as_pix=False, reduce_points=False,
    )
    assert NAME in _names(field.section)
    return field.section.n


def _names(section):
    return [t.name for t in section.tracesAsList()]


def _assert_kept(window, snum, tmp_path):
    from PyReconstruct.modules.datatypes.series import Series

    assert NAME in _names(window.field.section), "gone in memory"
    window.saveToJser()
    # a copy in its own folder: opening the file in place would share the
    # open window's working folder, and closing it deletes that folder
    copy = tmp_path / "reopened" / "series.jser"
    copy.parent.mkdir()
    shutil.copyfile(window.series.jser_fp, copy)
    reopened = Series.openJser(str(copy))
    try:
        assert NAME in _names(reopened.loadSection(snum)), "gone after reopening"
    finally:
        reopened.close()


def _labels_zarr(tmp_path, snum):
    """A zarr with one label, 7, on section snum."""
    fp = tmp_path / "labels.zarr"
    zg = zarr.open(str(fp), "w")
    raw = zg.create_dataset("raw", shape=(1, 100, 100), dtype=np.uint8)
    raw.attrs.update({
        "voxel_size": [50, 4, 4], "offset": [0, 0, 0],
        "true_mag": 0.004, "window": [0, 0, 0.4, 0.4], "sections": [snum],
        "alignment": {str(snum): Transform.identity().getList()},
    })
    labels = zg.create_dataset("labels_x", shape=(1, 100, 100), dtype=np.uint64)
    labels[0, 20:40, 20:40] = 7
    labels.attrs.update({"voxel_size": [50, 4, 4], "offset": [0, 0, 0]})
    return str(fp)


def test_switching_the_alignment_keeps_the_trace(window, tmp_path):
    snum = _draw(window)
    other = next(a for a in window.series.alignments
                 if a != window.series.alignment)
    window.changeAlignment(other)
    assert window.series.alignment == other
    _assert_kept(window, snum, tmp_path)


def test_importing_overlay_labels_keeps_the_trace(window, tmp_path,
                                                  monkeypatch):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    snum = _draw(window)
    window.series.zarr_overlay_fp = _labels_zarr(tmp_path, snum)
    window.series.zarr_overlay_group = "labels_x"
    window.field.createZarrLayer()
    assert window.field.zarr_layer.is_labels

    window.importLabels(all=True)

    assert "autoseg_7" in _names(window.field.section), "nothing imported"
    _assert_kept(window, snum, tmp_path)


def test_importing_zarr_labels_keeps_the_trace(window, tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as mw

    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    snum = _draw(window)
    fp = _labels_zarr(tmp_path, snum)
    monkeypatch.setattr(mw, "FileDialog",
                        types.SimpleNamespace(get=lambda *a, **k: fp))
    monkeypatch.setattr(mw, "QuickDialog", types.SimpleNamespace(
        get=lambda *a, **k: ([["labels_x"]], True)))

    window.importFromZarrLabels()

    assert "autoseg_7" in _names(window.field.section), "nothing imported"
    _assert_kept(window, snum, tmp_path)
