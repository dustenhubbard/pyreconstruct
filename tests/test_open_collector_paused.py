"""A series open keeps the cyclic garbage collector off while it reads and
builds (series.py, `_collectorPaused`), puts it back as it found it, and
leaves the same series and the same working folder as an open with it on.
"""
import contextlib
import gc
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes import Series, series as series_mod
from PyReconstruct.modules.datatypes.series import SeriesOpenError
from PyReconstruct.modules.datatypes.series_data import SeriesData

from tests.test_open_reads_rows import FIXTURES, _later_loads, _open, _state


@pytest.fixture
def collector_seen(monkeypatch):
    """gc.isenabled() at every section the series data adds."""
    seen = []
    add = SeriesData.addOpenedSection

    def recording(self, section):
        seen.append(gc.isenabled())
        return add(self, section)

    monkeypatch.setattr(SeriesData, "addOpenedSection", recording)
    return seen


def _collector_left_on(monkeypatch):
    """The open as it was before: the collector as the caller left it."""
    monkeypatch.setattr(series_mod, "_collectorPaused", contextlib.nullcontext)
    monkeypatch.setattr(Series, "_unpackJser", staticmethod(Series._unpackJser.__wrapped__))


def _folder(series):
    """Every file in the working folder, by name, with its bytes."""
    folder = os.path.dirname(series.filepath)
    out = {}
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), "rb") as f:
            out[name] = f.read()
    return out


def test_first_open_and_resume_build_with_the_collector_off(series_jser, collector_seen):
    assert gc.isenabled()
    first = _open(series_jser)
    try:
        assert collector_seen and not any(collector_seen)
        assert gc.isenabled()
        collector_seen.clear()
        resumed = Series(first.filepath, dict(first.sections))
        assert collector_seen and not any(collector_seen)
        assert gc.isenabled()
        assert _state(resumed) == _state(first)
    finally:
        first.close()


def test_a_collector_turned_off_by_the_caller_stays_off(series_jser):
    gc.disable()
    try:
        series = _open(series_jser)
        assert not gc.isenabled()
        Series(series.filepath, dict(series.sections))
        assert not gc.isenabled()
        series.close()
    finally:
        gc.enable()


def test_a_failed_open_turns_the_collector_back_on(tmp_path):
    bad = tmp_path / "bad.jser"
    bad.write_text('{"series": {}, "sections": [{"contours": ')
    with pytest.raises(SeriesOpenError):
        Series.openJser(str(bad))
    assert gc.isenabled()


@pytest.mark.parametrize("name", ["class", "parity"])
def test_the_open_matches_an_open_with_the_collector_on(name, series_jser, tmp_path, monkeypatch):
    source = series_jser if name == "class" else FIXTURES[name]
    opened = {}
    for arm in ("on", "paused"):
        folder = tmp_path / arm
        folder.mkdir()
        shutil.copy(source, folder / "series.jser")
        with monkeypatch.context() as m:
            if arm == "on":
                _collector_left_on(m)
            first = _open(folder / "series.jser")
            files, state = _folder(first), _state(first)
            resumed = Series(first.filepath, dict(first.sections))
            opened[arm] = (first, files, state, _state(resumed))
    try:
        on, paused = opened["on"], opened["paused"]
        assert on[0].data.objects, "the fixture has no trace data to compare"
        assert paused[1] == on[1]
        assert paused[2] == on[2]
        assert paused[3] == on[3]
        assert _later_loads(paused[0]) == _later_loads(on[0])
    finally:
        for first, *_ in opened.values():
            first.close()
