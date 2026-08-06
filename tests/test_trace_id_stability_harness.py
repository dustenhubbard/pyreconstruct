"""S2: the id-stability harness. What moves a trace's id, driven through the
application's own mutation entry points.

S1 (#297) gave every trace an id at load. This module is the slice that asks
what happens to that id afterwards, and it asks by driving a real fixture
series through the entry points a user reaches -- `Section.addTrace`,
`Section.removeTrace`, `Section.deleteTraces`, `Section.editTraceAttributes`,
`Series.copyObjects`, `Series.copyTracesToSections`, `SectionStates.undoState`,
`SectionStates.redoState`, `Section.save`, `Series.loadSection`,
`Series.saveJser` -- rather than by calling the columnar store's carry
primitives directly. `tests/test_columnar_store_parity.py` already covers the
primitives in isolation; what nothing covered before this module is whether the
application ever reaches them.

**It does not, and that is this harness's headline finding.** `copyRow` and
`duplicateRow`, the two operations `columnar_store.py`'s carry table is written
around, have **zero callers outside tests** at `978b4d91`. Every mutation entry
point in the application reaches `Section._dualWriteAppend`, which calls
`appendRow` with no `trace_id`, which asks the issuer for a fresh one. So the
table's `duplicateRow` half is satisfied by accident (a duplicate does get a new
id, just not through `duplicateRow`) and its `copyRow` half is **not satisfied
at all** (an attribute edit or a rename re-identifies the trace it edits, in
memory, with no save involved). Both are pinned below as the code actually
behaves, with the discrepancy named in the test's own docstring, because the
spec's instruction for this slice was to expect it to find real gaps rather than
to green the table.

**The second finding is undo and redo, which the carry table does not mention at
all.** An undo does not restore the `Trace` objects the section had; it builds
new ones from a baseline and then calls `resyncColumnarStore()`. The rebuild's
only correlation between a trace and an id is the outgoing row map, keyed on the
objects the undo just discarded, so nothing matches and every restored trace is
re-identified. The rebuild itself is not at fault -- it carries ids correctly
whenever it is handed traces it has seen, which
`test_a_rebuild_carries_every_id` pins -- so this is a gap between two correct
pieces rather than a defect in either, which is exactly the kind a
primitive-level test cannot see and a workload harness can.

WHAT THIS MODULE PINS THAT IS *KNOWN* AND *INTENDED*
-----------------------------------------------------
Two behaviours here look like defects and are not; they are Track A's shape, and
pinning them is the point, because S3+ (persisted ids) is what flips them and a
harness with no red test to flip is a harness that will not notice.

* **An edit, a save and a reload move the edited trace's id.** With nothing
  persisted, an id can only be a pure function of the row's stored content, and
  a pure function of content necessarily moves when the content moves.
  `trace_id.py`'s module docstring records why the alternative is worse. The
  neighbours keep their ids and the superseded id stays spoken for in `taken`;
  all three halves are asserted.
* **An id issued during a session does not survive a save and a reload.** The
  issued id is opaque and random, nothing writes it to a file, and the reload
  derives a fresh one from content. Same cause, other direction.

TWO ROWS ARE RESERVED TO THE MAINTAINER AND ARE NOT GUESSED AT
---------------------------------------------------------------
`trace_id.py`'s closing section reserves split-object `_{n}` traces (Q4: same
trace edited, or new trace?) and palette traces (Q3: templates rather than
annotations, and they "may want no id at all"). `columnar_store.py` says the
same and adds that "a caller reaching for either case finds nothing here rather
than an invented answer". This module therefore asserts **no semantic** for
either, and `CARRY_TABLE` below lists both as unexercised with the reason. What
today's code happens to do with them is reported in the pull request, not turned
into an expectation a future change would have to honour.

THE MANIFEST IS THE DONE CRITERION
-----------------------------------
`CARRY_TABLE` is a data structure rather than a comment, and
`test_every_carry_table_row_is_exercised_or_listed_unexercised` checks it: every
row is either exercised by tests that exist in this module, or listed as
unexercised with a non-empty reason. Adding a row to the carry table without
covering it or explaining why is what that test catches.
"""

import sys

import pytest

from PyReconstruct.modules.datatypes.trace_id import TRACE_ID_LENGTH


