"""Turning the launch-time update check on has to actually reach people, once.

``update_check_on_startup`` shipped ``False``, and `Series.getOption` writes a
default into the store the first time it is read -- the miss branch is
``option = defaults[option_name]`` followed by ``self.setOption(...)``. So every
machine that has ever opened the app carries a stored ``False`` that nobody
chose. Changing the shipped default cannot move any of them, because a stored
value always beats a default. That is the first section here, driven through a
real `Series`: the flip on its own is invisible to everyone who already has the
app.

The correction is a one-time migration, and the reason it is allowed to
overwrite a stored value is narrow and worth stating: **nobody chose that
value**. It was written by a read. Everything below is about keeping the
migration inside that justification.

  1. **It runs once per machine and records that it has.** The record is a
     marker key beside the option, in the same global scope, so it lives
     exactly as long as the option does.
  2. **A user who turns the check off after the migration keeps it off,
     forever.** This is the test the design stands or falls on. After the
     marker exists, a stored ``False`` is a decision and is never read as
     inherited again.
  3. **A fresh install is marked done without writing anything.** A machine
     with nothing stored has never read the option, so it gets the new default
     for free; writing there would add a settings entry nobody needs and would
     make a fresh install indistinguishable from an inherited ``False`` if the
     marker were ever lost. Marking it is what makes a later "off" stick on a
     new machine too.
  4. **A machine already on is a no-op, and still gets the marker.**

Two properties are load-bearing beyond the four states. The option is written
*before* the marker, so a failed write is retried rather than recorded as done.
And nothing raises: this runs on the startup path, where a settings correction
that could stop the app opening is far worse than a stale setting -- the same
contract the launch-time check itself keeps.

Nothing here writes the real application settings. The pure cases run against
`DictSettingsStore`, the wiring cases against the session's redirected
``QSettings``, and the last test asserts both the resolved path and the session
tripwire directly.
"""

import inspect
import os
import shutil

import pytest

from PySide6.QtCore import QSettings

import qsettings_isolation

from PyReconstruct.modules.backend import settings_migrations as M
from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    set_default_settings_store,
)
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.main import main_window as MW

ORG = "KHLab"
APP = "PyReconstruct"
OPTION = M.UPDATE_CHECK_KEY
MARKER = M.UPDATE_CHECK_DEFAULT_APPLIED_KEY

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


# --------------------------------------------------------------------------- #
# stores
# --------------------------------------------------------------------------- #

class _Store(DictSettingsStore):
    """A `DictSettingsStore` that logs every call.

    The counting claims here -- "the second launch writes nothing", "an
    already-on machine writes no option" -- are about calls that did *not*
    happen, and a value assertion cannot tell "wrote True over True" from
    "left it alone". So the calls are recorded and asserted on directly.

    Keyword arguments seed the global (``code=None``) scope, which is where
    this option lives.
    """

    def __init__(self, **seed):
        super().__init__()
        self.calls = []
        for key, value in seed.items():
            self._scope(None)[key] = value

    def contains(self, code, key):
        self.calls.append(("contains", code, key))
        return super().contains(code, key)

    def value(self, code, key, value_type):
        self.calls.append(("value", code, key))
        return super().value(code, key, value_type)

    def set_value(self, code, key, value):
        self.calls.append(("set_value", code, key, value))
        return super().set_value(code, key, value)

    @property
    def writes(self):
        return [call for call in self.calls if call[0] == "set_value"]

    def written(self, key):
        return [call for call in self.writes if call[2] == key]

    def get(self, key):
        return self._scope(None).get(key)

    def has(self, key):
        return key in self._scope(None)


class _UnwritableStore(_Store):
    """A store whose writes fail, like a read-only preferences directory.

    ``fail`` names the keys that cannot be written; the default is all of them.
    """

    def __init__(self, fail=None, **seed):
        super().__init__(**seed)
        self.fail = fail

    def set_value(self, code, key, value):
        if self.fail is None or key in self.fail:
            raise OSError(f"cannot write {key}")
        return super().set_value(code, key, value)


