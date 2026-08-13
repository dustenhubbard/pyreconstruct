"""The dual write from `Section` into the columnar store.

Slice 3 of the Phase 1 rewiring. Every `Section` carries a `SectionColumns`
beside its `self.contours`, mirrors every mutation into it, and checks the two
against each other. Nothing reads the store yet; this exists so that the store
is driven by real code on real data before one call site is flipped to read
from it.

WHAT CHANGED ON 2026-08-05, AND WHAT THIS FILE NOW HAS TO PROVE
---------------------------------------------------------------
This landed as a **test-only** harness behind `PYRECON_TEST_ONLY_COLUMNAR_DUAL_
WRITE`, and half of this file existed to prove the gate was unreachable from a
real launch. That property was deliberately removed: with the store built only
under the gate, `Section._columns` was `None` forever in production and there
was nothing for a consumer to read at all. The store is now built in every
session.

So the invisibility tests are **not deleted, and not left asserting something
that is now false**. Each one is replaced by the property that took its place:

  * "no shipped file may name the gate" became **the gate does not exist**, in
    any file, and no environment variable decides whether the store is built
    (`test_no_environment_variable_anywhere_decides_whether_the_store_exists`,
    `test_section_py_neither_reads_nor_writes_the_environment`). The same
    repository-wide deny-list walk is kept; only the question it asks changed.
  * "a section without the gate carries no store" became **every section
    carries a store**, whatever the environment says
    (`test_every_section_carries_a_store_whatever_the_environment_says`).
  * "mutating an ungated section stays storeless" became **mutating a section
    keeps the store in step** (`test_mutating_a_section_keeps_the_store_in_
    step`).
  * "nothing outside `Section` knows the harness exists" became **nothing
    outside `Section` writes to the store**, with the three modules that call
    the public *repair* enumerated by name so a fourth is a visible act
    (`test_only_section_py_writes_the_store_and_the_repair_sites_are_pinned`).

What did NOT change is the property the object model still has: **it is still
authoritative.** Nothing here reads a value out of the store to answer a
question, `getDict`/`save` serialize `self.contours`, and the store is a shadow
copy that is written and checked. `test_the_object_model_is_still_authoritative`
pins that directly.

THE CHECK'S SCOPE NARROWED IN TWO PLACES, ON PURPOSE, AND BOTH ARE TESTED
--------------------------------------------------------------------------
Under the gate the whole-section comparison ran after every mutation AND at
every build. Always-on made both impossible -- measured on `autoseg745`, a
whole-section comparison is ~81 ms on the median section and ~127 ms on the
busiest against a 0.002 ms `addTrace`, and a store is built at every section
load. So:

  * the per-mutation check is targeted at the row that moved
    (`test_a_mutation_does_not_materialize_the_whole_section`),
  * the build checks row arity and not values
    (`test_building_a_store_does_not_run_the_whole_section_comparison`,
    `test_building_a_store_still_checks_the_row_arity`),
  * the whole-section comparison runs at `save()`
    (`test_the_whole_section_check_runs_on_save`).

Both narrowings are asserted rather than described, so restoring the old scope
turns those tests red and reopens the cost question with a reviewer present.
What did NOT narrow is what the comparison compares: the `test_a_dropped_*`
family still drives real `Section` methods with a store entry point silently
broken and still requires the raise, and
`test_addTrace_alone_no_longer_detects_a_stale_row_map` pins the one detection
that was genuinely lost.

**That the consistency check actually catches divergence.** A safety net that is
written and trusted is worth nothing; a safety net that has been fired at is
worth what it caught. So every field the check compares gets deliberately
corrupted in the store and the check is required to notice
(`test_a_corrupted_*`), and four of the five store mutation entry points get
deliberately broken -- silently dropped, or dropped in one column only -- while a
real `Section` method drives a real mutation through them, and the assertion is
required to fire (`test_a_dropped_*`, `test_an_appendRow_that_loses_only_the_tags_
is_still_caught`). Those tests fail if the check is weakened, which is the
property that makes the rest of this file mean something.

WHAT THE FIXTURE SERIES CAN AND CANNOT EXERCISE
-----------------------------------------------
Same split `test_columnar_store_parity.py` documents: the real checked-in series
has no tagged, negative or hidden trace and no coordinate needing more than 7
decimal places, so the synthetic `tests/fixtures/parity_series.jser` carries
those domains and the tag/negative/hidden assertions run against it.
"""
import ast
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes import section as section_module
from PyReconstruct.modules.datatypes.columnar_store import SectionColumns
from PyReconstruct.modules.datatypes.section import ColumnarDualWriteMismatch


## The environment variable that used to gate this. Kept as a literal, and only
## here, because two tests below assert it appears nowhere else: a gate that was
## removed by deleting its `if` and left named in a launcher is a gate somebody
## rewires.
RETIRED_GATE = "PYRECON_TEST_ONLY_COLUMNAR_DUAL_WRITE"

SECTION_SOURCE = Path(section_module.__file__).resolve()
## `Trace`'s source, parsed rather than introspected: the set of methods that
## mutate a store-backed column is derived from it (see `_traceColumnSetters`),
## and a source walk sees `self.points[i] = ...` where `inspect` would only see
## a function object.
TRACE_SOURCE = SECTION_SOURCE.parent / "trace.py"
PACKAGE_ROOT = SECTION_SOURCE.parents[2]
REPO_ROOT = PACKAGE_ROOT.parent

SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"


# --- fixtures ----------------------------------------------------------------

def _busiest(sections):
    populated = [s for s in sections if s.contours]
    assert populated, "the fixture series has no populated section"
    return max(populated, key=lambda s: len(s.tracesAsList()))


@pytest.fixture
def real_section(real_series):
    """The busiest section of the real fixture series.

    No gate fixture any more, and that absence is the point: a section loaded by
    ordinary means has a store.
    """
    section = _busiest(
        [real_series.loadSection(n) for n in sorted(real_series.sections)]
    )
    assert section._columns is not None
    return section


@pytest.fixture
def synthetic_series(tmp_path):
    """The synthetic series, opened from a copy.

    A copy for the same reason the parity suite copies: `Series.openJser` builds
    a hidden working directory beside the file it is handed.
    """
    from PyReconstruct.modules.datatypes import Series

    destination = tmp_path / "parity_series.jser"
    shutil.copy(SYNTHETIC_FIXTURE, destination)
    series = Series.openJser(str(destination))
    yield series
    series.close()


@pytest.fixture
def synthetic_section(synthetic_series):
    """The busiest section of the synthetic series."""
    section = _busiest(
        [synthetic_series.loadSection(n) for n in sorted(synthetic_series.sections)]
    )
    assert section._columns is not None
    return section


def _aTrace(section, name="dual_write_probe", points=None):
    """A plausible trace, drawn near an existing one so it is in range."""
    trace = Trace(name, (11, 22, 33), closed=True)
    trace.points = points if points is not None else [
        (0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)
    ]
    return trace


def _anyTrace(section):
    """One real trace off the section, deterministically chosen."""
    name = sorted(section.contours, key=str)[0]
    return section.contours[name][0]


# =============================================================================
# The safety properties that replaced invisibility
# =============================================================================

def test_every_section_carries_a_store_whatever_the_environment_says(
    real_series, monkeypatch
):
    """The decision, at the object, and the thing Track C needs to be true.

    Replaces `test_a_section_loaded_without_the_gate_carries_no_store`, whose
    assertion is now false by design. Every value the retired gate could have
    held -- unset, "0", "1", nonsense -- produces the same section, because
    nothing reads it any more.
    """
    snum = sorted(real_series.sections)[0]

    for value in (None, "0", "", "1", "true", "2"):
        if value is None:
            monkeypatch.delenv(RETIRED_GATE, raising=False)
        else:
            monkeypatch.setenv(RETIRED_GATE, value)

        section = real_series.loadSection(snum)
        assert section._columns is not None, (
            f"no store with {RETIRED_GATE}={value!r}; the environment must not "
            "decide this any more"
        )
        assert len(section._columns) == len(section.tracesAsList())
        assert set(map(id, section._column_rows)) == {
            id(t) for t in section.tracesAsList()
        }


def test_mutating_a_section_keeps_the_store_in_step(real_series):
    """The runtime half, driving the same mutations the old ungated test drove.

    Replaces `test_mutating_an_ungated_section_stays_storeless`. Same sequence,
    opposite expectation: every hook does real work now, and the two
    representations agree at the end of it.
    """
    section = _busiest(
        [real_series.loadSection(n) for n in sorted(real_series.sections)]
    )
    trace = _aTrace(section)
    section.addTrace(trace)
    section.closeTraces([trace], closed=False)
    section.hideTraces([trace], hide=True)
    section.translateTraces(0.1, 0.1)
    section.setMag(section.mag * 2)
    section.removeTrace(trace)

    section._assertColumnsMatchObjectModel("the whole mutation sequence")
    assert len(section._columns) == len(section.tracesAsList())
    assert section_module.Section._column_rows == {}, (
        "the class-level default row map was written to"
    )


def test_the_object_model_is_still_authoritative(real_section):
    """The property that did NOT change, pinned so it cannot erode quietly.

    Always-on removed invisibility. It did not make the store a source of truth:
    `self.contours` still owns every value, and `getDict` -- what `save` writes
    -- is built from the object model alone. Corrupt the store and the section
    still serializes correctly, because nothing reads the store to answer a
    question.
    """
    trace = _anyTrace(real_section)
    row = real_section._column_rows[trace]
    expected = real_section.getDict()

    _corruptName(real_section._columns, row)
    _corruptColor(real_section._columns, row)

    assert real_section.getDict() == expected, (
        "getDict changed when only the store was corrupted, so something is "
        "reading the store as if it were authoritative"
    )
    ## And the divergence is still loud when the section is asked to check.
    with pytest.raises(ColumnarDualWriteMismatch):
        real_section._assertColumnsMatchObjectModel("a corrupted shadow copy")


def test_a_section_that_never_ran_its_constructor_is_unaffected():
    """`Section.__new__` with a handful of hand-set attributes, still working.

    A dozen test modules in this suite drive one `Section` method against a bare
    `Section.__new__` instance carrying only the attributes that method touches,
    deliberately, so the method is tested without a series, a file or a
    filesystem. `__init__` never runs on those, so a hook that reached for an
    attribute `__init__` sets would break all of them -- which is what happened
    on the first draft of this change, and is why `_columns` and `_column_rows`
    are class-level defaults as well as instance ones.

    KEPT UNCHANGED except for dropping the gate it used to set. It matters more
    now than it did: `_columns is None` used to be the shipped state and is now
    the ONLY remaining one, so this is the whole of what still has to tolerate
    it.
    """
    bare = section_module.Section.__new__(section_module.Section)
    bare.n = 1
    bare.contours = {}
    bare.added_traces = []
    bare.removed_traces = []

    trace = _aTrace(None)
    bare.addTrace(trace, log_event=False)
    bare.removeTrace(trace, log_event=False)

    assert bare._columns is None
    assert bare.added_traces == [trace]
    assert bare.removed_traces == [trace]
    assert section_module.Section._column_rows == {}