## --------------------------------------------------------------------------
## The carry table, as a manifest. `columnar_store.py`'s IDENTITY section and
## `trace_id.py`'s closing section are the sources; the `verdict` column is what
## this harness measured at `978b4d91`.
##
## `tests` names functions in THIS module. `reason` is required exactly when
## `tests` is empty, and the test below enforces both directions.
## --------------------------------------------------------------------------
CARRY_TABLE = (
    dict(
        row="appendRow, nothing passed -- a new annotation is ISSUED an id",
        entry_point="Section.addTrace",
        verdict="holds",
        tests=("test_adding_a_trace_issues_a_fresh_id_and_moves_no_neighbour",),
        reason="",
    ),
    dict(
        row="removeRow -- a delete retires one row and no other trace's id moves",
        entry_point="Section.removeTrace, Section.deleteTraces",
        verdict="holds",
        tests=(
            "test_removing_a_trace_moves_no_survivors_id",
            "test_delete_traces_moves_no_survivors_id",
        ),
        reason="",
    ),
    dict(
        row="copyRow KEEPS the id -- 'how an attribute edit and a rename are "
            "implemented'",
        entry_point="Section.editTraceAttributes",
        verdict="CONTRADICTED: copyRow has no caller outside tests; the edit "
                "re-identifies the trace in memory",
        tests=(
            "test_an_attribute_edit_moves_the_id_because_copyrow_is_not_wired",
            "test_a_rename_moves_the_id_because_copyrow_is_not_wired",
        ),
        reason="",
    ),
    dict(
        row="duplicateRow ISSUES a new id -- the duplicate-object shape",
        entry_point="Series.copyObjects",
        verdict="holds by outcome, not by mechanism: reached through "
                "appendRow-with-no-id, not through duplicateRow",
        tests=("test_duplicating_an_object_issues_new_ids_and_leaves_the_source",),
        reason="",
    ),
    dict(
        row="duplicateRow ISSUES a new id -- the copy-traces-to-sections shape",
        entry_point="Series.copyTracesToSections",
        verdict="holds by outcome, not by mechanism (as above)",
        tests=("test_copying_traces_to_sections_issues_ids_and_leaves_the_source",),
        reason="",
    ),
    dict(
        row="a rebuild CARRIES every id it can correlate (D10, #283)",
        entry_point="Section.resyncColumnarStore",
        verdict="holds",
        tests=("test_a_rebuild_carries_every_id",),
        reason="",
    ),
    dict(
        row="a clean save does not re-identify the traces it saves (#278)",
        entry_point="Section.save, Series.saveJser",
        verdict="holds",
        tests=(
            "test_a_clean_save_does_not_re_identify_the_traces_it_saves",
            "test_a_whole_series_save_and_reopen_moves_no_id",
        ),
        reason="",
    ),
    dict(
        row="a reload of unchanged content is stable (S1)",
        entry_point="Series.loadSection",
        verdict="holds",
        tests=("test_reloading_unchanged_content_moves_no_id",),
        reason="",
    ),
    dict(
        row="an undo restores traces from a baseline -- what happens to their ids",
        entry_point="SectionStates.undoState",
        verdict="CONTRADICTED: every trace on the section is re-identified, "
                "including traces in contours the undo never touched",
        tests=("test_an_undo_re_identifies_every_trace_on_the_section",),
        reason="",
    ),
    dict(
        row="a redo restores traces from a state -- what happens to their ids",
        entry_point="SectionStates.redoState",
        verdict="CONTRADICTED: every trace in a restored contour is "
                "re-identified; contours it does not restore keep their ids",
        tests=("test_a_redo_re_identifies_the_contours_it_restores",),
        reason="",
    ),
    dict(
        row="an edit, a save and a reload -- the edited trace's id moves and the "
            "neighbours' do not (Track A, inherent)",
        entry_point="Section.editTraceAttributes + Section.save + "
                    "Series.loadSection",
        verdict="known and intended for Track A; the red test S3+ flips",
        tests=(
            "test_an_edit_then_save_then_reload_moves_only_the_edited_traces_id",
        ),
        reason="",
    ),
    dict(
        row="an id issued in-session does not survive a save and a reload "
            "(Track A, inherent)",
        entry_point="Section.addTrace + Section.save + Series.loadSection",
        verdict="known and intended for Track A; the second red test S3+ flips",
        tests=("test_an_id_issued_in_session_does_not_survive_a_save_and_reload",),
        reason="",
    ),
    dict(
        row="two byte-identical rows in one contour: deleting the first transfers "
            "the survivor's id (pr297-duplicate-row-id-transfer)",
        entry_point="Section.addTrace + Section.removeTrace + save + reload",
        verdict="inherent to any content-derived scheme over indistinguishable "
                "rows; reproduced end to end here",
        tests=("test_deleting_one_of_two_identical_rows_transfers_the_survivors_id",),
        reason="",
    ),
    dict(
        row="appendRow(foreign_id=) -- an id from another series is ADOPTED, or "
            "reissued and reported on a clash",
        entry_point="(none)",
        verdict="unexercised",
        tests=(),
        reason=(
            "`foreign_id=` has no caller outside `columnar_store.py` itself at "
            "978b4d91 -- verified by grep across `PyReconstruct/`. The import "
            "path (`Section.importTraces`, `Series.importTraces`) builds traces "
            "through `addTrace`, so a merge's ids are issued locally rather "
            "than adopted. There is no application entry point to drive, and "
            "`test_columnar_store_parity.py` already covers the primitive "
            "directly. Wiring it is D10's remaining half, not this slice's."
        ),
    ),
    dict(
        row="split-object `_{n}` traces -- same trace edited, or new trace?",
        entry_point="Series.splitObject",
        verdict="unexercised BY DECISION",
        tests=(),
        reason=(
            "Reserved to the maintainer. `trace_id.py`'s closing section: the "
            "module 'decides nothing about split-object traces (Series split, "
            "renamed `_{n}`) ... those two rows of the carry table are "
            "semantics the maintainer owns and they are unimplemented on "
            "purpose'; the spec files it as Q4. Whether a split's output is the "
            "same annotation under a new name or a set of new annotations is "
            "the question, and asserting either answer here would decide it by "
            "accident. What the code does today is reported in the pull "
            "request instead."
        ),
    ),
    dict(
        row="palette traces -- do they get ids at all?",
        entry_point="Series.palette_traces",
        verdict="unexercised BY DECISION",
        tests=(),
        reason=(
            "Reserved to the maintainer, spec Q3. Palette traces are templates "
            "rather than annotations and the store's own docstring notes they "
            "'may want no id at all'. They also never reach a `SectionColumns` "
            "-- `series.palette_traces` is a plain list of `Trace` objects on "
            "the `Series`, with no store and no row -- so there is no id to "
            "assert about without first deciding that they should have one. "
            "`test_palette_traces_never_reach_a_store` records the mechanical "
            "half of that (which is a fact, not a semantic) and stops there."
        ),
    ),
)


## --------------------------------------------------------------------------
## Helpers
## --------------------------------------------------------------------------

def _idsByPosition(section) -> dict:
    """`{(contour name, index within contour): id}` for one section.

    Positional rather than keyed on the `Trace` object, because several entry
    points here replace the object: `editTraceAttributes` removes a trace and
    adds a copy, and an undo rebuilds every contour from a baseline. A position
    key survives that; an object key does not.

    It does NOT survive a reordering, and one entry point reorders: a
    remove/add round trip appends at the end of the contour. Tests that cross
    that boundary compare id *sets* or name the position they expect, and say
    so where they do.
    """
    out = {}
    for name in sorted(section.contours, key=str):
        for index, trace in enumerate(section.contours[name].getTraces()):
            out[(name, index)] = section._columns.getID(
                section._column_rows[trace]
            )
    return out


