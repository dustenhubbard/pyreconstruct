"""Zarr label export cuts out the holes of negative traces (fork #604).

``generateLabelsArray`` filled every trace with its object's label and never
looked at ``trace.negative``, so a negative trace painted over its own hole.
These run the real seriesToLabels, exportTraces and generateLabelsArray.
"""
import types

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.datatypes import Trace  # noqa: E402

IDENTITY = [1, 0, 0, 0, 1, 0]


def _square(name, lo, hi, negative=False):
    trace = Trace(name, (255, 0, 0), closed=True)
    trace.points = [(lo, lo), (hi, lo), (hi, hi), (lo, hi)]
    trace.negative = negative
    return trace


class _Contour:
    def __init__(self, traces):
        self._traces = traces

    def getTraces(self):
        return list(self._traces)


class _Series:
    def __init__(self, contours):
        self.window = None
        self.section = types.SimpleNamespace(mag=1.0, contours=contours, tform=None)
        self.object_groups = types.SimpleNamespace(
            getGroupObjects=lambda g: list(contours) if g == "cells" else []
        )

    def loadSection(self, snum):
        return self.section


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


def _export(tmp_path, monkeypatch, contours):
    """Labels for one 100 by 100 section at 1 px per unit; returns (array, ids)."""
    fp = str(tmp_path / "labels.zarr")
    zg = zarr.open(fp, mode="w")
    raw = zg.create_dataset("raw", shape=(1, 100, 100), dtype=np.uint8)
    raw.attrs.update({
        "alignment": {"0": IDENTITY},
        "window": [0, 0, 100, 100],
        "offset": [0, 0, 0],
        "sections": [0],
        "true_mag": 1.0,
        "voxel_size": [50, 1, 1],
    })
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)

    assert conversions.seriesToLabels(_Series(contours), fp, group="cells")

    labels = zarr.open(fp, mode="r")["labels_cells"]
    return labels[0], dict(labels.attrs["gt_lookup"])


def _at(arr, x, y):
    """The label at series point (x, y); rows run top down."""
    return int(arr[arr.shape[0] - 1 - y, x])


def test_negative_trace_leaves_a_hole(tmp_path, monkeypatch):
    donut = [_square("donut", 10, 90), _square("donut", 30, 70, negative=True)]

    arr, ids = _export(tmp_path, monkeypatch, {"donut": _Contour(donut)})

    assert _at(arr, 20, 20) == ids["donut"]  # the ring
    assert _at(arr, 50, 50) == 0  # the hole
    ## the ring is 80 by 80 less 40 by 40, give or take the polygon edges
    assert abs(int((arr == ids["donut"]).sum()) - (80 * 80 - 40 * 40)) < 400


@pytest.mark.parametrize("first", ["donut", "core"])
def test_object_inside_the_hole_keeps_its_label(tmp_path, monkeypatch, first):
    contours = {
        "donut": _Contour(
            [_square("donut", 10, 90), _square("donut", 30, 70, negative=True)]
        ),
        "core": _Contour([_square("core", 45, 55)]),
    }
    if first == "core":
        contours = {"core": contours["core"], "donut": contours["donut"]}

    arr, ids = _export(tmp_path, monkeypatch, contours)

    assert _at(arr, 50, 50) == ids["core"]
    assert _at(arr, 35, 35) == 0
    assert _at(arr, 20, 20) == ids["donut"]


def test_traces_without_holes_draw_as_before(tmp_path, monkeypatch):
    contours = {
        "a": _Contour([_square("a", 10, 30), _square("a", 60, 80)]),
        "b": _Contour([_square("b", 20, 40)]),
    }

    arr, ids = _export(tmp_path, monkeypatch, contours)

    assert _at(arr, 15, 15) == ids["a"]
    assert _at(arr, 70, 70) == ids["a"]
    ## b is drawn after a, so it wins where they overlap
    assert _at(arr, 25, 25) == ids["b"]
    assert _at(arr, 50, 50) == 0
