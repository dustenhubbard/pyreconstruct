"""Data-integrity invariants for destructive operations.

Why this module exists, and why it is shaped differently from the rest of the
suite. The three worst defects found in this codebase recently were all silent
data loss, and in all three cases the suite was green while the bug shipped:

* the section list deleted a section file and then raised ``KeyError``, leaving
  a half-updated series with no undo, because ``getSelected()`` returned one
  entry per selected *cell* rather than per row;
* accepting the trace attributes dialog on a multi-trace selection whose tags
  differ erased every selected trace's tags;
* the undo baseline was written into the shipped assets, and the cleanup path
  deleted the bundled file on a read-only install.

A unit test asserts what a function returns. None of the three changed what any
function returned. What each of them broke was a property of the *series*: a
section referenced but not on disk, a tag set that vanished from traces the
operation was not asked to touch, a file that should not have been written at
all. So the tests here assert properties of the whole series after an operation,
not the operation's return value.

Shape of the module:

1. ``check_series`` collects every violation of the invariants below and returns
   them as a list, so one failure reports everything that is wrong rather than
   the first thing.
2. ``snapshot`` renders the whole series (every section's ``getDict``, plus the
   series dict) into a canonical, comparable structure. ``state_diff`` reports
   every leaf that differs, by path. Undo is asserted as ``snapshot ==
   pre-operation snapshot``, a deep comparison, not a spot check.
3. The ``test_teeth_*`` tests put the series into the state a past defect left
   behind and assert that an invariant *fails*. An invariant nobody has watched
   fail is an invariant nobody should trust, and keeping the proof as a test
   means it stays true rather than being a claim in a pull request. Where the
   defect is still reachable through the code the test drives it; where it has
   since been fixed at the datatype layer, the test builds the damaged state
   directly, because what is worth pinning is that the checker catches the
   damage, not that some particular caller can still cause it.

Invariants asserted, and what each one is for:

I1 ``sections/disk``      every section the series believes it has is a file in
                          the hidden directory, and every numbered file in the
                          hidden directory is a section the series knows about.
                          Both directions: a missing file is data loss, an
                          unreferenced file is data the app can no longer reach.
I2 ``sections/index``     every section number is present in the in-memory index
                          (``series.data["sections"]``). One direction only, see
                          "Not asserted" below.
I3 ``contour/naming``     for every section, the contour key, ``contour.name``
                          and every ``trace.name`` inside it agree, and the name
                          is a non-empty string. This is the property a rename
                          breaks halfway.
I4 ``trace/points``       no trace has zero points. A pointless trace survives a
                          save and is invisible in the field.
I5 ``ztrace/sections``    every z-trace point lands on a section that exists.
                          This is the invariant the half-updated section delete
                          violates: the file and the ``sections`` entry go, and
                          the loop that repoints z-traces never runs.
I6 ``objects/tracked``    every non-empty contour is a tracked object, and no
                          tracked object has zero traces. An object with no
                          traces is a row in the object list that refers to
                          nothing.
I7 ``objects/references`` object group members, ``obj_attrs`` keys and
                          ``host_tree`` entries all name objects that still
                          exist. Verified against the real operations: deleting
                          an object's traces does clean all three, so a dangling
                          reference is a defect and not the normal state.

Not asserted, deliberately:

* Byte-stability of a ``.jser`` round trip. Already covered, thoroughly, by
  ``tests/test_jser_canonical_format.py`` (``test_save_round_trips_losslessly``
  and the canonical-ordering tests around it). Repeating it here would add
  runtime and no information. What is *not* covered there is a round trip taken
  after a destructive operation, so that is what
  ``test_destructive_edit_survives_save_and_reopen`` asserts, semantically.
* ``series.data["sections"]`` retaining an entry for a section that
  ``Series.deleteSections`` has removed. It does retain it: the datatype leaves
  the index refresh to its caller, which reaches it through
  ``TableManager.recreateTables(refresh_data=True)``. Asserting the strict
  bidirectional form would fail on the honest path, so I2 asserts only that the
  index never *lacks* a live section, which is the direction that hides data.
* Anything about which undo layer wins when both a section-level and a
  series-level undo are available. ``FieldState.updateTime`` stores
  ``round(time.time()*10)``, and ``SeriesStates.favor3D`` picks a layer by
  comparing those stamps with ``>``. Two states recorded inside the same 100 ms
  bucket compare equal, which is exactly what happens in a test. That is
  inherently timing-dependent, so it is left out rather than made flaky.
* Whether an operation writes outside the series directory (the bundled-asset
  defect). That is an install-layout property, not a series property: it needs a
  read-only installation to reproduce and it belongs with the code that picks the
  undo baseline path, not here.

The fixture is ``shapes1.jser`` (5 sections, 4 objects, 20 traces, 4 z-traces),
copied per test. It is the smallest checked-in series that has z-traces, which
I5 needs. It ships with no tags, no groups, no host tree and no per-object
attributes, so ``enrich`` adds them: an invariant that data survives an
operation proves nothing when the data is not there to begin with.
"""

import copy
import json
import os
import shutil

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.section import Section

