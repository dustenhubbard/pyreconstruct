"""One shared settings store, a small per-app overlay, and nothing in between.

Since 2026-09-27 PyReconstruct and PyReconstruct Dev read and write the same
QSettings domain for every preference; only the keys in PER_APP_KEYS (and the
``meta/`` bookkeeping group) live in each app's own domain. These tests pin
the routing, pin that every key the app is known to store is classified the
way the design intends, and pin that the stable app is untouched: without the
Dev environment variable, every domain resolves to the stable app's own
``PyReconstruct/PyReconstruct`` store.

The classification test enumerates keys from the places that define them
(`default_settings`, `default_series_settings`, the raw-site literals, and the
main-window inventory in `conftest.py`) rather than by grepping, and a source
scan checks that no raw ``QSettings`` construction in the application bypasses
`domain_for`. Together those are what stop a new key from landing in the wrong
store without anybody deciding it should.
"""

import os
import re
from pathlib import Path

import pytest

from PyReconstruct.modules.constants import settings_domain as SD
from PyReconstruct.modules.constants.settings_domain import (
    FOLD_MARKER,
    LEGACY_COPY_MARKER,
    PER_APP_KEYS,
    SEED_MARKER,
    SHARED_APP,
    domain_for,
    is_per_app_key,
    per_app_domain,
    settings_app,
    shared_domain,
)

DEV = "PyReconstruct Dev"
STABLE_DOMAIN = ("PyReconstruct", "PyReconstruct")
DEV_DOMAIN = ("PyReconstruct", DEV)

# Section 4 of the design (hub specs/settings-sync-two-apps-2026-09-27.md):
# the keys that must differ between the two installed apps, and nothing else.
SPEC_PER_APP = {
    "suppress_whatsnew",
    "last_whatsnew_version",
    "last_update_check_epoch",
    "window/geometry",
    "meta/settings_seeded",
    "meta/folded_into_shared",
    "meta/copied_from_khlab",
}


def _known_keys():
    """Every key the application is known to read or write, by origin.

    Returns ``{key: origin}`` so a failure names where the key came from.
    """
    from PyReconstruct.modules.datatypes.default_settings import (
        default_settings, default_series_settings,
    )
    from PyReconstruct.modules.gui.main.first_launch import (
        WHATSNEW_KEY, WHATSNEW_SUPPRESS_KEY,
    )
    from PyReconstruct.modules.gui.palette.mouse_palette import (
        PALETTE_VIS_KEYS, PALETTE_POS_KEYS,
    )
    from PyReconstruct.modules.backend.settings_migrations import (
        UPDATE_CHECK_DEFAULT_APPLIED_KEY,
    )
    import conftest

    keys = {}
    for key in default_settings:
        keys[key] = "default_settings"
    for key in default_series_settings:
        keys[key] = "default_series_settings"
    for key in conftest._MAIN_WINDOW_SETTINGS_KEYS:
        keys.setdefault(key, "conftest._MAIN_WINDOW_SETTINGS_KEYS")
    raw = {
        WHATSNEW_KEY: "first_launch.WHATSNEW_KEY",
        WHATSNEW_SUPPRESS_KEY: "first_launch.WHATSNEW_SUPPRESS_KEY",
        "last_update_check_epoch": "main_window.checkForUpdatesStartup",
        "window/geometry": "main_window.windowGeometrySettings",
        "last_folder": "file_dialog / main_window._rememberSeriesFolder",
        "username": "main_window / first_launch.resolve_username",
        UPDATE_CHECK_DEFAULT_APPLIED_KEY: "settings_migrations",
        SEED_MARKER: "settings_domain.SEED_MARKER",
        FOLD_MARKER: "settings_domain.FOLD_MARKER",
    }
    for key in PALETTE_VIS_KEYS.values():
        raw[key] = "mouse_palette.PALETTE_VIS_KEYS"
    for key in PALETTE_POS_KEYS:
        raw[key] = "mouse_palette.PALETTE_POS_KEYS"
    for key, origin in raw.items():
        keys.setdefault(key, origin)
    return keys


# --- the two domains ------------------------------------------------------------


def test_shared_domain_is_the_stable_store_with_and_without_the_flavor(monkeypatch):
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    assert shared_domain() == STABLE_DOMAIN
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert shared_domain() == STABLE_DOMAIN
    assert SHARED_APP == "PyReconstruct"


def test_per_app_domain_follows_the_flavor(monkeypatch):
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    assert per_app_domain() == STABLE_DOMAIN
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert settings_app() == DEV
    assert per_app_domain() == DEV_DOMAIN


