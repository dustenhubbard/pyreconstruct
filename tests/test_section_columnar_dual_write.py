"""The test-only dual write from `Section` into the columnar store.

Slice 3 of the Phase 1 rewiring. A `Section` can carry a `SectionColumns` beside
its `self.contours`, mirror every mutation into it, and check the two against
each other after every single mutation. Nothing reads the store; this exists so
that the store gets driven by real code on real data before one call site
anywhere is flipped to read from it.

TWO THINGS THIS FILE HAS TO PROVE, AND THE SECOND IS THE ONE THAT IS EASY TO FAKE
---------------------------------------------------------------------------------
**That the gate is genuinely unreachable from a normal launch.** This is the
maintainer's stated condition for the slice existing at all, so it is checked
structurally rather than by assertion-about-intent: the environment variable's
name appears in exactly one shipped file, that file never writes an environment
variable, and no launcher, workflow, packaging spec or script in the repository
mentions it. `test_no_shipped_file_anywhere_in_the_repository_mentions_the_gate`
is the one that would catch somebody wiring it to a settings toggle later.

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


GATE = section_module.DUAL_WRITE_ENV_VAR

SECTION_SOURCE = Path(section_module.__file__).resolve()
PACKAGE_ROOT = SECTION_SOURCE.parents[2]
REPO_ROOT = PACKAGE_ROOT.parent

SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"


# --- fixtures ----------------------------------------------------------------

@pytest.fixture
def gate_on(monkeypatch):
    """Turn the dual-write gate on for the rest of the test.

    `monkeypatch.setenv` and not `os.environ[...] = `, so the variable is gone
    again at teardown whatever the test does. The gate is read in
    `Section.__init__`, so this has to be in place before a section is loaded.
    """
    monkeypatch.setenv(GATE, "1")
    return GATE


def _busiest(sections):
    populated = [s for s in sections if s.contours]
    assert populated, "the fixture series has no populated section"
    return max(populated, key=lambda s: len(s.tracesAsList()))


@pytest.fixture
def real_section(real_series, gate_on):
    """The busiest section of the real fixture series, with a live store."""
    section = _busiest(
        [real_series.loadSection(n) for n in sorted(real_series.sections)]
    )
    assert section._columns is not None
    return section


@pytest.fixture
def synthetic_section(tmp_path, gate_on):
    """The busiest section of the synthetic series, with a live store.

    A copy for the same reason the parity suite copies: `Series.openJser` builds
    a hidden working directory beside the file it is handed.
    """
    from PyReconstruct.modules.datatypes import Series

    destination = tmp_path / "parity_series.jser"
    shutil.copy(SYNTHETIC_FIXTURE, destination)
    series = Series.openJser(str(destination))
    section = _busiest(
        [series.loadSection(n) for n in sorted(series.sections)]
    )
    assert section._columns is not None
    yield section
    series.close()


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
# The gate: that a normal launch cannot reach it
# =============================================================================

def test_the_variable_is_named_what_the_documentation_says():
    """The literal spelling is the contract, so pin it once here.

    Every other test addresses the gate through the constant, which would keep
    passing if the constant were renamed. A reviewer checking that this is not
    reachable from a real session is reading for the literal string.
    """
    assert GATE == "PYRECON_TEST_ONLY_COLUMNAR_DUAL_WRITE"
    assert "TEST_ONLY" in GATE, "the name has to say what it is on sight"


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "on", "2", "1 "])
def test_only_an_explicit_1_turns_the_gate_on(monkeypatch, value):
    """Anything other than exactly `1` leaves the harness off.

    The same spelling `PYRECON_UNATTENDED`, `PYRECON_FORCE_FROZEN` and
    `PYRECON_JSER_PRETTY` use. A stale `...=0` in a shell profile is off, not a
    third state, and no truthy-looking value opens the door by accident.
    """
    monkeypatch.setenv(GATE, value)
    assert section_module.dualWriteRequested() is False


def test_an_unset_variable_is_off(monkeypatch):
    monkeypatch.delenv(GATE, raising=False)
    assert section_module.dualWriteRequested() is False
    monkeypatch.setenv(GATE, "1")
    assert section_module.dualWriteRequested() is True


def test_a_section_loaded_without_the_gate_carries_no_store(
    real_series, monkeypatch
):
    """The invisibility claim, at the object.

    No store, no row map, and -- the part that matters for memory -- nothing
    built and nothing to keep alive.
    """
    monkeypatch.delenv(GATE, raising=False)
    section = _busiest(
        [real_series.loadSection(n) for n in sorted(real_series.sections)]
    )
    assert section._columns is None
    assert section._column_rows == {}


def test_mutating_an_ungated_section_stays_storeless(real_series, monkeypatch):
    """Every hook is a one-line return when there is no store.

    Drives the same mutations the gated tests below drive, and asserts nothing
    came into existence. This is what "invisible with the gate off" means at
    runtime, as opposed to at load.
    """
    monkeypatch.delenv(GATE, raising=False)
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

    assert section._columns is None
    assert section._column_rows == {}
    assert section_module.Section._column_rows == {}, (
        "the class-level default row map was written to"
    )


def test_a_section_that_never_ran_its_constructor_is_unaffected(monkeypatch):
    """`Section.__new__` with a handful of hand-set attributes, still working.

    A dozen test modules in this suite drive one `Section` method against a bare
    `Section.__new__` instance carrying only the attributes that method touches,
    deliberately, so the method is tested without a series, a file or a
    filesystem. `__init__` never runs on those, so a hook that reached for an
    attribute `__init__` sets would break all of them -- which is what happened
    on the first draft of this change, and is why `_columns` and `_column_rows`
    are class-level defaults as well as instance ones.

    The gate is set here on purpose: even asked for a store, a section that
    never ran `__init__` has none, because that is the only place one is built.
    """
    monkeypatch.setenv(GATE, "1")

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


def test_the_gate_is_read_per_section_not_cached_at_import(
    real_series, monkeypatch
):
    """One process, two sections, two answers.

    `dualWriteRequested()` is called from `Section.__init__` rather than
    evaluated once at import, so a test that turns the gate on cannot leak a
    store into a section another test loads afterwards.
    """
    snum = sorted(real_series.sections)[0]

    monkeypatch.setenv(GATE, "1")
    gated = real_series.loadSection(snum)
    monkeypatch.delenv(GATE)
    ungated = real_series.loadSection(snum)

    assert gated._columns is not None
    assert ungated._columns is None


## Files allowed to name the gate: the one module that defines and reads it, and
## the tests and changelog that describe it. Anything else is a shipped file
## that could put the harness into a user's session.
def _mentionsAllowed(path : Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    if path == SECTION_SOURCE:
        return True
    if relative.parts[0] in ("tests", "changelog.d", "CHANGELOG.md"):
        return True
    return False


def test_no_shipped_file_anywhere_in_the_repository_mentions_the_gate():
    """The safety condition, checked structurally rather than asserted.

    Reads every file in the repository that could carry text. If the gate's name
    ever appears in a launcher, a `.spec`, a CI workflow, an installer script or
    any module other than the one that defines it, this fails -- which is the
    failure a reviewer wants when somebody later tries to wire the harness to a
    settings toggle or export it from a launch script.

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
    ## into a job is one of the ways this could become reachable.
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
        if GATE in text:
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
        "the test-only dual-write gate is named outside the module that "
        f"defines it, so a real session could reach it: {offenders}"
    )