class _UnreadableStore(_Store):
    """A store that cannot even be read -- no Qt behind it, a corrupt file."""

    def contains(self, code, key):
        raise RuntimeError("settings are unreadable")


def _launch(store):
    """One application launch's worth of migration, for readability below."""
    return M.apply_update_check_on_startup_default(store)


def _real_series(tmp_path, store):
    """A real `Series` reading and writing options through ``store``."""
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(store)
    return series


# --------------------------------------------------------------------------- #
# 0. the premise: why a default change is not enough
# --------------------------------------------------------------------------- #

def test_reading_the_option_is_what_stores_it(tmp_path):
    """`getOption` persists the default on a miss, so a read creates the value.

    This is the whole reason a migration is needed rather than a default
    change. Asserted against a real `Series` because it is `getOption`'s own
    behavior that is the claim, not a paraphrase of it.
    """
    store = _Store()
    series = _real_series(tmp_path, store)

    assert not store.has(OPTION)
    series.getOption(OPTION)
    assert store.has(OPTION)


def test_the_flip_alone_reaches_nobody_who_already_has_the_app(tmp_path, monkeypatch):
    """A machine that read the option under the old default keeps the old value.

    Simulated exactly as it happened: read the option while the shipped default
    is ``False`` (which stores ``False``), then move the default to ``True`` as
    the release does. The stored value wins, so the new default is invisible --
    on every install that has ever launched.
    """
    store = _Store()
    series = _real_series(tmp_path, store)

    monkeypatch.setitem(Series.qsettings_defaults, OPTION, False)
    assert series.getOption(OPTION) is False  # and stores it

    monkeypatch.setitem(Series.qsettings_defaults, OPTION, True)
    assert series.getOption(OPTION) is False  # the flip changed nothing


def test_the_option_is_global_and_not_per_series():
    """The setting is machine-wide, so the marker has to be too.

    ``qsettings_defaults`` is the global scope (``code=None`` in the settings
    store); ``qsettings_series_defaults`` is the per-series one. A marker in the
    wrong one would re-run the migration for every series a user opens.
    """
    assert OPTION in Series.qsettings_defaults
    assert OPTION not in Series.qsettings_series_defaults
    assert default_settings[OPTION] is True


def test_the_marker_is_not_an_option():
    """The marker is bookkeeping, so it stays out of the options tables.

    An entry in ``default_settings`` would be persisted by the first read of
    it, would appear in the options dialog's defaults machinery, and would
    invite a "restore defaults" to erase the record and re-run the migration
    over somebody's deliberate "off".
    """
    assert MARKER not in default_settings
    assert MARKER not in Series.qsettings_defaults
    assert MARKER not in Series.qsettings_series_defaults


# --------------------------------------------------------------------------- #
# 1. the four states
# --------------------------------------------------------------------------- #

def test_an_inherited_false_is_flipped_to_true():
    """The case the migration exists for."""
    store = _Store(**{OPTION: False})

    assert _launch(store) is True
    assert store.get(OPTION) is True


def test_the_flip_is_recorded():
    """A flip that left no record would run again over a later "off"."""
    store = _Store(**{OPTION: False})

    _launch(store)

    assert store.get(MARKER) is True


def test_a_second_launch_rewrites_nothing():
    """Idempotent: the marker is checked first, so the next launch is inert."""
    store = _Store(**{OPTION: False})
    _launch(store)
    writes_after_first = len(store.writes)

    assert _launch(store) is False
    assert len(store.writes) == writes_after_first


def test_calling_it_twice_in_one_session_writes_once():
    """Idempotence within a process, not only across launches."""
    store = _Store(**{OPTION: False})

    assert _launch(store) is True
    assert _launch(store) is False
    assert len(store.written(OPTION)) == 1


def test_a_user_who_turns_it_off_afterwards_stays_off():
    """THE TEST. A decision made after the migration is permanent.

    The migration's whole justification is that the value it overwrites was
    written by a read rather than chosen. The moment the user chooses, that
    justification is gone, and no later launch may touch the value again.
    Driven across three launches because a marker that is written but not
    consulted would still pass a two-launch version of this.
    """
    store = _Store(**{OPTION: False})
    _launch(store)                       # first launch after updating
    assert store.get(OPTION) is True

    store.set_value(None, OPTION, False)  # the user turns it off

    _launch(store)                       # next launch
    assert store.get(OPTION) is False
    _launch(store)                       # and the one after that
    assert store.get(OPTION) is False


