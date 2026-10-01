"""Cropped Zarr labels import back to their own sections at any thickness.

A group exported a few sections into the Zarr gets a z offset of
``sections_in * thickness_nm``. With 25.4 nm sections, 3 in is
76.19999999999999 nm, and ``int(offset / thickness)`` read that back as 2, so
every section's labels landed one section low. These export with the real
seriesToLabels and import with the real labelsToObjects.
"""
import types

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.datatypes import Trace  # noqa: E402

IDENTITY = [1, 0, 0, 0, 1, 0]
WINDOW = [0, 0, 100, 100]


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


class _Contour:
    def __init__(self, traces):
        self._traces = traces

    def getTraces(self):
        return list(self._traces)


def _cell(snum):
    """A square named for its section, so a label shows where it came from."""
    trace = Trace(f"cell_{snum}", (255, 0, 0), closed=True)
    trace.points = [(20, 20), (80, 20), (80, 80), (20, 80)]
    return trace


class _ExportSeries:
    """Each section holds one object, named for the section."""

    def __init__(self, sections):
        self.window = None
        self.object_groups = types.SimpleNamespace(
            getGroupObjects=lambda g: [f"cell_{s}" for s in sections]
        )

    def loadSection(self, snum):
        trace = _cell(snum)
        return types.SimpleNamespace(
            mag=1.0, tform=None, contours={trace.name: _Contour([trace])}
        )


class _ImportSection:
    def __init__(self, store, snum):
        self.store, self.snum = store, snum

    def addTrace(self, trace):
        self.store.setdefault(self.snum, set()).add(trace.name)

    def save(self):
        pass


class _ImportSeries:
    """Records the names of the traces each section gets."""

    def __init__(self, sections):
        self.sections = dict.fromkeys(sections)
        self.imported = {}
        self.object_groups = types.SimpleNamespace(add=lambda *a: None)

    def loadSection(self, snum):
        return _ImportSection(self.imported, snum)

    def getOption(self, name):
        return None


@pytest.mark.parametrize("thickness_nm, sections_in", [(25.4, 3), (33.3, 63)])
def test_cropped_labels_import_to_their_own_sections(
    tmp_path, monkeypatch, thickness_nm, sections_in
):
    sections = list(range(sections_in + 3))
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)

    fp = str(tmp_path / "crop.zarr")
    zg = zarr.open(fp, mode="w")
    raw = zg.create_dataset("raw", shape=(len(sections), 100, 100), dtype=np.uint8)
    raw.attrs.update({
        "alignment": {str(s): IDENTITY for s in sections},
        "window": WINDOW,
        "offset": [0, 0, 0],
        "sections": sections,
        "true_mag": 1.0,
        "voxel_size": [thickness_nm, 1000, 1000],
    })

    ## the group covers the last 3 sections, sections_in from the start
    crop = (sections_in, sections_in + 3)
    assert conversions.seriesToLabels(
        _ExportSeries(sections), fp, group="cells", window=[WINDOW, crop],
        img_mag=1.0, raw_window=WINDOW,
    )
    labels = zarr.open(fp, mode="r")["labels_cells"]
    ## the offset really is fractional; that is what int() rounded down
    assert labels.attrs["offset"][0] / thickness_nm != sections_in
    assert int(labels.attrs["offset"][0] / thickness_nm) == sections_in - 1

    _, _, section_start = conversions.getLabelsToObjectsData(fp, "labels_cells")
    assert section_start == sections_in

    series = _ImportSeries(sections)
    conversions.setDT()
    assert conversions.labelsToObjects(series, fp, "labels_cells")

    lookup = dict(labels.attrs["gt_lookup"])
    expected = {
        s: {f"{conversions.AUTOSEG_TRACE_PREFIX}{lookup[f'cell_{s}']}"}
        for s in range(*crop)
    }
    assert series.imported == expected
