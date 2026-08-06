"""``Series.removeObjAttrs`` must clean up a name it has no ``obj_attrs`` for.

What this is and what it is not. No user-visible behavior changes here: on
``main`` the unconditional ``del self.obj_attrs[name]`` is not reachable with a
missing key, and the measurements that establish that are recorded below. This is
hardening plus a written-down invariant, not a bug fix, and the tests are split
so which is which stays legible: the first section pins the invariant that made
the ``del`` safe, and the rest pin that the method no longer depends on it.

The call graph, measured on ``main`` at ``a83c65be``. ``removeObjAttrs`` has
exactly one caller in the tree, ``SeriesData.updateSection``, inside
``if log_events and not self.supress_logging:``:

    for obj_name in removed_objects:
        self.series.addLog(obj_name, None, "Delete object")
        self.series.removeObjAttrs(obj_name)

``Series.addLog`` writes provenance as a side effect: for a truthy ``obj_name``
it calls ``setAttr(obj_name, "last_user", self.user)``, and ``setAttr`` creates
``obj_attrs[name] = {}`` before assigning. So the line above the call *creates*
the entry the line below deletes, for an object that may never have had one.
Instrumented on the fixture's ``star``, which ships with no attributes at all:
``removeObjAttrs`` was entered with ``{'last_user': ...}``, written microseconds
earlier by that log.

On the ordinary delete path the stamp is written twice, and that matters when
choosing what to test. ``Section.removeTrace`` also logs, "Delete trace(s)" for
the same object name, and its ``log_event`` defaults to ``True``. Measured: with
``updateSection``'s own ``addLog`` moved below the ``removeObjAttrs`` call, a
``Series.deleteAllTraces`` still found the entry present, put there by
``removeTrace``. So
``test_the_entry_is_present_at_every_removal_during_a_real_delete`` removes its
traces with ``log_event=False``, which is what makes it fail when the caller's own
stamp goes: ``[('star', {})]``.

That is an invariant of today's call graph and not a checked precondition. It
holds only while both of these are true, and neither is tested at the call site:

- ``obj_name`` is truthy, because ``addLog``'s ``setAttr`` sits under
  ``if obj_name:``
- ``series.user`` is not ``None``, because ``setAttr`` treats a ``None`` value as
  a removal: it assigns, deletes the key it just wrote, then deletes
  ``attrs[name]`` if that left it empty. Measured: with ``series.user`` forced to
  ``None``, deleting an object raised ``KeyError: 'triangle'`` out of
  ``Series.deleteAllTraces -> Section.save -> updateSection -> removeObjAttrs``.
  With ``None`` but a pre-existing ``comment`` attribute, no raise, because the
  surviving key kept the dict non-empty.

Neither condition is reachable through the application, which is why this ships
as hardening:

- ``series.user`` is ``getOption("username")``. Measured: ``username`` is not in
  ``Series.getEmptyDict()["options"]``; ``Series.qsettings_defaults["username"]``
  is ``get_username()``, a ``str`` with a ``'default'`` fallback on ``OSError``;
  and ``QSettings.value(key, type=str)`` returns ``''`` and never ``None``, for a
  missing key and for a stored list or dict alike. Only a ``SettingsStore``
  injected through ``Series.setSettingsStore`` that stores ``None`` outright
  produces it, and nothing outside the suite injects a store at all.
- an empty object name is not representable. ``Trace.fromList`` branches on
  ``if not name or len(l) == 9``, so a contour keyed on ``""`` re-reads as a
  name-prefixed row and fails with
  ``ValueError: not enough values to unpack (expected 8, got 7)``. An
  empty-named object cannot survive a save, so it cannot be deleted out of a
  reopened series. That is a separate defect and is not addressed here.

Why the ``del`` was worth replacing anyway, given all of the above. Two reasons,
both about the code as it stands rather than about hypothetical callers.

1. It was the odd one out among its own neighbors. ``removeObjAttrs`` performs
   three cleanups, and the other two are written to no-op on a name they do not
   know: ``HostTree.removeObject`` opens with
   ``if obj_name not in self.objects: return``, and
   ``ObjGroupDict.removeObject`` reaches ``getObjectGroups``, whose body is a
   ``try``/``except KeyError`` returning an empty set. The sibling method
   ``Series.renameObjAttrs`` guards the same dict with
   ``if old_name in self.obj_attrs``. Nothing in the docstring ("Delete all
   attrs associated with an object name") declares presence as a precondition.
2. It did not fail cleanly. The ``del`` sat *between* the group cleanup and the
   host cleanup, so a missing entry stripped group membership, skipped the
   ``host_tree`` cleanup entirely and threw out of ``Section.save()``. An
   assertion that half-mutates the series before it fires is not a useful
   assertion. ``test_removal_is_total_for_a_name_with_no_attrs_entry`` is the
   test that says so: it fails on a revert both by raising and, with the raise
   caught, by finding the deleted object still sitting in ``host_tree`` as the
   host of a surviving object.

``host_tree`` really can hold a name that ``obj_attrs`` does not:
``Series.setObjHosts`` writes only to ``host_tree``, and ``HostTree.add``
registers the host as well as the traveler. So "no attrs entry" does not imply
"no host entry", and the two cleanups are independent.

No ``gui`` marker: these drive the datatype directly and build no widgets. No
test here touches ``QSettings("KHLab", "PyReconstruct")``; the two that need a
username go through ``DictSettingsStore``, and none assigns ``series.user``.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)

# The fixture ships with an empty obj_attrs, which is what makes it useful here:
# every entry these tests reason about is one the test or the code put there.
NAME = "star"
TRAVELER = "square"


def open_fixture(tmp_path, name="s", username="tester"):
    """A real Series from a private copy of the checked-in fixture.

    ``shapes1.jser`` rather than ``conftest.py``'s ``real_series``: that one is
    ``class_series.jser`` at 198 sections, and this needs a series small enough
    to delete out of and re-read several times per module.

    The settings store is always injected. ``series.user`` is read on every
    ``addLog``, and the default store is backed by
    ``QSettings("KHLab", "PyReconstruct")``, which is machine-wide and holds the
    real user's preferences. Reading it would make the tests depend on the
    developer's own username; writing it is out of the question.
    """
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    store = DictSettingsStore()
    store.set_value(None, "username", username)
    series.setSettingsStore(store)
    return series


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    s.close()


def residue(series, name):
    """The three references ``removeObjAttrs`` owns, as a tuple of bools.

    ``host_tree.objects`` rather than ``host_tree.getDict()``: ``getDict`` drops
    an object with no hosts of its own, so a name that is purely somebody else's
    host serializes to nothing while still occupying the tree.
    """
    return (
        name in series.obj_attrs,
        bool(series.object_groups.getObjectGroups(name)),
        name in series.host_tree.objects,
    )


# --------------------------------------------------------------------------
# the invariant that made the unconditional del safe
# --------------------------------------------------------------------------

def test_a_log_creates_the_obj_attrs_entry_the_removal_relies_on(series):
    """The mechanism, isolated. ``addLog`` is what makes the removal safe.

    This is the test that replaces the ``KeyError`` as the thing that notices if
    the invariant breaks. It fails if ``addLog`` stops stamping ``last_user``, or
    starts stamping it conditionally, which is the refactor the bare ``del`` was
    standing guard against. It says nothing about ``del`` versus ``pop``: it
    asserts on what the caller builds, not on what the callee does with it.
    """
    assert NAME not in series.obj_attrs, "fixture is supposed to ship with none"

    series.addLog(NAME, None, "Delete object")

    assert series.obj_attrs[NAME] == {"last_user": "tester"}


def test_the_entry_is_present_at_every_removal_during_a_real_delete(series, monkeypatch):
    """End to end, with the trace-level log deliberately switched off.

    ``Section.removeTrace`` logs "Delete trace(s)" for the same object name by
    default, so on the ordinary delete path the entry is stamped twice and moving
    ``updateSection``'s own ``addLog`` does not expose anything. Measured: with
    that ``addLog`` moved below the ``removeObjAttrs`` call, the entry was still
    present at entry, put there by ``removeTrace``. So the traces here are removed
    with ``log_event=False``, which leaves ``updateSection``'s "Delete object"
    stamp as the only thing standing between the removal and a missing key.
    """
    seen = []
    original = Series.removeObjAttrs

    def spy(self, name):
        seen.append((name, dict(self.obj_attrs.get(name, {}))))
        return original(self, name)

    monkeypatch.setattr(Series, "removeObjAttrs", spy)

    for snum, section in series.enumerateSections(show_progress=False):
        if NAME not in section.contours:
            continue
        for trace in section.contours[NAME].getTraces():
            section.removeTrace(trace, log_event=False)
        section.save()
    series.data.refresh()

    assert NAME not in series.data["objects"]
    assert seen == [(NAME, {"last_user": "tester"})], seen


def test_the_username_the_invariant_depends_on_is_never_none(series):
    """Precondition 2, pinned where it is decided rather than where it is used.

    ``setAttr`` treats a ``None`` value as a removal, so a ``None`` username is
    the one way the log stamp writes nothing while still being called. It cannot
    happen: ``username`` resolves out of ``Series.qsettings_defaults``, whose
    default is ``get_username()``, and an unset key falls back to that default
    rather than to ``None``.
    """
    assert "username" not in Series.getEmptyDict()["options"]
    assert isinstance(Series.qsettings_defaults["username"], str)
    assert Series.qsettings_defaults["username"]

    empty_store = DictSettingsStore()
    series.setSettingsStore(empty_store)
    assert isinstance(series.user, str) and series.user


# --------------------------------------------------------------------------
# the method no longer depends on the invariant
# --------------------------------------------------------------------------

def test_removal_is_total_for_a_name_with_no_attrs_entry(series):
    """The regression test, and the argument for the change.

    The name has a group and a place in the host tree but no ``obj_attrs`` entry,
    which ``Series.setObjHosts`` makes an ordinary state: it writes only to
    ``host_tree``, and ``HostTree.add`` registers the host alongside the
    traveler.

    On a revert this fails twice over. It raises ``KeyError``, and if the raise
    is caught the series is left inconsistent rather than unchanged: the group
    membership is already gone (that cleanup runs first) while ``star`` is still
    in ``host_tree`` as ``square``'s host, because the ``del`` sat between the
    two and never let the third line run.
    """
    series.object_groups.add("shapes", NAME)
    series.setObjHosts([TRAVELER], [NAME])
    assert NAME not in series.obj_attrs
    assert residue(series, NAME) == (False, True, True)

    series.removeObjAttrs(NAME)

    assert residue(series, NAME) == (False, False, False)
    assert NAME not in series.host_tree.getHosts(TRAVELER)


def test_removal_still_removes_a_real_entry(series):
    """The guard must not have turned the removal into a no-op.

    A ``pop`` with a default is one keystroke away from a ``pop`` that silently
    keeps the data, and nothing else in this file would notice.
    """
    series.setAttr(NAME, "comment", "keep me")
    series.setAttr(NAME, "curation", (True, "tester", "2026-07-30"))
    assert series.obj_attrs[NAME] == {
        "comment": "keep me",
        "curation": (True, "tester", "2026-07-30"),
    }

    series.removeObjAttrs(NAME)

    assert NAME not in series.obj_attrs


def test_removal_of_a_name_the_series_never_had_is_a_no_op(series):
    """The docstring says "delete all attrs associated with an object name".

    For a name with none, that is nothing, and doing nothing should not require
    the caller to have checked first. This is the plain reading of the method's
    own contract.
    """
    before = dict(series.getDict()["obj_attrs"])

    series.removeObjAttrs("no_such_object")

    assert series.getDict()["obj_attrs"] == before


# --------------------------------------------------------------------------
# both halves at once: the guard gone and the caller's log stamp gone
# --------------------------------------------------------------------------

def test_a_delete_completes_when_the_log_stamp_writes_nothing(tmp_path):
    """The combined failure, driven end to end through the real delete path.

    A ``None`` username is the smallest way to make the caller lose its stamp
    without editing the caller: ``addLog`` still runs and still writes the log
    itself, but its ``setAttr(obj_name, "last_user", None)`` creates the entry
    and then removes it again, so ``removeObjAttrs`` is reached with nothing to
    delete. That is the state the ``del`` could not survive. Measured on a
    revert: ``KeyError: 'star'`` out of
    ``deleteAllTraces -> Section.save -> updateSection -> removeObjAttrs``,
    partway through the section loop.

    ``series.user`` is never assigned here. The username comes from an injected
    ``DictSettingsStore``, so the real ``QSettings`` domain is untouched.
    """
    series = open_fixture(tmp_path, name="nouser", username=None)
    try:
        assert series.user is None
        series.object_groups.add("shapes", NAME)
        series.setObjHosts([TRAVELER], [NAME])
        assert NAME not in series.obj_attrs

        series.deleteAllTraces(NAME)
        series.data.refresh()

        assert NAME not in series.data["objects"]
        assert residue(series, NAME) == (False, False, False)
        assert NAME not in series.host_tree.getHosts(TRAVELER)
        assert TRAVELER in series.data["objects"], "the traveler must survive"
    finally:
        series.close()
