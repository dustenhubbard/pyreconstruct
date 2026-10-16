"""A clean-up row finds its trace by the trace's id, saves in between or not.

Each trace has an id in memory. The working copy stores no ids, so a section
loaded again used to get its ids by row order, and a row could only tell
identical traces apart by their place among the lookalikes (#660): an edit
that changed how many there were left the row skipped. The issuer now gives a
file this session wrote the ids it was written with (hub #52), so the row's id
still names its trace after the edit. Identical traces are told apart here by
those ids.
"""
from test_cleanup_delete_recorded_trace import (
    DUST, SQUARE, _dust_records, _load_series, _remove_first, _seed, _states,
    _tags,
)


def _ids(series, snum, name):
    section = series.loadSection(snum)
    return [section.traceID(t) for t in section.contours.get(name, [])]


# ---------------------------------------------------------------------------
# the #660 skip: an edit outside the list changes the count of lookalikes
# ---------------------------------------------------------------------------

def test_deleting_one_twin_by_hand_leaves_the_row_for_the_other(tmp_path):
    """I pick the second of two identical traces, then delete the first by
    hand. The row still deletes the second."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "same"), ("DUST", DUST, "same")])
    record = _dust_records(series, snum)[1]
    _remove_first(series, snum, "DUST")

    ambiguous = []
    deleted = series.deleteMalformedTraces([record], ambiguous=ambiguous)

    assert ambiguous == []
    assert deleted == [record]
    assert _tags(series, snum, "DUST") == []


def test_pasting_a_third_twin_leaves_the_row_for_its_own(tmp_path):
    """I pick the first of two identical traces, then paste a third. The row
    deletes the first, and the other two are the ones left."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "same"), ("DUST", DUST, "same")])
    records = _dust_records(series, snum)
    first, second = (r.get("trace_id") for r in records)
    section = series.loadSection(snum)
    section.addTrace(section.contours["DUST"][0].copy(), log_event=False)
    section.save()

    ambiguous = []
    deleted = series.deleteMalformedTraces([records[0]], ambiguous=ambiguous)

    assert ambiguous == []
    assert deleted == [records[0]]
    left = _ids(series, snum, "DUST")
    assert len(left) == 2 and first not in left and second in left


def test_a_twin_deleted_by_hand_still_leaves_its_row(tmp_path):
    """The row's own trace is the one deleted by hand: its id is gone, the
    count rule takes over, and the twin is left."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "same"), ("DUST", DUST, "same")])
    record = _dust_records(series, snum)[0]
    _remove_first(series, snum, "DUST")

    ambiguous = []
    assert series.deleteMalformedTraces([record], ambiguous=ambiguous) == []
    assert ambiguous == [record]
    assert _tags(series, snum, "DUST") == [["same"]]


def test_a_trace_changed_in_place_is_not_found_by_its_id(tmp_path):
    """Smooth changes a trace's points in place, so it keeps its id. The scan's
    content no longer fits it, so the row is resolved as before and the
    changed trace is not deleted."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "a"), ("DUST", DUST, "b")])
    record = _dust_records(series, snum)[0]
    section = series.loadSection(snum)
    trace = section.contours["DUST"][0]
    trace.points = [(x * 2, y * 2) for x, y in trace.points]
    section.resyncColumnarStore()
    assert section.traceID(trace) == record["trace_id"]
    section.save()

    assert series.deleteMalformedTraces([record]) == []
    assert _tags(series, snum, "DUST") == [["a"], ["b"]]


# ---------------------------------------------------------------------------
# ids last from a save to the next load in one session
# ---------------------------------------------------------------------------

def test_a_save_and_a_load_keep_every_id(tmp_path):
    """Twins keep their own ids, and an edited trace and a trace made in the
    session keep the ids they were given."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUST", DUST, "same"), ("DUST", DUST, "same"), ("SQ", SQUARE, "sq"),
    ])
    section = series.loadSection(snum)
    twins = [section.traceID(t) for t in section.contours["DUST"]]
    section.editTraceAttributes(
        [section.contours["SQ"][0]], None, None, {"edited"}, None,
        log_event=False,
    )
    # an edit replaces the trace, and the new one has a new id
    square_id = section.traceID(section.contours["SQ"][0])
    new = section.contours["DUST"][0].copy()
    new.name = "NEW"
    section.addTrace(new, log_event=False)
    new_id = section.traceID(new)
    section.save()

    again = series.loadSection(snum)
    assert [again.traceID(t) for t in again.contours["DUST"]] == twins
    assert again.traceID(again.contours["SQ"][0]) == square_id
    assert again.traceID(again.contours["NEW"][0]) == new_id
    assert len({*twins, square_id, new_id}) == 4


def test_a_file_this_session_did_not_write_derives_as_before(tmp_path):
    """Bytes the issuer did not record get no saved ids back."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "same")])
    issuer = series.trace_id_issuer
    section = series.loadSection(snum)
    data = section.getDict()["contours"]
    assert issuer.restoreForSection(snum, b"not these bytes", data) is None
    assert issuer.restoreForSection(snum + 10_000, b"", data) is None


# ---------------------------------------------------------------------------
# undo brings a trace back with a new id
# ---------------------------------------------------------------------------

def test_a_trace_undone_back_has_a_new_id_and_the_count_rule_applies(
        tmp_path):
    """I delete the second twin from one list and undo it. Its row from
    another list no longer finds it by id, so when the first twin is then
    deleted by hand, the row is left as #660 leaves it."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUST", DUST, "same"), ("DUST", DUST, "same")])
    record = _dust_records(series, snum)[1]
    states = _states(series)
    assert series.deleteMalformedTraces(
        [dict(record)], series_states=states
    ) != []
    states.undoState()
    assert len(_ids(series, snum, "DUST")) == 2
    assert record["trace_id"] not in _ids(series, snum, "DUST")
    _remove_first(series, snum, "DUST")

    ambiguous = []
    assert series.deleteMalformedTraces([record], ambiguous=ambiguous) == []
    assert ambiguous == [record]
    assert _tags(series, snum, "DUST") == [["same"]]