def test_the_module_that_owns_the_gate_never_writes_an_environment_variable():
    """`section.py` reads the environment and never writes it.

    The previous test proves nothing else names the gate. This one proves the
    one file that does cannot set it either -- no `os.environ[...] = `, no
    `setdefault`, no `putenv`, no `environ.update` -- so the harness cannot turn
    itself on from inside the application under any code path at all.
    """
    tree = ast.parse(SECTION_SOURCE.read_text(encoding="utf-8"))

    writes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and "environ" in ast.dump(target.value)
                ):
                    writes.append(ast.dump(target))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            dumped = ast.dump(node.func)
            if node.func.attr in ("setdefault", "update", "pop", "clear") and "environ" in dumped:
                writes.append(dumped)
            if node.func.attr in ("putenv", "unsetenv"):
                writes.append(dumped)

    assert writes == [], f"section.py writes the environment: {writes}"


def test_nothing_outside_section_py_knows_the_harness_exists():
    """No call site outside `Section` was changed, and none can be.

    The dual write is meant to be invisible to the rest of the application: no
    module imports the mismatch exception, calls a hook, or reaches for the
    store hung off a section. Scanned by name because each of these names is
    distinctive enough that a hit is a real reference rather than a coincidence.

    `self._columns` is deliberately not in this list. It collided with an
    unrelated `TraceView._columns` (`columnar_store.py`, Phase 1 slices 4/6) the
    first time both landed on the same tree: the name is common enough that two
    independent classes picked it for unrelated fields. The other six names are
    confirmed harness-specific (grepped repo-wide, zero hits outside this file)
    and carry the actual leak-detection weight.
    """
    names = (
        "_dualWrite",
        "resyncColumnarStore",
        "ColumnarDualWriteMismatch",
        "_column_rows",
        "DUAL_WRITE_ENV_VAR",
        "dualWriteRequested",
    )
    offenders = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.resolve() == SECTION_SOURCE:
            continue
        text = path.read_text(encoding="utf-8")
        hits = [name for name in names if name in text]
        if hits:
            offenders[str(path.relative_to(PACKAGE_ROOT))] = hits

    assert offenders == {}, f"the harness leaked out of Section: {offenders}"


# =============================================================================
# The dual write itself, on real material
# =============================================================================

def test_a_freshly_loaded_gated_section_already_agrees(real_section):
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


def test_importTraces_rebuilds_the_store_from_the_result(real_series, gate_on):
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


def test_the_stale_row_map_is_caught_by_a_real_mutation_not_only_a_bare_check(
    real_section
):
    """Driven through a `Section` method, because that is how it would happen.

    `_assertColumnsMatchObjectModel` called by hand proves the comparison works.
    This proves the comparison is reached: the very next real mutation after the
    rebind stops the run, whatever kind of mutation it is.
    """
    _undoStyleRestore(real_section)

    with pytest.raises(ColumnarDualWriteMismatch) as caught:
        real_section.addTrace(_aTrace(real_section))

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
