"""Regression tests for the import paths that destroyed traces without saying so.

``Section.importTraces`` is the reconciliation layer for two copies of a series
that were edited in parallel. Four of its paths could remove a trace a human
had drawn while leaving behind neither a flag a reviewer could find nor a log
entry the next merge could see:

  1. ``keep_below="self"`` / ``"other"`` deletes every unfavoured conflict trace
     that overlaps a favoured one, then clears the favoured pool so that the
     flagging step below it has nothing left to flag.
  2. The ``(False, False)`` history branch discards the other section's contour
     whenever neither log mentions it after the divergence point -- including
     every contour a previous import changed, because an import suppresses
     logging while it runs.
  3. The ``(False, True)`` history branch replaces the current contour wholesale
     with the other one, on the strength of a log Boolean, without comparing any
     geometry.
  4. ``(True, False)`` propagates a removal, which is legitimate, but recorded
     it nowhere.

The rule these tests pin down is: **the import may only discard a trace that
overlaps something on the surviving side, or that a log entry records as
deliberately removed -- and a discarded trace always leaves a flag and a log
entry behind.** A trace that overlaps nothing on the surviving side is not an
older version of anything there; it is independent annotation work, and the
merge keeps it and flags the disagreement instead of picking a winner.

Geometry: axis-aligned squares of side 10. Two such squares offset along x by
``dx`` have Jaccard index ``(10-dx)/(10+dx)``, so ``dx=0.5`` gives ~0.913 --
below the 0.95 duplicate threshold but a real overlap. A square parked at
``FAR`` overlaps nothing at all. Every test asserts the ratios it depends on so
that a change in the overlap primitive fails loudly rather than quietly
invalidating the premise.

``Section`` cannot be constructed without series files on disk (``__init__``
reads the section file), so these tests drive the real method bodies on a
``Section.__new__`` instance with the handful of collaborators importTraces
actually touches, which is the smallest faithful way to exercise it headlessly.
"""
import pytest

from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.datatypes.log import LogSet, LogSetPair
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.trace import Trace


FAR = 500.0  # far enough that nothing overlaps it


def mk(dx=0.0, dy=0.0, side=10.0, name="square", tag=None):
    """A closed square of the given side, offset by (dx, dy)."""
    t = Trace(name, (0, 0, 0), True)
    t.points = [
        (dx, dy), (dx + side, dy), (dx + side, dy + side), (dx, dy + side)
    ]
    if tag:
        t.addTag(tag)
    return t


class _Series:
    """The slice of Series that Section.importTraces reaches for."""

    def __init__(self):
        self.user = "tester"
        self.logs = []          # (obj_name, snum, event)

    def addLog(self, obj_name, snum, event):
        self.logs.append((obj_name, snum, event))

    def getAttr(self, *args, **kwargs):
        return None


def mkSection(contours, snum=2, mag=0.01):
    """A Section instance carrying only what importTraces uses."""
    sec = Section.__new__(Section)
    sec.n = snum
    sec.mag = mag
    sec.contours = dict(contours)
    sec.flags = []
    sec.modified_contours = set()
    sec.series = _Series()
    sec.save = lambda *a, **k: None   # shadow the disk write
    return sec


def mkHistories(self_events, other_events, shared=1):
    """Build a LogSetPair with a real shared prefix and real divergent tails.

    ``self_events`` / ``other_events`` are ``(obj_name, section, event)``
    triples appended after the shared prefix. ``section`` may be None for a
    series-level (non section-specific) log such as "Delete object".
    """
    def fmt(obj_name, section, event):
        snum = "-" if section is None else str(section)
    # 09:00 and not the 0900 this used to say: fromList anchors a row on the
    # "YY-MM-DD, HH:MM, " stamp Log.__str__ writes, and getDateTime has used
    # "%H:%M" since the log was created, so a colon-less time was never a
    # shape this app could produce.
        return f"26-01-01, 09:00, u, {obj_name}, {snum}, {event}"

    prefix = [fmt("seed", 1, f"Modify trace(s) {i}") for i in range(shared)]
    ls0 = LogSet.fromList(prefix + [fmt(*e) for e in self_events])
    ls1 = LogSet.fromList(prefix + [fmt(*e) for e in other_events])
    pair = LogSetPair(ls0, ls1)
    assert pair.last_shared_index == shared - 1, "premise: the prefix is shared"
    assert not pair.complete_match, "premise: the logs diverge"
    return pair