def test_a_fresh_install_is_marked_done_without_writing_the_option():
    """Nothing stored means nothing to correct: record it and write nothing.

    A machine with no stored value has never read the option and therefore gets
    ``True`` from the shipped default already. The marker still goes down, so
    this machine can never be migrated later.
    """
    store = _Store()

    assert _launch(store) is False
    assert store.written(OPTION) == []
    assert not store.has(OPTION)
    assert store.get(MARKER) is True


def test_a_fresh_install_that_then_turns_it_off_stays_off():
    """The reason a fresh install is marked at all.

    Without the marker, a new machine that opted out would be "corrected" by
    the next launch, because an unmarked stored ``False`` is exactly what the
    migration looks for.
    """
    store = _Store()
    _launch(store)                        # fresh install, first launch

    store.set_value(None, OPTION, False)  # the user turns it off

    _launch(store)
    assert store.get(OPTION) is False


def test_a_machine_already_on_is_a_no_op_with_the_marker_set():
    """Someone who turned it on before the flip is left alone, and recorded.

    "Left alone" is asserted as *no write*, not as the value still being
    ``True``: rewriting ``True`` over ``True`` is invisible in the value and is
    still a settings write nobody asked for.
    """
    store = _Store(**{OPTION: True})

    assert _launch(store) is False
    assert store.written(OPTION) == []
    assert store.get(OPTION) is True
    assert store.get(MARKER) is True


# --------------------------------------------------------------------------- #
# 2. what counts as off, and what counts as done
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "stored", [False, "false", "False", "FALSE", "0", "no", "", "  false  ", 0, None]
)
def test_every_spelling_of_off_is_corrected(stored):
    """`QSettings` backends hand booleans back as bools or as strings.

    Which spelling arrives depends on the platform and the storage format, and
    an ini-backed store returns "false" where the macOS native one returns
    ``False``. A migration that only recognized one of them would silently skip
    whole platforms. A stored ``None`` is corrected too: it does not read as on,
    and the option's default is on.
    """
    store = _Store(**{OPTION: stored})

    assert _launch(store) is True
    assert store.get(OPTION) is True


@pytest.mark.parametrize("stored", [True, "true", "True", "1", "yes", 1])
def test_every_spelling_of_on_is_left_alone(stored):
    """The mirror of the above: nothing that reads as on is written."""
    store = _Store(**{OPTION: stored})

    assert _launch(store) is False
    assert store.written(OPTION) == []
    assert store.get(OPTION) == stored
    assert store.get(MARKER) is True


@pytest.mark.parametrize("marker", [True, False, "false", 0, None, ""])
def test_the_marker_being_present_is_the_record_whatever_its_value(marker):
    """Presence is what "already ran" means, not truthiness.

    Reading the marker's *value* would let a stored ``False`` -- from a hand
    edit, or from a backend that writes booleans as strings and reads them back
    as something else -- re-run the migration over a deliberate "off". Presence
    cannot be misread.
    """
    store = _Store(**{OPTION: False, MARKER: marker})

    assert _launch(store) is False
    assert store.get(OPTION) is False


def test_the_migration_only_ever_addresses_the_global_scope():
    """Every read and write goes to ``code=None``.

    A per-series scope would re-run the migration for each series a user opens,
    and would put a machine-wide record in a place that a second series does
    not see.
    """
    store = _Store(**{OPTION: False})

    _launch(store)

    assert {call[1] for call in store.calls} == {None}


def test_only_the_two_keys_are_touched():
    """The migration is not a general settings rewrite.

    Names the exact keys, so a future edit that reaches for a third one has to
    say so here.
    """
    store = _Store(**{OPTION: False})

    _launch(store)

    assert {call[2] for call in store.calls} == {OPTION, MARKER}