def _idsByTrace(section) -> dict:
    """`{Trace: id}`, through the store's own row map.

    For the operations that keep the `Trace` objects they started with -- a
    rebuild, a save -- where identity of the object is exactly the correlation
    under test.
    """
    return {
        trace: section._columns.getID(row)
        for trace, row in section._column_rows.items()
    }


def _idsForSeries(series) -> dict:
    """`{(section, contour, index): id}` for every trace in the series."""
    out = {}
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        for key, value in _idsByPosition(section).items():
            out[(snum,) + key] = value
    return out


def _aWorkingSection(series):
    """The lowest-numbered section with two contours, one of them holding two.

    Chosen by content rather than hard-coded, so the harness follows the
    fixture if its sections are renumbered. Both halves of the requirement earn
    their place: a second contour is what makes "the edit did not disturb
    another contour" a real assertion, and a contour holding two traces is what
    makes "the edited trace's neighbours kept their ids" a real one. A section
    with one trace per contour would pass several tests below vacuously.

    Skips rather than passing vacuously if the fixture has no such section.
    """
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        if len(section.contours) >= 2 and any(
            len(contour.getTraces()) >= 2 for contour in section.contours.values()
        ):
            return snum, section
    pytest.skip(  # pragma: no cover - fixture-shape guard
        "the fixture series has no section with two contours, one of them "
        "holding two traces, so the harness has nothing to drive"
    )


def _aCrowdedContour(section) -> str:
    """The first contour on the section holding at least two traces."""
    return next(
        name for name in sorted(section.contours, key=str)
        if len(section.contours[name].getTraces()) >= 2
    )


def _aTrace(section, name=None):
    """One trace off the section, from the named contour or the first one."""
    if name is None:
        name = sorted(section.contours, key=str)[0]
    return section.contours[name].getTraces()[0]


def _newTrace(name="harness_newcomer"):
    from PyReconstruct.modules.datatypes import Trace

    trace = Trace(name, [120, 30, 40], closed=True)
    trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    return trace


def _sectionStates(section, series):
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    return SectionStates(section, series)


## --------------------------------------------------------------------------
## The Done criterion itself
## --------------------------------------------------------------------------

def test_every_carry_table_row_is_exercised_or_listed_unexercised():
    """The spec's Done criterion for S2, checked rather than claimed.

    "every carry-table row is either exercised or explicitly listed as
    unexercised with the reason". A row with tests must name tests that exist
    in this module; a row with none must carry a reason. Adding a carry rule
    and forgetting to cover it is what this catches, and it catches it in the
    manifest rather than in a reviewer's memory.
    """
    module = sys.modules[__name__]
    assert CARRY_TABLE, "the manifest is empty, so this proves nothing"

    for entry in CARRY_TABLE:
        label = entry["row"]
        assert entry["verdict"], f"{label}: no verdict recorded"
        if entry["tests"]:
            assert not entry["reason"], (
                f"{label}: exercised rows do not carry an unexercised reason"
            )
            for name in entry["tests"]:
                assert hasattr(module, name), (
                    f"{label}: names {name!r}, which does not exist in this "
                    "module -- a renamed test silently stops covering its row"
                )
        else:
            assert entry["reason"], (
                f"{label}: unexercised and gives no reason. The spec requires "
                "the reason, because 'we did not get to it' and 'this is the "
                "maintainer's call' are different facts."
            )


def test_the_two_reserved_rows_are_present_and_unexercised():
    """Done criterion: the maintainer's two rows are REPORTED, not guessed at.

    Named individually rather than left to the count above, because the failure
    this guards is somebody helpfully adding an assertion for one of them: the
    row would move to `tests` and the check above would go on passing while the
    harness had quietly decided Q3 or Q4.
    """
    reserved = {
        entry["row"]: entry
        for entry in CARRY_TABLE
        if entry["verdict"].endswith("BY DECISION")
    }
    assert len(reserved) == 2, (
        "expected exactly the two rows trace_id.py reserves to the maintainer "
        f"(split-object `_{{n}}` traces, palette traces), found: {sorted(reserved)}"
    )
    assert any("split-object" in row for row in reserved)
    assert any("palette" in row for row in reserved)
    for row, entry in reserved.items():
        assert entry["tests"] == (), (
            f"{row}: a reserved row acquired tests. If the semantics have been "
            "decided, the decision belongs in trace_id.py's closing section "
            "first; if they have not, this harness must not decide them."
        )


def test_the_carry_primitives_have_no_production_caller():
    """The headline finding, pinned so that wiring them shows up as a change.

    `copyRow` and `duplicateRow` are the two operations the store's carry table
    is written around, and nothing outside `tests/` calls either at 978b4d91 --
    which is why the two `copyRow` tests below assert that an edit MOVES an id.
    When D10's remaining half wires them, this test goes red, and going red is
    the notification: the two contradiction pins below have to be turned over in
    the same change.

    Read off the source rather than by patching, because a monkeypatched method
    would only prove that the call sites this test knows about do not call it.
    """
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "PyReconstruct"
    callers = {}
    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for primitive in ("copyRow(", "duplicateRow("):
            if primitive in text and path.name != "columnar_store.py":
                callers.setdefault(primitive, []).append(str(path))
    ## `columnar_store.py` itself is excluded above: it defines both and
    ## documents them, and a module defining its own method is not a caller.
    assert not callers, (
        "copyRow/duplicateRow now have production callers, which is D10's "
        "remaining half landing. Turn over the two 'copyRow is not wired' "
        f"tests below in the same change.\n{callers}"
    )


## --------------------------------------------------------------------------
## Add / delete
## --------------------------------------------------------------------------

