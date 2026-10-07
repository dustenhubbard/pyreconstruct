"""The What's new pop-up comes back on for everyone, once; a fresh install stays quiet.

The popup shipped off by default from 2026-08-21 until this version, and all
that while the Help toggle and the dialog's "Don't show again" button wrote
``suppress_whatsnew``. Turning the default back on (his call, 2026-10-07) came
with two rules:

1. a user's choice to turn the popup off is respected from this version on. A
   value stored before it does not bind: the notes show once after this
   update, and the choice the user makes after that is kept across later
   updates;
2. a fresh install never shows the popup. Its first popup is the update after
   it.

``maybe_show_whats_new`` cannot tell an old "off" from a new one, nor a fresh
install from an upgrade on a store that never showed the popup (the once-per-
version record was never advanced while the popup was off). So
``reset_whats_new_popup_once`` runs first, from ``run.py`` before the window
exists, and records that it ran in ``whatsnew_popup_reset_applied``. These
tests pin each state of that reset, that it runs once, and that the gate
behind it then does what the two rules say.

Nothing here writes the real application settings: the pure cases run against
a dict, the wiring cases against the session's redirected ``QSettings``.
"""

import pytest

from PyReconstruct.modules.gui.main import first_launch as F
from PyReconstruct.modules.gui.dialog import whats_new as W

MARKER = F.WHATSNEW_RESET_MARKER
SEEN = F.WHATSNEW_KEY
OFF = F.WHATSNEW_SUPPRESS_KEY


class FakeSettings:
    """A QSettings-shaped dict with the four calls the reset makes."""

    def __init__(self, data=None):
        self._d = dict(data or {})
        self.writes = []

    def contains(self, key):
        return key in self._d

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, val):
        self._d[key] = val
        self.writes.append((key, val))

    def remove(self, key):
        self._d.pop(key, None)
        self.writes.append((key, None))


def _shown(settings, current, calls):
    """Run the startup gate for ``current`` and report whether it showed."""
    return W.maybe_show_whats_new(
        None, settings=settings, current=current,
        show=lambda parent, version, last_seen=None: calls.append((version, last_seen)),
    )


# ---- the upgrade: an old "off" does not bind ---------------------------------

def test_an_upgrade_with_a_stored_off_shows_the_notes_once():
    """Rule 1, the case that changes anything: the stored suppression is
    removed, the pending version shows once, and the marker records it."""
    settings = FakeSettings({SEEN: "1.23.0", OFF: True})
    calls = []

    assert F.reset_whats_new_popup_once(settings, "1.24.0") is True
    assert not settings.contains(OFF)
    assert settings.value(MARKER) is True

    assert _shown(settings, "1.24.0", calls) is True
    assert calls == [("1.24.0", "1.23.0")]
    assert _shown(settings, "1.24.0", calls) is False       # once only


@pytest.mark.parametrize("stored", [True, "true", "True", False, "false"])
def test_every_spelling_of_the_old_preference_is_dropped(stored):
    """Both polarities go: a stored False is the default now, and leaving it
    would make a user's later False indistinguishable from an inherited one."""
    settings = FakeSettings({SEEN: "1.23.0", OFF: stored})
    F.reset_whats_new_popup_once(settings, "1.24.0")
    assert not settings.contains(OFF)


def test_an_upgrade_that_never_showed_the_popup_still_counts_as_an_upgrade():
    """A store from the default-off releases has no last-seen version, because
    the suppressed path never advanced it. It is not a fresh install: the
    shared store carries ``username`` from every earlier launch, so the notes
    show on this launch (under the welcome framing, there being no "since")."""
    settings = FakeSettings({OFF: True})
    shared = FakeSettings({"username": "alice"})
    calls = []

    assert F.reset_whats_new_popup_once(settings, "1.24.0", shared=shared) is True
    assert not settings.contains(OFF)
    assert not settings.contains(SEEN)                     # nothing stamped
    assert _shown(settings, "1.24.0", calls) is True
    assert calls == [("1.24.0", None)]


def test_the_update_check_marker_alone_is_prior_install_evidence():
    settings = FakeSettings()
    shared = FakeSettings({"update_check_on_startup_default_applied": True})
    F.reset_whats_new_popup_once(settings, "1.24.0", shared=shared)
    assert not settings.contains(SEEN)                     # an upgrade, not fresh


def test_a_choice_made_after_the_reset_is_kept_across_later_updates():
    """Rule 1, the half the design stands on: once the marker exists, a stored
    "off" is a decision. The next update's reset is a no-op and the popup
    stays away, pending version bump and all."""
    settings = FakeSettings({SEEN: "1.23.0", OFF: True})
    calls = []
    F.reset_whats_new_popup_once(settings, "1.24.0")
    assert _shown(settings, "1.24.0", calls) is True        # the one showing

    settings.setValue(OFF, True)                            # Don't show again
    writes_before = len(settings.writes)

    assert F.reset_whats_new_popup_once(settings, "1.25.0") is False
    assert settings.writes[writes_before:] == []            # touched nothing
    assert settings.value(OFF) is True
    assert _shown(settings, "1.25.0", calls) is False
    assert _shown(settings, "1.26.0", calls) is False
    assert len(calls) == 1