# --------------------------------------------------------------------------- #
# 3. failing safely
# --------------------------------------------------------------------------- #

def test_the_option_is_written_before_the_marker():
    """Order matters: an unrecorded migration is retried, a false record is not.

    Asserted through the failure it protects against. With the marker write
    failing, the option correction has already landed and no record exists, so
    the next launch can finish the job rather than believing it already did.
    """
    store = _UnwritableStore(fail=(MARKER,), **{OPTION: False})

    assert _launch(store) is False
    assert store.get(OPTION) is True
    assert not store.has(MARKER)


def test_a_failed_marker_write_is_retried_and_then_settles():
    """The other half of the ordering claim: the retry finishes the job.

    The machine from the test above -- option corrected, no record -- launches
    again with a working store. The option already reads as on, so it is not
    written a second time, and the marker finally goes down.
    """
    failed = _UnwritableStore(fail=(MARKER,), **{OPTION: False})
    _launch(failed)

    store = _Store(**{key: failed.get(key) for key in (OPTION,)})
    assert _launch(store) is False
    assert store.written(OPTION) == []
    assert store.get(OPTION) is True
    assert store.get(MARKER) is True


def test_settings_that_cannot_be_written_do_not_raise():
    """A read-only preferences directory must not stop the app from opening.

    Same contract the launch-time check itself keeps: a background convenience
    swallows its own failures.
    """
    store = _UnwritableStore(**{OPTION: False})

    assert _launch(store) is False
    assert store.get(OPTION) is False
    assert not store.has(MARKER)


def test_settings_that_cannot_be_read_do_not_raise():
    """The failure can arrive on the read side too (no Qt, a corrupt file)."""
    store = _UnreadableStore(**{OPTION: False})

    assert _launch(store) is False


def test_an_unwritable_launch_is_repaired_by_a_later_writable_one():
    """A machine that failed once is not left behind permanently."""
    seed = {OPTION: False}
    _launch(_UnwritableStore(**seed))

    store = _Store(**seed)
    assert _launch(store) is True
    assert store.get(OPTION) is True
    assert store.get(MARKER) is True


# --------------------------------------------------------------------------- #
# 4. through the option plumbing the app actually uses
# --------------------------------------------------------------------------- #

def test_what_the_migration_writes_is_what_get_option_reads(tmp_path):
    """The migration and `Series.getOption` have to agree on scope and shape.

    The migration writes through the settings seam and `getOption` reads
    through it with ``type=bool``. Sharing one store between a real `Series`
    and the migration is what proves the two line up; a value written into the
    wrong scope, or in a shape `getOption` will not coerce, fails here.
    """
    store = _Store()
    series = _real_series(tmp_path, store)
    series.setOption(OPTION, False)  # the inherited value, however it got there

    _launch(store)

    assert series.getOption(OPTION) is True


def test_a_users_off_survives_get_option_across_launches(tmp_path):
    """The critical case, end to end through the real option reader."""
    store = _Store()
    series = _real_series(tmp_path, store)
    series.setOption(OPTION, False)
    _launch(store)
    assert series.getOption(OPTION) is True

    series.setOption(OPTION, False)  # the user turns it off in Series > Options

    _launch(store)
    assert series.getOption(OPTION) is False


# --------------------------------------------------------------------------- #
# 5. the startup wiring
# --------------------------------------------------------------------------- #

@pytest.fixture
def default_store():
    """Swap the process-wide settings store, and put the real one back.

    `apply_update_check_on_startup_default` resolves its store lazily, so this
    is what lets the startup method be driven without a `QSettings` in sight.
    """
    store = _Store()
    set_default_settings_store(store)
    yield store
    set_default_settings_store(None)


def test_the_startup_method_applies_the_migration(default_store):
    """`MainWindow.applyUpdateCheckDefaultStartup` does what it says.

    Called unbound against a bare object: the method touches nothing on the
    window, and building a real one to prove a two-line call would be an
    expensive way to test the import.
    """
    default_store.set_value(None, OPTION, False)

    MW.MainWindow.applyUpdateCheckDefaultStartup(object())

    assert default_store.get(OPTION) is True
    assert default_store.get(MARKER) is True


