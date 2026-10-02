"""The self-crossing repair changes the trace a record names, not a lookalike.

`Series.repairSelfCrossingTraces` re-found each record's trace by color and
points alone and repaired the FIRST trace that fit, the pattern
`deleteMalformedTraces` had before it learned to use the recorded index and
the full saved identity of the trace. With two traces of one color and points
under one name, the wrong one was repaired: the tags of the other trace ended
up on the repaired outline, and the repaired trace moved to the end of the
contour. The traces here differ only in tags (or in being open), which the
color-and-points signature does not cover, so the tags say which was repaired.
"""
import os
import shutil

import pytest

pytestmark = pytest.mark.gui

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

# the autoseg spike from test_repair_self_crossing: one real loop, repairable
SPIKED_SQUARE = [
    (0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
    (5.0, 10.0), (5.0, 10.5), (5.0, 10.0),
    (0.0, 10.0),
]
SQUARE = [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)]
NAME = "x_cross"


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    series.setProgressReporter(NullProgressReporter)
    return series


def _template(series):
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        for cname in section.contours:
            for trace in section.contours[cname]:
                if trace.closed and len(trace.points) >= 3:
                    return snum, trace
    pytest.skip("no closed trace anywhere in fixture")


def _seed(series, traces):
    """Add (points, tag, closed) traces under NAME to one section."""
    snum, template = _template(series)
    section = series.loadSection(snum)
    for points, tag, closed in traces:
        t = template.copy()
        t.name = NAME
        t.points = list(points)
        t.closed = closed
        t.tags = {tag}
        section.addTrace(t, log_event=False)
    section.save()
    return snum


def _contour(series, snum):
    """(tag, still crossed, closed) for each NAME trace, in contour order."""
    from shapely.geometry import Polygon
    out = []
    for t in series.loadSection(snum).contours.get(NAME, []):
        crossed = len(t.points) >= 3 and not Polygon(t.points).is_valid
        out.append((sorted(t.tags)[0], crossed, t.closed))
    return out


def _records(series, snum):
    return [
        r for r in series.findSelfCrossingTraces()
        if r["name"] == NAME and r["section"] == snum
    ]


def _states(series):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    return SeriesStates(series)


def test_the_second_of_two_identical_traces_is_the_one_repaired(tmp_path):
    """A record for the second trace repairs the second, in its own place."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        (SPIKED_SQUARE, "first", True),
        (SPIKED_SQUARE, "second", True),
    ])
    records = _records(series, snum)
    assert [r["index"] for r in records] == [0, 1]
    assert records[0]["match"] == records[1]["match"]   # the premise

    states = _states(series)
    repaired = series.repairSelfCrossingTraces(
        [records[1]], series_states=states
    )

    assert repaired == [records[1]]
    assert _contour(series, snum) == [
        ("first", True, True), ("second", False, True),
    ]

    states.undoState()
    assert _contour(series, snum) == [
        ("first", True, True), ("second", True, True),
    ]
    states.undoState(redo=True)
    assert _contour(series, snum) == [
        ("first", True, True), ("second", False, True),
    ]


def test_an_open_lookalike_is_not_the_one_repaired(tmp_path):
    """An open trace with the closed trace's color and points is not scanned,
    and the closed trace's record repairs the closed trace."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        (SPIKED_SQUARE, "open", False),
        (SPIKED_SQUARE, "closed", True),
    ])
    records = _records(series, snum)
    assert [r["index"] for r in records] == [1]

    states = _states(series)
    assert series.repairSelfCrossingTraces(
        records, series_states=states
    ) == records
    assert _contour(series, snum) == [
        ("open", True, False), ("closed", False, True),
    ]

    states.undoState()
    assert _contour(series, snum) == [
        ("open", True, False), ("closed", True, True),
    ]


def test_every_listed_trace_is_repaired_once_in_place(tmp_path):
    """Three crossed lookalikes and a plain trace between them: all three are
    repaired and keep their places."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        (SPIKED_SQUARE, "a", True),
        (SQUARE, "plain", True),
        (SPIKED_SQUARE, "b", True),
        (SPIKED_SQUARE, "c", True),
    ])
    records = _records(series, snum)
    assert [r["index"] for r in records] == [0, 2, 3]

    states = _states(series)
    assert series.repairSelfCrossingTraces(
        records, series_states=states
    ) == records
    assert _contour(series, snum) == [
        ("a", False, True), ("plain", False, True),
        ("b", False, True), ("c", False, True),
    ]

    states.undoState()
    assert _contour(series, snum) == [
        ("a", True, True), ("plain", False, True),
        ("b", True, True), ("c", True, True),
    ]


def test_a_changed_lookalike_count_skips_and_reports(tmp_path):
    """A lookalike added after the scan: nothing is repaired for the record,
    and it is reported as ambiguous."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        (SPIKED_SQUARE, "first", True),
        (SPIKED_SQUARE, "first", True),
    ])
    records = _records(series, snum)
    assert [r["lookalikes"] for r in records] == [2, 2]

    # a third, fully identical trace arrives before the repair runs
    section = series.loadSection(snum)
    section.addTrace(section.contours[NAME][0].copy(), log_event=False)
    section.save()

    ambiguous = []
    assert series.repairSelfCrossingTraces(
        [records[1]], ambiguous=ambiguous
    ) == []
    assert ambiguous == [records[1]]
    assert _contour(series, snum) == [("first", True, True)] * 3


def test_a_trace_that_moved_is_still_found(tmp_path):
    """Its only lookalike is gone, so the record's trace is found by its
    identity at its new index."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        (SQUARE, "plain", True),
        (SPIKED_SQUARE, "target", True),
    ])
    records = _records(series, snum)
    assert [r["index"] for r in records] == [1]

    section = series.loadSection(snum)
    section.removeTrace(section.contours[NAME][0], log_event=False)
    section.save()

    assert series.repairSelfCrossingTraces(records) == records
    assert _contour(series, snum) == [("target", False, True)]


def test_the_notice_says_repair_for_a_skipped_repair(monkeypatch):
    """The skipped-trace notice names the action it skipped."""
    from PyReconstruct.modules.gui.main import field_widget_3_object as fwo
    shown = []
    monkeypatch.setattr(fwo, "notify", shown.append)
    match = {"color": (255, 0, 0), "points": [(0.0, 0.0)]}

    fwo.notifyAmbiguousTraces([(NAME, 3, 1, match)], verb="repair")
    fwo.notifyAmbiguousTraces([(NAME, 3, 1, match)])

    assert shown[0].startswith("PyReconstruct did not repair 1 trace.")
    assert shown[1].startswith("PyReconstruct did not delete 1 trace.")
    assert f"{NAME} on section 3" in shown[0]
