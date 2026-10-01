"""Neuroglancer export of a series with a gap in its section numbers (fork #601).

Deleting section 3 leaves sections 1, 2, 4, 5, 6. ``seriesToLabels`` listed
the label sections with ``range(start, end)``, so a group with traces on both
sides of the gap asked for section 3 and raised ``KeyError: '3'``. A group
after the gap exported, but ``create_ng_zarr.py`` set its z offset from the
section number (4 - 1 = 3 slices) instead of from where section 4 sits in
``raw`` (index 2), so every label slice sat over the next section's image.

The padding half (fork #602): ``create_ng_zarr.py`` turned the padding from
pixels into micrometers once for the raw window and again for each label
window, so labels around a group got almost none of it.

These run the real script in this process, on a real series, with only the
progress-bar pool made inline and the dask rechunk skipped.
"""

import runpy
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend import autoseg, imports  # noqa: E402
from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.datatypes import Series, Trace  # noqa: E402

MAG = 0.01  # 400 px images are 4 um across
SECTIONS = [1, 2, 4, 5, 6]


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


def _box_x(snum):
    """Each section's box sits at its own x, so a label slice names its section."""
    return 0.3 + 0.4 * snum


@pytest.fixture
def gap_jser(tmp_path, qapp):
    images = []
    for i in range(7):
        fp = tmp_path / f"img{i}.png"
        cv2.imwrite(str(fp), np.full((400, 400, 3), 20 * i + 10, np.uint8))
        images.append(str(fp))

    series = Series.new(images, "gap", MAG, 0.05)
    try:
        for name, snums in (("span", [2, 4]), ("tail", [4, 5, 6])):
            for snum in snums:
                trace = Trace(name, (255, 0, 0), closed=True)
                x = _box_x(snum)
                trace.points = [(x, 1.0), (x + 0.2, 1.0), (x + 0.2, 3.0), (x, 3.0)]
                section = series.loadSection(snum)
                section.addTrace(trace, log_event=False)
                section.save()
        series.object_groups.add("g_span", "span")
        series.object_groups.add("g_tail", "tail")
        series.deleteSections([3], log_event=False)
        series.save()
        jser = tmp_path / "gap.jser"
        series.saveJser(str(jser))
    finally:
        series.close()
    return jser


def _export(monkeypatch, jser, out, *args):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    monkeypatch.setattr(imports, "modules_available", lambda *a, **k: True)
    monkeypatch.setattr(autoseg, "rechunk", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", [
        "create_ng_zarr.py", str(jser), "-s", "1", "-e", "6", "-m", str(MAG),
        "-o", str(out), *args,
    ])
    runpy.run_module(
        "PyReconstruct.assets.scripts.create_ng_zarr.create_ng_zarr",
        run_name="__main__",
    )
    return zarr.open(str(out), "r")


def _slice_sections(zg, name):
    """For each slice of a labels array: its raw z and the section it drew."""
    raw = zg["raw"]
    labels = zg[name]
    window = raw.attrs["window"]
    z0 = labels.attrs["offset"][0] // labels.attrs["voxel_size"][0]
    x0 = labels.attrs["offset"][2] / labels.attrs["voxel_size"][2]
    found = []
    for i in range(labels.shape[0]):
        cols = np.nonzero(labels[i].any(axis=0))[0]
        ## back to series x, then to the section whose box starts there
        x = window[0] + (x0 + cols.min()) * MAG
        found.append((z0 + i, round((x - 0.3) / 0.4)))
    return found


def test_a_group_across_the_gap_exports(monkeypatch, gap_jser, tmp_path):
    zg = _export(
        monkeypatch, gap_jser, tmp_path / "span.zarr", "-g", "g_span", "--max_tissue",
    )

    assert list(zg["raw"].attrs["sections"]) == SECTIONS
    ## sections 2 and 4, which are raw slices 1 and 2
    assert _slice_sections(zg, "labels_g_span") == [(1, 2), (2, 4)]


def test_labels_after_the_gap_sit_over_their_own_section(monkeypatch, gap_jser, tmp_path):
    zg = _export(
        monkeypatch, gap_jser, tmp_path / "tail.zarr", "-g", "g_tail", "--max_tissue",
    )

    raw_sections = list(zg["raw"].attrs["sections"])
    for z, snum in _slice_sections(zg, "labels_g_tail"):
        assert raw_sections[z] == snum


def test_label_window_gets_the_whole_padding(monkeypatch, gap_jser, tmp_path):
    ## the tail boxes span x 1.9 to 2.9 and y 1 to 3; 5 px of padding at
    ## 0.01 um per px adds 0.05 um on each side
    zg = _export(
        monkeypatch, gap_jser, tmp_path / "tail.zarr", "-g", "g_tail", "-p", "5",
    )

    assert zg["labels_g_tail"].shape == (3, 210, 110)