## Files allowed to name the retired gate: the tests and changelog that record
## that it was removed. Anything else is a live reference to a gate that no
## longer exists.
def _mentionsAllowed(path : Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    if relative.parts[0] in ("tests", "changelog.d", "CHANGELOG.md"):
        return True
    return False


def test_no_environment_variable_anywhere_decides_whether_the_store_exists():
    """The successor to the invisibility scan, asking the inverted question.

    This test used to prove the gate's name appeared in exactly one shipped
    file, so that no launcher could turn the harness on. The gate is gone, so
    the property worth protecting inverted with it: **the name must appear in NO
    shipped file at all**. A gate removed by deleting its `if` and left named in
    a launcher, a workflow or a settings module is a gate somebody rewires, and
    the failure mode of a half-removed gate is worse than the gate -- a store
    that exists on one machine and not another, with a consumer reading it.

    The scan machinery is kept exactly as it was, because it was hardened for a
    reason and the reason still applies; only the assertion changed.

    THE SELECTION IS A DENY-LIST, AND THAT IS THE POINT
    ---------------------------------------------------
    This test used to select files by an allow-list of fifteen "text file types
    we thought of". That list silently omitted `.command` -- the three macOS
    launchers under `launch/mac/`, including the one a user double-clicks to run
    PyReconstruct -- along with `.iss` (the Inno Setup installer script), `.in`
    (`packaging/linux/pyreconstruct.desktop.in`, the desktop-entry template the
    Linux installer expands), `.org` and every extensionless file (`Makefile`,
    `dev/Makefile`, thirteen `dev/scripts/*`). It also listed `.desktop`, which
    matches no file in this repository at all. So the detector was blind on
    precisely the shipped launch surface it exists to protect, and an allow-list
    goes blind again the moment somebody adds a file type nobody enumerated.

    Inverted, the failure mode reverses: a new file type is covered by default,
    and the only way to lose coverage is to add a suffix to `binary_suffixes`
    below -- a visible, reviewable act. Nothing here is skipped for being
    "probably fine"; the deny-list names formats that cannot hold a readable
    environment-variable export, and anything that fails to decode as UTF-8 is
    skipped by the decoder, not by a guess about its name.
    """
    ## Formats that cannot carry a shell-readable export. Everything else --
    ## `.command`, `.iss`, `.in`, `.org`, `.jser`, `.lock`, `.svg`, `.csv`, and
    ## every extensionless script -- is read.
    binary_suffixes = {
        ".png", ".ico", ".cur", ".icns", ".tif", ".tiff", ".jpg", ".jpeg",
        ".gif", ".bmp", ".webp", ".pdf",
        ".zip", ".gz", ".bz2", ".xz", ".zst", ".7z", ".tar", ".whl",
        ".pyc", ".pyo", ".pyd", ".so", ".dylib", ".dll", ".exe", ".o", ".a",
        ".ttf", ".otf", ".woff", ".woff2",
        ".npy", ".npz", ".h5", ".hdf5", ".mp4", ".mov",
    }
    ## Any hidden directory except `.github`, plus the two build/vendor trees.
    ## `.github` is deliberately NOT skipped: a CI workflow exporting the gate
    ## into a job is one of the ways a half-removed gate comes back.
    skip_dirs = {"__pycache__", "node_modules", "build", "dist"}

    def skipped(relative) -> bool:
        ## Directory components only. Checking the filename too would skip every
        ## dotfile -- `.gitignore`, and any `.envrc`/`.profile` somebody drops
        ## next to a launcher, which is exactly the shape of the leak this test
        ## is looking for.
        return any(
            part in skip_dirs or (part.startswith(".") and part != ".github")
            for part in relative.parts[:-1]
        )

    offenders = []
    scanned = 0
    for path in REPO_ROOT.rglob("*"):
        relative = path.relative_to(REPO_ROOT)
        if skipped(relative):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in binary_suffixes:
            continue
        if _mentionsAllowed(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError, ValueError):
            continue
        scanned += 1
        if RETIRED_GATE in text:
            offenders.append(str(relative))

    ## A selection bug that silently emptied the walk would otherwise leave this
    ## test passing vacuously, which is the failure mode that produced the
    ## allow-list hole in the first place. The repository ships far more than
    ## 200 readable files; this only has to be large enough to notice a walk
    ## that collapsed.
    assert scanned > 200, (
        f"the repository walk read only {scanned} files, so this test is not "
        "checking what it claims to check"
    )
    for launcher in (
        "launch/mac/run.command",
        "launch/windows/run.bat",
        "launch/linux/run.sh",
        "packaging/windows/PyReconstruct.iss",
        "packaging/linux/pyreconstruct.desktop.in",
    ):
        assert (REPO_ROOT / launcher).is_file(), (
            f"{launcher} moved; confirm the walk above still reaches the real "
            "launch surface before editing this list"
        )

    assert offenders == [], (
        "the retired dual-write gate is still named in a shipped file, so the "
        "removal is half done and somebody can rewire it: "
        f"{offenders}"
    )


def test_section_py_neither_reads_nor_writes_the_environment():
    """`section.py` has no environment dependency left at all.

    This used to prove only that the module could not *write* the gate. It now
    proves the stronger thing the removal is supposed to have achieved: the
    module does not consult the environment either, so there is no value any
    launcher, profile or CI job can set that changes whether a section carries a
    store. `os` is still imported and still used for paths; only `os.environ`
    and the `getenv`/`putenv` family are banned.
    """
    tree = ast.parse(SECTION_SOURCE.read_text(encoding="utf-8"))

    reaches = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "environ":
            reaches.append("os.environ")
        if isinstance(node, ast.Name) and node.id == "environ":
            reaches.append("bare environ")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("getenv", "putenv", "unsetenv"):
                reaches.append(node.func.attr)

    assert reaches == [], (
        f"section.py still consults or edits the environment: {reaches}"
    )


## The modules allowed to call `resyncColumnarStore`, and what each is
## repairing. Enumerated rather than counted so that adding a fifth is a
## visible edit to this list with a reviewer looking at it. Every one of these
## edits a section's traces or contours WITHOUT going through a `Section`
## mutator, so no dual-write hook sees it -- and every one of them was a
## `ColumnarDualWriteMismatch` raised in a real session before it called the
## repair. There are TWELVE sites across the four modules -- eleven rows below,
## and the `state_manager.py` row carries two:
##
##   state_manager.py         undoState, redoState        whole-dict / per-key rebind
##   series.py                deleteObjects               contour key deleted
##   series.py                hideObjects                 trace.setHidden in place
##   series.py                hideAllTraces               trace.setHidden in place
##   series.py                restoreObjectVisibility     trace.setHidden in place
##   series.py                smoothObject                trace.smooth in place
##   series.py                deleteDuplicateTraces       trace.mergeTags in place
##   conversions.py           seriesToLabels group delete contour keys deleted
##   field_widget_2_trace.py  findFlag import-conflict    trace.hidden in place
##   field_widget_2_trace.py  smoothTraces                trace.smooth in place
##   field_widget_2_trace.py  cutTrace tag merge          trace.tags.add in place
##
## READ THE COUNT ABOVE AS A WARNING, NOT AS A RESULT. It has been "five, six,
## seven" (the original PR), then "eight" (a reviewer read `findFlag`), then
## "nine and ten" (a reviewer read `smoothObject` and `deleteDuplicateTraces` --
## AFTER the static scan below had been built specifically to make that
## impossible), and now twelve (`smoothTraces` and `cutTrace`, found by widening
## the scan three ways at once). Four consecutive "complete" sets have been
## wrong. Nothing about the number twelve is more trustworthy than eight was; what
## has changed is that the scan below now derives its inputs instead of
## enumerating them, so the next one has fewer places to hide.
##
## **D11 LANDED AND THIS LIST STAYS. WHY.** D11 replaced `save()`'s consistency
## COMPARISON with a REBUILD, which was argued for -- correctly -- on the
## grounds that the count above kept being wrong. It removes the consequence
## that made a missed site severe: a thirteenth one can no longer leave a
## section unsaveable, and can no longer abort a multi-section operation
## partway through. It does not remove the sites, and it does not remove the
## need for the repair calls, because rebuilding at `save()` does nothing for
## the window between the edit and the next save -- which is where these bit,
## since a user edits before they save. `test_an_unrepaired_out_of_class_edit_
## still_raises_before_the_next_save` is the evidence for that rather than a
## paragraph asserting it, and it is what a future round should re-read before
## concluding that this list has become decoration.
##
## This allow-list pins which modules may call the REPAIR; it cannot enumerate
## which modules perform an out-of-class EDIT, and the edit is the thing that
## goes wrong.
REPAIR_SITES = {
    "modules/backend/func/state_manager.py": "undoState / redoState",
    "modules/datatypes/series.py": (
        "deleteObjects / hideObjects / hideAllTraces / "
        "restoreObjectVisibility / smoothObject / deleteDuplicateTraces"
    ),
    "modules/backend/autoseg/conversions.py": "seriesToLabels group deletion",
    "modules/gui/main/field_widget_2_trace.py": (
        "findFlag's import-conflict hide / smoothTraces / cutTrace's tag merge"
    ),
}


def test_only_section_py_writes_the_store_and_the_repair_sites_are_pinned():
    """`Section` still owns every write to the store. The repair is public.

    Replaces `test_nothing_outside_section_py_knows_the_harness_exists`, whose
    assertion is now false: three modules legitimately name
    `resyncColumnarStore`, because always-on made their out-of-class trace and
    contour edits into crashes that only a rebuild can fix.

    What survives, and is the property that actually protects the design, is
    narrower and sharper than "nobody has heard of it": **nothing outside
    `section.py` performs a store write.** No module calls a `_dualWrite` hook,
    reaches into `_column_rows`, or drives `SectionColumns`' six mutation entry
    points against a section's store. The single exception is
    `resyncColumnarStore`, the public repair, and it is allowed only at the
    sites named in `REPAIR_SITES`.

    `self._columns` is deliberately not scanned. It collided with an unrelated
    `TraceView._columns` (`columnar_store.py`, Phase 1 slices 4/6) the first
    time both landed on the same tree: the name is common enough that two
    independent classes picked it for unrelated fields.
    """
    ## Scanned through the AST rather than by substring, which is the difference
    ## between "this file references the name" and "this file mentions the name
    ## in a comment saying why it calls the repair". The repair sites explain
    ## themselves in prose, and prose is not a call.
    private_names = ("_column_rows", "ColumnarDualWriteMismatch")

    def identifiers(tree):
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
        return found

    private_offenders = {}
    repair_callers = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.resolve() == SECTION_SOURCE:
            continue
        relative = str(path.relative_to(PACKAGE_ROOT))
        names = identifiers(ast.parse(path.read_text(encoding="utf-8")))

        hits = sorted(
            name for name in names
            if name in private_names or name.startswith("_dualWrite")
        )
        if hits:
            private_offenders[relative] = hits

        if "resyncColumnarStore" in names:
            repair_callers[relative] = True

    assert private_offenders == {}, (
        "the dual write's private surface leaked out of Section: "
        f"{private_offenders}"
    )
    assert set(repair_callers) == set(REPAIR_SITES), (
        "the set of out-of-class sites calling resyncColumnarStore() changed. "
        "Every one of these replaces Section.contours from outside Section and "
        "is a ColumnarDualWriteMismatch in a real session without the repair, "
        f"so adding or losing one is a design change: {sorted(repair_callers)} "
        f"against {sorted(REPAIR_SITES)}"
    )


# =============================================================================
# The EDIT class, scanned rather than enumerated
# =============================================================================
#
# `REPAIR_SITES` above pins which modules may call the repair. That is not the
# same property and it never was: it says nothing about which modules perform an
# out-of-class EDIT, and the edit is the thing that breaks. The only mechanism
# that had ever found such a site was a test happening to exercise it at
# runtime, which is why the "complete set" claim has now been wrong twice --
# seven when the store went always-on, then eight when a reviewer read
# `findFlag`. Both times the missing site was reachable by an ordinary user
# click and both times it would have raised in that user's session.
#
# So the class gets a static scan, which is what turns "the ones the suite
# happened to reach" into a property that holds over code nothing executes.

## The eight columns the store mirrors, and therefore the eight attributes
## `_assertColumnsMatchObjectModel` compares. A write to any of them on a trace
## the section already holds is invisible to every dual-write hook.
STORE_BACKED_COLUMNS = (
    "closed", "color", "fill_mode", "hidden", "name", "negative", "points",
    "tags",
)

## `Trace`'s own mutating methods: the same eight columns reached through a call
## instead of an assignment, and `hideObjects` and its two siblings are exactly
## this shape.
##
## DERIVED FROM `trace.py` BY AST, NOT HAND-LISTED. The hand-written version of
## this tuple named two of the nine, and that single fact is what let
## `Series.smoothObject` (`Trace.smooth`) and `Series.deleteDuplicateTraces`
## (`Trace.mergeTags`) walk straight through the scan built to make exactly that
## impossible. A hand-maintained list of mutators is the same "we enumerated it
## and believe we are done" claim that has now been wrong three review rounds
## running; deriving it means a new `Trace` mutator widens the scan on the commit
## that adds it, instead of silently widening the hole.
##
## `_traceColumnSetters` is the derivation; `TRACE_COLUMN_SETTERS_EXPECTED`
## below pins its result so that a change to `Trace` is a visible, reviewed edit
## rather than a silent one. Note the difference in failure direction: if the
## derivation and the pin disagree, the *scan* has already widened (fail-safe)
## and only the pin complains.


def _mutatingSubcalls():
    """Container methods that mutate the receiver in place.

    `self.points.append(...)` and `self.tags.add(...)` write a store-backed
    column just as surely as `self.points = ...` does, and `Trace.add` and
    `Trace.addTag` are respectively those two calls and nothing else.
    """
    return (
        "append", "extend", "insert", "pop", "remove", "clear", "sort",
        "reverse", "add", "update", "discard", "difference_update",
        "intersection_update", "symmetric_difference_update",
    )


def _traceColumnSetters():
    """Every `Trace` method that mutates one of the eight store-backed columns.

    Walks `Trace`'s body and reports a method when it, or anything it calls on
    `self`, writes a store-backed column by any of the four routes a Python
    method has:

      1. `self.<column> = ...`          -- setHidden, mergeTags, centerAtOrigin,
                                          resize, reshape, smooth
      2. `self.<column>[i] = ...`       -- magScale, and ONLY magScale. This is
                                          the route a plain `ast.Attribute`
                                          target test misses, because the
                                          assignment target is an `ast.Subscript`
                                          whose `.value` is the attribute. A
                                          reviewer enumerating `Trace` by hand
                                          missed `magScale` for precisely this
                                          reason and recorded it as "not a
                                          mutator"; it is one.
      3. `self.<column>.<mutator>()`    -- add (points.append), addTag (tags.add)
      4. calling another such method on `self` -- transitive, so a future thin
                                          wrapper cannot launder a mutation

    Excluded, each for a stated reason rather than by omission:

      * `__init__` and other dunders. A `Trace` under construction is not in any
        section, so there is no store to drift; and `Section` builds its rows
        from the finished object. Naming `__init__` here would add no coverage
        and would flag every explicit `.__init__(...)` chain-up in the codebase.
      * `name`, the property setter. `trace.name = value` routes through it, but
        that is an *assignment* at the call site, and the assignment arm of
        `_storeBackedColumnWrites` already catches it by attribute name. Listing
        the setter as a method name would instead make every `.name(...)` call
        anywhere -- on any object at all -- look like a trace mutation.
    """
    tree = ast.parse(TRACE_SOURCE.read_text(encoding="utf-8"))
    trace_class = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "Trace"
    )

    subcalls = _mutatingSubcalls()
    direct = set()
    self_calls = {}

    def selfColumn(node):
        """`self.<store-backed column>` as the column name, else None."""
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and node.attr in STORE_BACKED_COLUMNS
        ):
            return node.attr
        return None

    def targets(node):
        """Assignment targets, flattened through tuple/list unpacking."""
        if isinstance(node, ast.Assign):
            pending = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            pending = [node.target]
        else:
            return
        while pending:
            target = pending.pop()
            if isinstance(target, (ast.Tuple, ast.List)):
                pending.extend(target.elts)
            else:
                yield target

    for method in trace_class.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if method.name.startswith("__"):
            continue
        ## Properties and their setters: see the docstring.
        decorators = {ast.unparse(d) for d in method.decorator_list}
        if "property" in decorators or any(
            d.endswith(".setter") for d in decorators
        ):
            continue

        called = set()
        for node in ast.walk(method):
            for target in targets(node):
                ## Route 1: self.<column> = ...
                if selfColumn(target):
                    direct.add(method.name)
                ## Route 2: self.<column>[...] = ...
                if isinstance(target, ast.Subscript) and selfColumn(
                    target.value
                ):
                    direct.add(method.name)

            if isinstance(node, ast.Call) and isinstance(
                node.func, ast.Attribute
            ):
                ## Route 3: self.<column>.append(...) and friends
                if node.func.attr in subcalls and selfColumn(node.func.value):
                    direct.add(method.name)
                ## Route 4 edge: self.<other method>(...)
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                ):
                    called.add(node.func.attr)

        self_calls[method.name] = called

    ## Route 4: transitive closure over calls on `self`.
    mutators = set(direct)
    changed = True
    while changed:
        changed = False
        for method, called in self_calls.items():
            if method not in mutators and called & mutators:
                mutators.add(method)
                changed = True

    return tuple(sorted(mutators))


TRACE_COLUMN_SETTERS = _traceColumnSetters()

## The derivation's result, pinned. Nine methods, and every one of them is a
## live way to change what `Section.save()` will write:
##
##   add             points.append(point)          -- appends a point in place
##   addTag          tags.add(tag)                 -- was in the old two
##   centerAtOrigin  points = <recentred>          -- whole-list replacement
##   magScale        points[i] = (x, y)            -- per-point, subscript form
##   mergeTags       tags = tags.union(other.tags) -- deleteDuplicateTraces' call
##   reshape         points = <reshaped>           -- also calls resize
##   resize          points = <resized>            -- whole-list replacement
##   setHidden       hidden = hidden               -- was in the old two
##   smooth          points = <smoothed>           -- smoothObject's call
##
## If `Trace` grows a tenth, the scan picks it up immediately and THIS assertion
## is what tells a reviewer it happened.
TRACE_COLUMN_SETTERS_EXPECTED = (
    "add", "addTag", "centerAtOrigin", "magScale", "mergeTags", "reshape",
    "resize", "setHidden", "smooth",
)


def test_the_trace_setter_list_is_derived_from_trace_and_still_matches():
    """`Trace`'s mutators, derived, and pinned against a reviewed list.

    The hand-written list this replaces named `addTag` and `setHidden` and
    stopped there -- two of nine. `smooth` and `mergeTags` were missing, and
    `Series.smoothObject` and `Series.deleteDuplicateTraces` were live crashes
    behind that gap for as long as the list was believed complete.

    So the list is now derived, and this test is the pin. A new `Trace` mutator
    fails here by name, having *already* widened the scan -- which is the safe
    order: the property tightens first and the reviewer is told second.
    """
    assert TRACE_COLUMN_SETTERS == TRACE_COLUMN_SETTERS_EXPECTED, (
        "the set of Trace methods that mutate a store-backed column changed. "
        "The scan has already widened to match (it derives this list), so "
        "nothing is unguarded -- but a new mutator means new out-of-class edit "
        "sites may now be reported, and a lost one means an entry in "
        f"OUT_OF_CLASS_TRACE_EDITS may be stale: {TRACE_COLUMN_SETTERS} "
        f"against {TRACE_COLUMN_SETTERS_EXPECTED}"
    )

    ## And the derivation is not vacuously agreeing with a stale pin: the four
    ## routes it exists to cover are each represented by a method that is only
    ## reachable through that route.
    assert "setHidden" in TRACE_COLUMN_SETTERS   # self.hidden = ...
    assert "magScale" in TRACE_COLUMN_SETTERS    # self.points[i] = ...
    assert "add" in TRACE_COLUMN_SETTERS         # self.points.append(...)
    assert "reshape" in TRACE_COLUMN_SETTERS     # self.resize(...) transitively

## Every function outside `section.py` that both reaches traces through a
## section AND writes a store-backed column, with the reason each one is safe.
## Keyed on `module::qualified.function`, so a nested helper is its own entry
## and a second function of the same name cannot silently take another's slot.
##
## Three kinds of entry, and the distinction is the whole value of the list:
##
##   REPAIRED   -- edits a trace the section holds, and calls
##                 `resyncColumnarStore()` afterwards. These are the sites the
##                 always-on change had to find.
##   DETACHED   -- edits a `Trace` that is not in any section at the moment of
##                 the write: freshly built, `.copy()`d, or removed first and
##                 added after. No store mirrors it, so there is nothing to
##                 drift.
##   NOT A SECTION -- the `.contours` it reaches is not a `Section.contours`.
##
## Adding an entry is a design decision and belongs in review. Adding a
## REPAIRED one without the repair call is the bug this test exists to stop.
## A fourth kind of entry appears below, and it is the one this round added:
##
##   NOT A TRACE -- the object written is a `Ztrace`, `Transform` or `Flag`.
##                  These share method names with `Trace` (`magScale`) but the
##                  store shadows none of them.
OUT_OF_CLASS_TRACE_EDITS = {
    "modules/backend/autoseg/conversions.py::exportTraces":
        "DETACHED: setHidden on traces held aside, before addTrace puts them "
        "back; the store learns the value at insertion",
    "modules/backend/func/state_manager.py::FieldState.getContours":
        "NOT A SECTION: writes .closed on a Trace.fromList product while "
        "rebuilding a saved FieldState; no Section and no store exist yet",
    "modules/backend/func/xml_json_conversions.py::sectionXMLtoJSON":
        "NOT A SECTION: `contours` is a plain dict in the section JSON being "
        "built from XML; the trace is never in a Section",
    "modules/backend/view/trace_layer.py::TraceLayer.getCopiedTraces":
        "DETACHED: `trace = trace.copy()` rebinds the loop name to a copy "
        "before .points is rewritten; the section's own trace is only read",
    "modules/datatypes/contour.py::Contour.importTraces.addDuplicate":
        "REPAIRED by its only caller: `Section.importTraces` is the sole "
        "caller of `Contour.importTraces`, and it ends in `_dualWriteResync()` "
        "on both sections precisely because the merge rebinds trace lists and "
        "mergeTags edits tags in place",
    "modules/datatypes/series.py::Series.copyObjects":
        "DETACHED: renames `trace.copy()`, then addTrace",
    "modules/datatypes/series.py::Series.copyTracesToSections":
        "DETACHED: `new_trace = trace.copy()`, re-projected, then addTrace",
    "modules/datatypes/series.py::Series.deleteDuplicateTraces":
        "REPAIRED: `trace1.mergeTags(trace2)` rewrites tags in place on a "
        "trace the section keeps, then resyncColumnarStore(). The TENTH site, "
        "found by a reviewer, and invisible to this scan while mergeTags was "
        "missing from TRACE_COLUMN_SETTERS",
    "modules/datatypes/series.py::Series.hideAllTraces":
        "REPAIRED: setHidden in place, then resyncColumnarStore()",
    "modules/datatypes/series.py::Series.hideObjects.edit":
        "REPAIRED: setHidden in place, then resyncColumnarStore()",
    "modules/datatypes/series.py::Series.importFlags":
        "NOT A TRACE: `o_flag.magScale(...)` is a Flag; the store does not "
        "shadow flags",
    "modules/datatypes/series.py::Series.importTransforms":
        "NOT A TRACE: `o_section.tforms[alignment].magScale(...)` is a "
        "Transform; the store does not shadow transforms",
    "modules/datatypes/series.py::Series.importZtraces":
        "NOT A TRACE: `o_ztrace.magScale(...)` is a Ztrace; the store does not "
        "shadow ztraces",
    "modules/datatypes/series.py::Series.restoreObjectVisibility":
        "REPAIRED: setHidden in place, then resyncColumnarStore()",
    "modules/datatypes/series.py::Series.smoothObject":
        "REPAIRED: `Trace.smooth` rewrites points in place on traces the "
        "section holds, then resyncColumnarStore() before its own save(). The "
        "NINTH site, and a crash on a shipped menu action -- it passed the "
        "scan because `smooth` was not in TRACE_COLUMN_SETTERS",
    "modules/datatypes/series.py::Series.splitObject":
        "DETACHED: removeTrace, then renames `trace.copy()`, then addTrace",
    "modules/gui/dialog/trace.py::TraceDialog.__init__":
        "DETACHED: `ct = trace.copy()` then ct.resize(1), to render the shape "
        "preview; the caller's trace is only read",
    "modules/gui/dialog/trace_palette.py::TracePaletteDialog.getStructure":
        "DETACHED: `t_copy = t.copy()` then t_copy.resize(1), same shape "
        "preview as TraceDialog",
    "modules/gui/main/field_widget_2_trace.py::FieldWidgetTrace.copyTracesToSections":
        "DETACHED: `field_trace = trace.copy()` before .points is re-projected",
    "modules/gui/main/field_widget_2_trace.py::FieldWidgetTrace.cutTrace":
        "REPAIRED: `example_trace.tags.add(tag)` merges tags in place on "
        "`section.selected_traces[0]` -- the list is copied, the traces are "
        "not -- then resyncColumnarStore(). The TWELFTH site. It survived "
        "even the widened scan until two further gaps were closed: the write "
        "is an in-place mutation of the column's own container (not an "
        "assignment and not a Trace method), and the reach is "
        "`selected_traces`, not `.contours`",
    "modules/gui/main/field_widget_2_trace.py::FieldWidgetTrace.findFlag":
        "REPAIRED: writes .hidden in place on the import-conflict path, then "
        "resyncColumnarStore(). This is the eighth site, and the one this scan "
        "exists because nothing structural caught",
    "modules/gui/main/field_widget_2_trace.py::FieldWidgetTrace.newTrace":
        "DETACHED: `new_trace = base_trace.copy()`; .points, .closed, add() "
        "and smooth() all run before addTrace puts it in the section",
    "modules/gui/main/field_widget_2_trace.py::FieldWidgetTrace.placeGrid":
        "DETACHED: `exc_trace`/`inc_trace` are `ref_trace.copy()` products "
        "used as grid stamps; nothing written is in a section yet",
    "modules/gui/main/field_widget_2_trace.py::FieldWidgetTrace.smoothTraces":
        "REPAIRED: `trace.smooth()` in place on the section's own selection, "
        "then resyncColumnarStore(). The ELEVENTH site, found by a reviewer as "
        "a SCAN GAP rather than as a crash: it takes its traces as a parameter "
        "and named no section at all, so the reach predicate could not see it",
    "modules/gui/main/field_widget_7_view.py::FieldWidgetView.setTracingTrace":
        "DETACHED: `t = trace.copy()` before .name is stripped of increment "
        "characters; the copy becomes the tracing template",
    "modules/gui/main/main_window.py::MainWindow.setPaletteButtonFromObj":
        "DETACHED: the trace written is a palette trace out of "
        "series.palette_traces; the section's trace is .copy()d and only read",
    "modules/gui/palette/mouse_palette.py::MousePalette.pasteAttributesToButton":
        "DETACHED: both branches write a `.copy()` (of the pasted trace or of "
        "the button's own trace) before it becomes a palette button",
}

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _qualifiedFunctions(tree):
    """Every function in `tree` as `(qualified.name, node)`, however nested."""
    found = []

    def descend(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNCTION_NODES):
                qualified = f"{prefix}{child.name}"
                found.append((qualified, child))
                descend(child, f"{qualified}.")
            elif isinstance(child, ast.ClassDef):
                descend(child, f"{prefix}{child.name}.")
            else:
                descend(child, prefix)

    descend(tree, "")
    return found