pytestmark = pytest.mark.gui

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "PyReconstruct", "assets", "checker", "files", "shapes1.jser",
)

# Provenance fields that an undo is not expected to restore, excluded from the
# deep comparison with a reason for each:
#
#   log_set    the log is append-only by design; undoing an edit does not
#              unwrite the record that the edit happened.
#   editors    the set of users who have touched the series. Same reason.
#   last_user  per-object provenance written by addLog. Series.editObjectAttributes
#              logs *before* it opens the section iterator, so the value is
#              already in the state the iterator captures and survives the undo;
#              Series.removeAllTraceTags logs after, so it does not. The
#              inconsistency is in when the log is written, not in the undo.
#
# Stripping ``last_user`` can leave ``obj_attrs[name]`` as an empty dict where
# there was no entry at all before, so empty entries are dropped too. An empty
# attribute dict carries no information, so nothing real is hidden by that.
_PROVENANCE_SERIES_KEYS = ("log_set", "editors")
_PROVENANCE_OBJ_ATTRS = ("last_user",)


# ---------------------------------------------------------------------------
# fixture plumbing
# ---------------------------------------------------------------------------

def open_fixture(tmp_path, name="s"):
    """A real Series opened from a private copy of the checked-in fixture."""
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


def enrich(series):
    """Give the fixture the content the preservation invariants are about.

    ``shapes1.jser`` has no tags, no groups, no host tree, no user columns and
    no per-object attributes, so an operation that silently dropped any of them
    would still pass against it untouched.
    """
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        for name, contour in section.contours.items():
            for trace in contour.getTraces():
                trace.tags = {f"tag_{name}", "shared"}
        section.save()
    series.object_groups.add("shapes", "star")
    series.object_groups.add("shapes", "square")
    series.setAttr("star", "comment", "keep me")
    series.addUserCol("stage", ["a", "b"], log_event=False)
    series.setUserColAttr("star", "stage", "a")
    series.setObjHosts(["square"], ["star"])
    series.data.refresh()
    series.save()
    return series


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    s.close()


@pytest.fixture
def rich_series(tmp_path):
    s = enrich(open_fixture(tmp_path))
    yield s
    s.close()


def unlock(series):
    """Clear the align lock on every section.

    Sections ship locked and ``SectionTableWidget.deleteSections`` refuses to
    touch a locked section, which would mask what the test is measuring. The
    attribute is the source of truth: clearing ``data["sections"][n]["locked"]``
    is overwritten by the next save.
    """
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        section.align_locked = False
        section.save()
    series.data.refresh()
    return series


# ---------------------------------------------------------------------------
# the invariants
# ---------------------------------------------------------------------------

def _section_files(series):
    """snum -> filename, for every numbered file actually in the hidden dir."""
    found = {}
    for filename in os.listdir(series.hidden_dir):
        if "." not in filename:  # the timer file
            continue
        ext = filename[filename.rfind(".") + 1:]
        if ext.isnumeric():
            found[int(ext)] = filename
    return found


