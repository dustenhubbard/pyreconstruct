"""The series data an open builds from the columnar store, all of a section's
traces measured together, is the data the build one trace at a time gave, to
the bit: the same objects in the same order, the same sections, and every
trace's numbers with the same repr.
"""
import shutil
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.calc import traceGeometries, traceGeometry
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.series_data import SeriesData

SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"


def _one_trace_at_a_time(monkeypatch):
    """Build from the store one TraceView at a time, as before the batch."""
    monkeypatch.setattr(SeriesData, "_storeRows", lambda self, store, section, names: None)


def _state(data):
    """Everything the series data holds about objects, traces and sections, as a repr."""
    objects = [
        (
            name,
            [
                (
                    snum,
                    [
                        (
                            td.index, td.closed, td.hidden, td.negative,
                            sorted(td.tags), td.color, td.length, td.area,
                            td.centroid, td.radius, td._tform.getList(), td._feret,
                        )
                        for td in traces
                    ],
                )
                for snum, traces in obj.traces.items()
            ],
        )
        for name, obj in data.objects.items()
    ]
    return repr((objects, sorted(data["sections"])))


def _open(path):
    series = Series.openJser(str(path))
    series.setSettingsStore(DictSettingsStore())
    return series


@pytest.fixture(params=["class", "synthetic"])
def jser_copies(request, series_jser, tmp_path):
    """Two copies of one fixture series, so each open unpacks its own."""
    source = series_jser if request.param == "class" else SYNTHETIC_FIXTURE
    copies = []
    for arm in ("before", "after"):
        folder = tmp_path / arm
        folder.mkdir()
        copies.append(folder / "series.jser")
        shutil.copy(source, copies[-1])
    return copies


def test_open_builds_the_same_data_as_one_trace_at_a_time(jser_copies, monkeypatch):
    before_fp, after_fp = jser_copies
    with monkeypatch.context() as m:
        _one_trace_at_a_time(m)
        before = _open(before_fp)
    after = _open(after_fp)
    try:
        assert before.data.objects, "the fixture has no trace data to compare"
        assert _state(after.data) == _state(before.data)
        ## the refresh after an edit elsewhere takes the same path
        after.data.refresh()
        assert _state(after.data) == _state(before.data)
    finally:
        before.close()
        after.close()


def test_objects_with_their_own_alignment_match(series_jser, monkeypatch):
    series = _open(series_jser)
    try:
        section = series.loadSection(sorted(series.sections)[0])
        other = next(a for a in section.tforms if a != series.alignment)
        names = sorted(series.data.objects)
        for name in names[::3]:
            series.setAttr(name, "alignment", other)
        series.setAttr(names[1], "alignment", "no such alignment")
        series.data.refresh()
        after = _state(series.data)
        assert series.getAttr(names[1], "alignment") is None
        series.setAttr(names[1], "alignment", "no such alignment")
        with monkeypatch.context() as m:
            _one_trace_at_a_time(m)
            series.data.refresh()
        assert series.getAttr(names[1], "alignment") is None
        assert after == _state(series.data)
        ## the objects given their own alignment were measured with it
        sections = series.data["sections"]
        assert all(
            td._tform is sections[snum]["tforms"][other]
            for snum, traces in series.data.objects[names[0]].traces.items()
            for td in traces
        )
    finally:
        series.close()


def _traces(seed):
    """Point arrays of many sizes and scales, with the cases traceGeometry branches on.

    Steps near 1e9 make lengths whose last bits survive the rounding to 7 places.
    """
    rng = np.random.default_rng(seed)
    traces = []
    for n in (0, 1, 2, 3, 4, 7, 8, 9, 84, 128, 129, 300):
        for _ in range(40):
            center = rng.normal(size=2) * rng.choice([1.0, 1e3, 1e5])
            traces.append(center + rng.normal(size=(n, 2)) * rng.choice([1e-4, 1e-2, 1.0, 10.0, 1e9]))
    for size in rng.integers(3, 400, 300):
        traces.append(rng.normal(size=(size, 2)) * 50)
    traces.append(np.full((5, 2), 3.5))  # no area: the mean is the centroid
    nan = rng.normal(size=(6, 2))
    nan[2, 0] = np.nan
    traces.append(nan)
    order = rng.permutation(len(traces))
    traces = [traces[i] for i in order]
    closed = [bool(c) for c in rng.integers(0, 2, len(traces))]
    return traces, closed


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_trace_geometries_match_trace_geometry_to_the_bit(seed):
    traces, closed = _traces(seed)
    expected = [traceGeometry(t, c) for t, c in zip(traces, closed)]
    got = traceGeometries(
        np.concatenate(traces), [len(t) for t in traces], closed
    )
    assert repr(got) == repr(expected)


def test_trace_geometries_of_nothing():
    assert traceGeometries(np.empty((0, 2)), [], []) == []
    assert traceGeometries(np.empty((0, 2)), [0, 0], [True, False]) == [
        traceGeometry([], True), traceGeometry([], False)
    ]