def test_adding_a_trace_issues_a_fresh_id_and_moves_no_neighbour(real_series):
    """`Section.addTrace` -> `appendRow` with no id -> `issue()`."""
    _, section = _aWorkingSection(real_series)
    before = _idsByPosition(section)
    assert before, "the chosen section has no traces"

    newcomer = _newTrace()
    section.addTrace(newcomer, log_event=False)

    issued = section._columns.getID(section._column_rows[newcomer])
    assert issued is not None and len(issued) == TRACE_ID_LENGTH
    assert issued not in set(before.values()), (
        "the new trace was handed an id a loaded trace already holds"
    )
    assert issued in real_series.trace_id_issuer.taken, (
        "an issued id was not registered in the series' index, so a later "
        "issue could hand it out again"
    )

    after = _idsByPosition(section)
    moved = {
        key: (before[key], after[key])
        for key in before
        if after.get(key) != before[key]
    }
    assert not moved, f"adding a trace moved an existing trace's id: {moved}"


def test_removing_a_trace_moves_no_survivors_id(real_series):
    """`Section.removeTrace` retires one row and touches nothing else.

    Compared as a set rather than by position: `removeTrace` renumbers the
    positions after the one it removed, which is a fact about the position key
    and not about any id.
    """
    _, section = _aWorkingSection(real_series)
    before = _idsByPosition(section)
    victim = _aTrace(section)
    victim_id = section._columns.getID(section._column_rows[victim])

    section.removeTrace(victim, log_event=False)

    after = _idsByPosition(section)
    assert set(after.values()) == set(before.values()) - {victim_id}, (
        "removing one trace changed which ids the section holds beyond "
        f"dropping {victim_id}: {sorted(before.values())} -> "
        f"{sorted(after.values())}"
    )
    assert victim_id in real_series.trace_id_issuer.taken, (
        "the removed trace's id was released back to the index. An id once "
        "handed out stays spoken for -- trace_id.py's collision policy -- so "
        "a later issue cannot resurrect it on a different trace."
    )


def test_delete_traces_moves_no_survivors_id(real_series):
    """The same property through the entry point the field's Delete reaches."""
    _, section = _aWorkingSection(real_series)
    before = _idsByPosition(section)
    victim = _aTrace(section)
    victim_id = section._columns.getID(section._column_rows[victim])

    section.deleteTraces([victim], log_event=False)

    after = _idsByPosition(section)
    assert set(after.values()) == set(before.values()) - {victim_id}, (
        f"deleteTraces disturbed a survivor's id: {sorted(before.values())} -> "
        f"{sorted(after.values())}"
    )


## --------------------------------------------------------------------------
## The contradicted copyRow rows
## --------------------------------------------------------------------------

def test_an_attribute_edit_moves_the_id_because_copyrow_is_not_wired(real_series):
    """DISCREPANCY, pinned as the code behaves rather than as the table says.

    `columnar_store.py`'s carry table:

        `copyRow(row)` **keeps** the id. This is the `editTraceAttributes`
        shape: remove, copy, mutate an attribute, add. It is how an attribute
        edit and a rename are implemented, and the result is the same trace.

    It is not how they are implemented. `editTraceAttributes` calls
    `Section.removeTrace` and `Section.addTrace`, and `addTrace` reaches
    `_dualWriteAppend`, which calls `appendRow` with no `trace_id` -- the "a new
    annotation" arm, which asks the issuer to mint one. `copyRow` is never
    reached (see `test_the_carry_primitives_have_no_production_caller`), so the
    edited trace comes out of an attribute edit as a DIFFERENT annotation, in
    memory, with no save anywhere near it.

    This is not the same finding as the known edit-then-reload movement further
    down. That one is inherent to deriving from content and cannot be fixed
    inside Track A; this one is a store operation that exists, does exactly the
    right thing, and has no caller. Recorded as the harness's headline gap.

    Asserted rather than xfailed on purpose: an xfail says "we expect to fix
    this and have not"; an assertion on the real behaviour says "this is what
    the program does today", which is what a stability harness is for. The day
    it is wired, this test and the rename one below both go red together with
    the primitive-caller test above.
    """
    _, section = _aWorkingSection(real_series)
    cname = sorted(section.contours, key=str)[0]
    victim = _aTrace(section, cname)
    before_id = section._columns.getID(section._column_rows[victim])
    untouched = {
        trace: value
        for trace, value in _idsByTrace(section).items()
        if trace is not victim
    }

    section.editTraceAttributes(
        [victim], name=None, color=(1, 2, 3), tags=None, mode=None,
        log_event=False,
    )

    replacements = [
        trace for trace in section.contours[cname].getTraces()
        if trace not in untouched
    ]
    assert len(replacements) == 1, (
        "editTraceAttributes did not replace exactly one trace, so the rest of "
        f"this test is not measuring what it says: {len(replacements)}"
    )
    after_id = section._columns.getID(section._column_rows[replacements[0]])
    assert after_id != before_id, (
        "an attribute edit KEPT the trace's id. That is what the carry table "
        "says should happen and it is not what this build does -- if it now "
        "does, copyRow has been wired and this test is the one that should be "
        "turned over, together with the rename test and the primitive-caller "
        "test."
    )
    assert replacements[0].color == (1, 2, 3), (
        "the edit did not take effect, so the id movement above proves nothing"
    )
    assert before_id in real_series.trace_id_issuer.taken, (
        "the superseded id was released rather than left spoken for"
    )

    now = _idsByTrace(section)
    disturbed = {
        trace.name: (value, now[trace])
        for trace, value in untouched.items()
        if trace in now and now[trace] != value
    }
    assert not disturbed, (
        f"the edit moved a bystander's id as well: {disturbed}"
    )


