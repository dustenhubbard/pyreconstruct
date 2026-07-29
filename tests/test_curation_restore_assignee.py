"""Restoring "Needs curation" from the log keeps the assignee.

``Series.setCuration(names, "Needs curation", assign_to)`` stores the assignee
in the object's curation attribute -- ``(False, assign_to, date)`` -- and the
object list shows it in the User column. But the log entry it wrote was the
bare event "Mark as needs curation", with no assignee anywhere in it, so
``Series.updateCurationFromHistory`` (Series > Restore object curation status
from log) had nothing to recover and stored ``(False, "", date)``: a restored
"Needs curation" row silently lost its assignment.

The fix has two halves, and this module exercises them together and apart:

* ``setCuration`` now logs "Mark as needs curation (assigned to <user>)" when
  an assignee is given (the bare event when not, so unassigned rows are logged
  exactly as before), and
* ``updateCurationFromHistory`` parses the assignee back out of that event.
  Logs written before this change still carry the bare event and restore with
  no assignee, exactly as they did -- there is nothing to recover from them.

Everything runs on a real ``Series`` opened from the ``shapes1.jser`` fixture
(copied to ``tmp_path``), through the real log set and the real restore path.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.log import Log
from PyReconstruct.modules.datatypes.series import Series

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


@pytest.fixture
def series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    s = Series.openJser(fp)
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.close()


def _lose_curation(series, name):
    """Simulate the loss the restore action exists for: the stored attribute
    is gone while the log survives."""
    del series.obj_attrs[name]["curation"]


# --------------------------------------------------------------------------- #
# the regression: assignee survives the round trip
# --------------------------------------------------------------------------- #
def test_restored_needs_curation_keeps_the_assignee(series):
    series.setCuration(["square"], "Needs curation", "alice")
    assert series.obj_attrs["square"]["curation"][:2] == (False, "alice")

    _lose_curation(series, "square")
    series.updateCurationFromHistory()

    flagged, user, date = series.obj_attrs["square"]["curation"]
    assert flagged is False
    assert user == "alice", "the restore dropped the assignee"
    assert date


def test_assignee_survives_log_string_serialization(series):
    """The full history is re-read from ``existing_log.csv`` as strings, so the
    event must round-trip through Log's own str form -- including an assignee
    with a comma in it, which the parser folds back into the event field."""
    series.setCuration(["star"], "Needs curation", "Frank, Ted")

    log = series.log_set.all_logs[-1]
    reparsed = Log.fromStr(str(log))
    assert reparsed.event == "Mark as needs curation (assigned to Frank, Ted)"

    _lose_curation(series, "star")
    series.updateCurationFromHistory()
    assert series.obj_attrs["star"]["curation"][1] == "Frank, Ted"


# --------------------------------------------------------------------------- #
# the event text: only assigned rows carry the suffix
# --------------------------------------------------------------------------- #
def test_unassigned_needs_curation_logs_the_bare_event(series):
    series.setCuration(["triangle"], "Needs curation")

    assert series.log_set.all_logs[-1].event == "Mark as needs curation"

    _lose_curation(series, "triangle")
    series.updateCurationFromHistory()
    assert series.obj_attrs["triangle"]["curation"][1] == ""


def test_assigned_event_still_matches_only_the_needs_curation_branch(series):
    """The restore walk dispatches on substrings; the suffixed event must keep
    matching "Mark as needs curation" and must not match "Mark as curated"."""
    series.setCuration(["circle2"], "Needs curation", "bob")
    event = series.log_set.all_logs[-1].event

    assert "Mark as needs curation" in event
    assert "Mark as curated" not in event


# --------------------------------------------------------------------------- #
# unchanged neighbours
# --------------------------------------------------------------------------- #
def test_old_format_logs_still_restore_with_no_assignee(series):
    """A pre-fix log carries the bare event; it restores exactly as before."""
    series.log_set.addExistingLog(
        Log("26-01-01", "1200", "carol", "square", None, "Mark as needs curation")
    )

    series.updateCurationFromHistory()

    assert series.obj_attrs["square"]["curation"] == (False, "", "26-01-01")


def test_curated_restore_is_untouched(series):
    series.setCuration(["star"], "Curated")
    _lose_curation(series, "star")

    series.updateCurationFromHistory()

    flagged, user, _date = series.obj_attrs["star"]["curation"]
    assert flagged is True
    assert user == series.user


def test_remove_curation_still_removes_the_assigned_log(series):
    """LogSet.removeCuration matches on "curation" in the event; the suffixed
    event must still be swept when the status is cleared."""
    series.setCuration(["triangle"], "Needs curation", "dave")
    assert any("assigned to dave" in log.event for log in series.log_set.all_logs)

    series.setCuration(["triangle"], "")

    assert not any("assigned to dave" in log.event for log in series.log_set.all_logs)
    assert series.getAttr("triangle", "curation") is None