def test_the_stable_app_has_one_domain(monkeypatch):
    """For the stable app the overlay is the same store: sharing costs it
    nothing and changes nothing."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    assert per_app_domain() == shared_domain()
    for key in _known_keys():
        assert domain_for(key) == STABLE_DOMAIN, key


def test_the_old_settings_domain_name_is_gone():
    """`settings_domain()` meant "this flavor's store" and every raw site used
    it. A stale call must fail at import rather than quietly land per app."""
    assert not hasattr(SD, "settings_domain")
    assert not hasattr(SD, "seed_flavor_settings_once")
    assert not hasattr(SD, "UNSEEDED_KEYS")


# --- routing ----------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(SPEC_PER_APP))
def test_per_app_keys_route_to_the_flavored_domain(monkeypatch, key):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert is_per_app_key(key)
    assert domain_for(key) == DEV_DOMAIN


@pytest.mark.parametrize("key", [
    "username", "last_folder", "recently_opened_series", "auto_merge",
    "left_handed", "theme", "update_channel", "update_branch",
    "update_check_on_startup", "update_check_on_startup_default_applied",
    "palette/trace_hidden", "palette/mode_x", "autobackup", "backup_dir",
    "list_layout", "pasteattributes_act",
])
def test_everything_else_routes_to_the_shared_domain(monkeypatch, key):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert not is_per_app_key(key)
    assert domain_for(key) == STABLE_DOMAIN


def test_domain_for_takes_several_keys_that_agree(monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert domain_for("palette/mode_x", "palette/mode_y") == STABLE_DOMAIN
    assert domain_for("suppress_whatsnew", "last_whatsnew_version") == DEV_DOMAIN


def test_domain_for_refuses_a_mix(monkeypatch):
    """One settings object cannot serve keys from both stores; half-routed
    keys would be the silent version of the bug this module exists to stop."""
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    with pytest.raises(ValueError):
        domain_for("username", "window/geometry")
    with pytest.raises(TypeError):
        domain_for()


def test_per_app_keys_is_the_single_source_of_truth():
    """The frozenset plus the ``meta/`` prefix classify exactly the spec's
    list. A key added to the code without a decision here fails the
    classification test below, not this one; this one pins the list itself."""
    assert PER_APP_KEYS == SPEC_PER_APP - {
        SEED_MARKER, FOLD_MARKER, LEGACY_COPY_MARKER,
    }
    assert SD.PER_APP_PREFIXES == ("meta/",)


def test_the_whats_new_literals_stay_in_step():
    """constants cannot import from gui, so the two What's new keys are
    literals in PER_APP_KEYS. If either name moves, both must."""
    from PyReconstruct.modules.gui.main.first_launch import (
        WHATSNEW_KEY, WHATSNEW_SUPPRESS_KEY,
    )
    assert WHATSNEW_KEY in PER_APP_KEYS
    assert WHATSNEW_SUPPRESS_KEY in PER_APP_KEYS


# --- every known key is classified -------------------------------------------------


def test_every_known_key_is_classified_as_the_design_intends(monkeypatch):
    """Every key the app stores lands where section 4 of the design says.

    The inventory is the union of `default_settings`, `default_series_settings`,
    the raw-site literals, and the main-window key list in `conftest.py`. A key
    that is per app but not in SPEC_PER_APP, or shared but listed there, is a
    routing decision nobody made. Add the key to one list or the other on
    purpose.
    """
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    keys = _known_keys()
    assert len(keys) > 130, "the inventory lost its biggest source"

    misrouted = {}
    for key, origin in keys.items():
        expected = DEV_DOMAIN if key in SPEC_PER_APP else STABLE_DOMAIN
        actual = domain_for(key)
        if actual != expected:
            misrouted[key] = (origin, actual)
    assert not misrouted, (
        "keys routed against the design (key: origin, where it went): "
        f"{misrouted}. A per-app key belongs in PER_APP_KEYS AND in this "
        "test's SPEC_PER_APP; everything else is shared."
    )


def test_conftest_inventory_carries_no_key_the_design_does_not_know():
    """`_MAIN_WINDOW_SETTINGS_KEYS` is the closest thing to a write inventory
    in the repo. Each of its keys is one this test already classifies by
    origin, so a key added there is a key added to the design too."""
    import conftest
    known = _known_keys()
    for key in conftest._MAIN_WINDOW_SETTINGS_KEYS:
        assert key in known, key


# --- no raw site bypasses the router ---------------------------------------------


APP_ROOT = Path(__file__).resolve().parents[1] / "PyReconstruct"

# The two modules allowed to construct QSettings from a domain of their own:
# the store seam addresses the shared domain by name, and the router module
# is where the domains come from.
ROUTER_MODULES = {
    APP_ROOT / "modules" / "backend" / "settings_store.py",
    APP_ROOT / "modules" / "constants" / "settings_domain.py",
}

_CONSTRUCTION = re.compile(r"\bQSettings\(")
_ROUTED = re.compile(r"\bQSettings\(\*domain_for\(")


def test_every_raw_qsettings_construction_in_the_app_goes_through_domain_for():
    """Scan the application sources for ``QSettings(``.

    Outside the two router modules, every construction must read
    ``QSettings(*domain_for(<key>...))``. A construction that names the domain
    itself (``QSettings(ORG, APP)``, ``QSettings(*settings_domain())``) is how
    a key ends up in the wrong store with nothing failing.
    """
    offenders = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path in ROUTER_MODULES:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if "`" in code:
                continue  # a docstring mention, not a construction
            if _CONSTRUCTION.search(code) and not _ROUTED.search(code):
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_the_router_modules_are_still_where_they_were():
    for path in ROUTER_MODULES:
        assert path.is_file(), path


# --- the store seam -----------------------------------------------------------------


def test_the_settings_store_addresses_the_shared_domain_under_the_dev_flavor(monkeypatch):
    """Replaces the old `test_dev_flavor_is_fully_isolated`: `Series.getOption`
    and `setOption` reach one store from either app, for both scopes."""
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    store = QSettingsStore()
    assert (store.ORG, store.APP) == STABLE_DOMAIN
    from PySide6.QtCore import QSettings
    assert store._settings(None).fileName() == QSettings("PyReconstruct", "PyReconstruct").fileName()
    assert store._settings("SER1").fileName() == QSettings("PyReconstruct", "PyReconstruct-SER1").fileName()


def test_the_settings_store_is_unchanged_for_the_stable_app(monkeypatch):
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    store = QSettingsStore()
    assert (store.ORG, store.APP) == STABLE_DOMAIN
    from PySide6.QtCore import QSettings
    assert store._settings(None).fileName() == QSettings("PyReconstruct", "PyReconstruct").fileName()
    assert store._settings("SER1").fileName() == QSettings("PyReconstruct", "PyReconstruct-SER1").fileName()


# --- the raw sites, per flavor ----------------------------------------------------


def test_window_geometry_is_per_app(monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as MW

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert (MW.windowGeometrySettings().organizationName(),
            MW.windowGeometrySettings().applicationName()) == DEV_DOMAIN
    monkeypatch.delenv("PYRECON_APP_NAME")
    assert (MW.windowGeometrySettings().organizationName(),
            MW.windowGeometrySettings().applicationName()) == STABLE_DOMAIN


def test_palette_settings_are_shared(monkeypatch):
    from PyReconstruct.modules.gui.palette import mouse_palette as MP

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    for settings in (MP._visibility_settings(), MP._position_settings()):
        assert (settings.organizationName(), settings.applicationName()) == STABLE_DOMAIN


def test_the_whats_new_gate_reads_and_writes_the_dev_store_under_the_dev_flavor(monkeypatch):
    """`maybe_show_whats_new` with no injected store resolves per app: a
    nightly's last-seen version never lands where the stable app reads."""
    from PySide6.QtCore import QSettings
    from PyReconstruct.modules.gui.dialog import whats_new as W
    from PyReconstruct.modules.gui.main import first_launch as F

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    dev = QSettings(*DEV_DOMAIN)
    stable = QSettings(*STABLE_DOMAIN)
    for s in (dev, stable):
        s.remove(F.WHATSNEW_KEY)
        s.remove(F.WHATSNEW_SUPPRESS_KEY)
    dev.setValue(F.WHATSNEW_SUPPRESS_KEY, False)
    dev.sync()
    stable_before = stable.value(F.WHATSNEW_KEY)
    try:
        shown = W.maybe_show_whats_new(None, current="9.9.9", show=lambda *a, **k: None)
        assert shown is True
        assert QSettings(*DEV_DOMAIN).value(F.WHATSNEW_KEY) == "9.9.9"
        assert QSettings(*STABLE_DOMAIN).value(F.WHATSNEW_KEY) == stable_before
    finally:
        for s in (QSettings(*DEV_DOMAIN), QSettings(*STABLE_DOMAIN)):
            s.remove(F.WHATSNEW_KEY)
            s.remove(F.WHATSNEW_SUPPRESS_KEY)
            s.sync()


def test_the_isolation_root_holds_every_domain_this_design_names(monkeypatch):
    """Sanity for the suite itself: the Dev domain, the shared domain, and a
    per-series domain under each all resolve into the throwaway root, so
    none of these tests can reach the developer's real preferences."""
    import qsettings_isolation as qi
    from PySide6.QtCore import QSettings

    if not qi.installed:
        pytest.skip("Qt not importable, nothing to isolate")
    root = os.path.abspath(qi.isolation_root)
    for app in ("PyReconstruct", DEV, "PyReconstruct-X", f"{DEV}-X"):
        assert os.path.abspath(QSettings("PyReconstruct", app).fileName()).startswith(root), app