def test_a_rename_moves_the_id_because_copyrow_is_not_wired(real_series):
    """The rename half of the same discrepancy, through the same entry point.

    Split from the attribute-edit test rather than parametrized with it because
    a rename additionally moves the trace between contours -- `addTrace` files
    it under the new name -- and the day `copyRow` is wired the two cases are
    entitled to different answers (a rename may or may not be judged to produce
    the same annotation). Two tests keep that decision separable.
    """
    _, section = _aWorkingSection(real_series)
    cname = sorted(section.contours, key=str)[0]
    new_name = f"{cname}_harness_renamed"
    victim = _aTrace(section, cname)
    before_id = section._columns.getID(section._column_rows[victim])

    section.editTraceAttributes(
        [victim], name=new_name, color=None, tags=None, mode=None,
        log_event=False,
    )

    assert new_name in section.contours, "the rename did not take effect"
    renamed = section.contours[new_name].getTraces()[0]
    after_id = section._columns.getID(section._column_rows[renamed])
    assert after_id != before_id, (
        "a rename KEPT the trace's id. The carry table says it should; this "
        "build does not, because copyRow has no caller. See the attribute-edit "
        "test's docstring."
    )
    assert before_id in real_series.trace_id_issuer.taken


## --------------------------------------------------------------------------
## Duplicate / copy-to-sections
## --------------------------------------------------------------------------

def test_duplicating_an_object_issues_new_ids_and_leaves_the_source(real_series):
    """`Series.copyObjects` -- the duplicate-object row.

    The outcome the carry table asks for (a duplicate is a new annotation and
    gets a new id) does hold. The MECHANISM is not the one the table names:
    `copyObjects` calls `Trace.copy()` and `Section.addTrace`, so the new id
    comes from `appendRow`'s no-id arm rather than from `duplicateRow`. Worth
    stating because the two are only accidentally in agreement -- the table's
    other half, `copyRow`, is reached by the same route and comes out wrong.
    """
    snum, section = _aWorkingSection(real_series)
    source_name = sorted(section.contours, key=str)[0]
    before = _idsByPosition(section)

    copy_names = real_series.copyObjects([source_name], log_event=False)
    assert copy_names == [f"{source_name}_copy"], (
        f"copyObjects refused or renamed the destination: {copy_names}"
    )

    section = real_series.loadSection(snum)
    after = _idsByPosition(section)

    kept = {key: after[key] for key in before if key in after}
    assert kept == before, (
        f"duplicating an object moved a source trace's id: {before} -> {kept}"
    )
    copies = {
        key: value for key, value in after.items()
        if key[0] == f"{source_name}_copy"
    }
    assert copies, "the copy produced no traces, so this proves nothing"
    assert not (set(copies.values()) & set(before.values())), (
        "a duplicate was handed one of the source's ids -- two live traces "
        f"sharing one identity: {copies}"
    )
    assert all(len(value) == TRACE_ID_LENGTH for value in copies.values())


def test_copying_traces_to_sections_issues_ids_and_leaves_the_source(real_series):
    """`Series.copyTracesToSections` -- the other duplicateRow row.

    The traces are handed to the destination in FIELD coordinates and each
    destination re-projects through its own inverse transform, which is why the
    source's points are mapped forward before the call. The identity property
    under test is unaffected by the projection: a copy landing on another
    section is a new annotation and must not carry the source's id.
    """
    snum, section = _aWorkingSection(real_series)
    others = [n for n in sorted(real_series.sections) if n != snum]
    if not others:  # pragma: no cover - fixture-shape guard
        pytest.skip("the fixture series has only one section")
    destination = others[0]

    source = _aTrace(section)
    source_id = section._columns.getID(section._column_rows[source])
    before_source = _idsByPosition(section)
    before_dest = _idsByPosition(real_series.loadSection(destination))

    in_field = source.copy()
    in_field.points = [section.tform.map(*point) for point in source.points]

    copied_to, skipped = real_series.copyTracesToSections(
        [in_field], [destination], log_event=False
    )
    assert copied_to == [destination], (
        f"the copy did not reach the destination: copied={copied_to} "
        f"skipped={skipped}"
    )

    dest_after = _idsByPosition(real_series.loadSection(destination))
    arrived = set(dest_after.values()) - set(before_dest.values())
    assert arrived, "the destination gained no id, so this proves nothing"
    assert source_id not in set(dest_after.values()), (
        f"the copy carried the source's id {source_id} onto section "
        f"{destination}: two live traces in one series under one identity"
    )
    assert _idsByPosition(real_series.loadSection(snum)) == before_source, (
        "copying traces away moved an id on the source section"
    )


## --------------------------------------------------------------------------
## Rebuild / save / reload
## --------------------------------------------------------------------------

def test_a_rebuild_carries_every_id(real_series):
    """D10 / #283: `resyncColumnarStore` throws the store away and keeps the ids.

    Keyed on the `Trace` object, because a rebuild is entitled to renumber rows
    and this is exactly the correlation `_rebuildColumnarStore` uses -- the
    outgoing row map read before `self._columns` is rebound.
    """
    _, section = _aWorkingSection(real_series)
    before = _idsByTrace(section)
    assert before and all(before.values()), "no ids to carry"
    generation = section._columns.generation

    section.resyncColumnarStore()

    assert section._columns.generation > generation, (
        "the rebuild did not advance the generation counter, so a cache "
        "holding the old value would conclude it was current"
    )
    after = _idsByTrace(section)
    assert after == before, (
        f"a rebuild re-identified traces it had already identified: {before} "
        f"-> {after}"
    )


def test_a_clean_save_does_not_re_identify_the_traces_it_saves(real_series):
    """#278's property, driven through the series rather than a hand-built store.

    `test_section_columnar_dual_write.py` pins this against a store a test
    installed by hand, because before S1 the production default carried no ids
    at all and the assertion would have passed vacuously. S1 removed that
    caveat: every trace on a real section now has an id at load, so the same
    property is worth re-asserting on the real thing.
    """
    snum, section = _aWorkingSection(real_series)
    before = _idsByTrace(section)
    store = section._columns
    ## Not decoration: on the pre-S1 build every id is `None`, and "before ==
    ## after" over a dict of `None`s passes while proving nothing. The
    ## revert-and-fail probe found this test green against `30a0dad0` until
    ## this line was added.
    assert before and all(before.values()), (
        "the section carries no ids, so comparing them before and after a save "
        "would pass vacuously"
    )

    section.save(update_series_data=False)
    section.save(update_series_data=False)
    section.save(update_series_data=False)

    assert section._columns is store, (
        "a clean save swapped the store; the ids below may be right for the "
        "wrong reason"
    )
    assert _idsByTrace(section) == before, "a clean save re-identified traces"


