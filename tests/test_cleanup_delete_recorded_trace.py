"""The clean-up lists delete the trace a record names, not its first lookalike.

`Series.deleteMalformedTraces` is the delete path behind the malformed,
pixel-dust, empty and duplicates-named-differently lists. Each record carries
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


def _row(records, name, index, other_name):
    for r in records:
        if (r["name"], r["index"], r["other_name"]) == (name, index, other_name):
            return r, "other"
        if (r["other_name"], r["other_index"], r["name"]) == (
                name, index, other_name):
            return r, "first"
    raise AssertionError(f"no pair deletes {name}[{index}] against {other_name}")


def test_a_duplicate_pair_deletes_the_trace_its_row_names(tmp_path):
    """Two identical `A` traces both pair with `B`; deleting the second `A`
    from its row leaves the first."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, "first"),
        ("A", SQUARE, "second"),
        ("B", SQUARE, "b"),
    ])
    records = series.findDifferentlyNamedDuplicates(0.95)
    choice = _row(records, "A", 1, "B")

    states = _states(series)
    applied = series.deleteDifferentlyNamedDuplicates(
        [choice], series_states=states
    )

    assert applied == [choice]
    assert _tags(series, snum, "A") == [["first"]]
    assert _tags(series, snum, "B") == [["b"]]

    states.undoState()
    assert _tags(series, snum, "A") == [["first"], ["second"]]


def test_two_rows_that_delete_one_trace_delete_only_that_trace(tmp_path):
    """`B` has two identical traces. Two rows both name the first `B` as the
    one to delete, so the second `B` must survive."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, "a"),
        ("C", SQUARE, "c"),
        ("B", SQUARE, "first"),
        ("B", SQUARE, "second"),
    ])
    records = series.findDifferentlyNamedDuplicates(0.95)
    choices = [_row(records, "B", 0, "A"), _row(records, "B", 0, "C")]

    states = _states(series)
    applied = series.deleteDifferentlyNamedDuplicates(
        choices, series_states=states
    )

    assert applied == choices
    assert _tags(series, snum, "B") == [["second"]]
    assert _tags(series, snum, "A") == [["a"]]
    assert _tags(series, snum, "C") == [["c"]]

    states.undoState()
    assert _tags(series, snum, "B") == [["first"], ["second"]]


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


def test_two_rows_naming_a_moved_trace_delete_it_once(tmp_path):
    """Both rows name the third `B`. The first `B` is deleted after the scan,
    so the index no longer fits; the one remaining lookalike is the trace,
    and both rows count as applied."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, "a"),
        ("C", SQUARE, "c"),
        ("B", SQUARE, "b0"),
        ("B", FAR, "b1"),
        ("B", SQUARE, "b2"),
    ])
    records = series.findDifferentlyNamedDuplicates(0.95)
    choices = [_row(records, "B", 2, "A"), _row(records, "B", 2, "C")]
    _remove_first(series, snum, "B")

    ambiguous = []
    applied = series.deleteDifferentlyNamedDuplicates(
        choices, series_states=_states(series), ambiguous=ambiguous
    )

    assert applied == choices
    assert ambiguous == []
    assert _tags(series, snum, "B") == [["b1"]]


def test_two_rows_naming_a_moved_trace_with_two_lookalikes_delete_none(
        tmp_path):
    """The same two rows, but two identical `B` traces could now be the third
    one. Nothing is deleted for either row, and both are reported."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, "a"),
        ("C", SQUARE, "c"),
        ("B", SQUARE, "b0"),
        ("B", SQUARE, "b1"),
        ("B", SQUARE, "b2"),
    ])
    records = series.findDifferentlyNamedDuplicates(0.95)
    choices = [_row(records, "B", 2, "A"), _row(records, "B", 2, "C")]
    _remove_first(series, snum, "B")

    ambiguous = []
    applied = series.deleteDifferentlyNamedDuplicates(
        choices, series_states=_states(series), ambiguous=ambiguous
    )

    assert applied == []
    assert ambiguous == choices
    assert _tags(series, snum, "B") == [["b1"], ["b2"]]


def test_a_moved_index_with_two_lookalikes_deletes_nothing(tmp_path):
    """A pixel-dust record for the third of three identical traces, after the
    first is deleted: two traces could be it, so neither goes."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "d0"),
        ("DUST", DUST, "d1"),
        ("DUST", DUST, "d2"),
    ])
    record = [
        r for r in series.findPixelDustTraces(1e9)
        if r["name"] == "DUST" and r["section"] == snum
    ][2]
    _remove_first(series, snum, "DUST")

    ambiguous = []
    assert series.deleteMalformedTraces([record], ambiguous=ambiguous) == []
    assert ambiguous == [record]
    assert _tags(series, snum, "DUST") == [["d1"], ["d2"]]


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
    no_index = {k: v for k, v in record.items() if k != "index"}

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


def test_the_pairs_list_is_told_which_rows_were_left(tmp_path, monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, "a"),
        ("C", SQUARE, "c"),
        ("B", SQUARE, "b0"),
        ("B", SQUARE, "b1"),
        ("B", SQUARE, "b2"),
    ])
    records = series.findDifferentlyNamedDuplicates(0.95)
    choices = [_row(records, "B", 2, "A"), _row(records, "B", 2, "C")]
    _remove_first(series, snum, "B")
    mod, notices = _notices(monkeypatch)

    applied = mod.FieldWidgetObject.deleteDifferentlyNamedDuplicates(
        _StubField(series), choices
    )

    assert applied == []
    assert notices == [
        "PyReconstruct did not delete 2 traces. They moved after the scan, "
        "and more than one identical trace under each name could be the one "
        "you chose:\n\n"
        f"  B on section {snum}\n  B on section {snum}\n\n"
        "Run the scan again to list them where they are now."
    ]


def test_a_cleanup_list_is_told_which_row_was_left(tmp_path, monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "d0"),
        ("DUST", DUST, "d1"),
        ("DUST", DUST, "d2"),
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
        "PyReconstruct did not delete 1 trace. It moved after the scan, and "
        "more than one identical trace under its name could be the one you "
        "chose:\n\n"
        f"  DUST on section {snum}\n\n"
        "Run the scan again to list it where it is now."
    ]
