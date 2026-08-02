"""``log_set`` belongs to the working directory, never to the .jser.

The series log has two representations. In the hidden working directory the
.ser carries ``log_set``, a JSON array of one CSV row per event, written by
``Series.getDict``. In the .jser there is no ``log_set`` at all: ``saveJser``
flattens the rows into the top-level ``"log"`` text and drops the key, and
``openJser`` overwrites whatever it finds with ``[]`` on the way back in. None
of the three .jser files checked into this repository has the key.

An audit read the removal as inverted -- ``[]`` written when the log is empty,
the key deleted when it is populated -- and asked whether a populated log
survives a save. **It does.** The rows are carried out by ``str(self.log_set)``
a few lines further down, which reads the in-memory log set and is not affected
by what happens to ``filedata``. The removal is not the thing that preserves
them, so it cannot be the thing that loses them; a populated log round trips
into ``"log"`` and comes back through ``getFullHistory``. Nothing was ever lost.

What was wrong is smaller and real. The guard was::

    if filedata.get("log_set"): del(filedata["log_set"])

introduced in 2024 (``decc35f5``, inherited from upstream) to stop an
unconditional ``del`` raising ``KeyError`` on a series dict that had no log set
-- the CLI xml conversion produced one. A truthiness test standing in for an
existence test also skips a log set that is present but empty, so the key
survived into the file in exactly the case where it says nothing. The visible
consequence is that the .jser's key set tracked session activity rather than
series content: save with no logged event and the file gained ``"log_set": []``,
save after one logged event and it did not. Measured on ``shapes1.jser``, a save
/ reopen / save cycle after a single logged event was not byte-idempotent for
that reason alone, a 13-byte difference that is the key itself.

``filedata.pop("log_set", None)`` restores the original intent with the
``KeyError`` safety that ``decc35f5`` was after.

The other finding raised against this writer, ``openJser`` forcing
``align_locked = True`` on every section and only the hidden-dir fast path
honoring the stored value, is **accepted, not a bug**. It is pinned with its
reasoning in ``tests/test_bc_profiles_and_section_lock.py`` (finding 2), which
covers both halves of the asymmetry. Nothing here duplicates it.

No ``gui`` marker: these drive the datatypes directly and build no widgets.
"""

import json
import os
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "PyReconstruct", "assets", "checker", "files", "shapes1.jser",
)


def reopen_at(fp):
    """Open a .jser headlessly, with the Qt seams filled by the null adapters."""
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    return series


@pytest.fixture
def jser(tmp_path):
    """A private copy of the checked-in fixture, and its path."""
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    return fp


def read(fp):
    """The .jser as raw bytes and as a parsed document."""
    with open(fp, "rb") as f:
        raw = f.read()
    return raw, json.loads(raw)


def save_once(fp, log_event=None):
    """Open, optionally log an event, save, close."""
    series = reopen_at(fp)
    if log_event is not None:
        series.addLog(None, 1, log_event)
    series.saveJser()
    series.close()


def test_the_checked_in_fixtures_have_no_log_set():
    """The shape being asserted below is the shape real files already have.

    Without this the tests would only be pinning the writer against itself.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    checker = os.path.join(root, "PyReconstruct", "assets", "checker", "files")
    found = [n for n in sorted(os.listdir(checker)) if n.endswith(".jser")]
    assert found, "no .jser fixtures to check"
    for name in found:
        with open(os.path.join(checker, name), "rb") as f:
            doc = json.load(f)
        assert "log_set" not in doc.get("series", {}), (
            f"{name} carries log_set; the .jser format is not what these tests assume"
        )


# ===========================================================================
# the key is gone from the .jser, whatever the log set held
# ===========================================================================

def test_an_empty_log_set_is_not_written_to_the_jser(jser):
    """THE BUG. A save with no logged event used to leave ``"log_set": []``."""
    save_once(jser)

    _, doc = read(jser)
    assert "log_set" not in doc["series"], (
        "an empty log set was written into the .jser; the key belongs to the "
        "hidden dir's .ser only"
    )


def test_a_populated_log_set_is_not_written_to_the_jser_either(jser):
    """The other half, which already held: activity does not change the shape."""
    save_once(jser, log_event="Probe event")

    _, doc = read(jser)
    assert "log_set" not in doc["series"]


def test_the_key_set_does_not_depend_on_session_activity(jser, tmp_path):
    """Two series with the same content must have the same series keys.

    Stated as the invariant rather than as the absence of one key, because the
    invariant is the point: what a .jser contains is a property of the series,
    not of what the user happened to do before pressing save.
    """
    quiet = jser
    busy = str(tmp_path / "busy.jser")
    shutil.copyfile(FIXTURE, busy)

    save_once(quiet)
    save_once(busy, log_event="Probe event")

    _, quiet_doc = read(quiet)
    _, busy_doc = read(busy)
    assert list(quiet_doc["series"]) == list(busy_doc["series"])


# ===========================================================================
# what the removal must not cost: the log itself
# ===========================================================================

def test_a_populated_log_survives_the_round_trip(jser):
    """The data-loss question, answered directly.

    Save, load, save. The event has to be in the .jser text after the first
    save, readable through ``getFullHistory`` after the reopen, and still in
    the text after the second save -- the save that no longer has a log set in
    memory to flatten and must therefore be carrying it in ``existing_log.csv``.
    """
    save_once(jser, log_event="Probe event")

    _, first = read(jser)
    assert "Probe event" in first["log"], "the log set never reached the .jser text"

    series = reopen_at(jser)
    try:
        assert series.log_set.all_logs == [], (
            "openJser is expected to start the session's log set empty"
        )
        assert "Probe event" in str(series.getFullHistory()), (
            "the reopened series cannot see an event it wrote"
        )
        series.saveJser()
    finally:
        series.close()

    _, second = read(jser)
    assert "Probe event" in second["log"], "the event was lost on the second save"
    assert second["log"] == first["log"], "the log text drifted across a round trip"


def test_the_log_does_not_accumulate_across_repeated_saves(jser):
    """The row is carried, not re-appended: four saves, one copy of the event."""
    save_once(jser, log_event="Probe event")
    for _ in range(3):
        save_once(jser)

    _, doc = read(jser)
    assert doc["log"].count("Probe event") == 1


# ===========================================================================
# byte idempotence, both ways
# ===========================================================================

@pytest.mark.parametrize("log_event", [None, "Probe event"])
def test_save_reopen_save_is_byte_idempotent(jser, log_event):
    """Save, load, save, compare -- with a populated log set and without one.

    The leading save is a settling save, deliberately outside the comparison:
    it puts the acting user in ``editors``, which is real content and converges
    immediately. It has to log something, because ``addLog`` is what adds the
    user and a bare save is not enough.

    The compared pair then straddles the transition that matters -- a save that
    flattens a populated log set, then a save whose log set is empty because
    the reopen cleared it. Before the fix the populated case failed here by
    exactly the 13 bytes of the key: absent after the first, present as ``[]``
    after the second. The ``None`` case is the control and passed either way.
    """
    save_once(jser, log_event="Settling event")

    save_once(jser, log_event=log_event)
    first, first_doc = read(jser)

    save_once(jser)
    second, second_doc = read(jser)

    assert first_doc["log"] == second_doc["log"], "the log text moved on its own"
    assert first == second, "a save with nothing to change rewrote the file"