def test_reloading_unchanged_content_moves_no_id(real_series):
    """`Series.loadSection` builds a fresh `Section` every call. Ids must not care.

    S1's own module pins this over the whole series; repeated here on one
    section because every later test in this module depends on it, and a
    harness whose baseline is unstable measures nothing.
    """
    snum, section = _aWorkingSection(real_series)
    first = _idsByPosition(section)
    taken = len(real_series.trace_id_issuer.taken)

    for _ in range(3):
        assert _idsByPosition(real_series.loadSection(snum)) == first, (
            "reloading an untouched section moved ids"
        )
    assert len(real_series.trace_id_issuer.taken) == taken, (
        "reloading an untouched section leaked ids into the index"
    )


def test_a_whole_series_save_and_reopen_moves_no_id(real_series, tmp_path):
    """The workload version: save every section, write the .jser, reopen, compare.

    The strongest form of "a clean save does not re-identify", and the one that
    would catch a re-identification that only shows up once the document has
    been through the writer: every id in the series, before and after a full
    save, and again after a fresh `openJser` of the file that save produced.

    Deliberately NOT marked `slow`, which was checked rather than assumed: it
    walks the fixture's 198 sections three times and costs 0.17 s, because the
    series is small in traces rather than in sections. `make fast` skipping the
    only whole-series pin in the harness would be a poor trade for that.
    """
    from PyReconstruct.modules.datatypes import Series

    before = _idsForSeries(real_series)
    assert before, "the fixture produced no traces"
    ## Same vacuity guard as the single-section save test above, for the same
    ## measured reason.
    assert all(before.values()), (
        "some trace in the series has no id, so the comparisons below would "
        "pass by comparing None to None"
    )

    for snum in sorted(real_series.sections):
        real_series.loadSection(snum).save(update_series_data=False)
    written = tmp_path / "resaved.jser"
    real_series.saveJser(save_fp=str(written))
    assert written.exists() and written.stat().st_size > 0

    assert _idsForSeries(real_series) == before, (
        "a full-series save moved ids in the open session"
    )

    reopened = Series.openJser(str(written))
    try:
        after = _idsForSeries(reopened)
    finally:
        reopened.close()
    assert after == before, (
        "reopening the saved file derived different ids. Nothing is persisted "
        "yet, so this is the two-process agreement property applied across a "
        "save: the written rows must be the rows that were read."
    )


## --------------------------------------------------------------------------
## Undo / redo -- the second contradiction
## --------------------------------------------------------------------------

def test_an_undo_re_identifies_every_trace_on_the_section(real_series):
    """DISCREPANCY, pinned as the code behaves.

    An undo does not restore the `Trace` objects the section had; it builds new
    ones, either by parsing the `.s0` baseline the `copyfile` path wrote
    (`FieldState.getContours`) or by `Contour.copy()`. `undoState` then calls
    `section.resyncColumnarStore()`, and the rebuild's only correlation between
    a trace and an id is the OUTGOING row map -- which is keyed on the objects
    the undo just discarded. Nothing matches, so every restored trace falls
    through to `issue()`.

    Two things make this worse than it first looks, and both are asserted:

    * it is not limited to the contours the undo touched. `undoState`'s
      single-undo-state branch -- a first undo, which is the case driven here
      -- replaces `section.contours` WHOLESALE, so a contour the user never
      edited is rebuilt too and its traces are re-identified along with the
      rest. The multi-state branch is narrower but not narrow: it restores
      every contour modified since `clearTracking` last ran, which accumulates
      across edits, and re-identifies all of them.
    * the superseded ids are not released, so an undo grows the series' index
      by a section's worth of orphans each time.

    Undo is not a row of the carry table -- the table names store operations,
    and an undo reaches the store only through the rebuild. That is precisely
    why it was worth driving: the rebuild carries ids correctly
    (`test_a_rebuild_carries_every_id`) and the undo still loses every one of
    them, because it destroys the correlation before the rebuild runs.
    """
    snum, section = _aWorkingSection(real_series)
    states = _sectionStates(section, real_series)
    before = _idsByPosition(section)
    taken_before = len(real_series.trace_id_issuer.taken)

    newcomer = _newTrace("harness_undo_probe")
    section.addTrace(newcomer, log_event=False)
    states.addState(section, real_series)
    assert ("harness_undo_probe", 0) in _idsByPosition(section)

    states.undoState(section, real_series)

    after = _idsByPosition(section)
    assert ("harness_undo_probe", 0) not in after, (
        "the undo did not undo the add, so the ids below mean nothing"
    )
    assert set(after) == set(before), (
        f"the undo did not restore the section's shape: {sorted(before)} -> "
        f"{sorted(after)}"
    )
    survived = {key: before[key] for key in before if after[key] == before[key]}
    assert not survived, (
        "an undo KEPT some ids. The measured behaviour at 978b4d91 is that it "
        "keeps none, because the rebuild's correlation is the outgoing row map "
        "and the undo replaced every Trace object in it. If ids now survive an "
        f"undo, this pin is the one to turn over: {survived}"
    )
    assert not (set(after.values()) & set(before.values())), (
        "an undo reissued an id a trace on this section already held"
    )
    assert len(real_series.trace_id_issuer.taken) > taken_before, (
        "the superseded ids were released rather than left spoken for"
    )