def test_a_choice_to_keep_it_on_is_also_kept():
    """The Help toggle writes False when the user turns the popup back on; a
    later reset must not read that as something to clean up either."""
    settings = FakeSettings({SEEN: "1.24.0", OFF: False, MARKER: True})
    assert F.reset_whats_new_popup_once(settings, "1.25.0") is False
    assert settings.value(OFF) is False
    assert settings.writes == []


# ---- the fresh install: never shows -------------------------------------------

def test_a_fresh_install_records_the_version_and_shows_nothing():
    """Rule 2: nothing stored anywhere, so the running version is recorded as
    seen and the gate declines. The update after it shows."""
    settings = FakeSettings()
    calls = []

    assert F.reset_whats_new_popup_once(settings, "1.24.0") is True
    assert settings.value(SEEN) == "1.24.0"
    assert not settings.contains(OFF)                      # the default is the "on"
    assert settings.value(MARKER) is True

    assert _shown(settings, "1.24.0", calls) is False
    assert calls == []
    assert _shown(settings, "1.24.1", calls) is True        # the next update
    assert calls == [("1.24.1", "1.24.0")]


def test_a_fresh_install_that_then_turns_it_off_stays_off():
    settings = FakeSettings()
    calls = []
    F.reset_whats_new_popup_once(settings, "1.24.0")
    settings.setValue(OFF, True)
    assert F.reset_whats_new_popup_once(settings, "1.24.1") is False
    assert _shown(settings, "1.24.1", calls) is False
    assert calls == []


def test_a_fresh_install_reads_the_evidence_from_the_shared_store():
    """Under the Dev flavor the popup keys and the evidence live in different
    stores; the reset asks the right one. A Dev install beside a stable one is
    not a fresh machine, and a bare one is."""
    beside_stable = FakeSettings()
    F.reset_whats_new_popup_once(
        beside_stable, "1.24.0", shared=FakeSettings({"username": "alice"})
    )
    assert not beside_stable.contains(SEEN)

    bare = FakeSettings()
    F.reset_whats_new_popup_once(bare, "1.24.0", shared=FakeSettings())
    assert bare.value(SEEN) == "1.24.0"


@pytest.mark.parametrize("current", [
    "1.24.0.dev20261007",      # a nightly
    "1.24.1.dev5+g0123abc",    # a source checkout of main
    None,                      # indeterminate
    "garbage",
])
def test_a_fresh_dev_build_records_nothing(current):
    """A dev build never shows the popup and records nothing, the same as its
    gate; the marker is still written so the reset does not run again."""
    settings = FakeSettings()
    assert F.reset_whats_new_popup_once(settings, current) is True
    assert not settings.contains(SEEN)
    assert settings.value(MARKER) is True


# ---- once, and only the keys it owns -------------------------------------------

def test_the_reset_runs_once_per_store():
    settings = FakeSettings({SEEN: "1.23.0", OFF: True})
    assert F.reset_whats_new_popup_once(settings, "1.24.0") is True
    assert F.reset_whats_new_popup_once(settings, "1.24.0") is False
    assert F.reset_whats_new_popup_once(settings, "1.25.0") is False
    assert settings.writes == [(OFF, None), (MARKER, True)]


@pytest.mark.parametrize("marker", [True, False, "false", 0, ""])
def test_the_marker_being_present_is_the_record_whatever_its_value(marker):
    """Presence, not truth: a hand-edited marker cannot cause a second pass
    over somebody's deliberate "off"."""
    settings = FakeSettings({SEEN: "1.23.0", OFF: True, MARKER: marker})
    assert F.reset_whats_new_popup_once(settings, "1.24.0") is False
    assert settings.value(OFF) is True


def test_only_the_whats_new_keys_are_touched():
    settings = FakeSettings({SEEN: "1.23.0", OFF: True, "username": "alice",
                             "last_folder": "/data", "theme": "qdark"})
    F.reset_whats_new_popup_once(settings, "1.24.0")
    touched = {key for key, _ in settings.writes}
    assert touched == {OFF, MARKER}


def test_the_marker_is_written_last():
    """A write that fails must leave the reset unrecorded, so it runs again
    next launch rather than being recorded as done."""
    settings = FakeSettings({SEEN: "1.23.0", OFF: True})
    F.reset_whats_new_popup_once(settings, "1.24.0")
    assert settings.writes[-1] == (MARKER, True)

    fresh = FakeSettings()
    F.reset_whats_new_popup_once(fresh, "1.24.0")
    assert fresh.writes == [(SEEN, "1.24.0"), (MARKER, True)]


