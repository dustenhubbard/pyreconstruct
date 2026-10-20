"""Kill a real process using the local store, reopen, and check what survived.

``tests/store_kill_child.py`` opens a copy of a small series with the local
store on in "store" mode, so its first open keeps the series in a new store.
It makes the edits of tests/save_kill_child.py, saves them to the store, and
closes, which writes the .jser from the store. It stops at one named point in
the import, the Save or the close, and this test SIGKILLs it there.

Then the series is reopened every way the window offers after a crash, each
from the same copy of what the kill left (the series folder and the store
folder, put back in place, since a store belongs to its .jser's path):

* declining the unsaved work: the working folder is deleted, as the window
  deletes it, and the .jser opens. A store that holds a Save the .jser lacks
  must be offered, and only then (taken: no answer means yes), and no store
  may be set aside. The .jser the close of that open writes must be exactly
  the series before the edits or exactly the series after them.
* declining the store's Save too, where one is offered: the .jser opens as it
  is, the store is set aside whole, and writing it out
  (``PyReconstruct --export-local-copy``) gives exactly the series after the
  edits.
* opening the unsaved work: the working folder opens, every section loads,
  it saves as the window does, and the .jser its close writes must be exactly
  the series after the edits (or, before any edit, the series as saved).

After every route the next open must be a quiet one: no question, nothing set
aside. "Exactly" is the whole .jser document, as parsed JSON, with only the
date and time of each history line cut (tests/test_save_kill_reopen.py).

The states compared against come from finished runs: the fixture, the
fixture as today's Save writes it with no edit, and the finished child. The
finished child's .jser is checked against today's Save of the same edits
(tests/save_kill_child.py with the store off): writing through the store
changes nothing.
"""

import json
import os
import shutil
import sys

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, hybrid_store, store_open, store_recovery, store_save

import test_save_kill_reopen as base
from test_save_kill_reopen import FIXTURE, NAME, document

pytestmark = pytest.mark.slow

ROOT = base.ROOT
CHILD = os.path.join(ROOT, "tests", "store_kill_child.py")

# Each point: the state the declined route ends in, the state the accepted
# route ends in, and whether the store then holds a Save the .jser lacks.
#   old        the fixture
#   old-saved  the fixture as today's Save writes it, no edit
#   new        the finished child
#   gone-or-new  no series file left to offer, or "new"
POINTS = {
    "import-between-sections": ("old", "old-saved", False),
    "import-before-numbers": ("old", "old-saved", False),
    "store-save-between-sections": ("old", "new", False),
    "store-save-before-commit": ("old", "new", False),
    "store-save-after-commit": ("new", "new", True),
    "close-injected-jser-half-write": ("new", "new", True),
    "close-jser-before-rename": ("new", "new", True),
    "close-jser-after-rename": ("new", "new", False),
    "close-remove": ("new", "gone-or-new", False),
}


def child_env(stores):
    return {
        store_open.ENV_SWITCH: "1",
        store_save.ENV_MODE: store_save.MODE_STORE,
        hybrid_store.ENV_DIR: str(stores),
    }


def run_child(jser_fp, point, stores, monkeypatch):
    """Run the store child to `point` and SIGKILL it there, or to the end."""
    with monkeypatch.context() as m:
        for key, value in child_env(stores).items():
            m.setenv(key, value)
        base.run_child(str(jser_fp), point, child=CHILD)


class Asker:
    """A notifier that answers every question with `answer` and keeps what it was told."""

    def __init__(self, answer=None):
        self.answer = answer
        self.asked = []
        self.told = []

    def confirm(self, message, title="Confirm"):
        self.asked.append(message)
        return self.answer

    def notify(self, message):
        self.told.append(message)
        return True


def open_series(jser_fp, asker):
    series = Series.openJser(str(jser_fp), progress=NullProgressReporter, notifier=asker)
    assert series is not None
    series.setProgressReporter(NullProgressReporter)
    return series


def set_aside(stores):
    return sorted(str(p) for p in stores.glob(f"*{store_recovery.SET_ASIDE}*.pyrstore")) if stores.is_dir() else []


class Place:
    """The series folder and store folder a kill left, and a copy to put back."""

    def __init__(self, tmp_path):
        self.folder = tmp_path / "series"
        self.stores = tmp_path / "stores"
        self.jser = self.folder / f"{NAME}.jser"
        self.copy = tmp_path / "as-killed"

    def keep(self):
        shutil.copytree(self.folder, self.copy / "series")
        if self.stores.is_dir():
            shutil.copytree(self.stores, self.copy / "stores")

    def restore(self):
        shutil.rmtree(self.folder)
        shutil.rmtree(self.stores, ignore_errors=True)
        shutil.copytree(self.copy / "series", self.folder)
        if (self.copy / "stores").is_dir():
            shutil.copytree(self.copy / "stores", self.stores)


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    stores = tmp_path / "stores"
    for key, value in child_env(stores).items():
        monkeypatch.setenv(key, value)
    return stores