def test_a_redo_re_identifies_the_contours_it_restores(real_series):
    """The redo half, same cause, measurably narrower scope. DISCREPANCY.

    `redoState` restores contours out of a `FieldState` -- `Contour.copy()`, so
    again fresh `Trace` objects -- and calls the same rebuild. It differs from
    `undoState` in what it replaces: only the contours the redo state carries,
    not the whole dict. That difference is visible in the ids and is asserted
    both ways here, because "a redo re-identifies everything" would be an
    overstatement and "a redo is harmless" would be a much worse one:

    * every trace in a RESTORED contour is re-identified;
    * every trace in an untouched contour keeps the id it held after the undo,
      carried by the rebuild -- which is the same rebuild
      `test_a_rebuild_carries_every_id` covers, doing its job on the traces
      whose objects survived;
    * no id from before the undo is recovered by anything. An undo/redo round
      trip is not an identity round trip: it burns two generations of ids and
      lands on a third.
    """
    snum, section = _aWorkingSection(real_series)
    states = _sectionStates(section, real_series)
    before = _idsByPosition(section)

    edited = _aCrowdedContour(section)
    untouched_names = [
        name for name in sorted(section.contours, key=str) if name != edited
    ]
    assert untouched_names, "no second contour, so the carry half is vacuous"

    section.editTraceAttributes(
        [section.contours[edited].getTraces()[0]],
        name=None, color=(11, 22, 33), tags=None, mode=None, log_event=False,
    )
    states.addState(section, real_series)

    states.undoState(section, real_series)
    after_undo = _idsByPosition(section)

    states.redoState(section, real_series)
    after_redo = _idsByPosition(section)

    restored_keys = [key for key in after_redo if key[0] == edited]
    assert restored_keys, "the redo left the edited contour empty"
    kept = {
        key: after_undo[key]
        for key in restored_keys
        if key in after_undo and after_redo[key] == after_undo[key]
    }
    assert not kept, (
        "a redo kept an id in the contour it restored. The measured behaviour "
        "at 978b4d91 is that it keeps none there, because the restore hands "
        f"the rebuild Trace objects it has never seen: {kept}"
    )

    carried = {
        key: (after_undo.get(key), after_redo[key])
        for key in after_redo
        if key[0] != edited
    }
    assert carried, "no untouched contour survived, so the carry half is vacuous"
    assert all(pair[0] == pair[1] for pair in carried.values()), (
        "a redo moved an id in a contour it did not restore. THAT would be a "
        f"defect in the rebuild's carry rather than in the redo: {carried}"
    )

    assert not (set(after_redo.values()) & set(before.values())), (
        "an undo/redo round trip recovered a pre-undo id. If ids now survive "
        "the round trip this pin is the one to turn over -- together with the "
        "undo test above."
    )


## --------------------------------------------------------------------------
## Track A's two inherent movements -- the red tests S3+ flips
## --------------------------------------------------------------------------

def test_an_edit_then_save_then_reload_moves_only_the_edited_traces_id(
    real_series,
):
    """KNOWN AND INTENDED for Track A. The pin S3 turns over.

    Nothing is persisted yet, so an id is a pure function of the row's stored
    content, and a pure function of content moves when the content moves.
    `trace_id.py`'s module docstring records the reasoning and the rejected
    alternative (keying the derivation record on position would survive an
    in-place edit and mass-reassign every id after an insert or delete, which
    is worse). Review 297 recorded the same measurement as
    `pr297-edit-moves-derived-id-undisclosed`.

    Three halves, all asserted, because the useful statement is not "an id
    moved" but "exactly the edited trace's id moved":

    * the edited trace's id is new;
    * every neighbour's id is unchanged;
    * the superseded id is orphaned -- still in `taken`, held by no live trace.

    Compared by id SET and not by position: the edit is a remove/add round trip,
    so the edited trace is appended at the end of its contour and the positions
    shift underneath it. That reordering is not an identity event and asserting
    on positions here would report it as one.
    """
    snum, section = _aWorkingSection(real_series)
    ## A contour with a neighbour, so "the neighbours kept theirs" is not
    ## vacuous. Fall back to any contour if the fixture has none.
    cname = next(
        (
            name for name in sorted(section.contours, key=str)
            if len(section.contours[name].getTraces()) >= 2
        ),
        sorted(section.contours, key=str)[0],
    )
    contour_before = [
        section._columns.getID(section._column_rows[trace])
        for trace in section.contours[cname].getTraces()
    ]
    series_before = _idsByPosition(section)

    victim = section.contours[cname].getTraces()[0]
    victim_id = section._columns.getID(section._column_rows[victim])
    section.removeTrace(victim, log_event=False)
    victim.points = [(x + 1.0, y) for x, y in victim.points]
    section.addTrace(victim, log_event=False)
    section.save(update_series_data=False)

    reloaded = real_series.loadSection(snum)
    contour_after = [
        reloaded._columns.getID(reloaded._column_rows[trace])
        for trace in reloaded.contours[cname].getTraces()
    ]

    assert len(contour_after) == len(contour_before)
    assert victim_id not in contour_after, (
        "the edited trace kept its id across a save and a reload. Under Track "
        "A that cannot happen -- nothing persists the id and the content it is "
        "derived from has changed -- so either an id is now persisted (S3+ has "
        "landed and this test is the one to turn over) or the edit did not "
        "reach the file."
    )
    neighbours_before = set(contour_before) - {victim_id}
    assert neighbours_before <= set(contour_after), (
        "editing one trace moved a neighbour's id as well. THAT would be a "
        f"defect rather than Track A's shape: {contour_before} -> "
        f"{contour_after}"
    )
    assert victim_id in real_series.trace_id_issuer.taken, (
        "the superseded id was released; trace_id.py's policy is that an id "
        "once handed out stays spoken for"
    )
    live = set(_idsByPosition(reloaded).values())
    assert victim_id not in live, (
        "the superseded id is still held by a live trace, so it is not "
        "orphaned and the description above is wrong"
    )
    ## Contours the edit never touched are untouched, including their positions.
    untouched = {
        key: value for key, value in series_before.items() if key[0] != cname
    }
    now = _idsByPosition(reloaded)
    assert {key: now.get(key) for key in untouched} == untouched, (
        "editing one contour moved ids in another contour on the same section"
    )