def _nodesOwnedBy(function):
    """`function`'s own nodes, excluding any function nested inside it.

    Attribution is to the INNERMOST enclosing function, so `hideObjects.edit`
    answers for its own `setHidden` and `hideObjects` does not answer twice.
    """
    owned = []
    pending = list(function.body) + list(function.decorator_list)
    while pending:
        node = pending.pop()
        if isinstance(node, _FUNCTION_NODES + (ast.Lambda,)):
            continue
        owned.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return owned


def _rootName(node):
    """The leftmost `Name` of an attribute/subscript/call chain, or None.

    `self.section.contours[n][0].hidden` roots at `self`; `trace.hidden` roots
    at `trace`. This is what says whose trace is being written.
    """
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return None


## Every `Section` attribute that holds `Trace` objects the section owns, and
## therefore every attribute through which an out-of-class function can get a
## live trace without ever naming `.contours`. Read off `Section.__init__`:
##
##   selected_traces     the current selection -- what every field-widget verb
##                       operates on, and the route `cutTrace` takes
##   temp_hide           traces hidden for this view
##   traces_group_hide   traces hidden by group visibility
##   added_traces        this save cycle's additions, still in the contours
##   removed_traces      this save cycle's deletions (detached, but scanning
##                       them costs an allow-list line and missing them costs a
##                       session -- the same trade the rest of this scan makes)
##
## `.contours` is handled separately because it is a dict and reaches traces one
## level deeper. This tuple is the flat lists.
SECTION_TRACE_ATTRIBUTES = (
    "added_traces", "removed_traces", "selected_traces", "temp_hide",
    "traces_group_hide",
)

## Setter names `Trace` shares with ordinary containers, where the name alone
## does not establish that the receiver is a trace. `Trace.add` appends a point;
## `set.add` adds an element, and this codebase calls the latter 55 times and
## the former not once. Naming `add` unconditionally would put ten pure-noise
## entries in `OUT_OF_CLASS_TRACE_EDITS` -- `section.modified_contours.add(...)`,
## `dwg.add(...)`, `seen.add(...)` -- and an allow-list a reviewer skims is an
## allow-list that stops working, which is the failure this whole scan is a
## response to. So an ambiguous setter is only counted when its receiver is a
## name the function actually obtained from a section or a parameter, which is
## what a real `trace.add(point)` looks like and what none of the 55 sets do.
AMBIGUOUS_TRACE_SETTERS = ("add",)


def _namesDerivedFromParameters(function, nodes):
    """Local names that hold something handed in as a parameter.

    Seeds with the function's own parameters (minus `self`/`cls`) and grows to a
    fixpoint through the two ways a parameter's contents get a local name:
    `for trace in traces:` and `t = traces[0]`. So in

        def smoothTraces(self, traces: list):
            for trace in traces:
                trace.smooth(window, spacing=0.004)

    `trace` is parameter-derived, and the write to `points` it performs is a
    write to somebody else's trace.
    """
    args = function.args
    derived = {
        arg.arg
        for arg in (
            list(getattr(args, "posonlyargs", []))
            + list(args.args)
            + list(args.kwonlyargs)
        )
        if arg.arg not in ("self", "cls")
    }
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            derived.add(extra.arg)

    return _grownThroughBindings(derived, nodes)


def _namesDerivedFromSectionTraces(nodes):
    """Local names that hold traces taken off a section's trace lists.

    `FieldWidgetTrace.cutTrace` does

        traces = self.section.selected_traces.copy()
        example_trace = traces[0]
        example_trace.tags.add(tag)

    and `selected_traces` holds the section's own `Trace` objects -- `.copy()`
    copies the list, not the traces. The function never names `.contours`,
    `.tracesAsList()` or `.getTraces()`, and it takes no traces as parameters,
    so neither of the other two reach arms sees it. It is reached through
    `SECTION_TRACE_ATTRIBUTES`, and that is a third route.
    """
    seeds = set()
    bindings = _bindingsIn(nodes)
    for target, source in bindings:
        ## `x = <anything>.selected_traces...` seeds `x`.
        walker = source
        found = False
        while isinstance(walker, (ast.Attribute, ast.Subscript, ast.Call)):
            if (
                isinstance(walker, ast.Attribute)
                and walker.attr in SECTION_TRACE_ATTRIBUTES
            ):
                found = True
                break
            walker = (
                walker.func if isinstance(walker, ast.Call) else walker.value
            )
        if not found:
            continue
        pending = [target]
        while pending:
            bound = pending.pop()
            if isinstance(bound, (ast.Tuple, ast.List)):
                pending.extend(bound.elts)
            elif isinstance(bound, ast.Name):
                seeds.add(bound.id)

    return _grownThroughBindings(seeds, nodes)


