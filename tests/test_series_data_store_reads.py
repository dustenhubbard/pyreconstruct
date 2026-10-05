"""The series-open pass reads traces from the columnar store (fork #429).

`SeriesData.refresh` and the cold `openJser` loop build every trace's table data
from `section._columns` instead of `section.contours`. These tests build the
same data both ways and require the results to be identical, field for field,
on both fixture series and on a section put through an add, a delete, a rename
and an undo.
"""
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.func.state_manager import SectionStates
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.datatypes.columnar_store import TraceView
from PyReconstruct.modules.datatypes.series_data import SeriesData, TraceData

SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"

## class_series section 44 holds three contours, one with three traces, on a
## series with a second alignment.
EDITED = 44


def _snapshot(data, sections):
    """Every TraceData field the tables read, keyed object -> section.

    `getFeret` reads the live trace at the data's index, so including it checks
    that the store path numbered each trace the way the contour lists it.
    """
    return {
        name: {
            snum: [
                (
                    td.index, td.closed, td.hidden, td.negative,
                    sorted(td.tags), td.color, td.length, td.area,
                    td.centroid, td.radius, td._tform.getList(),
                    td.getFeret(sections[snum], name),
                )
                for td in traces
            ]
            for snum, traces in obj.traces.items()
        }
        for name, obj in data.objects.items()
    }


def _build(series, read_store):
    """The series' data built from freshly loaded sections, one way."""
    data = SeriesData(series)
    sections = {}
    for snum, section in series.enumerateSections(show_progress=False):
        sections[snum] = section
        data.updateSection(
            section, update_traces=True, log_events=False, read_store=read_store
        )
    return data, sections


def _assert_same(series):
    old = _snapshot(*_build(series, read_store=False))
    new = _snapshot(*_build(series, read_store=True))
    assert old, "the series has no trace data to compare"
    assert new == old


def _assert_live_section_same(series, section):
    """A live, edited section's data read both ways, every contour."""
    section.clearTracking()
    sections = {section.n: section}
    snapshots = []
    for read_store in (False, True):
        data = SeriesData(series)
        data.updateSection(
            section, update_traces=True, log_events=False, read_store=read_store
        )
        snapshots.append(_snapshot(data, sections))
    assert snapshots[0], "the section has no trace data to compare"
    assert snapshots[1] == snapshots[0]


def _open(path):
    series = Series.openJser(str(path))
    series.setSettingsStore(DictSettingsStore())
    return series


@pytest.fixture
def class_series(series_jser):
    series = _open(series_jser)
    yield series
    series.close()


@pytest.fixture
def synthetic_series(tmp_path):
    destination = tmp_path / "parity_series.jser"
    shutil.copy(SYNTHETIC_FIXTURE, destination)
    series = _open(destination)
    yield series
    series.close()


def test_open_and_refresh_read_the_store_and_save_does_not(series_jser, monkeypatch):
    read_from_store = []
    real_init = TraceData.__init__

    def spy(self, trace, index, tform, points=None):
        read_from_store.append(isinstance(trace, TraceView) and points is not None)
        real_init(self, trace, index, tform, points)

    monkeypatch.setattr(TraceData, "__init__", spy)

    series = _open(series_jser)
    try:
        assert read_from_store and all(read_from_store)

        read_from_store.clear()
        series.data.refresh()
        assert read_from_store and all(read_from_store)

        ## A save reads the contours: an edit made outside `Section` can make
        ## the store stale until the save rebuilds it.
        read_from_store.clear()
        series.loadSection(EDITED).save()
        assert read_from_store and not any(read_from_store)
    finally:
        series.close()


def test_store_and_object_model_give_the_same_data_on_the_real_fixture(class_series):
    _assert_same(class_series)


def test_store_and_object_model_give_the_same_data_on_the_synthetic_fixture(synthetic_series):
    _assert_same(synthetic_series)


def test_the_open_and_refresh_paths_match_the_object_model(class_series):
    ## Opening a fresh copy takes the cold path, which builds `series.data`
    ## through the store; `refresh` is the warm path.
    old, sections = _build(class_series, read_store=False)
    expected = _snapshot(old, sections)
    assert _snapshot(class_series.data, sections) == expected
    class_series.data.refresh()
    assert _snapshot(class_series.data, sections) == expected


def test_store_reads_match_after_add_delete_rename_and_undo(class_series):
    series = class_series
    section = series.loadSection(EDITED)
    states = SectionStates(section, series)

    added = Trace("added_obj", (12, 34, 56), True)
    added.points = [(1.25, 1.5), (2.75, 1.5), (2.0, 3.125)]
    added.tags = {"t1"}
    section.addTrace(added, log_event=False)
    states.addState(section, series)
    _assert_live_section_same(series, section)

    section.removeTrace(section.contours["d03sp12"][1], log_event=False)
    states.addState(section, series)
    _assert_live_section_same(series, section)

    section.editTraceAttributes(
        [section.contours["d03p12"][0]], "renamed_obj", None, None, None,
        log_event=False,
    )
    states.addState(section, series)
    assert section.contours["renamed_obj"].getTraces()
    _assert_live_section_same(series, section)

    states.undoState(section, series)
    assert section.contours["d03p12"].getTraces()
    _assert_live_section_same(series, section)

    ## The next open of the edited series reads the saved section back through
    ## the store with the same result.
    section.save(update_series_data=False)
    _assert_same(series)