def test_an_id_issued_in_session_does_not_survive_a_save_and_reload(real_series):
    """KNOWN AND INTENDED for Track A. The second pin S3 turns over.

    A trace created during a session is handed an opaque RANDOM id, because
    identity has to survive an edit and a content hash does not
    (`trace_id.py`'s "two schemes" section). Nothing writes that id to the
    section file, so the reload finds a row it has never seen and DERIVES one
    from its content -- a different id, and the issued one is orphaned.

    This is the mirror image of the edit case and the same cause: within Track
    A, the only thing that crosses a save is the row's content. Both stop being
    true the moment a keyed row carries the id, which is why both are here.
    """
    snum, section = _aWorkingSection(real_series)
    newcomer = _newTrace("harness_persistence_probe")
    section.addTrace(newcomer, log_event=False)
    issued = section._columns.getID(section._column_rows[newcomer])
    assert issued is not None

    section.save(update_series_data=False)
    reloaded = real_series.loadSection(snum)
    derived = _idsByPosition(reloaded)[("harness_persistence_probe", 0)]

    assert derived is not None and len(derived) == TRACE_ID_LENGTH
    assert derived != issued, (
        "an id issued during the session survived a save and a reload. Under "
        "Track A nothing persists it, so this can only mean the writer now "
        "carries the id (S5) -- turn this pin over."
    )
    assert issued in real_series.trace_id_issuer.taken, (
        "the issued id was released when the reload replaced it"
    )


def test_deleting_one_of_two_identical_rows_transfers_the_survivors_id(
    real_series,
):
    """`pr297-duplicate-row-id-transfer`, reproduced through the entry points.

    Review 297 traced this by hand through `deriveForSection`'s occurrence
    counter and recorded it as informational, with the note that S2 should list
    it so the harness "does not report it as a surprise". It is reproduced here
    instead of listed, because it turned out to be reachable end to end: add a
    byte-identical twin, save, reload (the twin now holds the second recorded
    id), delete the FIRST of the pair, save, reload -- and the survivor is
    handed the FIRST id while its own is orphaned.

    No duplicate is ever minted, which is the property that keeps this
    informational rather than a defect: within one `deriveForSection` call the
    occurrence counter strictly increments per key, so two live rows can never
    draw the same list position. Asserted below.

    Inherent to any content-derived scheme over genuinely indistinguishable
    rows, and not fixable inside Track A: the two rows are the same bytes, so
    the derivation has nothing to tell them apart with except the order they
    appear in. A persisted id is what distinguishes them, which puts this on
    the same list as the two tests above.
    """
    snum, section = _aWorkingSection(real_series)
    cname = sorted(section.contours, key=str)[0]
    original = section.contours[cname].getTraces()[0]

    section.addTrace(original.copy(), log_event=False)
    section.save(update_series_data=False)

    section = real_series.loadSection(snum)
    pair = [
        section._columns.getID(section._column_rows[trace])
        for trace in section.contours[cname].getTraces()
    ]
    assert len(pair) >= 2, "the twin did not survive the save"
    first_id, second_id = pair[0], pair[1]
    assert first_id != second_id, (
        "two byte-identical rows were handed one id -- that WOULD be a defect, "
        "and the occurrence counter is what prevents it"
    )

    section.removeTrace(section.contours[cname].getTraces()[0], log_event=False)
    section.save(update_series_data=False)

    section = real_series.loadSection(snum)
    survivors = [
        section._columns.getID(section._column_rows[trace])
        for trace in section.contours[cname].getTraces()
    ]
    assert len(survivors) == len(pair) - 1
    assert survivors[0] == first_id, (
        "the survivor did not receive the deleted row's id. That would mean "
        "the derivation now distinguishes two byte-identical rows by something "
        f"other than occurrence order: expected {first_id}, got {survivors[0]}"
    )
    assert second_id in real_series.trace_id_issuer.taken, (
        "the transferred-away id was released instead of orphaned"
    )
    assert second_id not in set(_idsByPosition(section).values()), (
        "the id the survivor used to hold is still live somewhere, so nothing "
        "was transferred and this test is measuring the wrong thing"
    )


## --------------------------------------------------------------------------
## The reserved rows -- facts only, no semantics
## --------------------------------------------------------------------------

def test_palette_traces_never_reach_a_store(real_series):
    """The mechanical half of "palette traces are unexercised". Not a semantic.

    Spec Q3 is whether palette traces should have ids, and it is the
    maintainer's. What can be stated without answering it is where they live:
    `Series.palette_traces` is a dict of plain `Trace` lists hanging off the
    `Series`, never appended to a `SectionColumns`, so there is no id today and
    no row to read one off. That is a fact about the object graph and it is
    what makes "unexercised" the honest verdict rather than an omission.

    If palette traces ever do reach a store, this goes red and Q3 has been
    answered by whoever wired it -- which is exactly the notification the
    reserved rows deserve.
    """
    palettes = real_series.palette_traces
    assert palettes, "the fixture series has no palette traces"

    from PyReconstruct.modules.datatypes import Trace

    for palette_name, traces in palettes.items():
        assert traces, f"palette {palette_name!r} is empty"
        for trace in traces:
            assert isinstance(trace, Trace)

    ## Not one of them is in any loaded section's row map.
    palette_objects = {
        id(trace) for traces in palettes.values() for trace in traces
    }
    for snum in sorted(real_series.sections)[:5]:
        section = real_series.loadSection(snum)
        mapped = {id(trace) for trace in section._column_rows}
        assert not (mapped & palette_objects), (
            f"a palette trace has a store row on section {snum}; Q3 has been "
            "answered by wiring rather than by decision"
        )