def _bindingsIn(nodes):
    """`(bound target, source expression)` for every binding in `nodes`."""
    bindings = []
    for node in nodes:
        if isinstance(node, (ast.For, ast.AsyncFor)):
            bindings.append((node.target, node.iter))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                bindings.append((target, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bindings.append((node.target, node.value))
        elif isinstance(node, ast.comprehension):
            bindings.append((node.target, node.iter))
    return bindings


def _grownThroughBindings(seeds, nodes):
    """`seeds`, grown to a fixpoint through local rebinding.

    `for trace in traces:` and `t = traces[0]` both put a seeded object under a
    new name. Without this, aliasing through one intermediate variable is enough
    to leave the scan behind -- and `cutTrace` aliases twice.
    """
    derived = set(seeds)
    bindings = _bindingsIn(nodes)

    changed = True
    while changed:
        changed = False
        for target, source in bindings:
            if _rootName(source) not in derived:
                continue
            pending = [target]
            while pending:
                bound = pending.pop()
                if isinstance(bound, (ast.Tuple, ast.List)):
                    pending.extend(bound.elts)
                elif isinstance(bound, ast.Name) and bound.id not in derived:
                    derived.add(bound.id)
                    changed = True

    return derived


def _traceDerivedNames(function, nodes):
    """Every local name that may hold a trace the function did not build."""
    return _namesDerivedFromParameters(
        function, nodes
    ) | _namesDerivedFromSectionTraces(nodes)


def _reachesTracesThroughASection(nodes, function=None, writes=None):
    """How this function gets its hands on traces, or None.

    Three routes. The original predicate had only the first, and each of the
    other two was a live crash hiding behind its absence.

    **Through a section's contours**, the original test: the function itself
    names `.contours`, `.tracesAsList()` or `.getTraces()`.

    **Through its own parameters**: the function is *handed* traces already
    resolved, and writes a store-backed column on one of them. A function of
    that shape names none of the first route's markers, so under the original
    predicate it was invisible no matter what it wrote --
    `FieldWidgetTrace.smoothTraces(self, traces)` is exactly it, mutating
    `points` in place on the section's own selected traces and matching nothing.
    Callers pass section-held traces routinely (that is what a selection is), so
    "received as a parameter" has to count as reach.

    **Through a section's trace lists** (`SECTION_TRACE_ATTRIBUTES`): the
    selection, the temp-hide list, the group-hide list. `cutTrace` merges tags
    in place on `self.section.selected_traces` and satisfies neither of the
    other two arms. Same class, third hiding place.

    The last two arms are deliberately conditioned on the function actually
    writing a store-backed column through such a name -- otherwise every
    function in the codebase with a parameter would "reach traces". They
    over-report in the other direction instead (a caller that only ever passes
    detached traces looks the same as one that passes held ones), and the
    allow-list carries that distinction in prose, as it already does for the
    `.contours` arm.
    """
    for node in nodes:
        if isinstance(node, ast.Attribute) and node.attr == "contours":
            return ".contours"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("tracesAsList", "getTraces"):
                return f".{node.func.attr}()"

    if function is None or not writes:
        return None
    roots = {root for _, root in writes}
    if roots & _namesDerivedFromParameters(function, nodes):
        return "parameter"
    if roots & _namesDerivedFromSectionTraces(nodes):
        return ".selected_traces / .temp_hide / ..."
    return None


def _storeBackedColumnWrites(nodes, function=None):
    """Writes to a store-backed column on something other than `self`.

    Returns `(description, root name)` pairs -- the root name being who is
    written, which is what the parameter arm of the reach predicate needs.

    Four routes, because there are four ways to change what `save()` will
    serialise, and the first version of this scan knew two:

        trace.hidden = True            assignment to the column
        trace.setHidden(True)          a `Trace` method (TRACE_COLUMN_SETTERS)
        trace.tags.add(tag)            in-place mutation of the column itself
        trace.points[i] = (x, y)       assignment through a subscript

    `self.<column> = ...` is excluded because that is a class writing its own
    field -- `Trace.setHidden` doing `self.hidden = hidden` is the definition of
    the setter, not an out-of-class edit of somebody else's trace.

    `function` is optional and only affects `AMBIGUOUS_TRACE_SETTERS`: without
    it, `add` is skipped entirely rather than guessed at.
    """
    hits = []
    derived = (
        _traceDerivedNames(function, nodes) if function is not None else set()
    )
    for node in nodes:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]

        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            if target.attr not in STORE_BACKED_COLUMNS:
                continue
            if isinstance(target.value, ast.Name) and target.value.id == "self":
                continue
            hits.append((
                f"line {target.lineno}: .{target.attr} = ...",
                _rootName(target.value),
            ))

        ## Route three, and the one that hid a twelfth site: mutating the
        ## column's own container in place. `trace.tags.add(tag)` writes `tags`
        ## exactly as `trace.addTag(tag)` does, but it is neither an assignment
        ## to a column nor a call to a `Trace` method, so both of the arms above
        ## look straight past it. `FieldWidgetTrace.cutTrace` is this shape.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            container = node.func.value
            if (
                node.func.attr in _mutatingSubcalls()
                and isinstance(container, ast.Attribute)
                and container.attr in STORE_BACKED_COLUMNS
                and not (
                    isinstance(container.value, ast.Name)
                    and container.value.id == "self"
                )
            ):
                hits.append((
                    f"line {node.lineno}: "
                    f".{container.attr}.{node.func.attr}(...)",
                    _rootName(container.value),
                ))

        ## Route four: `trace.points[i] = ...`, the subscript form. `magScale`
        ## is `Trace`'s own instance of it.
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            column = target.value
            if not isinstance(column, ast.Attribute):
                continue
            if column.attr not in STORE_BACKED_COLUMNS:
                continue
            if isinstance(column.value, ast.Name) and column.value.id == "self":
                continue
            hits.append((
                f"line {target.lineno}: .{column.attr}[...] = ...",
                _rootName(column.value),
            ))

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in TRACE_COLUMN_SETTERS:
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id == "self":
                continue
            ## `trace.tags.add(tag)` is the container route above, already
            ## reported there; without this it is also reported here as
            ## `Trace.add` on a receiver that happens to be trace-derived.
            if (
                isinstance(receiver, ast.Attribute)
                and receiver.attr in STORE_BACKED_COLUMNS
            ):
                continue
            ## `add` is `Trace.add` only when the receiver is something the
            ## function got from a section or a caller; otherwise it is one of
            ## the codebase's 55 `set.add` calls. See AMBIGUOUS_TRACE_SETTERS.
            if node.func.attr in AMBIGUOUS_TRACE_SETTERS and not (
                isinstance(receiver, ast.Name) and receiver.id in derived
            ):
                continue
            hits.append((
                f"line {node.lineno}: .{node.func.attr}(...)",
                _rootName(receiver),
            ))

    return sorted(hits)


def _writeDescriptions(writes):
    """Just the human-readable half of `_storeBackedColumnWrites`' pairs."""
    return [description for description, _ in writes]


def test_no_module_outside_section_py_edits_a_store_backed_trace_column():
    """The out-of-class EDIT class, as a property rather than a body count.

    `REPAIR_SITES` pins which modules may call the repair; it cannot enumerate
    the modules that perform an out-of-class *edit*, and that is the class that
    actually costs a user their session. Seven such sites were found by running
    the suite and watching it raise; the other five (`findFlag`, `smoothObject`,
    `deleteDuplicateTraces`, `smoothTraces` and `cutTrace`) were found only by
    reviewers reading the source, on paths an ordinary click reaches. A
    thirteenth would be found the same way, or by a user.

    So this scans for the shape instead of counting instances: a function
    outside `section.py` that reaches traces through a section
    (`.contours`, `.tracesAsList()`, `.getTraces()`) **and** writes one of the
    eight store-backed columns, either by assignment or through `Trace`'s own
    setters. Every such function must be in `OUT_OF_CLASS_TRACE_EDITS` with a
    stated reason it is safe.

    A new one fails here, at review time, with the file and line in the message
    -- instead of in a user's session on whatever path the suite happens not to
    cover. That is the difference between "we found the ones the suite reached"
    and a property.

    This is deliberately a shape scan and not dataflow. It over-reports (a
    trace edited before it is ever added to a section looks the same as one
    edited after) and the allow-list carries that distinction in prose. The
    over-report is the safe direction: a new entry costs a reviewer one line of
    reasoning, a missed one costs a user their unsaved work.
    """
    offenders = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.resolve() == SECTION_SOURCE:
            continue
        relative = str(path.relative_to(PACKAGE_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for qualified, function in _qualifiedFunctions(tree):
            owned = _nodesOwnedBy(function)
            writes = _storeBackedColumnWrites(owned, function)
            if not writes:
                continue
            ## Writes are computed first now: the parameter arm of the reach
            ## predicate asks *whose* trace is written, so it needs them.
            reached = _reachesTracesThroughASection(owned, function, writes)
            if reached is None:
                continue
            offenders[f"{relative}::{qualified}"] = (
                reached, _writeDescriptions(writes)
            )

    unlisted = {
        site: detail for site, detail in offenders.items()
        if site not in OUT_OF_CLASS_TRACE_EDITS
    }
    assert unlisted == {}, (
        "a function outside section.py reaches a section's traces and writes a "
        "store-backed column, and is not in OUT_OF_CLASS_TRACE_EDITS. If it "
        "edits a trace the section already holds, it owes a "
        "resyncColumnarStore() afterwards -- without one the user's NEXT EDIT "
        "raises ColumnarDualWriteMismatch, through _rowFor for a rebind or "
        "_assertRowMatchesTrace for an in-place write. (Since D11 the next "
        "SAVE does not: it rebuilds the store and writes the drift to the log. "
        "That closes the unsaveable-section failure mode, not this one.) If "
        "the trace is detached or is not a section's, add it to the list with "
        f"that reason: {unlisted}"
    )

    ## And the list does not outlive the code it describes: an entry whose site
    ## has been deleted or renamed is a stale exemption, and a stale exemption
    ## is how the next one gets in.
    stale = sorted(set(OUT_OF_CLASS_TRACE_EDITS) - set(offenders))
    assert stale == [], (
        "OUT_OF_CLASS_TRACE_EDITS exempts sites that no longer match the scan. "
        f"Delete them so the list keeps meaning what it says: {stale}"
    )


def test_the_edit_scan_catches_a_planted_out_of_class_write(tmp_path):
    """The scan above is only worth having if it actually fires.

    A structural test that has never been shown to fail is a structural test
    nobody knows the shape of. This plants `findFlag`'s exact shape -- iterate
    `section.contours`, write `.hidden` in place -- in a module the scan has
    never seen, and requires it to be reported.
    """
    planted = tmp_path / "planted_leak.py"
    planted.write_text(
        "def hideEverything(section):\n"
        "    for cname, contour in section.contours.items():\n"
        "        for trace in contour:\n"
        "            trace.hidden = True\n",
        encoding="utf-8",
    )

    tree = ast.parse(planted.read_text(encoding="utf-8"))
    reported = []
    for qualified, function in _qualifiedFunctions(tree):
        owned = _nodesOwnedBy(function)
        writes = _storeBackedColumnWrites(owned, function)
        if not writes:
            continue
        if _reachesTracesThroughASection(owned, function, writes) is None:
            continue
        reported.append((qualified, _writeDescriptions(writes)))

    assert reported == [("hideEverything", ["line 4: .hidden = ..."])], (
        f"the edit scan did not catch a planted in-place write: {reported}"
    )

    ## And the setter form, which is what series.py's three sites use.
    planted.write_text(
        "def hideEverything(section):\n"
        "    for trace in section.tracesAsList():\n"
        "        trace.setHidden(True)\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    qualified, function = _qualifiedFunctions(tree)[0]
    owned = _nodesOwnedBy(function)
    writes = _storeBackedColumnWrites(owned, function)
    assert (
        _reachesTracesThroughASection(owned, function, writes)
        == ".tracesAsList()"
    )
    assert _writeDescriptions(writes) == ["line 3: .setHidden(...)"]


def test_the_edit_scan_catches_the_two_shapes_that_slipped_past_it(tmp_path):
    """The two gaps that let `smoothObject` and `smoothTraces` through.

    Both were live, both were found by a reviewer reading source, and both are
    reproduced here as the smallest code that has each shape -- so a later
    "simplification" of the scan that reopens either gap fails here rather than
    in a user's session.

    Gap one, the setter list (`Trace.smooth` was not in it). Gap two, the reach
    predicate (a function *handed* traces names no section at all).
    """
    planted = tmp_path / "planted_gap.py"

    ## Gap one: `smoothObject`'s exact shape -- reach via `.contours`, write via
    ## a `Trace` method the old two-name list did not know about.
    planted.write_text(
        "def smoothEverything(section, window):\n"
        "    for name, contour in section.contours.items():\n"
        "        for trace in contour.traces:\n"
        "            trace.smooth(window=window, spacing=0.004)\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    qualified, function = _qualifiedFunctions(tree)[0]
    owned = _nodesOwnedBy(function)
    writes = _storeBackedColumnWrites(owned, function)
    assert _writeDescriptions(writes) == ["line 4: .smooth(...)"], (
        "Trace.smooth is not being recognised as a store-backed column write; "
        "this is the gap Series.smoothObject crashed through"
    )
    assert _reachesTracesThroughASection(owned, function, writes) == ".contours"

    ## And `mergeTags`, the same gap, `deleteDuplicateTraces`' call.
    planted.write_text(
        "def mergeEverything(section, other):\n"
        "    for name, contour in section.contours.items():\n"
        "        for trace in contour:\n"
        "            trace.mergeTags(other)\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    qualified, function = _qualifiedFunctions(tree)[0]
    owned = _nodesOwnedBy(function)
    writes = _storeBackedColumnWrites(owned, function)
    assert _writeDescriptions(writes) == ["line 4: .mergeTags(...)"]

    ## Gap two: `FieldWidgetTrace.smoothTraces`' exact shape. No `.contours`, no
    ## `.tracesAsList()`, no `.getTraces()` -- traces arrive as a parameter, and
    ## under the old predicate this function was invisible whatever it wrote.
    planted.write_text(
        "def smoothTraces(self, traces: list):\n"
        "    for trace in traces:\n"
        "        self.section.modified_contours.add(trace.name)\n"
        "        trace.smooth(10, spacing=0.004)\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    qualified, function = _qualifiedFunctions(tree)[0]
    owned = _nodesOwnedBy(function)
    writes = _storeBackedColumnWrites(owned, function)
    assert _writeDescriptions(writes) == ["line 4: .smooth(...)"]
    assert _reachesTracesThroughASection(owned, function, writes) == (
        "parameter"
    ), (
        "a function handed traces as a parameter is invisible to the reach "
        "predicate again; this is the gap FieldWidgetTrace.smoothTraces sits in"
    )

    ## Aliasing through an intermediate name still counts as parameter-derived.
    planted.write_text(
        "def recolour(traces, color):\n"
        "    chosen = traces[0]\n"
        "    chosen.color = color\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    qualified, function = _qualifiedFunctions(tree)[0]
    owned = _nodesOwnedBy(function)
    writes = _storeBackedColumnWrites(owned, function)
    assert _reachesTracesThroughASection(owned, function, writes) == "parameter"

    ## And the arm does not fire on a function that merely has parameters: the
    ## write has to land on something the caller handed in.
    planted.write_text(
        "def buildOne(name, color):\n"
        "    trace = Trace(name)\n"
        "    trace.color = color\n"
        "    return trace\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    qualified, function = _qualifiedFunctions(tree)[0]
    owned = _nodesOwnedBy(function)
    writes = _storeBackedColumnWrites(owned, function)
    assert writes, "the local write should still be seen"
    assert _reachesTracesThroughASection(owned, function, writes) is None, (
        "the parameter arm fired on a trace the function built itself"
    )


def test_the_retired_gate_is_gone_from_the_module_that_defined_it():
    """No constant, no predicate, no dormant branch.

    A gate left as a constant nobody reads is a gate a later change re-wires by
    adding one `if`. `section.py` must not carry the name, the predicate that
    read it, or an exported symbol either could hang off.
    """
    source = SECTION_SOURCE.read_text(encoding="utf-8")
    assert RETIRED_GATE not in source
    assert not hasattr(section_module, "DUAL_WRITE_ENV_VAR")
    assert not hasattr(section_module, "dualWriteRequested")


# =============================================================================
# The dual write itself, on real material
# =============================================================================

def test_a_freshly_loaded_section_already_agrees(real_section):
    """Construction alone puts the two representations in step.

    `Section.__init__` builds the store from the contours it just parsed, and
    the check runs there too -- so a load that produced a store disagreeing with
    the section it was built from never gets as far as a mutation.
    """
    assert len(real_section._columns) == len(real_section.tracesAsList())
    assert real_section._column_rows
    real_section._assertColumnsMatchObjectModel("a check with nothing wrong")


def test_the_row_map_is_an_identity_map(real_section):
    """Keyed on the trace object, which is what the object model matches on.

    `Trace` defines neither `__eq__` nor `__hash__`, so the dict below is keyed
    on identity -- the same identity `Contour.remove` runs on via `list.remove`.
    Two traces that are equal field-for-field are two different rows, and this
    pins that rather than leaving it to be inferred.
    """
    original = _anyTrace(real_section)
    twin = original.copy()
    real_section.addTrace(twin)

    assert real_section._column_rows[original] != real_section._column_rows[twin]
    assert len(real_section._columns) == len(real_section.tracesAsList())


def test_addTrace_then_removeTrace_stays_consistent(real_section):
    before = len(real_section._columns)
    trace = _aTrace(real_section)

    real_section.addTrace(trace)
    assert len(real_section._columns) == before + 1
    assert real_section._columns.getPoints(real_section._column_rows[trace]) == [
        tuple(p) for p in trace.points
    ]

    real_section.removeTrace(trace)
    assert len(real_section._columns) == before
    assert trace not in real_section._column_rows


def test_a_trace_with_too_few_points_enters_neither_representation(real_section):
    """`addTrace` refuses a one-point trace, and the store must refuse it too.

    The guard is the first thing `addTrace` does, before the store hook, so this
    is really a test that the hook sits on the far side of the early return.
    """
    before = len(real_section._columns)
    real_section.addTrace(_aTrace(real_section, points=[(0.0, 0.0)]))
    assert len(real_section._columns) == before
    real_section._assertColumnsMatchObjectModel("a refused addTrace")


def test_a_two_point_trace_is_forced_open_in_both(real_section):
    """`addTrace` flips `closed` for a two-point trace before appending.

    Which means the store has to be written from the *coerced* trace, not the
    one the caller handed over. Reading `trace.closed` after the coercion is
    what makes that true, and this is the test that would catch the hook being
    moved above it.
    """
    trace = _aTrace(real_section, points=[(0.0, 0.0), (1.0, 1.0)])
    assert trace.closed is True
    real_section.addTrace(trace)
    assert trace.closed is False
    assert real_section._columns.getFlag(
        real_section._column_rows[trace], "closed"
    ) is False


def test_editTraceAttributes_renames_recolours_retags_and_refills(real_section):
    """The composite path, all four fields at once, including a rename.

    A rename moves the trace between contours in the object model and between
    contour indices in the store; the check compares the whole contour set, so a
    rename that landed in one and not the other is caught by the contour-set
    complaint rather than by a field comparison.
    """
    trace = _anyTrace(real_section)
    old_name = trace.name

    real_section.editTraceAttributes(
        [trace],
        name="renamed_by_the_dual_write_test",
        color=(9, 8, 7),
        tags={"alpha", "beta"},
        mode=("solid", "selected"),
    )

    assert "renamed_by_the_dual_write_test" in real_section._columns.contourNames()
    rows = real_section._columns.rowsForContour("renamed_by_the_dual_write_test")
    assert len(rows) == 1
    assert real_section._columns.getTags(rows[0]) == {"alpha", "beta"}
    assert real_section._columns.getColor(rows[0]) == [9, 8, 7]
    assert real_section._columns.getFillMode(rows[0]) == ["solid", "selected"]
    assert old_name not in real_section._columns.contourNames() or rows[0] not in \
        real_section._columns.rowsForContour(old_name)


def test_translateTraces_moves_the_stored_coordinates(real_section):
    trace = _anyTrace(real_section)
    real_section.addSelectedTrace(trace)
    before = [tuple(p) for p in trace.points]

    real_section.translateTraces(0.25, -0.5)

    after = [tuple(p) for p in trace.points]
    assert after != before
    row = real_section._column_rows[trace]
    assert real_section._columns.getPoints(row) == after


@pytest.mark.parametrize(
    "drive",
    [
        pytest.param(lambda s, t: s.editTraceRadius([t], 0.9), id="editTraceRadius"),
        pytest.param(
            lambda s, t: s.editTraceShape([t], [(0, 0), (1, 0), (1, 1), (0, 1)]),
            id="editTraceShape",
        ),
        pytest.param(lambda s, t: s.makeNegative([t], negative=True), id="makeNegative"),
        pytest.param(lambda s, t: s.deleteTraces([t]), id="deleteTraces"),
    ],
)
def test_the_other_remove_mutate_add_composites_stay_consistent(real_section, drive):
    """Six `Section` methods are built out of removeTrace/addTrace, not two.

    The design proposal named four mutation paths to route. Reading the class
    says `editTraceAttributes`, `translateTraces`, `editTraceRadius`,
    `editTraceShape`, `makeNegative` and `deleteTraces` are all composed of the
    two primitives, so hooking the primitives covers all of them -- and each of
    them is driven here rather than left as a claim about the source.
    """
    drive(real_section, _anyTrace(real_section))
    real_section._assertColumnsMatchObjectModel("a composite mutation")


def test_the_composites_write_through_the_primitives_and_nothing_else(
    real_section, monkeypatch
):
    """Pin the composition, so a future hook cannot be added and double-write.

    `editTraceAttributes` must produce exactly one store removal and one store
    append per trace, through `removeTrace`/`addTrace`, and must not reach any
    in-place hook. If somebody later gives `editTraceAttributes` its own hook,
    this fails rather than the store quietly gaining a duplicate row.
    """
    calls = []
    for hook in ("_dualWriteAppend", "_dualWriteRemove", "_dualWriteAttribute",
                 "_dualWriteAllCoordinates"):
        real = getattr(real_section, hook)

        def wrapper(*args, __hook=hook, __real=real, **kwargs):
            calls.append(__hook)
            return __real(*args, **kwargs)

        monkeypatch.setattr(real_section, hook, wrapper)

    real_section.editTraceAttributes(
        [_anyTrace(real_section)], name=None, color=(1, 2, 3), tags=None, mode=None
    )

    assert calls == ["_dualWriteRemove", "_dualWriteAppend"]


@pytest.mark.parametrize(
    "drive, attribute, expected",
    [
        pytest.param(
            lambda s, t: s.hideTraces([t], hide=True), "hidden", True, id="hideTraces"
        ),
        pytest.param(
            lambda s, t: s.closeTraces([t], closed=False), "closed", False,
            id="closeTraces",
        ),
    ],
)
def test_the_in_place_attribute_mutators_reach_the_store(
    real_section, drive, attribute, expected
):
    """The four mutators that never leave the contour need their own hooks.

    `hideTraces`, `hideOtherTraces`, `unhideAllTraces` and `closeTraces` write a
    trace attribute in place and do not go through addTrace/removeTrace, so the
    primitives do not cover them. Two are driven here; the other two below.
    """
    trace = _anyTrace(real_section)
    drive(real_section, trace)
    row = real_section._column_rows[trace]
    assert real_section._columns.getFlag(row, attribute) is expected


def test_unhideAllTraces_and_hideOtherTraces_reach_the_store(real_section):
    keep = _anyTrace(real_section)
    real_section.hideOtherTraces(keep=[keep])
    for trace in real_section.tracesAsList():
        row = real_section._column_rows[trace]
        assert real_section._columns.getFlag(row, "hidden") == trace.hidden

    real_section.unhideAllTraces()
    for trace in real_section.tracesAsList():
        assert real_section._columns.getFlag(
            real_section._column_rows[trace], "hidden"
        ) is False


def test_setMag_rewrites_every_stored_coordinate(real_section):
    """`setMag` scales every trace's points in place and never touches a contour.

    The one mutator that needs `setCoordinates` rather than an attribute write,
    and the one that moves every row of the section at once.
    """
    before = {
        id(t): [tuple(p) for p in t.points] for t in real_section.tracesAsList()
    }
    generation = real_section._columns.generation

    real_section.setMag(real_section.mag * 2)

    for trace in real_section.tracesAsList():
        row = real_section._column_rows[trace]
        assert real_section._columns.getPoints(row) == [tuple(p) for p in trace.points]
        assert [tuple(p) for p in trace.points] != before[id(trace)]
    assert real_section._columns.generation > generation


def test_the_tform_setter_moves_the_generation_and_no_row(real_section):
    """An alignment change rewrites rendered geometry and no stored byte.

    The store's docstring is explicit that a counter which did not move here
    would reproduce a measured stale-render bug in a new place, so the hook
    exists even though nothing this slice does reads the counter.
    """
    from PyReconstruct.modules.datatypes import Transform

    generation = real_section._columns.generation
    rows = real_section._columns.rowCount

    real_section.tform = Transform([2, 0, 5, 0, 2, 5])

    assert real_section._columns.generation > generation
    assert real_section._columns.rowCount == rows
    real_section._assertColumnsMatchObjectModel("a transform change")


def test_tags_negative_and_hidden_survive_a_mutation_on_synthetic_material(
    synthetic_section
):
    """The domains the real fixture series does not carry at all.

    Measured in `test_columnar_store_parity.py`: the checked-in real series has
    no tagged, negative or hidden trace, so a dual-write suite that only used it
    would leave three of the eight compared fields untested on real material.
    """
    tagged = [t for t in synthetic_section.tracesAsList() if t.tags]
    assert tagged, "the synthetic fixture stopped carrying a tagged trace"

    trace = tagged[0]
    synthetic_section.editTraceAttributes(
        [trace], name=None, color=None, tags={"kept", "added"}, mode=None
    )
    synthetic_section._assertColumnsMatchObjectModel("a tag edit")

    stored_tags = {
        frozenset(synthetic_section._columns.getTags(row))
        for row in synthetic_section._columns.rowsForContour(trace.name)
    }
    assert frozenset({"kept", "added"}) in stored_tags


def test_importTraces_rebuilds_the_store_from_the_result(real_series):
    """The one path that replaces contour lists wholesale instead of mutating.

    `Contour.importTraces` rebinds `self.traces` outright, so there is no
    sequence of row operations to mirror and the store is rebuilt from the
    object model afterwards. Stated as a limit in the source and pinned here:
    what is guaranteed is that the two agree once the import returns.
    """
    numbers = sorted(real_series.sections)
    keeper = _busiest([real_series.loadSection(n) for n in numbers])
    donor = real_series.loadSection(keeper.n)

    extra = _aTrace(donor, name="imported_by_the_dual_write_test")
    donor.addTrace(extra)

    keeper.importTraces(donor)

    keeper._assertColumnsMatchObjectModel("an import")
    donor._assertColumnsMatchObjectModel("an import, on the donor")
    assert len(keeper._columns) == len(keeper.tracesAsList())


# =============================================================================
# Mutation-testing the safety net: prove the check catches things
# =============================================================================

def _corruptName(store, row):
    store.setAttribute(row, "name", "a_name_the_object_model_does_not_have")


def _corruptPoints(store, row):
    store.setCoordinates(row, [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])


def _corruptPointValue(store, row):
    points = store.getPoints(row)
    points[0] = (points[0][0] + 1e-9, points[0][1])
    store.setCoordinates(row, points)


def _corruptColor(store, row):
    current = store.getColor(row)
    store.setAttribute(row, "color", [(current[0] + 1) % 256, current[1], current[2]])


def _corruptFillMode(store, row):
    current = store.getFillMode(row)
    replacement = ("solid", "selected") if current != ["solid", "selected"] \
        else ("transparent", "unselected")
    store.setAttribute(row, "fill_mode", replacement)


def _corruptTags(store, row):
    store.setTags(row, {"a-tag-the-object-model-does-not-have"})


def _corruptRowCount(store, row):
    store.removeRow(row)


@pytest.mark.parametrize(
    "corrupt, expected_in_message",
    [
        pytest.param(_corruptName, "contours only in", id="name"),
        pytest.param(_corruptPoints, "points:", id="points-length"),
        pytest.param(_corruptPointValue, "points[0]:", id="points-value"),
        pytest.param(_corruptColor, "color:", id="color"),
        pytest.param(_corruptFillMode, "fill_mode:", id="fill_mode"),
        pytest.param(_corruptTags, "tags:", id="tags"),
        ## The chosen trace is its contour's only one, so losing its row loses
        ## the whole contour from the store. `test_a_missing_row_inside_a_shared
        ## _contour_is_caught` covers the other shape, where the contour
        ## survives with one trace too few.
        pytest.param(_corruptRowCount, "contours only in the object model",
                     id="removed-row"),
        pytest.param(
            lambda store, row: store.setAttribute(
                row, "closed", not store.getFlag(row, "closed")
            ),
            "closed:", id="closed",
        ),
        pytest.param(
            lambda store, row: store.setAttribute(
                row, "negative", not store.getFlag(row, "negative")
            ),
            "negative:", id="negative",
        ),
        pytest.param(
            lambda store, row: store.setAttribute(
                row, "hidden", not store.getFlag(row, "hidden")
            ),
            "hidden:", id="hidden",
        ),
    ],
)
def test_a_corrupted_column_is_caught_by_the_check(
    real_section, corrupt, expected_in_message
):
    """Every field the check compares, deliberately broken, one at a time.

    This is the mutation test for the safety net. A check that compared six of
    the eight fields would pass every other test in this file and would let a
    real divergence through in the two it skipped; the only way to know it
    compares all of them is to break each one and watch it fire.

    The corruptions go through the store's own public mutation entry points, so
    each one is a divergence of a shape a genuinely buggy hook could produce --
    a write that landed on the wrong value, not an impossible state poked into a
    private list.
    """
    trace = _anyTrace(real_section)
    row = real_section._column_rows[trace]

    ## Sanity: the check passes before the corruption. Without this the test
    ## could be green because the section was already broken.
    real_section._assertColumnsMatchObjectModel("a check with nothing wrong")

    corrupt(real_section._columns, row)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section._assertColumnsMatchObjectModel("a deliberate corruption")

    assert expected_in_message in str(caught.value)
    assert "a deliberate corruption" in str(caught.value)


def test_a_missing_row_inside_a_shared_contour_is_caught(real_section):
    """A contour that survives with one trace too few.

    The parametrized case above removes the only row of its contour, which the
    contour-set comparison catches. This is the harder one: the contour is still
    in both, the names still line up, and only the length differs -- which is
    what a routing bug that dropped one `addTrace` out of two would look like.
    """
    trace = _anyTrace(real_section)
    twin = trace.copy()
    real_section.addTrace(twin)
    assert len(real_section.contours[trace.name]) >= 2

    real_section._columns.removeRow(real_section._column_rows[twin])

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section._assertColumnsMatchObjectModel("a lost row")

    assert "the store holds" in str(caught.value)
    assert "traces, the object model holds" in str(caught.value)


def test_a_dropped_appendRow_is_caught_by_addTrace(real_section, monkeypatch):
    """Break the store write, drive the real method, require the raise.

    The corruption tests above call the check directly. This family goes through
    `Section`'s own mutators with a store entry point silently doing nothing,
    which is the shape a real routing bug has: the object model moves, the store
    does not, and nothing else in the process notices.
    """
    monkeypatch.setattr(SectionColumns, "appendRow", lambda self, **kwargs: None)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.addTrace(_aTrace(real_section))

    assert "addTrace" in str(caught.value)


def test_a_dropped_removeRow_is_caught_by_removeTrace(real_section, monkeypatch):
    trace = _anyTrace(real_section)
    monkeypatch.setattr(SectionColumns, "removeRow", lambda self, row: None)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.removeTrace(trace)

    assert "removeTrace" in str(caught.value)


def test_a_dropped_setAttribute_is_caught_by_closeTraces(real_section, monkeypatch):
    trace = _anyTrace(real_section)
    monkeypatch.setattr(
        SectionColumns, "setAttribute", lambda self, row, attribute, value: None
    )

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.closeTraces([trace], closed=not trace.closed)

    assert "closed" in str(caught.value)


def test_a_dropped_setCoordinates_is_caught_by_setMag(real_section, monkeypatch):
    monkeypatch.setattr(SectionColumns, "setCoordinates", lambda self, row, points: None)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.setMag(real_section.mag * 2)

    assert "points" in str(caught.value)


def test_an_appendRow_that_loses_only_the_tags_is_still_caught(
    synthetic_section, monkeypatch
):
    """The subtle break, not the total one.

    A store write that succeeds in seven columns and drops the eighth is what a
    real hook bug looks like -- a forgotten keyword argument -- and it is the
    case a check comparing "the same number of traces in the same contours"
    would sail straight past. Run on the synthetic series because the real one
    has no tagged trace to lose.
    """
    tagged = [t for t in synthetic_section.tracesAsList() if t.tags]
    assert tagged, "the synthetic fixture stopped carrying a tagged trace"
    trace = tagged[0]

    real_append = SectionColumns.appendRow

    def appendWithoutTags(self, **kwargs):
        kwargs["tags"] = ()
        return real_append(self, **kwargs)

    monkeypatch.setattr(SectionColumns, "appendRow", appendWithoutTags)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        ## A remove/mutate/add composite, so the broken append is reached
        ## through a real edit rather than by adding an invented trace.
        synthetic_section.editTraceAttributes(
            [trace], name=None, color=None, tags=None, mode=("solid", "selected")
        )

    assert "tags:" in str(caught.value)


def test_a_trace_the_store_has_no_row_for_is_refused_loudly(real_section):
    """The other half of "raise loudly": an unmirrored trace, not a bad value.

    A `Section` mutator handed a trace that never entered through `addTrace` has
    no row to write to. Guessing one, or skipping the write, would be exactly
    the silent divergence this slice exists to prevent.
    """
    stranger = _aTrace(real_section, name=_anyTrace(real_section).name)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.hideTraces([stranger], hide=True)

    assert "holds no row for" in str(caught.value)


def test_the_check_reports_every_divergent_field_not_only_the_first(real_section):
    """One bad mutation usually breaks more than one column.

    Reporting only the first difference makes the second one invisible until the
    first is fixed, which turns one debugging session into three.
    """
    trace = _anyTrace(real_section)
    row = real_section._column_rows[trace]
    _corruptColor(real_section._columns, row)
    _corruptTags(real_section._columns, row)
    real_section._columns.setAttribute(row, "hidden", not trace.hidden)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section._assertColumnsMatchObjectModel("three corruptions at once")

    message = str(caught.value)
    assert "color:" in message and "tags:" in message and "hidden:" in message


def test_resyncing_repairs_a_corrupted_store(real_section):
    """The escape hatch the import path uses, and its only guarantee.

    `resyncColumnarStore` throws the store away and rebuilds it from the object
    model, so it *cannot* report a divergence that happened before it ran. That
    is why it is used only where there is no per-row mutation to mirror, and
    saying so here is part of the record.
    """
    row = real_section._column_rows[_anyTrace(real_section)]
    _corruptTags(real_section._columns, row)
    with pytest.raises(ColumnarDualWriteMismatch):
        real_section._assertColumnsMatchObjectModel("a corruption")

    real_section.resyncColumnarStore()
    real_section._assertColumnsMatchObjectModel("after a resync")


def _driftReports(capsys) -> str:
    """Every save-time drift report printed since the last read, as one string.

    D11 replaced `save()`'s whole-section COMPARISON with a REBUILD, so an
    out-of-class edit no longer raises there -- the store is simply made
    correct again. What survives is the discipline signal: the rebuild is
    compared against the store it replaced, and any difference is printed to
    stderr, which `backend/func/logging_setup.py` tees into the per-user log
    file the user can open from Help > View log file.

    Reading it back is what keeps the tests below pins on the real path. Each
    one used to assert `pytest.raises(ColumnarDualWriteMismatch)` around a
    `save()`; asserting on the report instead is the same claim -- this edit
    drifted the store, in this column -- against the mechanism that replaced
    the raise.

    Returns "" when nothing drifted, which is the case on every clean save.
    """
    reports = capsys.readouterr().err.split("WARNING: the columnar store")
    return "\n".join(reports[1:])


def _undoStyleRestore(section):
    """An out-of-class whole-dict rebind to equal-valued copies.

    The shape `backend/func/state_manager.py` restores a section with. Every
    trace is a `Contour.copy()` product: equal field for field to the trace it
    replaces, and a different object.
    """
    section.contours = {
        name: contour.copy() for name, contour in section.contours.items()
    }


def test_an_out_of_class_rebind_is_caught_even_though_every_value_matches(
    real_section
):
    """The staleness the value comparison alone could not see.

    An undo restore replaces `Section.contours` wholesale with copies. Reading
    values back out of the store finds nothing wrong -- the copies are equal
    field for field -- while `_column_rows` is left keyed on traces no contour
    holds any more. Before the row map was compared as well, this passed, and
    the run then died several mutations later on a "holds no row for" naming a
    trace that was plainly still in its contour. The failure belongs here, at
    the first hooked mutation after the rebind, naming the rebind.
    """
    _undoStyleRestore(real_section)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section._assertColumnsMatchObjectModel("after an undo-style restore")

    message = str(caught.value)
    assert "the row map is stale" in message
    assert "resyncColumnarStore" in message


@pytest.mark.parametrize(
    "drive",
    [
        pytest.param(lambda s: s.removeTrace(_anyTrace(s)), id="removeTrace"),
        pytest.param(
            lambda s: s.hideTraces([_anyTrace(s)], hide=True), id="hideTraces"
        ),
        pytest.param(
            lambda s: s.closeTraces([_anyTrace(s)], closed=False), id="closeTraces"
        ),
        pytest.param(lambda s: s.setMag(s.mag * 2), id="setMag"),
    ],
)
def test_a_mutation_touching_an_existing_trace_still_names_a_stale_row_map(
    real_section, drive
):
    """Driven through a `Section` method, because that is how it would happen.

    REWRITTEN, AND THE REWRITE IS THE HONEST PART
    ----------------------------------------------
    This used to drive `addTrace` and require the raise, on the strength of the
    whole-section check running after every mutation. Always-on made that check
    unaffordable per mutation (81-127 ms on `autoseg745`), so the per-mutation
    check is targeted at the row that moved -- and `addTrace` after an
    undo-style rebind writes a brand-new row that is perfectly correct, so
    **`addTrace` no longer detects a stale row map.** That is a real narrowing,
    it is pinned by `test_addTrace_alone_no_longer_detects_a_stale_row_map`
    below rather than left for somebody to discover, and it is why the four
    out-of-class rebind sites now call the repair instead of relying on
    detection.

    What survives is the case that matters more: any mutation that touches a
    trace the section already held goes through `_rowFor`, which cannot find the
    replaced object in the identity map and says so. That is every edit a user
    performs on existing work.
    """
    _undoStyleRestore(real_section)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        drive(real_section)

    assert "holds no row for" in str(caught.value)


def test_addTrace_alone_no_longer_detects_a_stale_row_map(real_section):
    """The gap the narrowed check leaves, pinned rather than left to be found.

    A brand-new trace gets a brand-new row, and a targeted check compares that
    row against that trace and finds them in agreement -- correctly, because
    they are. Nothing about the append can see that every OTHER row is now keyed
    on a discarded object. `save()` catches it, and the four out-of-class rebind
    sites do not reach here at all because they repair first.

    If a future change puts a whole-section comparison back on the mutation
    path, this test fails, and that is the right outcome: it means the cost
    trade was reopened and somebody should look at the measurement again.
    """
    _undoStyleRestore(real_section)

    real_section.addTrace(_aTrace(real_section))  # does not raise

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section._assertColumnsMatchObjectModel("the coarse net, by hand")
    assert "the row map is stale" in str(caught.value)


def test_resyncing_after_an_out_of_class_rebind_is_the_documented_remedy(
    real_section
):
    """The harness comment says to call `resyncColumnarStore()`. It works.

    A detector that fires with no way to clear it is a detector nobody keeps, so
    pin the remedy next to the detection.
    """
    _undoStyleRestore(real_section)
    with pytest.raises(ColumnarDualWriteMismatch):
        real_section._assertColumnsMatchObjectModel("after an undo-style restore")

    real_section.resyncColumnarStore()
    real_section._assertColumnsMatchObjectModel("after the remedy")
    real_section.addTrace(_aTrace(real_section))
    real_section.removeTrace(_anyTrace(real_section))


def test_a_trace_removed_from_its_contour_from_outside_is_caught(real_section):
    """The other direction: the map holds a row the object model dropped.

    `Contour.remove` reached directly, bypassing `Section.removeTrace` and so
    bypassing the hook. The columns still carry the row, so the arity comparison
    would catch this one too -- both complaints are wanted, because together
    they say which side moved.
    """
    trace = _anyTrace(real_section)
    real_section.contours[trace.name].remove(trace)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section._assertColumnsMatchObjectModel("an out-of-class removal")

    assert "the row map is stale" in str(caught.value)


# =============================================================================
# The out-of-class repair sites: the paths always-on turned into crashes
# =============================================================================
#
# Under the gate none of these could reach a section carrying a store, and the
# source comment said only that they "owe the resync". Always-on made each one a
# `ColumnarDualWriteMismatch` raised at the user on the next edit, which was the
# single largest thing this change had to fix. Each is driven for real here --
# not simulated with `_undoStyleRestore` -- because a repair call that is present
# but unreachable, or placed before the rebind instead of after it, would pass
# every simulated test and still crash a session.

class _StubFieldForFindFlag():
    """The smallest thing `FieldWidgetTrace.findFlag` will run against.

    `findFlag` is a method on a `QWidget` subclass whose `__init__` builds a
    scene, a pixmap and a table. None of that is what is under test and all of
    it would drag a `QApplication` into a datatypes test, so the real, unbound
    function is called against a stand-in carrying only the four attributes it
    actually touches. That keeps this a test of the production function --
    `FieldWidgetTrace.findFlag(field, flag)` is literally the shipped code --
    rather than of a re-implementation of it, which is the distinction that
    matters here: a re-implementation would have "passed" before the fix.
    """

    class _Layer():
        image_found = False
        base_corners = []

    def __init__(self, series, section):
        self.series = series
        self.section = section
        self.section_layer = self._Layer()
        self.hide_trace_layer = False
        self.generated = 0

    def generateView(self):
        self.generated += 1


def test_clicking_an_import_conflict_flag_leaves_the_section_saveable(
    real_section, real_series
):
    """The eighth out-of-class edit site, driven through the real `findFlag`.

    THE USER PATH
    -------------
    Import traces from another series -> overlapping traces raise
    `import-conflict_<name>` flags (`Section.importTraces`) -> the user clicks
    one to jump to it (`MainWindow` -> `field.findFlag`) -> `findFlag` hides
    every contour except the conflicting one by writing `trace.hidden` **in
    place**, from outside `Section`, with no hook watching and no repair.

    Every one of those is a store-backed column, so the store kept the old
    flags while the object model took the new ones. The next `save()` -- which
    `Section.save`'s own comment says runs on every section change, a
    mouse-wheel scroll included -- compared the two and raised
    `ColumnarDualWriteMismatch` in the user's face. Nothing on that path
    repaired the store, so it raised again on every later save too, and the
    section stayed unsaveable for the rest of the session.

    This was the PR's own stated largest residual risk ("that seven out-of-class
    sites is the complete set"), realised. No structural test could have found
    it, which is why `test_no_module_outside_section_py_edits_a_store_backed_
    trace_column` now exists beside it.
    """
    from PyReconstruct.modules.datatypes.flag import Flag
    from PyReconstruct.modules.gui.main.field_widget_2_trace import (
        FieldWidgetTrace
    )

    ## The flag `importTraces` raises, spelled the way it spells it:
    ## `f"import-conflict_{trace.name}"`.
    conflicted = sorted(real_section.contours, key=str)[0]
    assert len(real_section.contours) > 1, (
        "the fixture section has one contour, so findFlag's else-branch -- the "
        "branch that hides everything -- would never run"
    )
    flag = Flag(
        f"import-conflict_{conflicted}", 0, 0, real_section.n, (255, 0, 0)
    )
    real_section.flags.append(flag)

    field = _StubFieldForFindFlag(real_series, real_section)

    ## The real, shipped function.
    FieldWidgetTrace.findFlag(field, flag)

    ## It did what it is supposed to do to the object model.
    assert field.generated == 1, "findFlag did not run to completion"
    for name, contour in real_section.contours.items():
        expected = name != conflicted
        for trace in contour:
            assert trace.hidden is expected, (
                f"findFlag left {name!r} at hidden={trace.hidden}"
            )

    ## And the store came with it. Before the fix this raised, and kept raising.
    real_section._assertColumnsMatchObjectModel("after findFlag")
    real_section.save()

    ## The user's next edit, which is what actually used to blow up: the raise
    ## did not arrive at the click, it arrived at the scroll after it.
    real_section.addTrace(_aTrace(real_section))
    real_section.save()


def test_findFlag_without_the_repair_really_would_have_drifted(
    real_section, real_series, monkeypatch, capsys
):
    """The fix is load-bearing, not decorative.

    A repair call is only worth a line if removing it breaks something. With
    `resyncColumnarStore` neutered for this section alone -- after its store is
    built, so the section is in exactly the state a real one is in -- the same
    click drifts the store and `save()` names the drifted column. This is the
    failure a user would have hit.

    Neutering the method wholesale would ALSO disable `__init__`'s build, which
    leaves the section storeless and makes every check return on its first line
    -- a false pass that looks like a fix. The store is already built here, so
    patching the bound method on this one instance reverts exactly the call
    this fixup added and nothing else.

    **The assertion changed with D11 and the claim did not.** `save()` used to
    raise `ColumnarDualWriteMismatch` here; it now rebuilds and reports. The
    drift is the same drift, in the same column, caused by the same click --
    what changed is that it costs the user a line in the log rather than an
    unsaveable section. Neutering the repair is also what makes the rebuild
    itself observable: with the real repair in place there is nothing left to
    report by the time `save()` runs.
    """
    from PyReconstruct.modules.datatypes.flag import Flag
    from PyReconstruct.modules.gui.main.field_widget_2_trace import (
        FieldWidgetTrace
    )

    assert real_section._columns is not None, "the store was never built"
    monkeypatch.setattr(real_section, "resyncColumnarStore", lambda: None)

    conflicted = sorted(real_section.contours, key=str)[0]
    flag = Flag(
        f"import-conflict_{conflicted}", 0, 0, real_section.n, (255, 0, 0)
    )
    real_section.flags.append(flag)

    FieldWidgetTrace.findFlag(_StubFieldForFindFlag(real_series, real_section), flag)

    capsys.readouterr()
    real_section.save()          # no longer raises: it rebuilds
    message = _driftReports(capsys)

    assert message, "the drift went unreported, so nothing signals the edit"
    assert "hidden:" in message, (
        f"the drift was caught but not attributed to `hidden`: {message}"
    )
    ## And the rebuild left the section correct, which is the other half of
    ## what replaced the raise.
    real_section._assertColumnsMatchObjectModel("after the rebuild at save")


def _aSmoothableObject(series):
    """An object name whose traces all have enough points to smooth.

    `Trace.smooth` returns False without touching `points` below three points,
    so a contour of "pixel dust" would make this test pass while proving
    nothing -- the same false-negative-from-a-bad-fixture trap that let
    `mergeTags` look clean to a reviewer on a single-trace contour.
    """
    for number in sorted(series.sections):
        section = series.loadSection(number)
        for name, contour in section.contours.items():
            if contour.traces and all(
                len(trace.points) >= 3 for trace in contour.traces
            ):
                return name
    raise AssertionError("no smoothable object in the fixture series")


def test_smoothing_an_object_leaves_every_touched_section_saveable(real_series):
    """`Series.smoothObject` -- the NINTH out-of-class edit site.

    "Smooth object traces" is a shipped menu action on the object list.
    `smoothObject` reaches traces through `section.contours`, rewrites `points`
    in place with `Trace.smooth`, and then calls `section.save()` itself -- so
    the mismatch used to raise inside the operation's own save, aborting a
    multi-section pass partway through and leaving every later section
    un-smoothed.

    It survived the static scan that was built to end this whole class, because
    the scan's setter list named two of the nine `Trace` methods that write a
    store-backed column and `smooth` was not one of them. This drives the real
    function.
    """
    name = _aSmoothableObject(real_series)

    ## The real, shipped entry point -- not a re-implementation of its loop.
    real_series.smoothObject([name], log_event=False)

    ## Every section it touched must still be saveable, which is the property
    ## the crash violated. Reload from disk so this is the bytes, not the
    ## in-memory objects the operation just held.
    touched = real_series.getObjectSections([name])
    assert touched, "the fixture object appears on no section"
    for number in sorted(touched):
        real_series.loadSection(number).save()


def test_smoothObject_without_the_repair_really_would_have_drifted(
    real_series, monkeypatch, capsys
):
    """The `smoothObject` repair is load-bearing.

    `smoothObject` loads its own sections through `enumerateSections`, so the
    sections it edits are not ones this test can get hold of and prepare first.
    Neutering the method wholesale would therefore also disable `__init__`'s
    build, leave every section storeless, and make every check return on its
    first line -- a false pass shaped exactly like a fix. Written that way, this
    test reported no drift at all.

    So the patch reverts the REPAIR and not the BUILD: a section's first call --
    `__init__`'s -- is passed through, and every later one, which is what this
    fixup added, is dropped.
    """
    from PyReconstruct.modules.datatypes.section import Section

    name = _aSmoothableObject(real_series)
    original = Section.resyncColumnarStore
    built = []

    def onlyTheBuild(self):
        if self._columns is None:   # __init__'s call: the store must exist
            original(self)
            built.append(self.n)
            return
        return                      # the repair this fixup added: reverted

    monkeypatch.setattr(Section, "resyncColumnarStore", onlyTheBuild)

    capsys.readouterr()
    ## It no longer raises INSIDE the operation, which is the user-visible half
    ## of D11: `smoothObject` calls `section.save()` in its own loop, so the
    ## raise used to abort a multi-section pass partway through and leave every
    ## later section un-smoothed. The pass now completes.
    real_series.smoothObject([name], log_event=False)
    message = _driftReports(capsys)

    assert built, (
        "no section ever built a store, so the check never ran and this would "
        "have passed for the wrong reason"
    )
    assert message, "the drift went unreported, so nothing signals the edit"
    assert "points:" in str(message), (
        "the drift was caught but not attributed to `points`: "
        f"{message}"
    )


def test_deleting_duplicate_traces_leaves_the_section_saveable(real_section):
    """`Series.deleteDuplicateTraces` -- the TENTH site, via `mergeTags`.

    `trace1.mergeTags(trace2)` rewrites `tags` in place on a trace the section
    keeps; `section.removeTrace(trace2)` is hooked and repairs `trace2`'s row,
    but nothing repaired `trace1`'s. It only drifts when the two duplicates
    carry different tags -- rare, and exactly the messy series this clean-up
    operation is run on.

    Driven at the mechanism: the call, the receiver and the ordering are the
    operation's own, and this is the test that attributes the drift to `tags`.
    It does NOT pin the production repair -- deleting
    `series.py`'s `resyncColumnarStore()` call leaves it green, because it never
    calls `deleteDuplicateTraces`. `test_a_planted_duplicate_pair_is_merged_and_
    persisted_by_the_real_operation` below is the one that goes red for that,
    and it is what the "pinned by a test that reverts the repair" claim rests
    on.
    """
    name = next(
        c for c in sorted(real_section.contours, key=str)
        if len(real_section.contours[c]) >= 2
    )
    first, second = (
        real_section.contours[name][0], real_section.contours[name][1]
    )
    second.tags = {"a_regression_tag"}
    real_section.resyncColumnarStore()   # start from a store that agrees

    first.mergeTags(second)              # deleteDuplicateTraces' exact call
    real_section.resyncColumnarStore()   # ...and its repair
    real_section.save()

    assert "a_regression_tag" in real_section.contours[name][0].tags


def test_mergeTags_on_a_held_trace_without_the_repair_really_drifts(
    real_section, capsys
):
    """Without the repair, the same two calls drift -- naming `tags`.

    Reported by the save-time rebuild rather than raised by a save-time
    comparison, since D11. Same drift, same column, same cause.
    """
    name = next(
        c for c in sorted(real_section.contours, key=str)
        if len(real_section.contours[c]) >= 2
    )
    first, second = (
        real_section.contours[name][0], real_section.contours[name][1]
    )
    second.tags = {"a_regression_tag"}
    real_section.resyncColumnarStore()

    first.mergeTags(second)

    capsys.readouterr()
    real_section.save()
    message = _driftReports(capsys)

    assert message, "the drift went unreported, so nothing signals the edit"
    assert "tags:" in message, (
        f"the drift was caught but not attributed to `tags`: {message}"
    )


def _plantADuplicatePair(section, name="a_planted_duplicate", tags=("one", "two")):
    """Two identical closed traces under one name, carrying different tags.

    `deleteDuplicateTraces` only reaches `mergeTags` when it finds a pair that
    `Trace.overlaps` accepts, and it only *drifts* when the two carry different
    tags. The fixture series offers no such pair, and the earlier version of
    this file took that as a reason to drop down to the mechanism -- which is
    exactly how the production repair came to be unguarded. Planting the pair is
    eight lines and keeps the real function in the loop.

    Identical point lists rather than merely overlapping ones, because
    `Trace.overlaps` short-circuits on `pointsMatch` before it ever needs
    `getOverlapRatio`, so the pair is a duplicate at any threshold and the test
    does not depend on a ratio computation it is not about.

    Both traces go in through `Section.addTrace`, which is hooked, so the store
    agrees before the operation starts: a test that began from a drifted store
    would raise for the wrong reason.
    """
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    for tag in tags:
        trace = Trace(name, (255, 0, 0), closed=True)
        trace.points = list(points)
        trace.tags = {tag}
        section.addTrace(trace, log_event=False)
    section.save()
    return name


def test_a_planted_duplicate_pair_is_merged_and_persisted_by_the_real_operation(
    real_series
):
    """`Series.deleteDuplicateTraces`, driven -- the pin for the TENTH site.

    "Delete duplicate traces" is a shipped series-wide clean-up. The real
    function loads its own sections through `enumerateSections` and calls
    `section.save()` itself, so with the repair gone the mismatch raises *inside
    the operation*: the clean-up dies partway through and every later section
    goes unprocessed. That is what makes this test go red rather than merely
    fail an assertion at the end.

    Written this way on purpose. The two tests above reproduce
    `mergeTags`-then-`save` inline and pass whatever `deleteDuplicateTraces`
    does, so no revert of the production repair can make them red -- which a
    reviewer established by deleting the call and running the whole suite green.
    This one calls the shipped function with nothing patched.

    The survivors are read back **off disk after a reload**, so the merged tags
    asserted here are the persisted bytes and not the in-memory objects the
    operation happened to be holding.
    """
    number = sorted(real_series.sections)[0]
    name = _plantADuplicatePair(real_series.loadSection(number))

    ## The real, shipped entry point. Its own `section.save()` is what raises
    ## when the repair is missing.
    removed = real_series.deleteDuplicateTraces(0.95, log_event=False)

    assert removed.get(number) and name in removed[number], (
        f"the operation did not report removing a duplicate of {name!r}: "
        f"{removed}"
    )

    survivors = real_series.loadSection(number).contours[name]
    assert len(survivors) == 1, (
        f"expected one survivor of the planted pair, found {len(survivors)}"
    )
    assert survivors[0].tags == {"one", "two"}, (
        "the surviving trace's merged tags did not reach the disk: "
        f"{sorted(survivors[0].tags)}"
    )


# --- the two sites that need a live field ------------------------------------
#
# `cutTrace` and `smoothTraces` are methods on `FieldWidget`, and both reach the
# section's own traces through the field's selection. Neither is drivable
# against a stand-in the way `findFlag` is: `cutTrace` needs
# `section_layer.traceToPix` and a real `Series.getOption`, and `smoothTraces`
# is wrapped in `trace_function`, which reads the table manager and calls
# `mainwindow.saveAllData()` before the method body runs.
#
# So these two use the same live-`main_window` harness `tests/test_knife_cut_
# guards.py` uses, marked `gui` per test rather than per module because the rest
# of this file must keep running under `-m "not gui"`.
#
# `local_series_settings` is not optional in either. `cutTrace` reads
# `knife_del_threshold` and `smoothTraces` reads `roll_window`, both global-scope
# options, and `Series.getOption` writes the default back when a key is absent --
# so without the injected store a run of this file would leave keys in the
# developer's real `QSettings`.


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from `field_widget_2_trace`.

    That module does `from ... import notify`, binding the function in its own
    namespace, so patching the helper at its source has no effect. Required
    rather than convenient: offscreen, `notify` falls through to a console branch
    ending in `input()`, which raises under pytest's capture and hangs under
    `-s`, and the refusal below trips it on purpose.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    notices = []
    monkeypatch.setattr(
        field_widget_2_trace,
        "notify",
        lambda message, *a, **kw: notices.append(message),
    )
    return notices


def _aReferenceContour(section):
    """A contour with points, to size the planted traces against.

    Only so the planted geometry lands where the field is actually looking and
    `traceToPix` returns something sane; nothing here depends on which contour it
    is.
    """
    for name in sorted(section.contours, key=str):
        if section.contours[name] and len(section.contours[name][0].points) >= 3:
            return section.contours[name][0]
    raise AssertionError("the fixture section the window opens on has no traces")


def _plantASelectedBowtiePair(field, name="a_planted_bowtie"):
    """Two same-named self-crossing closed traces, selected, tagged differently.

    Every element is one `cutTrace` needs to reach its tag merge and then refuse:

      * **two of them**, or the `for trace in traces[1:]` loop is empty and
        nothing is merged;
      * **the same name**, or `cutTrace` refuses at "Select a single object to
        cut at a time" before the merge;
      * **different tags**, or `merged_any` stays False and the store never
        drifts -- the false-negative-from-a-bad-fixture trap that let `mergeTags`
        look clean to a reviewer on a single-trace contour;
      * **self-crossing and closed**, so `uncuttable_closed_traces` refuses the
        cut *after* the merge, which is the whole point: the drift outlives an
        operation the user was told did nothing.

    The two diagonals of an existing object's bounding box, taken in an order
    that crosses in the middle -- the shape freehand tracing makes when a stroke
    doubles back over itself. Asserted invalid rather than assumed, because a
    fixture that quietly stopped being a bowtie would make this test pass while
    proving nothing.
    """
    reference = [tuple(p) for p in _aReferenceContour(field.section).points]
    xs = [p[0] for p in reference]
    ys = [p[1] for p in reference]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    points = [(x0, y0), (x1, y1), (x1, y0), (x0, y1)]

    from shapely.geometry import Polygon

    assert not Polygon(points).is_valid, "the planted trace is not a bowtie"

    planted = []
    for tag in ("tag_from_first", "tag_from_second"):
        trace = Trace(name, (0, 255, 0), closed=True)
        trace.points = list(points)
        trace.tags = {tag}
        field.section.addTrace(trace, log_event=False)   # hooked: store agrees
        planted.append(trace)

    field.section.selected_traces = list(planted)
    return name, planted


def _aScalpelAcross(field, trace):
    """A knife stroke, in pixel coordinates, that crosses `trace`.

    Lifted from `tests/test_knife_cut_guards.py`. `cutTrace` refuses a
    self-crossing trace before it looks at the stroke at all, so this only has to
    be a well-formed argument -- but it is the real shape a real cut arrives as,
    and passing a degenerate one would be testing a different early return.
    """
    pix = field.section_layer.traceToPix(trace)
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    mid_y = (min(ys) + max(ys)) / 2
    left, right = min(xs) - 10, max(xs) + 10
    steps = 20
    return [(left + (right - left) * i / steps, mid_y) for i in range(steps + 1)]


@pytest.mark.gui
def test_a_refused_scalpel_cut_leaves_the_section_saveable(
    main_window, local_series_settings, field_notices
):
    """`FieldWidgetTrace.cutTrace`, driven -- the pin for the TWELFTH site.

    THE USER PATH
    -------------
    Select two traces of one object -> scalpel across them -> one of them
    crosses itself, so the cut is refused and the user is told the object was
    left unchanged -> but the tag merge above the refusal already ran, in place,
    on a trace the section still holds. The next `Section.save()` -- an autosave,
    a section change, a mouse-wheel scroll -- then raises
    `ColumnarDualWriteMismatch` at the user for an action they already watched
    get refused, and keeps raising.

    `test_merging_tags_across_a_selection_leaves_the_section_saveable` above
    reproduces that merge inline and therefore passes whatever `cutTrace` does;
    deleting the production repair leaves it green. This calls the real method
    with nothing patched but `notify`, so the repair is what keeps the final
    `save()` from raising.
    """
    local_series_settings(main_window)
    field = main_window.field
    name, planted = _plantASelectedBowtiePair(field)
    first = planted[0]

    ## Baseline: the store agrees before the cut, so a raise below is the cut's.
    field.section.save()

    refused = field.cutTrace(_aScalpelAcross(field, first))

    ## It refused, visibly, and left the object alone -- the guarantee the user
    ## was given.
    assert refused is False
    assert len(field_notices) == 1
    assert field_notices[0].startswith(
        "A selected trace's outline crosses over itself"
    )
    assert "The object was left unchanged." in field_notices[0]
    assert len(field.section.contours[name]) == 2
    assert field.section.contours[name][0] is first, "the trace was replaced"

    ## And it merged the tags on its way to that refusal, in place, on a trace
    ## the section still holds. This is the drift.
    assert first.tags == {"tag_from_first", "tag_from_second"}

    ## The store came with it. Before the repair this raised, and kept raising.
    field.section.save()

    ## The user's next edit, which is where the raise actually used to arrive.
    field.section.addTrace(_aTrace(field.section))
    field.section.save()


@pytest.mark.gui
def test_smoothing_the_selection_leaves_the_section_saveable(
    main_window, local_series_settings
):
    """`FieldWidgetTrace.smoothTraces`, driven -- the pin for the ELEVENTH site.

    "Smooth traces" is a shipped field action on the selection. `traces` is the
    section's own selection, not copies, so `Trace.smooth` rewrites `points` in
    place on traces the section holds, from outside `Section`, where no
    dual-write hook sees it. `field_interaction` then calls `saveState()` and
    `generateView()`, neither of which repairs the store, so the drift survives
    to whichever later `Section.save()` happens first.

    This is the sibling of `Series.smoothObject` and it had no test of any kind
    until now -- deleting its repair left all 5,939 tests green.

    Called with no arguments: `trace_function` reads the selection off the
    section (or the trace table) and inserts it as the first parameter, and the
    wrapper returns None, so the assertion that the method did something has to
    be that `points` actually moved. A contour whose traces are all too short to
    smooth would leave `points` untouched and make this pass while proving
    nothing, so the contour is chosen for having enough points.
    """
    local_series_settings(main_window)
    field = main_window.field
    name = next(
        c for c in sorted(field.section.contours, key=str)
        if field.section.contours[c]
        and all(len(t.points) >= 3 for t in field.section.contours[c])
    )
    traces = list(field.section.contours[name])
    before = [[tuple(p) for p in trace.points] for trace in traces]

    ## Baseline: the store agrees before the smooth.
    field.section.save()
    field.section.selected_traces = list(traces)

    ## The real, shipped method.
    field.smoothTraces()

    after = [[tuple(p) for p in trace.points] for trace in traces]
    assert after != before, (
        f"`smooth` left {name!r} untouched, so no drift was possible and this "
        "would have passed for the wrong reason"
    )

    ## The store came with it.
    field.section.save()


@pytest.mark.gui
def test_smoothTraces_without_the_repair_really_would_have_drifted(
    main_window, local_series_settings, monkeypatch, capsys
):
    """The `smoothTraces` repair is load-bearing, and the drift is in `points`.

    Same shape as `test_smoothObject_without_the_repair_really_would_have_
    drifted`: the patch reverts the REPAIR and not the BUILD. Neutering
    `resyncColumnarStore` wholesale would also disable `__init__`'s call, leave
    the section storeless and make every check return on its first line -- a
    false pass shaped exactly like a fix. The store is already built by the time
    the window is up, so patching the bound method on this one section reverts
    exactly the call this fixup added and nothing else.

    The section is repaired again at the end. Left drifted, it takes the
    `main_window` fixture's own teardown down with it, which reports as an error
    beside the pass and buries the result.
    """
    local_series_settings(main_window)
    field = main_window.field
    section = field.section
    name = next(
        c for c in sorted(section.contours, key=str)
        if section.contours[c]
        and all(len(t.points) >= 3 for t in section.contours[c])
    )
    section.save()

    assert section._columns is not None, "the store was never built"
    original = type(section).resyncColumnarStore
    monkeypatch.setattr(section, "resyncColumnarStore", lambda: None)

    section.selected_traces = list(section.contours[name])
    field.smoothTraces()

    capsys.readouterr()
    section.save()
    message = _driftReports(capsys)

    assert message, "the drift went unreported, so nothing signals the edit"
    assert "points:" in message, (
        f"the drift was caught but not attributed to `points`: {message}"
    )

    ## Hand the section back consistent, or teardown's save raises too.
    original(section)


def test_merging_tags_across_a_selection_leaves_the_section_saveable(
    real_section, capsys
):
    """`FieldWidgetTrace.cutTrace`'s tag merge -- the TWELFTH site.

    `traces = self.section.selected_traces.copy()` copies the LIST; the traces
    in it are the section's own. `example_trace.tags.add(tag)` then writes a
    store-backed column in place, and three refusal paths return before
    `deleteTraces` would have dropped the drifted rows.

    Doubly invisible before this round: the write is an in-place mutation of the
    column's own container -- neither an assignment to a column nor a call to a
    `Trace` method -- and the reach is `selected_traces`, which the predicate
    did not know was a route to a section's traces.

    Driven at the mechanism: the selection, the receiver and the in-place
    `tags.add` are the widget's own, and this is the test that shows the same
    state both raises without the repair and saves with it. It does NOT pin the
    production repair -- it never calls `cutTrace`, so deleting the call in
    `field_widget_2_trace.py` leaves it green.
    `test_a_refused_scalpel_cut_leaves_the_section_saveable` above is the one
    that goes red for that.
    """
    name = next(
        c for c in sorted(real_section.contours, key=str)
        if len(real_section.contours[c]) >= 2
    )
    real_section.selected_traces = list(real_section.contours[name][:2])
    real_section.selected_traces[1].tags = {"a_cut_tag"}
    real_section.resyncColumnarStore()

    traces = real_section.selected_traces.copy()
    example_trace = traces[0]
    for trace in traces[1:]:
        for tag in trace.tags:
            example_trace.tags.add(tag)

    ## Without the repair this drifts, and the save-time rebuild says so,
    ## naming `tags`.
    capsys.readouterr()
    real_section.save()
    assert "tags:" in _driftReports(capsys)

    ## With it, the same state saves without a word.
    real_section.resyncColumnarStore()
    capsys.readouterr()
    real_section.save()
    assert _driftReports(capsys) == "", (
        "a repaired section still reported drift at save"
    )
    assert "a_cut_tag" in real_section.contours[name][0].tags


def test_deleting_an_object_leaves_every_touched_section_consistent(real_series):
    """`Series.deleteObjects` drops a contour key from outside `Section`.

    It also removes from a list it is iterating, so `removeTrace` is not reached
    for every trace of a multi-trace contour. Either alone leaves rows in the
    store for traces the object model no longer has.
    """
    name = sorted(real_series.data["objects"])[0]

    touched = [
        snum for snum, section in real_series.enumerateSections(show_progress=False)
        if name in section.contours and len(section.contours[name])
    ]
    assert touched, "the fixture object is on no section"

    real_series.deleteObjects([name])

    for snum in touched:
        section = real_series.loadSection(snum)
        assert name not in section.contours or section.contours[name].isEmpty()
        section._assertColumnsMatchObjectModel("after deleteObjects")
        ## And the section takes another edit without raising, which is what the
        ## user does next and what used to fail.
        section.addTrace(_aTrace(section))
        section.save()


def test_a_section_edited_after_an_undo_does_not_raise(real_section, real_series):
    """The undo restore, driven through `SectionStates` itself.

    `undoState` replaces `section.contours` from outside `Section` -- the whole
    dict on the single-state branch, one key at a time on the multi-state one --
    and both branches end in the repair. Without it the `addTrace` at the bottom
    of this test raises `ColumnarDualWriteMismatch`, which is a crash in the
    user's face on the first stroke after Ctrl+Z.
    """
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    states = SectionStates(real_section, real_series)

    before = len(real_section.tracesAsList())
    states.addState(real_section, real_series)
    real_section.addTrace(_aTrace(real_section, name="undone_by_the_dual_write_test"))
    assert len(real_section.tracesAsList()) == before + 1

    states.undoState(real_section, real_series)
    assert len(real_section.tracesAsList()) == before, (
        "the undo restored nothing, so this test is not exercising the rebind"
    )

    ## The rebind really did replace the trace objects: this is the state that
    ## used to leave `_column_rows` keyed on discarded traces.
    real_section._assertColumnsMatchObjectModel("after an undo")
    assert set(map(id, real_section._column_rows)) == {
        id(t) for t in real_section.tracesAsList()
    }

    ## The next real edit, which is what actually broke.
    real_section.addTrace(_aTrace(real_section, name="the_stroke_after_the_undo"))
    real_section.save()


def test_a_section_edited_after_a_redo_does_not_raise(real_section, real_series):
    """Same for `redoState`, which restores contour keys one at a time.

    Asserted on the store rather than on how much the redo restored: what this
    test owns is that the rebind leaves a consistent store and a section that
    accepts another edit. The fixture's redo happens to restore the pre-edit
    contours here, and pinning that number would make this test fail for
    reasons that have nothing to do with the dual write.
    """
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    states = SectionStates(real_section, real_series)

    states.addState(real_section, real_series)
    real_section.addTrace(_aTrace(real_section, name="redone_by_the_dual_write_test"))
    states.undoState(real_section, real_series)
    assert states.redo_states, "nothing to redo, so this test proves nothing"

    states.redoState(real_section, real_series)

    real_section._assertColumnsMatchObjectModel("after a redo")
    assert set(map(id, real_section._column_rows)) == {
        id(t) for t in real_section.tracesAsList()
    }
    real_section.addTrace(_aTrace(real_section, name="the_stroke_after_the_redo"))
    real_section.save()


def test_the_generation_counter_survives_a_rebuild(real_section):
    """A resync must not restart the counter at 0.

    `SectionColumns`' own docstring says the generation "is monotonic and is
    never reset by anything", because a cache stores the value it was built at
    and compares. A rebuild makes a NEW store, so without carrying the count
    forward an undo would hand every cache a generation below the one it holds
    and every cache would conclude it was current -- the stale-render bug class
    the counter exists to prevent, arriving through the repair. Unreachable
    under the gate, because nothing outside a test rebuilt a store; live now.
    """
    for _ in range(5):
        real_section.addTrace(_aTrace(real_section))
    before = real_section._columns.generation
    assert before > 0, "the setup did not move the counter at all"

    real_section.resyncColumnarStore()

    ## `>`, not `>=`. Equality is the failure this counter exists to prevent:
    ## a cache holding `before` and reading `before` back off a store that was
    ## thrown away and rebuilt underneath it concludes it is current. The
    ## rebuild itself has to be the advance.
    assert real_section._columns.generation > before, (
        f"the rebuilt store came back at generation "
        f"{real_section._columns.generation}, not above the {before} a cache "
        "may already hold"
    )
    ## And it keeps moving from there.
    moved = real_section._columns.generation
    real_section.addTrace(_aTrace(real_section))
    assert real_section._columns.generation > moved


def test_the_generation_advances_even_when_the_resync_empties_the_section(
    real_section
):
    """The case that seeding with `previous` rather than `previous + 1` missed.

    `fromSection` bumps once per appended row, so a rebuild seeded with the
    outgoing count only moves past it if it has at least one row to append. A
    resync that produces ZERO rows would not advance at all -- and this is not
    a contrived shape: `Series.deleteObjects` deletes every contour key on a
    section and then calls the repair, so deleting the last object on a section
    resyncs an empty one. A cache holding the old generation would then read
    the same value back off a store that had just been emptied and conclude it
    was current, which is exactly the stale-render class the counter exists to
    prevent, arriving through the repair rather than the fault.
    """
    for _ in range(5):
        real_section.addTrace(_aTrace(real_section))
    before = real_section._columns.generation
    assert before > 0, "the setup did not move the counter at all"

    ## `Series.deleteObjects`' own sequence: drop every contour key from
    ## outside `Section`, then repair.
    for name in list(real_section.contours):
        del real_section.contours[name]
    real_section.resyncColumnarStore()

    assert len(real_section._columns) == 0, "the setup did not empty the store"
    assert real_section._columns.generation > before, (
        f"an emptying resync left the generation at "
        f"{real_section._columns.generation}, so a cache holding {before} "
        "would conclude it was current against a store that now has no rows"
    )


def test_the_whole_section_rebuild_runs_on_save(real_section, capsys):
    """The coarse net's new home, and its new kind. D11.

    Per-mutation checking is targeted at the row that moved and cannot see drift
    caused from outside the class. `save()` is the one non-per-frame path that
    is already O(section), so the whole-section work runs there.

    What runs there changed from a COMPARISON to a REBUILD. The comparison
    asked whether the store already agreed and raised when it did not, which
    made a missed out-of-class edit site into an unsaveable section; the
    rebuild makes the store agree, so the question does not arise. Three
    claims, and all three are the point:

      1. `save()` does not raise, however badly the store had drifted,
      2. the store agrees with the object model afterwards, and
      3. the drift is still reported, so nothing goes silently unnoticed.
    """
    trace = _anyTrace(real_section)
    real_section.contours[trace.name].remove(trace)  # out of class, no hook

    capsys.readouterr()
    real_section.save()                                     # (1)
    real_section._assertColumnsMatchObjectModel("after the rebuild")   # (2)

    report = _driftReports(capsys)                          # (3)
    assert report, "the drift was absorbed without a word"
    assert "the row map was stale" in report


def test_a_clean_save_keeps_the_store_it_already_had(real_section, capsys):
    """The rebuild is discarded when it changes nothing, and that is deliberate.

    A rebuild produces a NEW store with a higher generation counter, and a save
    fires on every section change -- a mouse-wheel scroll included. Adopting
    one unconditionally would hand every generation-keyed cache a fresh number
    several times a second and make the counter useless for the one thing the
    store's own docstring says it exists for.

    So `_rebuildColumnarStoreForSave` compares the rebuild against the store it
    would replace and keeps the existing one when they agree. Pinned on the
    three things a consumer can observe: the store object itself, its
    generation, and the row map.
    """
    real_section.addTrace(_aTrace(real_section, name="a_perfectly_normal_edit"))

    store = real_section._columns
    generation = store.generation
    row_map = real_section._column_rows

    capsys.readouterr()
    real_section.save()

    assert _driftReports(capsys) == "", "a clean save reported drift"
    assert real_section._columns is store, (
        "a clean save swapped the store for an equivalent rebuild, so every "
        "generation-keyed cache was invalidated for nothing"
    )
    assert real_section._columns.generation == generation
    assert real_section._column_rows is row_map


def _installAStoreCarryingIDs(section):
    """Rebuild the section's store with an id issuer wired in, and map the rows.

    Nothing in the application injects one today -- `Section.__init__` reaches
    `resyncColumnarStore`, and a section with no outgoing store has no issuer
    to carry into the new one, so every row's id is `None` and `Trace` carries
    no id attribute at all. The tests below are about what happens on the day
    one IS wired (D10,
    `specs/phase1-foreign-trace-id-acquisition-2026-08-05.md`), so they have to
    build that state by hand.

    Mirrors `resyncColumnarStore`'s own row-map construction rather than
    reimplementing it differently, so the section is in the state the
    production path would put it in, plus the issuer.
    """
    from PyReconstruct.modules.datatypes.columnar_store import SectionColumns
    from PyReconstruct.modules.datatypes.trace_id import TraceIDIssuer

    section._columns = SectionColumns.fromSection(
        section, id_issuer=TraceIDIssuer(),
        generation=section._columns.generation + 1,
    )
    section._column_rows = {}
    for name in sorted(section.contours, key=str):
        for trace, row in zip(
            section.contours[name].getTraces(),
            section._columns.rowsForContour(name),
        ):
            section._column_rows[trace] = row

    ids = {
        row: section._columns.getID(row)
        for row in section._column_rows.values()
    }
    assert all(ids.values()), "the setup produced no ids, so this proves nothing"
    return ids


def test_a_save_does_not_re_identify_the_traces_it_saves(real_section):
    """An ordinary save leaves every row's id alone. The D10 interaction.

    D11 puts a rebuild on `save()`, and `SectionColumns.fromSection` ISSUES ids
    rather than carrying them: it appends every row without a `trace_id`, so a
    rebuild with an issuer wired re-identifies the whole section and leaks the
    outgoing ids into the issuer's taken-set. An id is meant to be a birth
    certificate. A save that re-mints one for every trace in the section, on
    every mouse-wheel scroll, would be a severe regression hiding inside a
    safety-mechanism swap.

    It does not happen, and the reason is structural rather than lucky: a save
    that finds no drift keeps the store it already had and discards the rebuild
    entirely -- ids, generation, row numbers and all. That property is asserted
    here against a store that actually carries ids, because with the production
    default (`id_issuer=None`, every id `None`) the assertion would pass
    vacuously.

    Carrying ids through `fromSection` is D10's scope call, not this change's;
    see the test below for what remains uncovered and why it is pinned rather
    than fixed here.
    """
    before = _installAStoreCarryingIDs(real_section)
    store = real_section._columns

    real_section.save()
    real_section.save()
    real_section.save()

    assert real_section._columns is store, "the save swapped the store"
    after = {
        row: real_section._columns.getID(row)
        for row in real_section._column_rows.values()
    }
    assert after == before, (
        "an ordinary save re-identified traces: every one of these is a trace "
        f"whose birth certificate was reissued by a save\n{before} -> {after}"
    )


def _idsByTrace(section):
    """`{Trace: id}` for the section's store, through its own row map.

    Keyed on the trace rather than on the row number because a rebuild is
    entitled to renumber rows; what it is not entitled to do is change which id
    belongs to which trace.
    """
    return {
        trace: section._columns.getID(row)
        for trace, row in section._column_rows.items()
    }


def test_a_drifted_save_keeps_the_ids_it_can_correlate(real_section):
    """The residue D11 pinned as a known limitation. D10 closed it.

    This test is the inversion of D11's `test_a_drifted_save_does_lose_the_ids
    _and_that_is_D10s_to_fix`, which asserted the loss and said in its own body
    that the day `fromSection` learned to carry ids it should be deleted. This
    is that day, and the assertion is turned over rather than dropped, so the
    property it was watching still has a test on it.

    A save that finds drift adopts the rebuild -- that has not changed. What
    changed is that the rebuild now carries every id it can correlate through
    the outgoing row map, so adopting it is no longer destructive.
    """
    _installAStoreCarryingIDs(real_section)
    before = _idsByTrace(real_section)

    victim = _anyTrace(real_section)
    victim.setHidden(not victim.hidden)   # out of class, unrepaired: drift

    real_section.save()

    after = _idsByTrace(real_section)
    assert after == before, (
        "a drifted save re-identified traces it had already identified: the "
        f"rebuild was adopted without carrying the ids\n{before} -> {after}"
    )
    assert all(v is not None for v in after.values()), (
        "every id came back None, so this passed by comparing nothing"
    )


def test_a_no_op_rebuild_does_not_re_identify_an_unchanged_trace(real_section):
    """D10's part one, against the defect exactly as it was reproduced.

    `specs/phase1-foreign-trace-id-acquisition-2026-08-05.md` §5 measured this
    directly and recorded `PRESERVED: False`: a trace that nothing touched came
    out of a rebuild under a new id. `resyncColumnarStore()` is reached from
    fourteen call sites -- undo, redo, six in `series.py`, autoseg, three in
    the field widget, `Section.__init__` and `_dualWriteResync` -- and since
    D11 from `save()` as well, so this ran several times a second.

    An id is a birth certificate. Re-minting one makes "the same trace,
    edited" indistinguishable from "a different trace" to anything that later
    merges, which `trace_id.py` names as the one property a merge cannot lose.
    """
    _installAStoreCarryingIDs(real_section)
    before = _idsByTrace(real_section)
    assert before and all(v is not None for v in before.values())

    real_section.resyncColumnarStore()

    after = _idsByTrace(real_section)
    assert after == before, f"the rebuild re-identified traces\n{before} -> {after}"


def test_a_rebuild_carries_the_issuer_and_does_not_leak_dead_ids(real_section):
    """Two halves of the same loss, and the first was worse than §5 recorded.

    §5 measured the `fromSection` layer, where an issuer IS passed and every
    row takes the `issue()` arm -- so an id changed. At the `Section` layer it
    was worse: `_rebuildColumnarStore` passed no `id_issuer` at all, so the
    replacement store had none and every id came back `None`. The series' id
    index went with the store it was attached to.

    The leak is the other half. Every rebuild that re-issued left the outgoing
    id in the issuer's taken-set with no row holding it, so a long session's
    index filled with ids belonging to nothing.
    """
    _installAStoreCarryingIDs(real_section)
    issuer = real_section._columns.id_issuer
    assert issuer is not None
    taken_before = len(issuer.taken)
    trace_count = len(real_section._column_rows)

    for _ in range(5):
        real_section.resyncColumnarStore()

    assert real_section._columns.id_issuer is issuer, (
        "the rebuild dropped the issuer, so the series' id index was discarded "
        "with the store it happened to be attached to"
    )
    assert all(v is not None for v in _idsByTrace(real_section).values())
    assert len(issuer.taken) == taken_before == trace_count, (
        f"five no-op rebuilds moved the taken-set {taken_before} -> "
        f"{len(issuer.taken)} for {trace_count} traces: each one leaked the "
        f"ids it replaced"
    )


def test_a_rebuild_issues_only_for_a_trace_the_store_has_not_seen(real_section):
    """Carrying ids must not stop a genuinely new trace from getting one.

    The fall-through arm: a trace the outgoing row map does not hold is a
    trace this store has never seen -- just created, or arrived through an
    import -- and it still takes the issuer's `issue()` arm.
    """
    _installAStoreCarryingIDs(real_section)
    before = _idsByTrace(real_section)

    ## Added out of class, straight onto the contour, which is exactly the
    ## shape `resyncColumnarStore()` is the documented repair for.
    name = sorted(real_section.contours, key=str)[0]
    newcomer = _aTrace(real_section, name=name)
    real_section.contours[name].append(newcomer)
    real_section.resyncColumnarStore()

    after = _idsByTrace(real_section)
    assert {t: i for t, i in after.items() if t in before} == before, (
        "adding one trace re-identified the traces already there"
    )
    assert newcomer in after and after[newcomer] is not None, (
        "the new trace was not issued an id"
    )
    assert after[newcomer] not in before.values(), (
        "the new trace was handed an id another trace already holds"
    )


def test_a_rebuild_reports_no_clash_against_the_sections_own_ids(real_section):
    """The distinction D10 turns on, asserted at the layer that could break it.

    A rebuild re-appends traces this series ALREADY issued ids for. Those ids
    are in the issuer's taken-set precisely because this series put them there,
    so routing the carry through `adopt()` would report a clash of every trace
    against itself -- and a report that is wrong every time trains a reader to
    ignore the one that is right. The carry therefore uses `appendRow`'s
    `trace_id=` arm, which does not consult the issuer at all; `foreign_id=` is
    the arm that adopts.
    """
    _installAStoreCarryingIDs(real_section)
    issuer = real_section._columns.id_issuer

    for _ in range(3):
        real_section.resyncColumnarStore()
        real_section.save()

    assert issuer.collisions == (), (
        "a rebuild of this section's own traces reported an id clash against "
        f"itself: {issuer.collisions}"
    )
    assert real_section._columns.foreign_id_reissues == (), (
        "a rebuild reissued an id as though it had arrived from another series"
    )


def test_the_drift_report_is_capped_rather_than_flooding_the_log(
    real_section, capsys
):
    """A whole-section drift must not evict the log it is written to.

    The report lands in the per-user log file through the stdout/stderr tee,
    and that file rotates at 2 MB. An alignment applied from outside this class
    drifts every trace on the section -- 1,291 of them on the busiest section
    of the production dataset on record -- so an uncapped report would push out
    the history somebody opened the log to read.
    """
    from PyReconstruct.modules.datatypes.section import DRIFT_REPORT_LIMIT

    while len(real_section.tracesAsList()) <= DRIFT_REPORT_LIMIT + 5:
        real_section.addTrace(_aTrace(real_section), log_event=False)

    for trace in real_section.tracesAsList():
        trace.points = [(x + 7.5, y + 7.5) for x, y in trace.points]

    capsys.readouterr()
    real_section.save()
    report = _driftReports(capsys)

    assert "points" in report
    assert "and at least" in report, "a whole-section drift was not capped"
    ## One line per complaint, plus the leading sentence the marker split left
    ## on the first line and the "... and at least N more" tail.
    assert len(report.splitlines()) <= DRIFT_REPORT_LIMIT + 2, (
        f"the cap did not hold:\n{report}"
    )


def test_a_thirteenth_edit_site_would_no_longer_cost_the_session(real_section):
    """The risk class D11 was taken to remove, stated as a property.

    Every previous round of this work ended by claiming a complete list of
    out-of-class edit sites, and four of those claims were wrong. This does not
    depend on the list being right: whatever the drift, however it arrived,
    `save()` absorbs it and the next save is clean too. That is the difference
    between "the count is finally correct" and "the count no longer decides
    whether a user can save".

    Four shapes at once, chosen to span both classes the twelve known sites
    fall into: a value written in place, geometry rewritten in place, a whole
    contour dropped, and the undo-style rebind that leaves every value matching
    and every row-map key discarded.
    """
    victim = _anyTrace(real_section)
    victim.setHidden(not victim.hidden)
    victim.tags = {"a_thirteenth_site"}

    geometric = _anyTrace(real_section)
    geometric.points = [(x + 3.5, y - 1.25) for x, y in geometric.points]

    dropped = sorted(real_section.contours, key=str)[-1]
    del real_section.contours[dropped]

    _undoStyleRestore(real_section)

    real_section.save()
    real_section._assertColumnsMatchObjectModel("after four kinds of drift")

    ## And the section is not poisoned: it takes the next edit and the next
    ## save, which is exactly what the comparison-based check refused to do.
    real_section.addTrace(_aTrace(real_section, name="the_next_stroke"))
    real_section.removeTrace(_anyTrace(real_section))
    real_section.save()


def test_an_unrepaired_out_of_class_edit_still_raises_before_the_next_save(
    real_section
):
    """Why the twelve repair calls STAY, and the scan that finds them with them.

    It would be easy to read "the rebuild removes the missed-site class" as
    "the repair calls are now redundant". They are not, and this is the test
    that says so rather than a paragraph claiming it.

    Rebuilding at `save()` fixes the store AT `save()`. It does nothing for the
    window between the out-of-class edit and the next save, and that window is
    where these sites actually bit -- a user edits, they do not save first.
    Both shapes still raise there, through the per-mutation hooks, which D11
    did not touch:

      * an IN-PLACE write leaves one row stale, so the next hooked mutation of
        that same trace runs `_assertRowMatchesTrace` over the whole row and
        raises on the column that drifted, and
      * a REBIND leaves `_column_rows` keyed on discarded `Trace` objects, so
        the next hooked mutation of a surviving trace cannot find its row.

    If a future change ever does make these redundant, this test goes red and
    the repair calls can go with it. Until then it is the evidence for keeping
    them.
    """
    ## The in-place shape. A `hidden` write nothing mirrored, then an unrelated
    ## edit to the same trace through a hooked mutator.
    victim = _anyTrace(real_section)
    victim.setHidden(not victim.hidden)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.closeTraces([victim], closed=not victim.closed)
    assert "hidden:" in str(caught.value), (
        f"the stale row was reached but not attributed: {caught.value}"
    )

    real_section.resyncColumnarStore()

    ## The rebind shape, which no value comparison can see.
    _undoStyleRestore(real_section)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.removeTrace(_anyTrace(real_section))
    assert "holds no row for" in str(caught.value)


def test_a_shadow_mismatch_no_longer_costs_the_save(real_section, capsys):
    """Divergence is still reported, and it no longer vetoes the user's data.

    THE ORDERING, AND WHY IT CHANGED
    --------------------------------
    The whole-section comparison used to run BEFORE the write, so a section
    whose store disagreed with its object model raised instead of being
    written. That inverted what the two representations are. The object model
    is authoritative and nothing reads the store, so a bookkeeping fault in a
    shadow copy was refusing to persist the model that owns every value: the
    user's edits were valid and `getDict()` would have serialized them
    correctly. Worse, it was not transient -- nothing on the failing path
    repairs the store, so the refusal recurred on every later save and the
    section stayed unsaveable for the rest of the session. F1's `findFlag` was
    severe precisely because of this.

    So the comparison moved to after the write. This pins both halves of what
    that is supposed to mean, because either alone would be the wrong change:

      1. the valid data DOES reach disk, and
      2. the mismatch is STILL reported, naming the divergent column.

    **(2) is a printed report rather than a raise since D11**, which replaced
    the comparison with a rebuild. The ordering it was written for survives the
    change and is still the right one: `resyncColumnarStore` can raise on the
    build's arity check, and even that must not withhold bytes that were
    already correct.

    That check was originally described here as "a genuine store-construction
    bug". Review of D11 showed the attribution was wrong, and the correction
    matters because it is the whole reason the save path had to be made
    tolerant of it rather than left to raise: the check also fires on a
    perfectly healthy store when the OBJECT MODEL is self-contradictory, which
    an out-of-class rename makes it. See
    `test_a_rebuild_that_cannot_be_built_leaves_the_section_usable`.
    """
    import json

    ## A legitimate edit through the normal path, so the object model is valid
    ## and `getDict()` would serialize it correctly.
    added = _aTrace(real_section, name="reaches_disk_probe")
    real_section.addTrace(added, log_event=False)

    ## And an out-of-class in-place write, the `findFlag`/`hideObjects` shape,
    ## which drifts the shadow copy without touching the object model's
    ## correctness.
    victim = _anyTrace(real_section)
    victim.setHidden(not victim.hidden)

    capsys.readouterr()
    real_section.save()

    ## (2) still reported, and still attributed.
    message = _driftReports(capsys)
    assert "hidden:" in message, (
        f"the divergence was not reported as a `hidden` mismatch: {message}"
    )
    assert f"section {real_section.n}" in message

    ## (1) and the user's work is on disk anyway.
    with open(real_section.filepath, "rb") as f:
        written = json.loads(f.read().decode())

    assert "reaches_disk_probe" in written["contours"], (
        "a shadow-copy mismatch still vetoed the write, so the user's valid "
        "edit did not reach disk"
    )
    ## Including the out-of-class edit itself, which the object model owns and
    ## which is exactly what the old ordering discarded.
    on_disk = written["contours"][victim.name]
    assert any(
        Trace.fromList(list(entry), victim.name).hidden == victim.hidden
        for entry in on_disk
    ), "the in-place `hidden` edit did not reach disk"

    ## And the section is not poisoned for the session: the repair works and
    ## the very next save is clean, rather than raising forever.
    real_section.resyncColumnarStore()
    real_section.save()


def test_a_rebuild_that_cannot_be_built_leaves_the_section_usable(
    real_section, capsys
):
    """A save whose rebuild fails must not cost the section its row map.

    THE SHAPE, AND WHY IT IS NOT A STORE BUG
    ----------------------------------------
    `SectionColumns.fromSection` indexes each row under `trace.name`, while
    `_rebuildColumnarStore` reads the rows back by CONTOUR KEY to check that
    the two line up. Those are the same string for every section the
    application produces -- until something renames a trace in place from
    outside `Section`, which leaves `Section.contours`'s key saying `'d03'`
    and the trace it holds saying something else. The build then reports zero
    rows for `'d03'` against one trace and raises, on a store that was
    perfectly healthy and against an object model `getDict()` had just
    serialized correctly (under the contour key, which is the name the file
    round-trips).

    WHAT THIS PINS
    --------------
    The first version of D11 raised out of that path, and because
    `_rebuildColumnarStore` assigns `self._columns` before it fills
    `self._column_rows`, the raise left the section holding a new store and an
    EMPTY row map. Every subsequent hooked mutation -- of any trace on the
    section, not only the renamed one -- then went through `_rowFor` and
    raised "holds no row for". So a single save turned a section that was
    merely unsaveable into one nobody could edit for the rest of the session,
    on the exact path D11 exists to make safe. Reported in review of the
    change; this is its pin.

    Four things, and the fourth is the one the original defect broke:

      1. `save()` does not raise,
      2. the failure is REPORTED, where a user can retrieve it,
      3. the section keeps the store and row map it already had, rather than
         a half-built pair, and
      4. it stays editable and re-saveable afterwards.

    WHAT IT DELIBERATELY DOES NOT CLAIM
    -----------------------------------
    The disagreement is not repaired -- there is no store to build -- so
    `resyncColumnarStore()` still raises on the same section, and the renamed
    trace itself still fails the per-mutation check that names the
    disagreement. Both are asserted below rather than left implicit, because
    "the save is safe" and "the section is repaired" are different claims and
    only the first is being made.
    """
    victim = _anyTrace(real_section)
    other = next(
        trace for trace in real_section.tracesAsList() if trace is not victim
    )
    store = real_section._columns
    row_map = real_section._column_rows
    live = len(real_section.tracesAsList())

    ## The thirteenth-site shape: a rename nothing mirrored, and nothing
    ## repaired.
    victim.name = "renamed_out_of_class"

    capsys.readouterr()
    real_section.save()                                   # (1) does not raise

    ## (2) and it says which section and what happened.
    message = _driftReports(capsys)
    assert f"section {real_section.n}" in message, (
        f"the unbuildable rebuild was not reported: {message!r}"
    )
    assert "could not be rebuilt" in message, (
        f"the report did not say the rebuild failed: {message!r}"
    )

    ## (3) the section still holds exactly what it held before the save --
    ## the objects themselves, not merely equal ones.
    assert real_section._columns is store, (
        "the failed rebuild was adopted anyway"
    )
    assert real_section._column_rows is row_map, (
        "the failed rebuild left its half-built row map behind"
    )
    assert len(real_section._column_rows) == live, (
        f"the row map holds {len(real_section._column_rows)} entries for "
        f"{live} live traces; the failed save emptied it"
    )

    ## (4) the section is not bricked. An ordinary hooked edit of an unrelated
    ## trace is what used to raise "holds no row for" immediately.
    real_section.closeTraces([other], closed=not other.closed)
    real_section.save()

    ## And the limits, stated rather than assumed. The renamed trace's own row
    ## is still named by the per-mutation check, which is the discipline
    ## signal D11 is not supposed to give up: the save absorbed the cost, not
    ## the evidence.
    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.closeTraces([victim], closed=not victim.closed)
    assert "name:" in str(caught.value), (
        f"the renamed trace's row was reached but not attributed: "
        f"{caught.value}"
    )

    ## ...and the disagreement itself survives, because nothing repaired it.
    ## `resyncColumnarStore()` is the caller asking for a store to be built,
    ## and there is still none to build.
    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.resyncColumnarStore()
    assert "building the store" in str(caught.value)


def test_a_rebuild_that_fails_for_any_other_reason_still_restores_the_map(
    real_section, monkeypatch
):
    """The unexpected failure still reaches the caller, just not through a
    bricked section.

    The tolerance above is deliberately narrow: only
    `ColumnarDualWriteMismatch` is downgraded to a report, because only that
    one has a known, benign reading. Anything else out of the rebuild is a
    real fault and must still raise. What must NOT differ between the two is
    the section's state afterwards -- an aborted rebuild leaves a half-built
    row map whatever aborted it.

    The failure is planted in `rowsForContour` rather than in `fromSection`
    deliberately: `fromSection` raises BEFORE `_rebuildColumnarStore` has
    assigned anything, so a failure there could never have left a half-built
    pair and a test that used it would pass with or without the guard.
    `rowsForContour` runs inside the row-map loop, which is where the damage
    was.
    """
    store = real_section._columns
    row_map = real_section._column_rows
    live = len(real_section.tracesAsList())

    def explode(self, name):
        raise RuntimeError("rowsForContour fell over")

    monkeypatch.setattr(SectionColumns, "rowsForContour", explode)

    with pytest.raises(RuntimeError, match="rowsForContour fell over"):
        real_section.save()

    assert real_section._columns is store
    assert real_section._column_rows is row_map
    assert len(real_section._column_rows) == live

    monkeypatch.undo()
    ## And it is still an ordinary, editable, saveable section.
    real_section.closeTraces(
        [_anyTrace(real_section)], closed=not _anyTrace(real_section).closed
    )
    real_section.save()


# =============================================================================
# Track C: a normal consumer can reach the store
# =============================================================================

def test_a_normal_consumer_reaches_a_live_store_on_every_section(real_series):
    """What the decision was made to unblock, checked as a consumer would.

    No environment set, no gate, nothing test-only: load the series the way any
    code in the application does and every section answers with a store that
    agrees with its contours. This is the precondition the first consumer flip
    (`svg_conversion.py`) found missing, and the whole reason D2 was reopened.

    Deliberately NOT flipping a consumer here -- that is separate work. This
    docstring used to name a second blocker on it as live: `contourNames()`
    being sorted-only where `Section.contours` is insertion-ordered. That one
    was answered on 2026-08-06 by adding `contourNamesInInsertionOrder()`
    beside it, and the tests below this one pin both orders. The flip itself is
    still separate work.
    """
    from PyReconstruct.modules.datatypes.columnar_store import ContourView

    checked = 0
    for snum, section in real_series.enumerateSections(show_progress=False):
        store = section._columns
        assert store is not None, f"section {snum} has no store"
        assert len(store) == len(section.tracesAsList())

        for name in store.contourNames():
            view = ContourView(store, name)
            assert len(view) == len(section.contours[name])

            ## Actually READ through the view, not only measure it. Taking the
            ## view's length proves the store is arity-consistent; it does not
            ## prove a consumer can get a value out, which is the thing Track C
            ## needs and the thing the `svg_conversion.py` flip attempt found
            ## missing. So read a row's name and its coordinates back through
            ## the view and require them to agree with the object model.
            for index, trace in enumerate(section.contours[name]):
                row = view[index]
                assert row.name == trace.name
                assert len(row.points) == len(trace.points)
                checked += 1

    assert checked > 0, "the fixture series produced no trace to read"


def test_the_store_answers_both_contour_orders_at_once(real_section):
    """The ordering question, answered. Replaces the test that pinned it open.

    That test (`test_the_store_ordering_mismatch_is_still_open_and_still_
    reproduces`) asserted `contourNames()` and `list(section.contours)` differ,
    and it was right to: the store had one enumerator and it was sorted. The
    2026-08-06 decision was to add a second rather than change the first, so
    the property that replaces it is that **both** hold simultaneously --
    `contourNames()` still sorted, `contourNamesInInsertionOrder()` matching
    the object model. Asserting only that "the mismatch is fixed" would pass
    just as well if the sorted enumerator had quietly been made insertion
    ordered, which is the change the decision rejected.

    Same probe the old test used: one object whose name sorts FIRST, added
    LAST, so sorted order and insertion order disagree on it maximally.
    """
    real_section.addTrace(_aTrace(real_section, name="aaa_added_last"))

    object_order = list(real_section.contours)
    sorted_order = real_section._columns.contourNames()
    insertion_order = real_section._columns.contourNamesInInsertionOrder()

    ## The probe really does separate the two orders.
    assert object_order[-1] == "aaa_added_last"
    assert sorted_order[0] == "aaa_added_last"
    assert sorted_order != insertion_order

    ## The OLD method is unchanged: still sorted, still not the object model's.
    assert sorted_order == sorted(sorted_order, key=str)
    assert sorted_order != object_order

    ## The NEW method is the object model's order exactly.
    assert insertion_order == object_order

    ## And the two enumerate the same contours, differing only in order.
    assert sorted(insertion_order, key=str) == sorted_order


def test_insertion_order_reflects_real_history_and_not_an_accident(real_section):
    """Add, remove, add again -- the order has to follow what actually happened.

    An enumerator that was merely stable would pass a check on an unmodified
    section, so the sequence here is chosen to make a wrong answer visible:

      * `zzz_first` is added first and sorts LAST, so an accidentally-sorted
        answer puts it in the wrong place;
      * `mmm_second` is added after it and sorts BETWEEN the two;
      * `zzz_first` is then EMPTIED and refilled, which on the object model
        keeps its original position (`Contour.remove` leaves the key behind)
        rather than moving it to the tail -- so an implementation that dropped
        and recreated the key would answer `mmm_second, zzz_first` and the
        object model would answer `zzz_first, mmm_second`.
    """
    baseline = list(real_section.contours)

    first = _aTrace(real_section, name="zzz_first")
    real_section.addTrace(first)
    real_section.addTrace(_aTrace(real_section, name="mmm_second"))

    store = real_section._columns
    assert store.contourNamesInInsertionOrder() == baseline + [
        "zzz_first", "mmm_second"
    ]

    ## Emptied: gone from BOTH enumerators, while the object model keeps an
    ## empty contour under the key. That divergence is deliberate and is what
    ## makes the refill below a real test of position rather than of order.
    real_section.removeTrace(first)
    assert real_section.contours["zzz_first"].isEmpty()
    assert "zzz_first" not in store.contourNamesInInsertionOrder()
    assert "zzz_first" not in store.contourNames()

    ## Refilled: back in its ORIGINAL position, not at the tail.
    real_section.addTrace(_aTrace(real_section, name="zzz_first"))
    assert store.contourNamesInInsertionOrder() == baseline + [
        "zzz_first", "mmm_second"
    ]
    assert store.contourNamesInInsertionOrder() == [
        name for name in real_section.contours
        if not real_section.contours[name].isEmpty()
    ]


def test_insertion_order_survives_a_rebuild_and_a_save(real_section):
    """The path that used to erase it, and the reason the fix is in
    `fromSection`.

    A rebuild re-derives the store from the object model, and since D11 every
    `save()` rebuilds -- so an insertion order that were only correct at first
    construction would be correct for about as long as it took the user to hit
    save. `fromSection` appends rows in sorted order and seeds the index's keys
    in the section's order for exactly this.

    Checked after the public repair and after a real `save()`, and the row
    numbering is checked to be untouched by the seeding, because the rebuild
    correlates every `Trace` to a row through the sorted append walk.
    """
    real_section.addTrace(_aTrace(real_section, name="aaa_added_last"))
    expected = list(real_section.contours)

    real_section.resyncColumnarStore()
    assert real_section._columns.contourNamesInInsertionOrder() == expected
    assert real_section._columns.contourNames() == sorted(expected, key=str)

    real_section.save()
    assert real_section._columns.contourNamesInInsertionOrder() == expected
    assert real_section._columns.contourNames() == sorted(expected, key=str)

    ## The seeding fixed key order and moved no row NUMBER: a rebuild numbers
    ## rows 0..n-1 down the SORTED walk, contour by contour, and still does.
    ## (Not a comparison against the pre-rebuild numbering, which a rebuild has
    ## always been free to change and does: `aaa_added_last` was appended last
    ## and comes back first.) This is the numbering
    ## `Section._rebuildColumnarStore` correlates every `Trace` to a row
    ## through, so it is the half the seeding had to leave alone.
    store = real_section._columns
    walk = []
    for name in sorted(real_section.contours, key=str):
        walk.extend(store.rowsForContour(name))
    assert walk == list(range(len(walk)))
    assert len(walk) == len(real_section.tracesAsList())


def test_every_section_of_the_real_series_agrees_on_insertion_order(real_series):
    """Both enumerators against the object model on every real section.

    The freshly-loaded case, where the two orders happen to agree because
    `Section.updateJSON` canonicalizes a file's contours to sorted order on the
    way in. Worth asserting anyway: it is the state every session starts from,
    and it is what makes `test_the_store_answers_both_contour_orders_at_once`'s
    single added object the whole of the divergence rather than one of many.
    """
    checked = 0
    for snum, section in real_series.enumerateSections(show_progress=False):
        store = section._columns
        populated = [
            name for name in section.contours
            if not section.contours[name].isEmpty()
        ]
        assert store.contourNamesInInsertionOrder() == populated, (
            f"section {snum} disagrees with its store on contour order"
        )
        assert store.contourNames() == sorted(populated, key=str)
        checked += len(populated)

    assert checked > 0, "the fixture series produced no contour to check"


# =============================================================================
# The narrowing itself, pinned so that putting it back is a visible act
# =============================================================================
#
# Two places gave up whole-section checking when this became a production path,
# both because of the same measurement (`autoseg745`: a whole-section check is
# ~81 ms on the median section, ~127 ms on the busiest, against a 0.002 ms
# `addTrace`). Neither is a quiet loss: each is asserted here, so a change that
# restores the old scope turns these red and reopens the cost question with a
# reviewer looking at it.

def test_a_mutation_does_not_materialize_the_whole_section(real_section, monkeypatch):
    """The per-mutation check touches one row, not every row.

    `materializeContours` is the O(section) read; a single-row mutation must not
    reach it. This is the assertion that makes the per-mutation cost a property
    of the code rather than a claim in a comment.
    """
    calls = []
    real = SectionColumns.materializeContours

    def counted(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(SectionColumns, "materializeContours", counted)

    trace = _aTrace(real_section)
    real_section.addTrace(trace)
    real_section.hideTraces([trace], hide=True)
    real_section.closeTraces([trace], closed=False)
    real_section.removeTrace(trace)

    assert calls == [], (
        f"{len(calls)} whole-section materializations for four single-row "
        "mutations; the per-mutation check went back to O(section)"
    )


def test_building_a_store_does_not_run_the_whole_section_comparison(
    real_series, monkeypatch
):
    """A store is built at every section load, so the build cannot be O(section)
    twice.

    `fromSection` copies values straight out of the object model, so the only
    divergence a build-time value comparison can find is a bug in the store's own
    encode/decode -- which does not vary section to section and which
    `test_columnar_store_parity.py` covers directly. Running it per load cost a
    measured 11x on section load and 8.2x on a full-series pass.
    """
    calls = []
    real = SectionColumns.materializeContours

    def counted(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(SectionColumns, "materializeContours", counted)

    section = real_series.loadSection(sorted(real_series.sections)[0])
    assert section._columns is not None
    assert calls == [], "building a store materialized the whole section"


def test_building_a_store_still_checks_the_row_arity(real_section, monkeypatch):
    """What the build DOES still check, and why it is worth its O(contours).

    The row map is built by zipping each contour's traces against the rows the
    store reports for that contour. If those ever stop lining up -- a change to
    `fromSection`'s walk order, a contour index that drops a row -- every trace
    on the section is silently mapped to the wrong row, and every later check
    then compares the wrong pair. That is a per-section question, so it stays.
    """
    real = SectionColumns.rowsForContour

    def short(self, name):
        rows = real(self, name)
        return rows[:-1] if len(rows) > 1 else rows

    monkeypatch.setattr(SectionColumns, "rowsForContour", short)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.resyncColumnarStore()

    assert "building the store" in str(caught.value)