def test_the_startup_method_does_not_raise_when_settings_are_unwritable():
    """Startup survives a settings failure, which is the point of swallowing."""
    set_default_settings_store(_UnwritableStore(**{OPTION: False}))
    try:
        MW.MainWindow.applyUpdateCheckDefaultStartup(object())
    finally:
        set_default_settings_store(None)


def test_the_migration_runs_before_the_check_is_scheduled():
    """Ordering inside ``__init__``, which no unit test can observe.

    The correction has to land before anything reads the option in the running
    app, and the only reader on the startup path is the timer that dispatches
    ``checkForUpdatesStartup``. Reading the source is the honest way to assert
    an ordering between a synchronous call and a timer that fires later.
    """
    src = inspect.getsource(MW.MainWindow.__init__)

    assert "applyUpdateCheckDefaultStartup" in src
    assert src.index("applyUpdateCheckDefaultStartup") < src.index(
        "checkForUpdatesStartup"
    )


def test_it_is_wired_to_launching_the_app_not_to_opening_a_series():
    """Once per machine, not once per series.

    ``openSeries`` runs every time a series is opened, including the welcome
    series and every File > Open after it. A machine-wide correction wired
    there would be re-evaluated all day; the marker would make it harmless, but
    the placement would still be wrong.
    """
    assert "applyUpdateCheckDefaultStartup" not in inspect.getsource(
        MW.MainWindow.openSeries
    )


@pytest.fixture
def inherited_off():
    """A machine carrying the stored ``False`` that a read left behind.

    Seeded into the session's redirected ``QSettings``, and cleared afterwards,
    so a real window build starts from the state this migration is about
    whatever an earlier test in the session left behind.
    """
    settings = QSettings(ORG, APP)
    settings.setValue(OPTION, False)
    settings.remove(MARKER)
    settings.sync()
    yield settings
    restore = QSettings(ORG, APP)
    restore.remove(OPTION)
    restore.remove(MARKER)
    restore.sync()


@pytest.mark.gui
def test_a_real_launch_corrects_an_inherited_false(inherited_off, main_window):
    """The whole thing, through a real ``MainWindow`` construction.

    Everything above drives the migration or the method directly. This is the
    one that fails if the call is deleted from ``__init__``: a genuine launch,
    on a machine whose stored value is the inherited ``False``, ends with the
    check on and the correction recorded -- and the open series agrees, since
    `getOption` is what the check itself reads.
    """
    settings = QSettings(ORG, APP)

    assert settings.value(OPTION, type=bool) is True
    assert settings.contains(MARKER)
    assert main_window.series.getOption(OPTION) is True


# --------------------------------------------------------------------------- #
# 6. no settings pollution
# --------------------------------------------------------------------------- #

def test_it_writes_only_inside_the_isolation_root():
    """The migration's real store is `QSettings`-backed, so it has to be redirected.

    Two claims, because either alone is weak: the domain the migration
    addresses resolves inside the session's throwaway root, and the session
    tripwire -- which records any mutating call that reaches the real
    ``QSettings`` class -- stays empty across a launch that definitely writes.
    """
    if not qsettings_isolation.installed:  # pragma: no cover - Qt is installed here
        pytest.skip("Qt not importable, nothing to isolate")

    set_default_settings_store(None)  # the real QSettings-backed store
    settings = QSettings(ORG, APP)
    settings.setValue(OPTION, False)
    settings.remove(MARKER)
    settings.sync()
    before = len(qsettings_isolation.recorded_bypasses())
    try:
        assert M.apply_update_check_on_startup_default() is True

        path = os.path.abspath(QSettings(ORG, APP).fileName())
        assert path.startswith(os.path.abspath(qsettings_isolation.isolation_root))
        assert QSettings(ORG, APP).value(OPTION, type=bool) is True
        assert QSettings(ORG, APP).contains(MARKER)
        assert len(qsettings_isolation.recorded_bypasses()) == before
    finally:
        cleanup = QSettings(ORG, APP)
        cleanup.remove(OPTION)
        cleanup.remove(MARKER)
        cleanup.sync()
