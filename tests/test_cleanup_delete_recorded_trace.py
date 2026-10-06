"""The clean-up lists delete the trace a record names, not its first lookalike.

`Series.deleteMalformedTraces` is the delete path behind the malformed,
pixel-dust and empty-trace lists, and the duplicates list re-finds its traces
the same way (`Series._resolveRecordedTraces`). Each record carries
the trace's position in its contour ("index") and a color-and-points
signature. Matching on the signature alone deleted the FIRST trace that fit it,
so two identical traces under one name on one section lost the wrong one. The
traces here differ only in their tags, which the signature does not cover, so
the tags say which trace survived.
"""
import os
import shutil

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]
DUST = [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)]


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


def _snum_and_template(series):
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        for cname in section.contours:
            for trace in section.contours[cname]:
                if trace.closed and len(trace.points) >= 3:
                    return snum, trace
    pytest.skip("no closed trace anywhere in fixture")


def _seed(series, traces):
    """Add (name, points, tag) traces to one section; return its number."""
    snum, template = _snum_and_template(series)
    section = series.loadSection(snum)
    for name, points, tag in traces:
        t = template.copy()
        t.name = name
        t.points = list(points)
        t.closed = True
        t.tags = {tag}
        section.addTrace(t, log_event=False)
    section.save()
    return snum


def _tags(series, snum, name):
    """The tag of each trace of an object, in contour order."""
    return [
        sorted(t.tags) for t in series.loadSection(snum).contours.get(name, [])
    ]


def _states(series):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    return SeriesStates(series)


def test_the_second_of_two_identical_traces_is_the_one_deleted(tmp_path):
    """A pixel-dust record for the second trace deletes the second trace."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "first"), ("DUST", DUST, "second")])

    records = [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ]
    assert [r["index"] for r in records] == [0, 1]
    assert records[0]["match"] == records[1]["match"]

    states = _states(series)
    deleted = series.deleteMalformedTraces([records[1]], series_states=states)

    assert deleted == [records[1]]
    assert _tags(series, snum, "DUST") == [["first"]]

    states.undoState()
    assert _tags(series, snum, "DUST") == [["first"], ["second"]]


def test_a_batch_deletes_each_recorded_trace_once(tmp_path):
    """Records for traces 0 and 2 of three lookalikes leave trace 1."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "first"),
        ("DUST", DUST, "second"),
        ("DUST", DUST, "third"),
    ])
    records = [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ]
    chosen = [records[0], records[2]]

    states = _states(series)
    assert series.deleteMalformedTraces(chosen, series_states=states) == chosen
    assert _tags(series, snum, "DUST") == [["second"]]

    states.undoState()
    assert _tags(series, snum, "DUST") == [["first"], ["second"], ["third"]]


def test_a_stale_index_still_finds_the_trace_by_its_signature(tmp_path):
    """A trace that moved since the scan is still found by color and points."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "dust")])
    record = next(
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    )
    stale = dict(record, index=5)

    assert series.deleteMalformedTraces([stale]) == [stale]
    assert _tags(series, snum, "DUST") == []


# ---------------------------------------------------------------------------
# an edit after the scan: the recorded index no longer fits
# ---------------------------------------------------------------------------

FAR = [(x + 100.0, y) for x, y in SQUARE]


def _remove_first(series, snum, name):
    """An outside edit: delete the first trace of an object after the scan."""
    section = series.loadSection(snum)
    section.removeTrace(section.contours[name][0], log_event=False)
    section.save()


def test_a_moved_index_with_two_lookalikes_deletes_nothing(tmp_path):
    """A pixel-dust record for the third of three identical traces, after the
    first is deleted: two traces could be it, so neither goes."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
    ])
    record = [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ][2]
    _remove_first(series, snum, "DUST")

    ambiguous = []
    assert series.deleteMalformedTraces([record], ambiguous=ambiguous) == []
    assert ambiguous == [record]
    assert _tags(series, snum, "DUST") == [["same"], ["same"]]


# ---------------------------------------------------------------------------
# records with no index name the same trace as their indexed copy
# ---------------------------------------------------------------------------

def test_a_copy_with_no_index_shares_its_indexed_records_trace(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "d0"), ("DUST", DUST, "d1")])
    record = [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ][1]
    none_index = dict(record, index=None)
    no_index = {k: v for k, v in record.items() if k != "index"}
    batch = [none_index, record, no_index]

    assert series.deleteMalformedTraces(batch) == batch
    assert _tags(series, snum, "DUST") == [["d0"]]