def check_series(series, ignore=()):
    """Return every invariant violation, as a list of readable strings.

    Collecting rather than asserting is deliberate: a half-updated series
    usually breaks several invariants at once, and seeing all of them is how you
    tell which operation ran and how far it got.

        Params:
            ignore (tuple): violation-message prefixes to drop. Used only where
                current behavior knowingly breaks an invariant and the gap is
                pinned by its own test, so that the rest of the checker still
                applies instead of being switched off wholesale.
    """
    problems = []

    on_disk = _section_files(series)
    known = dict(series.sections)

    # I1: sections <-> files, both directions
    for snum in sorted(set(known) - set(on_disk)):
        problems.append(
            f"I1 sections/disk: series claims section {snum} "
            f"({known[snum]!r}) but no such file exists"
        )
    for snum in sorted(set(on_disk) - set(known)):
        problems.append(
            f"I1 sections/disk: file {on_disk[snum]!r} is not referenced by "
            f"any section in the series"
        )
    for snum, filename in sorted(known.items()):
        if snum in on_disk and on_disk[snum] != filename:
            problems.append(
                f"I1 sections/disk: section {snum} names {filename!r} but the "
                f"file on disk is {on_disk[snum]!r}"
            )

    # I2: the in-memory index never lacks a live section
    for snum in sorted(set(known) - set(series.data["sections"])):
        problems.append(
            f"I2 sections/index: section {snum} exists but is absent from "
            f"series.data['sections']"
        )

    tracked = set(series.data["objects"])
    seen_names = set()

    for snum in sorted(known):
        if snum not in on_disk:
            continue  # already reported by I1; loading would raise
        section = series.loadSection(snum)
        for key, contour in section.contours.items():
            traces = contour.getTraces()
            if contour.name != key:
                problems.append(
                    f"I3 contour/naming: section {snum} key {key!r} holds a "
                    f"contour named {contour.name!r}"
                )
            for index, trace in enumerate(traces):
                if not isinstance(trace.name, str) or not trace.name:
                    problems.append(
                        f"I3 contour/naming: section {snum} {key!r}[{index}] "
                        f"has name {trace.name!r}"
                    )
                elif trace.name != key:
                    problems.append(
                        f"I3 contour/naming: section {snum} {key!r}[{index}] "
                        f"is a trace named {trace.name!r}"
                    )
                if not trace.points:
                    problems.append(
                        f"I4 trace/points: section {snum} {key!r}[{index}] "
                        f"has no points"
                    )
            if traces:
                seen_names.add(key)
                if key not in tracked:
                    problems.append(
                        f"I6 objects/tracked: section {snum} has traces for "
                        f"{key!r}, which is not in series.data['objects']"
                    )

    # I5: z-trace points land on sections that exist
    for zname, ztrace in series.ztraces.items():
        missing = sorted({pt[2] for pt in ztrace.points} - set(known))
        if missing:
            problems.append(
                f"I5 ztrace/sections: z-trace {zname!r} has points on "
                f"section(s) {missing}, which the series no longer has"
            )

    # I6, other direction: a tracked object with no traces anywhere
    for name, obj_data in series.data["objects"].items():
        if obj_data.isEmpty() or name not in seen_names:
            problems.append(
                f"I6 objects/tracked: {name!r} is a tracked object with no "
                f"traces on any section"
            )

    # I7: nothing references an object that is gone
    series_dict = series.getDict()
    for group, members in sorted(series_dict["object_groups"].items()):
        for member in sorted(members):
            if member not in tracked:
                problems.append(
                    f"I7 objects/references: group {group!r} lists {member!r}, "
                    f"which is not an object in the series"
                )
    for name, attrs in sorted(series_dict["obj_attrs"].items()):
        # An entry holding nothing but provenance (who last touched the name) is
        # not a dangling reference to data, so it does not count. Every real
        # attribute does.
        real = set(attrs) - set(_PROVENANCE_OBJ_ATTRS) if isinstance(attrs, dict) else attrs
        if real and name not in tracked:
            problems.append(
                f"I7 objects/references: obj_attrs holds {name!r} with "
                f"{sorted(real)}, but it is not an object in the series"
            )
    for host, children in sorted(series_dict["host_tree"].items()):
        for name in [host] + sorted(children):
            if name not in tracked:
                problems.append(
                    f"I7 objects/references: host_tree names {name!r}, which "
                    f"is not an object in the series"
                )

    if ignore:
        problems = [p for p in problems if not p.startswith(tuple(ignore))]
    return problems


def assert_coherent(series, context="", ignore=()):
    problems = check_series(series, ignore=ignore)
    assert not problems, (
        f"series is not internally coherent{' after ' + context if context else ''}:\n  "
        + "\n  ".join(problems)
    )


# ---------------------------------------------------------------------------
# deep state comparison
# ---------------------------------------------------------------------------