def flagNames(section):
    return [f.name for f in section.flags]


# --------------------------------------------------------------------------- #
# premises
# --------------------------------------------------------------------------- #
def test_geometry_premises():
    """The overlap ratios every test below depends on."""
    assert 0.91 < mk(0.0).getOverlapRatio(mk(0.5)) < 0.95, (
        "a 0.5 offset is a real overlap but below the 0.95 duplicate threshold"
    )
    assert mk(0.0).getOverlapRatio(mk(FAR, FAR)) == 0, "the far square overlaps nothing"
    assert mk(0.0).overlaps(mk(0.5), threshold=0), "overlaps(threshold=0) means 'at all'"
    assert not mk(0.0).overlaps(mk(FAR, FAR), threshold=0)


# --------------------------------------------------------------------------- #
# path 1: keep_below deletes the unfavoured trace
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("keep_below", ["self", "other"])
def test_keep_below_records_the_traces_it_deletes(keep_below):
    """keep_below deletes drawn traces. It may, but not without a trace of it.

    The favoured pool is cleared before the flagging step runs, so before the
    fix this produced no flag, no log entry and no tag -- the traces were simply
    gone.
    """
    s_trace, o_trace = mk(0.0, tag="drawn_by_A"), mk(0.5, tag="drawn_by_B")
    sec = mkSection({"square": Contour("square", [s_trace])})
    other = mkSection({"square": Contour("square", [o_trace])})

    sec.importTraces(other, threshold=0.95, keep_below=keep_below, flag_conflicts=True)

    survivor = s_trace if keep_below == "self" else o_trace
    assert [t for t in sec.contours["square"]] == [survivor], (
        "premise: keep_below still resolves the conflict in favour of one side"
    )
    assert any(n.startswith("import-removed_") for n in flagNames(sec)), (
        "the deleted trace left no flag: a reviewer has no way to find out that "
        f"keep_below={keep_below!r} destroyed a trace here"
    )
    assert sec.series.logs, (
        "the deletion was not logged, so neither the user nor the next merge "
        "can see that this contour lost a trace"
    )


def test_keep_below_flag_carries_an_explanation():
    """A flag with no comment tells a reviewer only that something happened."""
    sec = mkSection({"square": Contour("square", [mk(0.0)])})
    other = mkSection({"square": Contour("square", [mk(0.5)])})

    sec.importTraces(other, threshold=0.95, keep_below="self")

    removed = [f for f in sec.flags if f.name.startswith("import-removed_")]
    assert removed, "premise: a removal flag exists"
    assert removed[0].comments, "the removal flag must say why the trace is gone"