def test_the_marker_is_a_per_app_key_in_step_with_the_literal():
    """The marker sits beside the two keys it governs, in this app's own store,
    so a nightly's reset never records itself where the stable app looks."""
    from PyReconstruct.modules.constants.settings_domain import (
        PER_APP_KEYS, domain_for,
    )
    assert MARKER in PER_APP_KEYS
    assert domain_for(SEEN, OFF, MARKER) == domain_for(OFF)


# ---- the wiring: the real (redirected) stores --------------------------------

def _clear(settings):
    for key in (SEEN, OFF, MARKER):
        settings.remove(key)
    settings.sync()


@pytest.fixture
def redirected_store(qapp):
    """The stable app's one store, cleared of the three keys before and after.

    The suite points every ``QSettings`` at a throwaway location, so this is
    never the developer's own preferences file. ``username`` is not cleared:
    the session's store carries one from every ``main_window`` build, and the
    tests below set or remove it themselves.
    """
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)
    _clear(settings)
    yield settings
    _clear(QSettings(W.ORG, W.APP))


def test_startup_resets_the_stable_store(redirected_store, monkeypatch):
    """Through ``reset_whats_new_popup_startup`` with no injection: the stable
    app resolves one domain for the popup keys and the evidence, and an
    upgrading store with a stored "off" comes out ready to show once."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    from PySide6.QtCore import QSettings

    redirected_store.setValue(SEEN, "1.23.0")
    redirected_store.setValue(OFF, True)
    redirected_store.setValue("username", "alice")
    redirected_store.sync()

    assert F.reset_whats_new_popup_startup(current="1.24.0") is True

    store = QSettings(W.ORG, W.APP)
    assert not store.contains(OFF)
    assert store.value(SEEN) == "1.23.0"
    assert store.contains(MARKER)
    # and the second launch is a no-op
    assert F.reset_whats_new_popup_startup(current="1.24.0") is False


def test_startup_keeps_a_fresh_stable_install_quiet(redirected_store, monkeypatch):
    """No last-seen version and no ``username``: the launch records the
    running version, and the real gate, asked the way ``MainWindow`` asks it,
    declines."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    from PySide6.QtCore import QSettings

    had_username = redirected_store.value("username")
    redirected_store.remove("username")
    redirected_store.remove("update_check_on_startup_default_applied")
    redirected_store.sync()
    try:
        assert F.reset_whats_new_popup_startup(current="1.24.0") is True
        store = QSettings(W.ORG, W.APP)
        assert store.value(SEEN) == "1.24.0"
        assert W.maybe_show_whats_new(
            None, settings=store, current="1.24.0",
            show=lambda *a, **k: pytest.fail("a fresh install showed the popup"),
        ) is False
    finally:
        if had_username is not None:
            QSettings(W.ORG, W.APP).setValue("username", had_username)


def test_startup_under_the_dev_flavor_resets_the_dev_store_only(qapp, monkeypatch):
    """The Dev app's popup state is its own: the reset lands in the Dev
    domain, reads the shared store for the evidence, and leaves the stable
    app's keys exactly as they were."""
    from PySide6.QtCore import QSettings

    DEV = ("KHLab", "PyReconstruct Dev")
    STABLE = ("KHLab", "PyReconstruct")
    monkeypatch.setenv("PYRECON_APP_NAME", DEV[1])
    dev, stable = QSettings(*DEV), QSettings(*STABLE)
    _clear(dev)
    stable_before = {key: stable.value(key) for key in (SEEN, OFF, MARKER)}
    stable.setValue("username", "alice")
    dev.setValue(OFF, True)
    dev.sync(); stable.sync()
    try:
        assert F.reset_whats_new_popup_startup(current="1.24.0.dev20261007") is True
        dev = QSettings(*DEV)
        assert not dev.contains(OFF)
        assert dev.contains(MARKER)
        assert not dev.contains(SEEN)
        stable = QSettings(*STABLE)
        for key, before in stable_before.items():
            assert stable.value(key) == before, key
    finally:
        _clear(QSettings(*DEV))


def test_startup_never_raises(monkeypatch):
    """On the launch path a settings correction that could stop PyReconstruct
    from opening is worse than a stale setting."""
    def boom(*a, **k):
        raise RuntimeError("no settings today")
    monkeypatch.setattr(F, "reset_whats_new_popup_once", boom)
    assert F.reset_whats_new_popup_startup(current="1.24.0") is False


def test_run_calls_the_reset_before_the_application_exists():
    """``run.py`` runs the reset beside the settings fold, before the
    ``QApplication`` and the window, which is the only point at which a fresh
    store is still empty of the keys the fresh-install test reads."""
    import inspect
    import PyReconstruct.run as run

    source = inspect.getsource(run.runPyReconstruct)
    fold = source.index("fold_flavor_settings_once()")
    reset = source.index("reset_whats_new_popup_startup()")
    app = source.index("QApplication(sys.argv)")
    assert fold < reset < app