@pytest.fixture(scope="module")
def states(tmp_path_factory):
    """Every state a kill may leave, as whole documents (see POINTS)."""
    with pytest.MonkeyPatch.context() as m:
        tmp = tmp_path_factory.mktemp("store-kill-states")
        m.delenv(store_open.ENV_SWITCH, raising=False)
        (tmp / "old").mkdir()
        shutil.copyfile(FIXTURE, tmp / "old" / f"{NAME}.jser")
        old = document(str(tmp / "old" / f"{NAME}.jser"))
        (tmp / "old-saved").mkdir()
        resaved = tmp / "old-saved" / f"{NAME}.jser"
        shutil.copyfile(FIXTURE, resaved)
        series = open_series(resaved, Asker())
        try:
            series.saveJser()
        finally:
            series.close()
        old_saved = document(str(resaved))
        # today's Save of the child's edits, with the store off
        today = base.finished_save(tmp, "none")

        (tmp / "new").mkdir()
        jser = tmp / "new" / f"{NAME}.jser"
        shutil.copyfile(FIXTURE, jser)
        run_child(jser, "none", tmp / "new-stores", m)
        new = document(str(jser))

    assert new == today, "the .jser written through the store is not today's Save"
    assert len({json.dumps(d, sort_keys=True) for d in (old, old_saved, new)}) == 3
    return {"old": old, "old-saved": old_saved, "new": new}


def check_quiet_reopen(place):
    """The next open asks nothing and sets nothing aside."""
    before = set_aside(place.stores)
    asker = Asker()
    series = open_series(place.jser, asker)
    try:
        assert store_save.heldStore(series) is not None, "the next open has no store"
    finally:
        series.close()
    assert asker.asked == [], "the next open asked again"
    assert set_aside(place.stores) == before
    assert asker.told == [] or before, asker.told


def check_declined(place, expect, offered, states):
    """Decline the working folder: the store's Save is offered if it has one."""
    place.restore()
    base.clear_hidden(str(place.folder))
    asker = Asker()
    series = open_series(place.jser, asker)
    try:
        for snum in series.sections:
            series.loadSection(snum)
    finally:
        series.close()
    assert len(asker.asked) == int(offered), asker.asked
    assert asker.told == [], asker.told
    assert set_aside(place.stores) == []
    assert document(str(place.jser)) == states[expect], f"the .jser is not exactly the {expect} series"
    check_quiet_reopen(place)


def check_declined_twice(place, untouched, states, tmp_path):
    """Decline the folder and the store's Save: kept aside, and written out whole."""
    place.restore()
    base.clear_hidden(str(place.folder))
    asker = Asker(False)
    open_series(place.jser, asker).close()
    assert len(asker.asked) == 1
    kept = set_aside(place.stores)
    assert len(kept) == 1 and len(asker.told) == 1 and kept[0] in asker.told[0]
    assert untouched, "the .jser was written before the close finished"
    out = tmp_path / "written-out.jser"
    assert store_recovery.exportMain([kept[0], str(out)], out=sys.stderr) == 0
    assert document(str(out)) == states["new"], "the set-aside store is not exactly the new series"


def check_accepted(place, expect, states):
    """Open the working folder: its Save and close write exactly the state it held."""
    place.restore()
    if expect == "gone-or-new" and not base.has_working_series(str(place.folder)):
        return
    assert base.has_working_series(str(place.folder)), "the working folder is not offered"
    want = states["new" if expect == "gone-or-new" else expect]
    asker = Asker()
    series = open_series(place.jser, asker)
    try:
        for snum in series.sections:
            series.loadSection(snum)
        if not series.saveToStore():
            series.saveJser()
    finally:
        series.close()
    assert asker.asked == [] and asker.told == [], (asker.asked, asker.told)
    assert set_aside(place.stores) == []
    assert document(str(place.jser)) == want, f"a save from the working folder is not exactly the {expect} state"
    base.clear_hidden(str(place.folder))  # the resumed folder is left open (leave_open)
    check_quiet_reopen(place)


@pytest.mark.skipif(os.name != "posix", reason="SIGKILL")
@pytest.mark.parametrize("point", POINTS)
def test_kill_with_the_store_then_reopen(tmp_path, states, store_env, point, monkeypatch):
    declined, accepted, offered = POINTS[point]
    place = Place(tmp_path)
    place.folder.mkdir()
    shutil.copyfile(FIXTURE, place.jser)
    run_child(place.jser, point, place.stores, monkeypatch)
    with open(FIXTURE, "rb") as a, open(place.jser, "rb") as b:
        untouched = a.read() == b.read()
    place.keep()
    check_declined(place, declined, offered, states)
    if offered:
        check_declined_twice(place, untouched, states, tmp_path)
    check_accepted(place, accepted, states)