def test_one_record_twice_with_no_index_does_not_guess(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "d0"), ("DUST", DUST, "d1")])
    record = next(
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    )
    # a record from before the count existed, with nothing to place it by
    no_index = {
        k: v for k, v in record.items()
        if k not in ("index", "lookalikes", "lookalike_ordinal")
    }

    ambiguous = []
    assert series.deleteMalformedTraces(
        [no_index, no_index], ambiguous=ambiguous
    ) == []
    assert ambiguous == [no_index, no_index]
    assert _tags(series, snum, "DUST") == [["d0"], ["d1"]]


def test_one_record_twice_with_no_index_and_one_match_deletes_it_once(
        tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "d0"), ("OTHER", DUST, "o")])
    record = next(
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    )
    no_index = {k: v for k, v in record.items() if k != "index"}

    assert series.deleteMalformedTraces([no_index, no_index]) == [
        no_index, no_index
    ]
    assert _tags(series, snum, "DUST") == []
    assert _tags(series, snum, "OTHER") == [["o"]]


# ---------------------------------------------------------------------------
# the field layer says which rows were left
# ---------------------------------------------------------------------------

class _StubField:
    def __init__(self, series):
        from types import SimpleNamespace
        self.series = series
        self.series_states = _states(series)
        self.table_manager = SimpleNamespace(updateObjects=lambda names: None)
        self.mainwindow = SimpleNamespace(
            saveAllData=lambda: None, seriesModified=lambda *a: None
        )

    def reload(self):
        pass


def _notices(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_3_object as mod
    notices = []
    monkeypatch.setattr(
        mod, "notify", lambda message, *a, **k: notices.append(message)
    )
    return mod, notices


def test_a_cleanup_list_is_told_which_row_was_left(tmp_path, monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
    ])
    record = [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ][2]
    _remove_first(series, snum, "DUST")
    mod, notices = _notices(monkeypatch)

    assert mod.FieldWidgetObject.deleteMalformedContours(
        _StubField(series), [record]
    ) == []
    assert notices == [
        "PyReconstruct did not delete 1 trace. The section changed after the "
        "scan, and PyReconstruct cannot tell which of the identical traces "
        "you chose:\n\n"
        f"  DUST on section {snum}\n\n"
        "Run the scan again to list it where it is now."
    ]


# ---------------------------------------------------------------------------
# an index that still lands on a lookalike: the recorded count catches it
# ---------------------------------------------------------------------------

def _dust_records(series, snum):
    return [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ]


def test_scans_record_how_many_lookalikes_each_trace_has(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, "same"),
        ("A", SQUARE, "same"),
        ("A", SQUARE, "tagged differently"),
        ("B", SQUARE, "b"),
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
    ])
    dust = _dust_records(series, snum)
    assert [r["lookalikes"] for r in dust] == [3, 3, 3]
    assert [r["lookalike_ordinal"] for r in dust] == [0, 1, 2]
    group = next(
        g for g in series.findDuplicateTraces(0.95)
        if g["section"] == snum and "B" in g["names"]
    )
    by_place = {(m["name"], m["index"]): m for m in group["members"]}
    a_traces = sorted(i for n, i in by_place if n == "A")
    assert by_place[("A", a_traces[1])]["lookalikes"] == 2
    assert by_place[("A", a_traces[1])]["lookalike_ordinal"] == 1
    assert by_place[("A", a_traces[2])]["lookalikes"] == 1
    b_index = next(i for n, i in by_place if n == "B")
    assert by_place[("B", b_index)]["lookalikes"] == 1
    assert by_place[("B", b_index)]["lookalike_ordinal"] == 0


def test_a_trace_that_differs_in_its_tags_is_found_where_it_moved(tmp_path):
    """I pick the second of three traces with the same color and points but
    different tags, then the first is deleted outside the list. Index 1 now
    holds the third, but the second is the only trace with its saved data."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "b0"),
        ("DUST", DUST, "b1"),
        ("DUST", DUST, "b2"),
    ])
    record = _dust_records(series, snum)[1]
    _remove_first(series, snum, "DUST")

    assert series.deleteMalformedTraces([record]) == [record]
    assert _tags(series, snum, "DUST") == [["b2"]]


def test_an_unchanged_count_keeps_the_index(tmp_path):
    """A change elsewhere on the section does not make a row ambiguous."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "d0"),
        ("DUST", DUST, "d1"),
        ("OTHER", FAR, "o"),
    ])
    record = _dust_records(series, snum)[1]
    _remove_first(series, snum, "OTHER")

    assert series.deleteMalformedTraces([record]) == [record]
    assert _tags(series, snum, "DUST") == [["d0"]]


