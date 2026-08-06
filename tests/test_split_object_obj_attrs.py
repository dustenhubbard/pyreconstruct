"""``Series.splitObject`` must not leave ``obj_attrs`` keyed on the source.

The mechanism, because the diff is a moved statement and does not show it.
Cleanup of a vanished object is centralized in ``SeriesData.updateSection``:
when an object's last trace goes, the object is dropped from
``series.data["objects"]`` and ``Series.removeObjAttrs`` clears its group
membership, its ``obj_attrs`` entry and its ``host_tree`` entry. A split empties
the source object, so that cleanup does run, on the last ``section.save()`` of
the split loop.

``Series.addLog`` also writes: for a named object it calls
``setAttr(name, "last_user", user)``, which *creates* ``obj_attrs[name]`` if
there is none. ``splitObject`` logged after its loop, so the stamp landed after
the cleanup and re-created an entry for a name with no traces on any section.
Measured on the split of a 5-trace object carrying a comment and a user column:

    before  obj_attrs = {'star': {'comment': 'keep me', 'user_columns': {...}}}
    after   obj_attrs = {'star': {'last_user': 'dusten'}, 'star_1': {...}, ...}

``Series.deleteAllTraces`` and ``Series.deleteObjects`` both end with a clean
``obj_attrs``, and for the same reason in reverse: their "Delete object" log is
written by ``updateSection`` immediately *before* it calls ``removeObjAttrs``, so
their stamp is the one that gets cleared. Three operations empty an object and
one of them kept a key, which is an ordering accident and not a contract.

Moving the log above the split loop is *not* the fix, and
``test_split_still_logs_the_event_against_the_source`` is the test that says so.
``LogSet.addLog`` treats "Delete object" specially: it drops every earlier log
carrying that object name. ``updateSection`` emits exactly that log for the
emptied source, so a split logged first loses its own event. Measured: with the
log moved up, ``log_set.all_logs`` held five "Create object" entries and one
"Delete object" and no split event at all. So the log stays after the loop and
``splitObject`` drops the re-created entry explicitly.

The residue is small but it is persistent, not cosmetic: ``obj_attrs`` is
serialized into the ``.jser``, so the entry outlives the session, accumulates
one key per split, and is never collected.
``test_split_residue_does_not_survive_a_save`` is the one that would catch a fix
that only cleaned memory, and
``test_repeated_splits_do_not_accumulate_dead_keys`` the one that shows the count
grows.

No ``gui`` marker: these drive the datatype directly and build no widgets.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)

SOURCE = "star"  # 5 traces, one per section, and a z-trace of the same name


def open_fixture(tmp_path, name="s"):
    """A real Series opened from a private copy of the checked-in fixture.

    ``shapes1.jser`` rather than the ``real_series`` fixture in ``conftest.py``:
    that one is ``class_series.jser`` (198 sections), and this needs a series
    small enough to split and re-read whole, several times, per test.
    """
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    s.close()


def give_the_source_attributes(series):
    """The fixture ships with no per-object attributes, so add some.

    Without this the assertions would hold for the wrong reason: an object that
    never had an ``obj_attrs`` entry cannot leave one behind, and the entry that
    the defect left was created by the log stamp alone.
    """
    series.object_groups.add("shapes", SOURCE)
    series.setAttr(SOURCE, "comment", "keep me")
    series.addUserCol("stage", ["a", "b"], log_event=False)
    series.setUserColAttr(SOURCE, "stage", "a")
    series.setObjHosts(["square"], [SOURCE])
    series.data.refresh()
    series.save()
    return series


def trace_counts(series):
    """object name -> total traces across the series, empty contours omitted."""
    counts = {}
    for snum in sorted(series.sections):
        for name, contour in series.loadSection(snum).contours.items():
            n = len(contour.getTraces())
            if n:
                counts[name] = counts.get(name, 0) + n
    return counts


# --------------------------------------------------------------------------
# the premise: the source really is emptied, and really did have attributes
# --------------------------------------------------------------------------

def test_the_source_starts_with_attributes_and_ends_with_no_traces(series):
    """Guards both halves of the setup the other tests rely on."""
    give_the_source_attributes(series)
    assert series.getDict()["obj_attrs"][SOURCE]["comment"] == "keep me"
    assert trace_counts(series)[SOURCE] == 5

    new_names = series.splitObject(SOURCE)
    series.data.refresh()

    counts = trace_counts(series)
    assert SOURCE not in counts, "the split left traces on the source name"
    assert SOURCE not in series.data["objects"]
    assert sorted(new_names) == sorted(n for n in counts if n.startswith("star_"))


# --------------------------------------------------------------------------
# the defect
# --------------------------------------------------------------------------

def test_split_leaves_no_obj_attrs_entry_for_the_source(series):
    """The regression test. Before the fix: ``{'last_user': 'dusten'}``."""
    give_the_source_attributes(series)
    series.splitObject(SOURCE)
    series.data.refresh()

    obj_attrs = series.getDict()["obj_attrs"]
    assert SOURCE not in obj_attrs, (
        f"obj_attrs kept {SOURCE!r} -> {obj_attrs.get(SOURCE)!r} for an object "
        f"with no traces on any section"
    )


def test_split_cleans_obj_attrs_the_same_way_the_deletes_do(tmp_path):
    """The comparison that makes this an inconsistency rather than a choice.

    Three operations empty an object. All three should leave the same references
    behind, which is none of the three that ``removeObjAttrs`` owns. Before the
    fix, ``splitObject`` read ``(True, False, False)`` and the other two
    ``(False, False, False)``.
    """
    def residue(label, run):
        s = give_the_source_attributes(open_fixture(tmp_path, name=label))
        try:
            run(s)
            s.data.refresh()
            d = s.getDict()
            return (
                SOURCE in d["obj_attrs"],
                any(SOURCE in members for members in d["object_groups"].values()),
                any(
                    SOURCE == host or SOURCE in children
                    for host, children in d["host_tree"].items()
                ),
            )
        finally:
            s.close()

    results = {
        "splitObject": residue("split", lambda s: s.splitObject(SOURCE)),
        "deleteAllTraces": residue("dat", lambda s: s.deleteAllTraces(SOURCE)),
        "deleteObjects": residue("do", lambda s: s.deleteObjects([SOURCE])),
    }
    assert set(results.values()) == {(False, False, False)}, results


def test_split_residue_does_not_survive_a_save(series, tmp_path):
    """``obj_attrs`` is written to the ``.jser``, so the entry outlived the run.

    This is the assertion that makes the residue a data defect rather than an
    in-memory untidiness, and it is the one a fix that only patched the
    in-memory dict would fail.
    """
    give_the_source_attributes(series)
    series.splitObject(SOURCE)
    series.data.refresh()
    fp = series.jser_fp
    series.saveJser()
    series.close()

    reopened = Series.openJser(fp, progress=NullProgressReporter)
    try:
        reopened.setProgressReporter(NullProgressReporter)
        assert SOURCE not in reopened.getDict()["obj_attrs"]
        assert SOURCE not in reopened.data["objects"]
    finally:
        reopened.close()


def test_repeated_splits_do_not_accumulate_dead_keys(series):
    """One dead key per split, and splitting is not a once-per-series action.

    Splitting an object and then splitting one of the results left two keys for
    two names that no longer exist. There is no ceiling on that: the count grows
    with the number of splits the series has ever seen and nothing ever collects
    it.
    """
    give_the_source_attributes(series)
    first_round = series.splitObject(SOURCE)
    series.data.refresh()
    second_source = sorted(first_round)[0]
    series.splitObject(second_source)
    series.data.refresh()

    obj_attrs = series.getDict()["obj_attrs"]
    tracked = set(series.data["objects"])
    dead = sorted(set(obj_attrs) - tracked)
    assert not dead, f"obj_attrs holds {dead} for objects the series does not have"


# --------------------------------------------------------------------------
# what the move must not break
# --------------------------------------------------------------------------

def test_split_still_logs_the_event_against_the_source(series):
    """The split event survives, which is why the log stays after the loop.

    This is the test that rules out the tidier-looking fix. ``LogSet.addLog``
    drops every earlier log for an object name when it sees "Delete object" for
    it, and ``SeriesData.updateSection`` emits that log for the source the split
    has just emptied. So a ``splitObject`` that logged before its loop would
    silently lose the only record that ``star_N`` came from ``star``.
    """
    give_the_source_attributes(series)
    series.splitObject(SOURCE)

    matching = [
        log for log in series.log_set.all_logs
        if log.obj_name == SOURCE
        and log.event == "Split into individual objects per trace"
    ]
    assert len(matching) == 1, [
        (log.obj_name, log.event) for log in series.log_set.all_logs
    ]
    assert series.user in series.editors


def test_split_still_logs_nothing_when_asked_not_to(series):
    give_the_source_attributes(series)
    series.splitObject(SOURCE, log_event=False)

    assert not [
        log for log in series.log_set.all_logs
        if log.event == "Split into individual objects per trace"
    ]
    assert SOURCE not in series.getDict()["obj_attrs"]


def test_split_still_carries_the_source_attributes_onto_the_new_objects(series):
    """The attributes the split is supposed to copy still arrive.

    ``getSourceAttrs`` is read before the loop and ``assignCopyAttrs`` runs after
    it, so the cleanup in between must not be able to eat the values in flight.
    Group membership and the fixed alignment are what the split promises to
    carry; hosts are read too, but ``star`` is ``square``'s host rather than
    having one of its own, so there is nothing to carry there and asserting on it
    would only pin the fixture's shape.
    """
    give_the_source_attributes(series)
    alignment = series.getAttr(SOURCE, "alignment")

    new_names = series.splitObject(SOURCE)
    series.data.refresh()

    groups = series.getDict()["object_groups"]
    for name in sorted(new_names):
        assert name in groups["shapes"], f"{name!r} lost the source's group"
        assert series.getAttr(name, "alignment") == alignment


def test_split_of_an_object_with_no_attributes_leaves_nothing_behind(series):
    """The bare case: no groups, no attrs, no host.

    ``Series.removeObjAttrs`` does an unconditional ``del self.obj_attrs[name]``,
    so an object with no entry would raise if the log stamp had not created one
    first. Logging before the loop keeps that true.
    """
    assert "triangle" not in series.getDict()["obj_attrs"]

    new_names = series.splitObject("triangle")
    series.data.refresh()

    assert new_names
    assert "triangle" not in series.getDict()["obj_attrs"]
    assert "triangle" not in series.data["objects"]
