"""The one-time settings seed for flavored builds.

The Dev flavor keeps its own QSettings domain so the side-by-side apps never
share state; the seed copies the stable domain into a flavored domain exactly
once, on first launch, so a tester's options survive the move (Patrick's
report, 2026-08-25: auto-merge and rolling smoothing came up as defaults).

Every test runs against ini-backed QSettings in a temp directory: the real
domains on the machine running the suite must never be read or written.
"""

import pytest

from PyReconstruct.modules.constants.settings_domain import (
    SEED_MARKER,
    seed_flavor_settings_once,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def ini_settings(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    def make(name):
        # tmp_path.name in the basename: the suite's QSettings isolation
        # redirects explicit-file settings into one shared folder BY BASENAME,
        # so a plain "dev.ini" would be the same store in every test here
        return QSettings(
            str(tmp_path / f"{name}-{tmp_path.name}.ini"), QSettings.IniFormat
        )

    return make


def test_first_run_copies_the_stable_settings(ini_settings):
    stable = ini_settings("stable")
    stable.setValue("auto_merge", True)
    stable.setValue("roll_average", True)
    stable.sync()
    dev = ini_settings("dev")

    assert seed_flavor_settings_once(flavored=dev, stable=stable) is True
    assert dev.value("auto_merge") == stable.value("auto_merge")
    assert dev.value("roll_average") == stable.value("roll_average")
    assert dev.value(SEED_MARKER, type=bool) is True


def test_seed_runs_exactly_once(ini_settings):
    stable = ini_settings("stable")
    stable.setValue("auto_merge", True)
    dev = ini_settings("dev")
    assert seed_flavor_settings_once(flavored=dev, stable=stable) is True

    # the user clears their choice; a later launch must not bring it back
    dev.remove("auto_merge")
    assert seed_flavor_settings_once(flavored=dev, stable=stable) is False
    assert dev.value("auto_merge") is None


def test_empty_stable_still_marks_and_stops(ini_settings):
    """A fresh machine: nothing to copy, but the marker is set so later
    launches skip the scan (and never re-seed after the user makes choices)."""
    dev = ini_settings("dev")
    assert seed_flavor_settings_once(flavored=dev, stable=ini_settings("stable")) is True
    assert dev.value(SEED_MARKER, type=bool) is True


def test_meta_keys_are_never_copied(ini_settings):
    stable = ini_settings("stable")
    stable.setValue("meta/settings_seeded", True)
    stable.setValue("meta/anything", "x")
    stable.setValue("auto_merge", True)
    stable.sync()
    dev = ini_settings("dev")
    seed_flavor_settings_once(flavored=dev, stable=stable)
    assert dev.value("meta/anything") is None
    assert dev.value("auto_merge") is not None


def test_stable_app_never_seeds(monkeypatch):
    """Resolved from the environment: the stable app is a no-op and never
    even opens a stable-domain handle to copy from."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    assert seed_flavor_settings_once() is False


def test_per_series_scoped_keys_ride_along(ini_settings):
    """Options scoped by series code (QSettings groups) come across whole."""
    stable = ini_settings("stable")
    stable.setValue("SER123/left_handed", True)
    stable.sync()
    dev = ini_settings("dev")
    seed_flavor_settings_once(flavored=dev, stable=stable)
    assert dev.value("SER123/left_handed") == stable.value("SER123/left_handed")