def test_a_record_without_a_count_keeps_the_index(tmp_path):
    """Records made before the count existed behave as they did."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "b0"),
        ("DUST", DUST, "b1"),
        ("DUST", DUST, "b2"),
    ])
    record = _dust_records(series, snum)[1]
    del record["lookalikes"]
    _remove_first(series, snum, "DUST")

    assert series.deleteMalformedTraces([record]) == [record]
    assert _tags(series, snum, "DUST") == [["b1"]]


@pytest.mark.gui
def test_a_delete_made_from_the_list_does_not_make_the_rest_ambiguous(
        tmp_path, qtbot, monkeypatch):
    """The list counts its own deletes off the rows it keeps, so the next
    delete from it still goes through."""
    from PyReconstruct.modules.gui.dialog import PixelDustDialog
    from PyReconstruct.modules.gui.dialog import malformed_contours
    monkeypatch.setattr(
        malformed_contours, "notifyConfirm", lambda *a, **k: True
    )
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
    ])
    records = _dust_records(series, snum)
    ambiguous = []
    dialog = PixelDustDialog(
        None, records,
        delete=lambda recs: series.deleteMalformedTraces(
            recs, ambiguous=ambiguous
        ),
    )
    qtbot.addWidget(dialog)

    dialog._deleteRecords([records[0]])
    assert records[2]["index"] == 1
    assert records[2]["lookalikes"] == 2
    assert records[2]["lookalike_ordinal"] == 1
    dialog._deleteRecords([records[2]])

    assert ambiguous == []
    assert _tags(series, snum, "DUST") == [["same"]]


def test_an_unchanged_count_finds_the_trace_after_its_index_shifts(tmp_path):
    """An unrelated trace before both lookalikes is deleted by hand. The count
    is the same, but index 1 now holds `second`; the place among the
    lookalikes still names `first`."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", FAR, "other"),
        ("DUST", DUST, "first"),
        ("DUST", DUST, "second"),
    ])
    record = _dust_records(series, snum)
    record = next(r for r in record if r["index"] == 1)
    assert record["lookalike_ordinal"] == 0
    _remove_first(series, snum, "DUST")

    assert series.deleteMalformedTraces([record]) == [record]
    assert _tags(series, snum, "DUST") == [["second"]]


def test_the_twin_of_a_trace_deleted_by_hand_is_left(tmp_path):
    """I pick `b0` of two identical traces, then delete `b0` by hand. One
    match is left, but it is the twin, so nothing is deleted."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "same"), ("DUST", DUST, "same")])
    record = _dust_records(series, snum)[0]
    _remove_first(series, snum, "DUST")

    ambiguous = []
    assert series.deleteMalformedTraces([record], ambiguous=ambiguous) == []
    assert ambiguous == [record]
    assert _tags(series, snum, "DUST") == [["same"]]


def test_an_index_that_lands_on_an_identical_trace_deletes_nothing(tmp_path):
    """Three traces identical in every saved field, I pick the second, and
    the first is deleted outside the list. One fewer is left, so nothing is
    deleted."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
        ("DUST", DUST, "same"),
    ])
    record = _dust_records(series, snum)[1]
    _remove_first(series, snum, "DUST")

    ambiguous = []
    assert series.deleteMalformedTraces([record], ambiguous=ambiguous) == []
    assert ambiguous == [record]
    assert _tags(series, snum, "DUST") == [["same"], ["same"]]


def test_editing_a_twin_after_the_scan_never_deletes_it_for_me(tmp_path):
    """Two identical traces and an unrelated one. I pick the second, then
    edit the first's tags, which moves it to the end of the object. The
    trace I picked must not be the one left behind."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "b"),
        ("DUST", DUST, "b"),
        ("DUST", FAR, "x"),
    ])
    record = next(r for r in _dust_records(series, snum) if r["index"] == 1)
    section = series.loadSection(snum)
    section.editTraceAttributes(
        [section.contours["DUST"][0]], None, None, {"b", "edited"}, None,
        log_event=False,
    )
    section.save()
    assert _tags(series, snum, "DUST") == [["b"], ["x"], ["b", "edited"]]

    ambiguous = []
    deleted = series.deleteMalformedTraces([record], ambiguous=ambiguous)

    left = _tags(series, snum, "DUST")
    assert left in ([["x"], ["b", "edited"]], [["b"], ["x"], ["b", "edited"]])
    # the count of identical traces fell from 2 to 1, so this row is left
    assert deleted == [] and ambiguous == [record]


def test_a_cleanup_list_is_told_a_trace_is_gone(tmp_path, monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "only")])
    record = next(
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    )
    _remove_first(series, snum, "DUST")
    mod, notices = _notices(monkeypatch)

    assert mod.FieldWidgetObject.deleteMalformedContours(
        _StubField(series), [record]
    ) == []
    assert notices == [
        "1 of 1 listed traces was not found and could not be deleted. It "
        "may have changed or been deleted after the list was made."
    ]