def _canon(value):
    """Normalize for comparison: tuple/list alike, sets sorted, keys sorted.

    A save round-trips tuples to lists and sets to sorted lists, so an in-memory
    snapshot and a reloaded one must be normalized the same way or every color
    would read as a difference.
    """
    if isinstance(value, dict):
        return {
            str(k): _canon(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (set, frozenset)):
        return sorted((_canon(v) for v in value), key=json.dumps)
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def snapshot(series):
    """Everything a destructive operation could change, canonically."""
    sections = {
        str(snum): series.loadSection(snum).getDict()
        for snum in sorted(series.sections)
    }
    series_dict = copy.deepcopy(series.getDict())
    for key in _PROVENANCE_SERIES_KEYS:
        series_dict.pop(key, None)
    obj_attrs = series_dict.get("obj_attrs")
    if isinstance(obj_attrs, dict):
        for name, attrs in list(obj_attrs.items()):
            if not isinstance(attrs, dict):
                continue
            for key in _PROVENANCE_OBJ_ATTRS:
                attrs.pop(key, None)
            if not attrs:
                del obj_attrs[name]
    return _canon({"sections": sections, "series": series_dict})


def state_diff(before, after, path="", out=None):
    """Every leaf that differs between two snapshots, as ``path: a != b``."""
    if out is None:
        out = []
    if type(before) is not type(after):
        out.append(f"{path or '<root>'}: {type(before).__name__} vs {type(after).__name__}")
    elif isinstance(before, dict):
        for key in sorted(set(before) | set(after)):
            if key not in before:
                out.append(f"{path}.{key}: added")
            elif key not in after:
                out.append(f"{path}.{key}: removed")
            else:
                state_diff(before[key], after[key], f"{path}.{key}", out)
    elif isinstance(before, list):
        if len(before) != len(after):
            out.append(f"{path}: length {len(before)} vs {len(after)}")
        for index, (a, b) in enumerate(zip(before, after)):
            state_diff(a, b, f"{path}[{index}]", out)
    elif before != after:
        out.append(f"{path}: {before!r} vs {after!r}")
    return out


def assert_state_restored(before, after, context=""):
    differences = state_diff(before, after)
    assert not differences, (
        f"undo did not restore the series{' after ' + context if context else ''} "
        f"({len(differences)} differences):\n  " + "\n  ".join(differences[:40])
    )


def trace_counts(series):
    """(object name -> total traces across the series), empty contours omitted."""
    counts = {}
    for snum in sorted(series.sections):
        for name, contour in series.loadSection(snum).contours.items():
            n = len(contour.getTraces())
            if n:
                counts[name] = counts.get(name, 0) + n
    return counts


def section_counts(section):
    """(object name -> traces on this one section), empty contours omitted."""
    return {
        name: len(contour.getTraces())
        for name, contour in section.contours.items()
        if contour.getTraces()
    }


def tags_by_object(series, snum=0):
    """object name -> list of sorted tag lists, for one section."""
    section = series.loadSection(snum)
    return {
        name: sorted(sorted(t.tags) for t in contour.getTraces())
        for name, contour in section.contours.items()
        if contour.getTraces()
    }


# ---------------------------------------------------------------------------
# the checker itself must not be vacuous
# ---------------------------------------------------------------------------

def test_pristine_fixture_is_coherent(series):
    """Every invariant holds on the fixture as shipped."""
    assert_coherent(series)


def test_enriched_fixture_is_coherent_and_actually_carries_the_data(rich_series):
    """``enrich`` must not itself break coherence, and must not be a no-op.

    The second half is the point: every "X survived the operation" assertion
    below is vacuous if X was never in the series.
    """
    assert_coherent(rich_series)
    d = rich_series.getDict()
    assert d["object_groups"], "enrich added no groups"
    assert d["host_tree"], "enrich added no host tree"
    assert d["user_columns"], "enrich added no user columns"
    assert d["obj_attrs"], "enrich added no per-object attributes"
    assert all(tags for tags in tags_by_object(rich_series).values()), \
        "enrich added no tags"
    assert rich_series.ztraces, "the fixture lost its z-traces"


def test_snapshot_notices_a_single_changed_tag(rich_series):
    """``snapshot``/``state_diff`` must see a one-tag change on one trace.

    A deep comparison that compares nothing is the classic way an undo test goes
    green. This pins the resolution of the comparison at one tag on one trace on
    one section.
    """
    before = snapshot(rich_series)
    section = rich_series.loadSection(2)
    trace = section.contours["star"].getTraces()[0]
    trace.tags = trace.tags | {"a_new_tag"}
    section.save()

    differences = state_diff(before, snapshot(rich_series))
    assert differences, "snapshot did not notice a changed tag"
    assert any("sections.2" in d for d in differences), differences


# ---------------------------------------------------------------------------
# delete sections
# ---------------------------------------------------------------------------

def test_delete_sections_keeps_the_series_coherent(rich_series):
    """The datatype call: files, index, z-traces and objects all agree after."""
    before = snapshot(rich_series)
    rich_series.deleteSections([2])

    assert_coherent(rich_series, "deleteSections([2])")
    assert sorted(rich_series.sections) == [0, 1, 3, 4]
    assert 2 not in _section_files(rich_series)

    # the surviving sections are untouched, byte for byte
    after = snapshot(rich_series)
    for snum in ("0", "1", "3", "4"):
        assert after["sections"][snum] == before["sections"][snum], \
            f"deleting section 2 changed section {snum}"


def test_delete_sections_repoints_ztraces_exactly(rich_series):
    """Z-trace points on the deleted section go, and only those."""
    before = {
        name: [tuple(p) for p in ztrace.points]
        for name, ztrace in rich_series.ztraces.items()
    }
    assert any(p[2] == 2 for pts in before.values() for p in pts), \
        "fixture has no z-trace point on section 2"

    rich_series.deleteSections([2])

    for name, ztrace in rich_series.ztraces.items():
        expected = [p for p in before[name] if p[2] != 2]
        assert [tuple(p) for p in ztrace.points] == expected, \
            f"z-trace {name!r} lost or kept the wrong points"


def test_delete_sections_through_the_section_list_keeps_the_series_coherent(
    qapp, rich_series, section_list
):
    """The real ``SectionTableWidget.deleteSections`` slot, on a real selection."""
    widget, _window = section_list
    widget.table.clearSelection()
    widget.table.selectRow(2)
    assert widget.getSelected() == [2], "the list did not report one selected row"

    widget.deleteSections()

    assert_coherent(rich_series, "SectionTableWidget.deleteSections")
    assert sorted(rich_series.sections) == [0, 1, 3, 4]


# ---------------------------------------------------------------------------
# edit attributes across a multi-object selection
# ---------------------------------------------------------------------------

def test_edit_object_attributes_touches_only_what_it_was_asked_to(rich_series):
    """A color-only edit across two objects must not disturb anything else."""
    before_tags = tags_by_object(rich_series)
    before_dict = rich_series.getDict()
    before_groups = copy.deepcopy(before_dict["object_groups"])
    before_hosts = copy.deepcopy(before_dict["host_tree"])
    before_cols = copy.deepcopy(before_dict["user_columns"])
    before_counts = trace_counts(rich_series)

    rich_series.editObjectAttributes(["star", "square"], color=(1, 2, 3))

    assert_coherent(rich_series, "editObjectAttributes(color=...)")
    assert tags_by_object(rich_series) == before_tags, "a color edit changed tags"
    assert trace_counts(rich_series) == before_counts
    after = rich_series.getDict()
    assert after["object_groups"] == before_groups
    assert after["host_tree"] == before_hosts
    assert after["user_columns"] == before_cols
    assert rich_series.getUserColAttr("star", "stage") == "a"
    assert rich_series.getAttr("star", "comment") == "keep me"

    section = rich_series.loadSection(0)
    assert [tuple(t.color) for t in section.contours["star"].getTraces()] \
        == [(1, 2, 3)]
    assert [tuple(t.color) for t in section.contours["triangle"].getTraces()] \
        != [(1, 2, 3)]


def test_edit_object_attributes_undo_restores_the_series(rich_series):
    states = SeriesStates(rich_series)
    before = snapshot(rich_series)

    rich_series.editObjectAttributes(
        ["star", "square"], color=(1, 2, 3), series_states=states
    )
    assert state_diff(before, snapshot(rich_series)), "the operation changed nothing"

    states.undoState()
    assert_state_restored(before, snapshot(rich_series), "editObjectAttributes")
    assert_coherent(rich_series, "undo of editObjectAttributes")


def test_rename_across_a_multi_object_selection_stays_coherent(rich_series):
    """Renaming two objects into one is the most destructive attribute edit.

    Every trace has to be re-keyed under the new contour name, the object index
    has to follow, and the per-object attributes have to migrate rather than be
    left behind pointing at a name that no longer exists (I7).

    ``circle2`` and ``triangle`` are used rather than ``star`` and ``square``
    so that this test covers a plain rename with no host relationship in play.
    The host case is covered separately by
    ``test_renaming_an_object_to_its_host_stays_coherent`` below.
    """
    before_counts = trace_counts(rich_series)
    states = SeriesStates(rich_series)
    before = snapshot(rich_series)

    rich_series.editObjectAttributes(
        ["circle2", "triangle"], name="merged", series_states=states
    )
    rich_series.data.refresh()

    assert_coherent(rich_series, "editObjectAttributes(name='merged')")
    counts = trace_counts(rich_series)
    assert "circle2" not in counts and "triangle" not in counts
    assert counts["merged"] == before_counts["circle2"] + before_counts["triangle"]
    assert sum(counts.values()) == sum(before_counts.values()), "traces were lost"

    states.undoState()
    rich_series.data.refresh()
    assert_state_restored(before, snapshot(rich_series), "the rename")
    assert_coherent(rich_series, "undo of the rename")


def test_renaming_an_object_to_its_host_stays_coherent(rich_series):
    """Renaming an object onto its own host has to leave the series coherent.

    ``square`` is hosted by ``star``. Renaming ``square`` to ``star`` used to
    make ``star`` a host of itself, and the ``checkRedundantHosts`` call at the
    end of ``HostTree.add`` then recursed through ``getHosts`` until the stack
    was gone, leaving the series half-renamed. Reached from the object list's
    rename action, so a user could hit it.

    ``HostTree`` now refuses to create the cycle and drops the relationship
    between the two objects being collapsed, so the rename completes.
    """
    assert rich_series.getDict()["host_tree"] == {"square": ["star"]}
    rich_series.editObjectAttributes(["square"], name="star")
    rich_series.data.refresh()
    assert_coherent(rich_series, "renaming an object to its host's name")


# ---------------------------------------------------------------------------
# remove all tags
# ---------------------------------------------------------------------------

def test_remove_all_trace_tags_spares_every_other_object(rich_series):
    before = tags_by_object(rich_series)
    before_counts = trace_counts(rich_series)
    assert before["star"] != [[]], "fixture star has no tags to remove"

    rich_series.removeAllTraceTags(["star"])

    assert_coherent(rich_series, "removeAllTraceTags(['star'])")
    after = tags_by_object(rich_series)
    assert after["star"] == [[]], "tags were not removed from the target"
    for name in ("square", "triangle", "circle2"):
        assert after[name] == before[name], f"tags changed on {name!r}"
    assert trace_counts(rich_series) == before_counts, "traces moved or vanished"


def test_remove_all_trace_tags_undo_restores_the_series(rich_series):
    states = SeriesStates(rich_series)
    before = snapshot(rich_series)

    rich_series.removeAllTraceTags(["star"], series_states=states)
    assert state_diff(before, snapshot(rich_series)), "the operation changed nothing"

    states.undoState()
    assert_state_restored(before, snapshot(rich_series), "removeAllTraceTags")
    assert_coherent(rich_series, "undo of removeAllTraceTags")


# ---------------------------------------------------------------------------
# split, and delete every trace of an object
# ---------------------------------------------------------------------------

def test_split_object_conserves_every_trace(rich_series):
    before_counts = trace_counts(rich_series)
    states = SeriesStates(rich_series)
    before = snapshot(rich_series)

    new_names = rich_series.splitObject("star", series_states=states)
    rich_series.data.refresh()

    # I7 applies in full. splitObject copies the source object's attributes
    # onto every new object and now also drops the source's own entry, so
    # obj_attrs keeps no key for an object that no longer has traces, the same
    # way group membership and the host tree are already cleaned. Covered
    # directly by test_split_object_leaves_no_obj_attrs_behind below.
    assert_coherent(rich_series, "splitObject('star')")
    counts = trace_counts(rich_series)
    assert "star" not in counts
    assert sorted(new_names) == sorted(n for n in counts if n.startswith("star_"))
    assert sum(counts[n] for n in new_names) == before_counts["star"]
    assert sum(counts.values()) == sum(before_counts.values()), "traces were lost"
    # the attributes splitObject promises to carry over: alignment, group
    # membership and hosts, via ObjectTableItems.assignCopyAttrs
    groups = rich_series.getDict()["object_groups"]
    for name in new_names:
        assert name in groups["shapes"], f"{name!r} lost the source's group"
        assert rich_series.getAttr(name, "alignment") \
            == rich_series.getAttr("star", "alignment")

    states.undoState()
    rich_series.data.refresh()
    assert_state_restored(before, snapshot(rich_series), "splitObject")
    assert_coherent(rich_series, "undo of splitObject")


def test_split_object_leaves_no_obj_attrs_behind(rich_series):
    """A split has to leave no ``obj_attrs`` entry for the object it emptied.

    ``Series.splitObject`` copies the source object's attributes onto each new
    object, and used to never drop the source's own entry, so ``obj_attrs`` kept
    a key for a name with no traces. ``Series.deleteAllTraces`` and
    ``Series.deleteObjects`` both did clean it, so this was an inconsistency and
    not the intended contract.

    ``splitObject`` now drops the entry its own ``addLog`` re-creates after the
    centralized cleanup has run, so all three paths that empty an object end the
    same way.
    """
    rich_series.splitObject("star")
    rich_series.data.refresh()
    assert "star" not in rich_series.getDict()["obj_attrs"]


def test_delete_all_traces_undo_restores_the_series(rich_series):
    states = SeriesStates(rich_series)
    before = snapshot(rich_series)

    rich_series.deleteAllTraces("star", series_states=states)
    rich_series.data.refresh()
    assert_coherent(rich_series, "deleteAllTraces('star')")
    assert "star" not in trace_counts(rich_series)

    states.undoState()
    rich_series.data.refresh()
    assert_state_restored(before, snapshot(rich_series), "deleteAllTraces")
    assert_coherent(rich_series, "undo of deleteAllTraces")


# ---------------------------------------------------------------------------
# section-level operations, asserted at the section-level undo layer
# ---------------------------------------------------------------------------

def _record(states, section, series):
    """Push a section undo state, the way ``FieldWidget.saveState`` does."""
    states[section].addState(section, series)
    section.save()


def test_merge_trace_attributes_undo_restores_the_section(rich_series, field):
    """``FieldWidgetTrace.mergeTraces(merge_attrs_only=True)``, the real method.

    Merging attributes renames the selected traces onto the first one's object,
    so it moves traces between contours. Asserted at ``SectionStates``, which is
    the layer ``field_interaction`` writes to, not at ``SeriesStates.undoState``.
    """
    section, states, widget = field
    before = snapshot(rich_series)
    before_total = sum(trace_counts(rich_series).values())

    for trace in (section.contours["star"].getTraces()
                  + section.contours["square"].getTraces()):
        section.addSelectedTrace(trace)
    widget.mergeTraces(merge_attrs_only=True)

    assert widget.saved == 1, "the merge recorded no undo state"
    assert len(section.contours["star"].getTraces()) == 2
    assert sum(trace_counts(rich_series).values()) == before_total, "traces were lost"
    assert_coherent(rich_series, "mergeTraces(merge_attrs_only=True)")

    states.undoSection(section)
    section.save()
    assert_state_restored(before, snapshot(rich_series), "the attribute merge")
    assert_coherent(rich_series, "undo of the attribute merge")


def test_focus_mode_split_undo_restores_the_section(rich_series, field):
    """The focus-mode split: rename one trace out of its object, then undo.

    Two edits are recorded before the split on purpose. With a single recorded
    state ``SectionStates.undoState`` takes its wholesale-replace branch, which
    would restore the section even if the split had never been recorded; two or
    more takes the per-contour branch, which is the one a real editing session
    is always in and the one that can lose a trace.
    """
    section, states, widget = field

    for index in range(2):
        bystander = section.contours["triangle"].getTraces()[0]
        section.editTraceAttributes(
            [bystander], None, (7, 7, index), None, None, log_event=False
        )
        _record(states, section, rich_series)
    before = snapshot(rich_series)
    before_counts = section_counts(section)

    victim = section.contours["star"].getTraces()[0]
    section.editTraceAttributes(
        [victim], f"{victim.name}_split", victim.color, victim.tags,
        victim.fill_mode, log_event=False,
    )
    _record(states, section, rich_series)

    split_counts = section_counts(section)
    assert "star_split" in split_counts and "star" not in split_counts
    assert sum(split_counts.values()) == sum(before_counts.values())

    states.undoSection(section)
    section.save()
    assert section_counts(section) == before_counts
    assert_state_restored(before, snapshot(rich_series), "the focus-mode split")
    assert_coherent(rich_series, "undo of the focus-mode split")


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_destructive_edit_survives_save_and_reopen(tmp_path, rich_series):
    """The result of a destructive operation must be what a reopen gives back.

    ``tests/test_jser_canonical_format.py`` already proves an *unmodified* series
    round trips losslessly and byte-stably. What it does not cover is a round
    trip taken after an operation has removed data, where the risk is the
    opposite one: an in-memory change that the save never wrote, or a removal the
    save silently undid.
    """
    rich_series.removeAllTraceTags(["star"])
    rich_series.deleteAllTraces("square")
    rich_series.data.refresh()
    before = snapshot(rich_series)

    jser_fp = rich_series.jser_fp
    rich_series.saveJser()
    rich_series.close()

    reopened = Series.openJser(jser_fp, progress=NullProgressReporter)
    reopened.setProgressReporter(NullProgressReporter)
    try:
        assert_state_restored(before, snapshot(reopened), "a save and reopen")
        assert_coherent(reopened, "a save and reopen")
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# proof the invariants have teeth: put the damage in and watch them fire
# ---------------------------------------------------------------------------

def test_teeth_a_half_deleted_section_is_caught(rich_series):
    """Build the wreckage a half-finished section delete leaves and watch I5 fire.

    The defect this remembers: the section list reported one entry per selected
    *cell* rather than per row, so a single selected row asked
    ``Series.deleteSections`` to delete the same number five times. The first
    pass removed the file and the ``sections`` entry, the second raised
    ``KeyError`` on the entry that was already gone, and the z-trace loop at the
    end of the function never ran. What shipped to the user was a series with a
    section deleted from disk and from the index while four z-traces still
    carried points on it, with no undo, because the no-undo warning had already
    been accepted.

    That end state is what this builds, and it builds it directly rather than
    driving a caller into it. Two reasons. The datatype now collapses repeats
    and validates the whole request before it deletes anything, so no caller can
    reach the half-deleted state any more, and the tests next to that change own
    the proof that it cannot; and the property worth pinning here was never that
    a particular caller can commit the violation, it is that ``check_series``
    *notices* one. Reconstructing the state costs no duplicated production code
    and does not care how a series came to be corrupt, which is the point of a
    whole-series invariant. The two lines below are the definition of "the
    section is gone" -- the same ``sections`` dict and working directory that
    ``check_series`` itself reads -- not a copy of any algorithm.

    Kept surgical on purpose: the assertion is that I5 and *only* I5 fires, so
    the test cannot pass on the strength of some unrelated violation if the I5
    check is ever weakened or dropped.
    """
    snum = 2
    assert not check_series(rich_series), "the fixture was not coherent to begin with"
    assert any(
        pt[2] == snum for ztrace in rich_series.ztraces.values()
        for pt in ztrace.points
    ), f"fixture has no z-trace point on section {snum}"

    # Exactly what the loop had done when it raised: the file and the index
    # entry for section 2 are gone, and nothing has repointed the z-traces.
    os.remove(os.path.join(rich_series.getwdir(), rich_series.sections[snum]))
    del rich_series.sections[snum]

    problems = check_series(rich_series)
    i5 = [p for p in problems if p.startswith("I5 ztrace/sections")]
    assert i5, (
        "I5 did not fire on a series whose z-traces point at a section it no "
        f"longer has; check_series reported {problems}"
    )
    assert len(i5) == len(rich_series.ztraces), \
        f"expected every z-trace to be reported, got {i5}"
    assert all(f"section(s) [{snum}]" in p for p in i5), i5
    assert problems == i5, (
        "the reconstruction was meant to break I5 and nothing else, but "
        f"check_series also reported {[p for p in problems if p not in i5]}"
    )


def test_teeth_tag_wiping_sentinel_is_caught(rich_series, monkeypatch):
    """Inject the mixed-selection tag defect and watch the tag assertion fire.

    The defect's shape: a sentinel that should mean "leave tags alone" reaches
    ``Section.editTraceAttributes`` as an empty set with ``add_tags=False``,
    which means "replace the tags with nothing". Injected at that boundary
    rather than in the dialog, because the boundary is where the damage is done
    and it is the same for every caller.
    """
    honest = Section.editTraceAttributes

    def defective(self, traces, name, color, tags, mode, add_tags=False,
                  log_event=True):
        if tags is None:
            tags, add_tags = set(), False
        return honest(self, traces, name, color, tags, mode,
                      add_tags=add_tags, log_event=log_event)

    before_tags = tags_by_object(rich_series)
    monkeypatch.setattr(Section, "editTraceAttributes", defective)
    rich_series.editObjectAttributes(["star", "square"], color=(9, 9, 9))
    monkeypatch.undo()

    after_tags = tags_by_object(rich_series)
    assert after_tags["star"] == [[]] and after_tags["square"] == [[]], \
        "the defect did not reproduce"
    with pytest.raises(AssertionError, match="changed tags"):
        assert after_tags == before_tags, "a color edit changed tags"


def test_teeth_unrecorded_focus_split_loses_a_trace(rich_series, field):
    """Reintroduce the unrecorded focus-mode split and watch the invariants fire.

    Before the split recorded an undo state, ``SectionStates.undoState`` restored
    only the contours named in the *previous* edit's modified set. The
    ``<obj>_split`` contour was in no state's modified set, so an undo left it
    alone and did not bring the original object back. This asserts both that the
    object set changed across operation-plus-undo and that the deep comparison
    reports it.
    """
    section, states, widget = field

    for index in range(2):
        bystander = section.contours["triangle"].getTraces()[0]
        section.editTraceAttributes(
            [bystander], None, (7, 7, index), None, None, log_event=False
        )
        _record(states, section, rich_series)
    before = snapshot(rich_series)
    before_counts = section_counts(section)

    victim = section.contours["star"].getTraces()[0]
    section.editTraceAttributes(
        [victim], f"{victim.name}_split", victim.color, victim.tags,
        victim.fill_mode, log_event=False,
    )
    section.save()  # the defect: no state recorded for the split

    states.undoSection(section)
    section.save()

    after_counts = section_counts(section)
    assert "star" not in after_counts, "the defect did not reproduce"
    assert after_counts != before_counts
    assert state_diff(before, snapshot(rich_series)), \
        "the deep comparison missed a lost object"
    with pytest.raises(AssertionError, match="undo did not restore"):
        assert_state_restored(before, snapshot(rich_series))


# ---------------------------------------------------------------------------
# widget plumbing for the two GUI-driven tests
# ---------------------------------------------------------------------------

class _StubField:
    """The two attributes of ``MainWindow.field`` the section list touches."""

    def __init__(self, section):
        self.section = section

    def reload(self):
        pass

    def reloadImage(self):
        pass

    def clearStates(self):
        pass


class _StubTableManager:
    """The manager surface the section list and ``trace_function`` use.

    Deliberately a stub: the real ``TableManager`` owns every list in the app
    plus the undo stack, and building it would drag in ``MainWindow``, which
    blocks indefinitely under the offscreen platform.
    """

    def __init__(self):
        self.series_states = {}
        self.tables = {
            "section": [], "trace": [], "ztrace": [], "flag": [], "object": [],
        }

    def hasFocus(self):
        return None

    def updateSections(self, *args, **kwargs):
        pass

    def updateObjects(self, *args, **kwargs):
        pass

    def refresh(self):
        pass

    def recreateTable(self, table=None):
        pass

    def recreateTables(self, refresh_data=False):
        pass


@pytest.fixture
def section_list(qapp, rich_series, monkeypatch):
    """A real ``SectionTableWidget`` over the fixture series, with no modals.

    ``notify`` and ``noUndoWarning`` are called straight from the slot and each
    spins a modal event loop; offscreen there is nobody to dismiss it, so they
    have to be replaced by name in the module that imported them.
    """
    from PySide6.QtWidgets import QWidget
    from PyReconstruct.modules.gui.table import section as section_module
    from PyReconstruct.modules.gui.table.section import SectionTableWidget

    unlock(rich_series)
    notices = []
    monkeypatch.setattr(
        section_module, "notify", lambda m, *a, **k: notices.append(m)
    )
    monkeypatch.setattr(section_module, "noUndoWarning", lambda *a, **k: True)

    series = rich_series

    class _StubMainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.series = series
            self.field = _StubField(series.loadSection(sorted(series.sections)[0]))
            self.notices = notices

        def saveAllData(self):
            pass

        def seriesModified(self, modified=True):
            pass

        def changeSection(self, snum, save=False):
            pass

        def checkActions(self, *args, **kwargs):
            pass

        def optimizeBC(self, *args, **kwargs):
            pass

    window = _StubMainWindow()
    widget = SectionTableWidget(series, window, _StubTableManager())
    yield widget, window
    widget.deleteLater()
    window.deleteLater()


@pytest.fixture
def field(qapp, rich_series, monkeypatch):
    """Section 0, a live ``SeriesStates``, and the real field trace methods.

    Bound onto a duck-typed object rather than a real ``FieldWidget`` for the
    same reason as ``tests/test_focus_split_undo_duplicate.py``: constructing one
    needs ``MainWindow``, which blocks under the offscreen platform. The methods
    under test are the real ones.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace as trace_module
    from PyReconstruct.modules.gui.main.field_widget_2_trace import FieldWidgetTrace

    notices = []
    monkeypatch.setattr(
        trace_module, "notify", lambda m, *a, **k: notices.append(m)
    )

    states = SeriesStates(rich_series)
    section = rich_series.loadSection(0)
    states[section]  # initialize the baseline for this section

    class _Widget:
        mergeTraces = FieldWidgetTrace.mergeTraces
        # The lock check `trace_function` now runs before doing anything. The
        # real one, not a stub: nothing here is locked, so it passes through,
        # and if it ever stops passing through that is worth failing on.
        refuseLockedTraces = FieldWidgetTrace.refuseLockedTraces

        def __init__(self):
            self.series = rich_series
            self.section = section
            self.series_states = states
            self.table_manager = _StubTableManager()
            self.mainwindow = self
            self.hide_trace_layer = False
            self.saved = 0
            self.notices = notices

        def saveAllData(self):
            pass

        def saveState(self):
            self.saved += 1
            self.series_states[self.section].addState(self.section, self.series)
            self.section.save()

        def generateView(self, *args, **kwargs):
            pass

    return section, states, _Widget()