# --------------------------------------------------------------------------- #
# path 2: the (False, False) history branch
# --------------------------------------------------------------------------- #
def test_history_silence_does_not_discard_independent_work():
    """(False, False) means 'neither log mentions this contour', not 'the two
    contours are the same'.

    The other section holds a trace that overlaps nothing of ours. Before the
    fix the whole contour was skipped and that trace vanished with no flag.
    """
    shared = mk(0.0)
    extra = mk(FAR, FAR)                      # independent work, unlogged
    sec = mkSection({"square": Contour("square", [mk(0.0)])})
    other = mkSection({"square": Contour("square", [shared, extra])})
    histories = mkHistories(
        self_events=[("unrelated", 1, "Modify trace(s)")],
        other_events=[("other_unrelated", 1, "Modify trace(s)")],
    )
    assert histories.getModifiedSinceDiverge("square", 2) == (False, False), (
        "premise: neither log mentions 'square' after the divergence point"
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert any(t is extra for t in sec.contours["square"]), (
        "a trace the other person drew was discarded because the log happened "
        "not to mention the contour"
    )
    assert any(n == "import-conflict_square" for n in flagNames(sec)), (
        "the merge could not use the history here and kept both sides; that "
        "must be flagged rather than resolved silently"
    )


def test_history_silence_still_skips_contours_that_really_do_agree():
    """The honest case must stay quiet: no new flags, no new work.

    This is the overwhelmingly common shape of a (False, False) contour and the
    reason the shortcut exists. If it started flagging here the change would
    bury real conflicts in noise.
    """
    sec = mkSection({"square": Contour("square", [mk(0.0)])})
    other = mkSection({"square": Contour("square", [mk(0.0)])})
    histories = mkHistories(
        self_events=[("unrelated", 1, "Modify trace(s)")],
        other_events=[("other_unrelated", 1, "Modify trace(s)")],
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert len(sec.contours["square"]) == 1, "the contours agree; nothing to merge"
    assert sec.flags == [], "an agreeing contour must not produce a flag"
    assert sec.series.logs == [], "nor a log entry"


# --------------------------------------------------------------------------- #
# path 3: the (False, True) history branch
# --------------------------------------------------------------------------- #
def test_history_does_not_replace_a_contour_holding_unlogged_work():
    """(False, True) replaced our contour wholesale with theirs.

    Our contour holds a trace that overlaps nothing of theirs. The log does not
    know about it -- an import suppresses logging, so anything a previous merge
    brought in looks unmodified. Before the fix it was overwritten out of
    existence with no flag.
    """
    mine = mk(FAR, FAR)                       # our own work, absent from the log
    sec = mkSection({"square": Contour("square", [mk(0.0), mine])})
    other = mkSection({"square": Contour("square", [mk(0.5)])})
    histories = mkHistories(
        self_events=[("unrelated", 1, "Modify trace(s)")],
        other_events=[("square", 2, "Modify trace(s)")],
    )
    assert histories.getModifiedSinceDiverge("square", 2) == (False, True), (
        "premise: only the other log mentions 'square' after the divergence point"
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert any(t is mine for t in sec.contours["square"]), (
        "our own trace was destroyed because the log did not happen to record it"
    )
    assert any(n == "import-conflict_square" for n in flagNames(sec)), (
        "keeping both versions is a conflict and must be flagged"
    )


def test_history_replacement_still_happens_when_it_loses_nothing():
    """When our contour holds nothing theirs does not overlap, the shortcut is
    the point of the feature and must still fire silently."""
    sec = mkSection({"square": Contour("square", [mk(0.0)])})
    theirs = mk(0.5)
    other = mkSection({"square": Contour("square", [theirs])})
    histories = mkHistories(
        self_events=[("unrelated", 1, "Modify trace(s)")],
        other_events=[("square", 2, "Modify trace(s)")],
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert [t for t in sec.contours["square"]] == [theirs], (
        "the other series is the only one whose log records an edit, and we hold "
        "nothing it does not overlap, so its version wins"
    )
    assert sec.flags == [], "a lossless shortcut must not raise a flag"


# --------------------------------------------------------------------------- #
# path 4: a recorded removal may propagate, but must be recorded
# --------------------------------------------------------------------------- #
def test_deleted_object_stays_deleted_and_the_removal_is_recorded():
    """A logged deletion is a human's recorded intent, so propagating it is
    right -- but it destroys the other side's traces, so it must leave a flag
    and a log entry.
    """
    theirs = mk(0.0)
    sec = mkSection({})                       # we deleted 'square'
    other = mkSection({"square": Contour("square", [theirs])})
    histories = mkHistories(
        self_events=[("square", None, "Delete object")],
        other_events=[("other_unrelated", 1, "Modify trace(s)")],
    )
    assert histories.getModifiedSinceDiverge("square", 2) == (True, False), (
        "premise: only our log mentions 'square', and it records a deletion"
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert "square" not in sec.contours, (
        "a deletion recorded in the log must still propagate -- otherwise the "
        "default resurrects every deleted object"
    )
    assert any(n == "import-removed_square" for n in flagNames(sec)), (
        "propagating the deletion destroyed the other series' traces with no "
        "flag to show where"
    )
    assert any(e[0] == "square" for e in sec.series.logs), (
        "and with no log entry, so the next merge cannot see it either"
    )


def test_removal_flag_is_not_suppressed_by_the_flag_conflicts_option():
    """"Flag conflicts" is about conflicts. A record of destroyed work is not
    optional: unchecking that box must not make a deletion silent again."""
    sec = mkSection({})
    other = mkSection({"square": Contour("square", [mk(0.0)])})
    histories = mkHistories(
        self_events=[("square", None, "Delete object")],
        other_events=[("other_unrelated", 1, "Modify trace(s)")],
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=False)

    assert any(n == "import-removed_square" for n in flagNames(sec))


def test_unlogged_disappearance_is_not_treated_as_a_deletion():
    """The same shape as the test above but with no removal event in the log:
    our contour is simply empty and the log says only "modified".

    Silence is not a deletion. Their traces must survive and be flagged, not be
    thrown away on the assumption that we meant to delete them.
    """
    theirs = mk(0.0)
    sec = mkSection({})
    other = mkSection({"square": Contour("square", [theirs])})
    histories = mkHistories(
        self_events=[("square", 2, "Modify trace(s)")],
        other_events=[("other_unrelated", 1, "Modify trace(s)")],
    )
    assert histories.getModifiedSinceDiverge("square", 2) == (True, False)

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert "square" in sec.contours and any(t is theirs for t in sec.contours["square"]), (
        "our log records an edit but no removal, so their trace is independent "
        "work and must be kept"
    )
    assert any(n == "import-conflict_square" for n in flagNames(sec))


def test_rename_is_a_recorded_removal_so_it_still_propagates():
    """Renaming an object logs "Rename object to X" under the OLD name. That is
    a recorded removal of the old name, so the old contour must not come back as
    a duplicate object."""
    sec = mkSection({"box": Contour("box", [mk(0.0, name="box")])})  # renamed square -> box
    other = mkSection({"square": Contour("square", [mk(0.0)])})
    histories = mkHistories(
        self_events=[
            ("square", None, "Rename object to box"),
            ("box", None, "Create trace(s) from square"),
        ],
        other_events=[("other_unrelated", 1, "Modify trace(s)")],
    )

    sec.importTraces(other, threshold=0.95, histories=histories, flag_conflicts=True)

    assert "square" not in sec.contours, (
        "the renamed-away object was resurrected under its old name, giving two "
        "objects for one structure"
    )
    assert any(n == "import-removed_square" for n in flagNames(sec))


# --------------------------------------------------------------------------- #
# the history queries, which the new default makes everybody pay for
# --------------------------------------------------------------------------- #
def test_modified_since_diverge_matches_the_definition_it_replaced():
    """getModifiedSinceDiverge now reads a per-object index of the
    post-divergence logs instead of reverse-scanning the whole log through
    LogSet.getLastIndex once per contour per section. That is what makes
    history checking affordable enough to default on, so pin that it did not
    change the answers: compare against getLastIndex over a log built to hit
    every branch -- section-specific logs, series-level logs with no section
    range, ztrace logs (which must be ignored), and objects absent entirely.
    """
    entries = [
        ("A", "1", "Modify trace(s)"),
        ("B", "2-4", "Modify trace(s)"),
        ("A", "-", "Delete object"),          # series-level: applies everywhere
        ("C", "7", "Modify ztrace"),          # ztrace logs are not trace edits
        ("D", "9", "Create trace(s)"),
    ]
    logs = [f"26-01-01, 09:00, u, {o}, {s}, {e}" for o, s, e in entries]

    for split in range(len(logs) + 1):
        ls0 = LogSet.fromList(logs[:split] + ["26-01-01, 09:00, u, Z, 1, Modify trace(s)"])
        ls1 = LogSet.fromList(logs)
        pair = LogSetPair(ls0, ls1)

        for cname in ("A", "B", "C", "D", "absent"):
            for snum in (1, 2, 3, 5, 7, 9):
                expected = tuple(
                    ls.getLastIndex(snum, cname) > pair.last_shared_index
                    for ls in (ls0, ls1)
                )
                assert pair.getModifiedSinceDiverge(cname, snum) == expected, (
                    f"split={split} cname={cname} snum={snum}"
                )


def test_removal_events_are_recognised_per_section():
    """getRemovedSinceDiverge must distinguish a recorded removal from any other
    edit, and must respect section ranges."""
    ls0 = LogSet.fromList([
        "26-01-01, 09:00, u, A, 1, Modify trace(s)",       # an edit, not a removal
        "26-01-01, 09:00, u, B, 2, Delete trace(s)",       # a removal, section 2 only
        "26-01-01, 09:00, u, C, -, Rename object to D",    # a removal, every section
    ])
    ls1 = LogSet.fromList(["26-01-01, 09:00, u, Z, 1, Modify trace(s)"])
    pair = LogSetPair(ls0, ls1)
    assert pair.last_shared_index == -1, "premise: the two logs diverge at index 0"

    assert pair.getRemovedSinceDiverge("A", 1)[0] is False, "an edit is not a removal"
    assert pair.getRemovedSinceDiverge("B", 2)[0] is True
    assert pair.getRemovedSinceDiverge("B", 3)[0] is False, "wrong section"
    assert pair.getRemovedSinceDiverge("C", 99)[0] is True, "a rename applies everywhere"
    assert pair.getRemovedSinceDiverge("absent", 1) == (False, False)


# --------------------------------------------------------------------------- #
# a crashed import must not poison the session or the next merge
# --------------------------------------------------------------------------- #
def test_a_failed_import_restores_logging():
    """Series.importTraces suppresses object create/delete logging while it runs
    and used to clear the flag with a bare assignment after the loop.

    An exception part way through therefore left logging suppressed for the rest
    of the session, and the holes that put in the log then corrupted the
    divergence detection of every later import -- a crashed merge quietly made
    the next merge unsafe.
    """
    import types

    from PyReconstruct.modules.datatypes.series import Series

    class _Boom(Exception):
        pass

    log_set = LogSet.fromList(["26-01-01, 09:00, u, seed, 1, Modify trace(s)"])
    stub = types.SimpleNamespace(
        data=types.SimpleNamespace(supress_logging=False),
        getFullHistory=lambda: log_set,
        enumerateSections=lambda **kwargs: (_ for _ in ()).throw(_Boom()),
    )
    other = types.SimpleNamespace(getFullHistory=lambda: log_set, sections={})

    with pytest.raises(_Boom):
        Series.importTraces(stub, other, srange=(0, 1))

    assert stub.data.supress_logging is False, (
        "logging is still suppressed after a failed import: object creations and "
        "deletions will go unlogged for the rest of this session"
    )


# --------------------------------------------------------------------------- #
# the default a user actually gets
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def test_history_checking_is_on_by_default(qapp):
    """The shipped default was a plain geometric union: the checkbox was created
    unchecked and its value is what gets passed, so out of the box an import
    resurrected every object the other person had deleted and produced a second
    copy of every object they had renamed. Series.importTraces has always
    declared check_history=True; only the dialog disagreed.
    """
    import types

    from PyReconstruct.modules.gui.dialog import import_series as imp

    series = types.SimpleNamespace(sections={0: "s0", 1: "s1"})
    other = types.SimpleNamespace(
        sections={0: "s0", 1: "s1"},
        data={"objects": {}},
        object_groups=types.SimpleNamespace(getGroupList=lambda: []),
    )

    widget = imp.ImportTracesWidget(None, series, other)

    assert widget.check_histories.isChecked(), (
        "history checking must default on, otherwise deletions resurrect and "
        "renames duplicate in the configuration everybody actually uses"
    )
    assert widget.flag_conflicts.isChecked(), "premise: conflict flagging stays on"


def test_series_import_traces_still_defaults_to_checking_history():
    import inspect

    from PyReconstruct.modules.datatypes.series import Series

    sig = inspect.signature(Series.importTraces)
    assert sig.parameters["check_history"].default is True
    assert sig.parameters["keep_below"].default == "", (
        "'keep both' must remain the default for traces below the threshold: it "
        "is the only lossless choice"
    )


# --------------------------------------------------------------------------- #
# the helper the branches share
# --------------------------------------------------------------------------- #
def test_traces_without_counterpart():
    from PyReconstruct.modules.datatypes.section import tracesWithoutCounterpart

    keeper = Contour("square", [mk(0.0)])
    orphan = mk(FAR, FAR)
    donor = Contour("square", [mk(0.5), orphan])

    assert tracesWithoutCounterpart(donor, keeper) == [orphan], (
        "a trace that overlaps the keeper at all is a version of it; only the "
        "one overlapping nothing is independent work"
    )
    assert tracesWithoutCounterpart(Contour("square", []), keeper) == []
    assert tracesWithoutCounterpart(donor, Contour("square", [])) == [t for t in donor], (
        "with nothing to overlap, every donor trace is independent work"
    )
