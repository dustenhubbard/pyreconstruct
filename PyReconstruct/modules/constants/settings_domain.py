"""The QSettings domains: one shared store, and a small per-app overlay.

Two builds install side by side (PyReconstruct and PyReconstruct Dev). The
Dev packaging stamps PYRECON_APP_NAME (packaging/rthook_flavor.py), and that
variable still decides everything that has to differ between the two apps:
the window title, the update channel, the series ownership marker. Stored
settings are the exception. Since 2026-09-27 both apps read and write ONE
shared domain, ``KHLab / PyReconstruct``, for global preferences and
``KHLab / PyReconstruct-<code>`` for per-series ones, so a preference changed
in either app is what the other app sees at its next read. A user who runs
both no longer sets everything twice.

A short list of keys must stay per app (PER_APP_KEYS, PER_APP_PREFIXES):
the What's new popup state, the update-check throttle, the window position,
and the store's own bookkeeping under ``meta/``. Those route to the flavored
domain ``KHLab / <settings_app()>``. For the stable app the two domains are
the same name, so its behavior is unchanged: same file, same keys, same
values as before the Dev app started sharing.

Every raw ``QSettings`` construction in the app goes through
``domain_for(key)``; ``QSettingsStore`` (backend/settings_store.py), which
carries ``Series.getOption``, addresses the shared domain directly. A test
scans the sources for any construction that bypasses this module.

Forward compatibility is the one real hazard of sharing: a nightly runs
against a store the stable build also reads, and stable coerces each value
with the type of ITS default. So a key's type or JSON shape never changes;
a shape change is a new key name, the old key is left in place, and stable
keeps reading it. tests/settings_manifest.json pins the type of every
default and the test on it fails when one moves.

Read at call time, not import time, so tests can flip the environment
without reimporting, and so import order against the runtime hook cannot
matter.
"""
import json
import os

SETTINGS_ORG = "KHLab"

# The application name of the shared store. Also the stable app's own name,
# which is what makes sharing free for the stable app: it reads and writes
# exactly what it always did.
SHARED_APP = "PyReconstruct"


def settings_app():
    """The application name of this flavor (``PyReconstruct Dev`` under the
    Dev bundle's environment, ``PyReconstruct`` otherwise)."""
    return os.environ.get("PYRECON_APP_NAME", SHARED_APP)


def shared_domain():
    """(org, app) of the store both apps share. Never flavored."""
    return SETTINGS_ORG, SHARED_APP


def per_app_domain():
    """(org, app) of this flavor's own store, for the few PER_APP_KEYS.

    The stable app's per-app domain IS the shared domain.
    """
    return SETTINGS_ORG, settings_app()


# Keys that must differ between the two installed apps. Everything not listed
# here (and not under a PER_APP_PREFIXES group) is shared. This list is the
# single source of truth: domain_for() reads it, the fold skips it, and
# tests/test_settings_domains.py pins that every key the app stores is
# classified the way the design intends.
#
#   suppress_whatsnew        each app's own popup choice: a "Don't show again"
#                            in one app must not silence the other
#   last_whatsnew_version    version lines differ (1.23.0 versus
#                            1.24.0.dev<date>); a nightly writing a higher
#                            version would hide every future stable popup
#   whatsnew_popup_reset_applied
#                            the one-time reset of the two keys above ran in
#                            this store (first_launch.reset_whats_new_popup_once)
#   last_update_check_epoch  the 24h throttle is per feed; a stable check
#                            must not silence the Dev check for a day
#   window/geometry          the two apps run side by side; one shared blob
#                            would put one window exactly over the other
#   update_notice_version    the newer build the launch check found; each app
#                            follows its own feed, so a nightly version must
#                            not show up in the stable app
#
# The What's new keys mirror WHATSNEW_KEY, WHATSNEW_SUPPRESS_KEY and
# WHATSNEW_RESET_MARKER in gui/main/first_launch.py as literals: constants
# cannot import from gui. test_settings_domains.py checks the literals stay in
# step.
PER_APP_KEYS = frozenset({
    "suppress_whatsnew",
    "last_whatsnew_version",
    "whatsnew_popup_reset_applied",
    "last_update_check_epoch",
    "window/geometry",
    "update_notice_version",
})

# Key groups that are bookkeeping about one particular store rather than a
# preference: the seed marker the old split wrote, the fold marker below.
PER_APP_PREFIXES = ("meta/",)


def is_per_app_key(key):
    """True when ``key`` lives in this flavor's own store, not the shared one."""
    return key in PER_APP_KEYS or key.startswith(PER_APP_PREFIXES)


def domain_for(*keys):
    """(org, app) for a raw ``QSettings`` that reads or writes ``keys``.

    Unpack into ``QSettings(*domain_for(key))``. Several keys can be named
    when one settings object serves them all; they must all land in the same
    domain, and a mix raises rather than silently routing half of them to the
    wrong store.
    """
    if not keys:
        raise TypeError("domain_for() needs at least one key")
    per_app = {is_per_app_key(key) for key in keys}
    if len(per_app) != 1:
        raise ValueError(
            "keys split across the shared and per-app domains: "
            + ", ".join(sorted(keys))
        )
    return per_app_domain() if per_app.pop() else shared_domain()


# Marker the retired one-shot seed wrote into a Dev domain (2026-08-25 to
# 2026-09-27). Left named so a reader of their own settings can still tell
# what it was; the fold does not depend on it.
SEED_MARKER = "meta/settings_seeded"

# Marker the fold writes into a Dev domain once that domain's values have
# been offered to the shared store. Per-app by prefix, so it never travels.
FOLD_MARKER = "meta/folded_into_shared"


def _fold(flavored, shared, mark_always, validate_list_layout=False):
    """Copy ``flavored``'s shareable keys into ``shared`` where missing.

    The stable value wins where both hold a key: the user set most things
    twice to the same value, and where they differ, stable is the app for
    real work. Per-app keys and ``meta/`` stay where they are. The flavored
    domain is left in place, so a downgraded nightly still runs.

    ``mark_always`` writes FOLD_MARKER even when nothing was copied. The
    global fold does: the Dev domain exists regardless, for the per-app
    keys. The per-series fold does not, so that opening a series in Dev
    does not create a ``PyReconstruct Dev-<code>`` store holding nothing
    but a marker; a domain with nothing to give is rescanned on the next
    open, which is a few reads. Returns the keys that were copied.

    On macOS ``allKeys()`` on a NativeFormat store also lists the global
    NSUserDefaults domain (tests/qsettings_isolation.py measured it). Those
    keys are present in the shared store by the same rule, so ``contains``
    skips them; only a key the Dev store alone holds is written.
    """
    copied = []
    for key in flavored.allKeys():
        if is_per_app_key(key) or shared.contains(key):
            continue
        value = flavored.value(key)
        if validate_list_layout and key == "list_layout":
            # Series.getOption decodes this as a JSON dictionary. Do not
            # carry a damaged Dev layout into the stable app's store.
            try:
                layout = json.loads(value)
            except (TypeError, ValueError):
                continue
            if not isinstance(layout, dict):
                continue
        shared.setValue(key, value)
        copied.append(key)
    if copied:
        from PySide6.QtCore import QSettings
        shared.sync()
        if shared.status() != QSettings.NoError:
            # Leave the Dev domain unmarked so a later launch can retry
            # when the shared store is writable again.
            return []
    if copied or mark_always:
        flavored.setValue(FOLD_MARKER, True)
        flavored.sync()
    return copied


def fold_flavor_settings_once(flavored=None, shared=None):
    """First launch of a flavored build on the shared store: fold its old
    domain in, once.

    Before 2026-09-27 the Dev app kept its own copy of every global setting
    (seeded from the stable app on first launch, then edited on its own).
    This carries any value the Dev domain holds and the shared domain lacks
    into the shared store, then writes FOLD_MARKER into the Dev domain so it
    never runs again. Where both domains hold a key the stable value stays.

    The stable app is a no-op and never opens a Dev domain. Returns True
    when a fold ran (whether or not anything was copied).

    ``flavored``/``shared`` are injectable for tests; production resolves
    both from the real domains.
    """
    if flavored is None:
        if settings_app() == SHARED_APP:
            return False
        from PySide6.QtCore import QSettings
        flavored = QSettings(*per_app_domain())
    if flavored.contains(FOLD_MARKER):
        return False
    if shared is None:
        from PySide6.QtCore import QSettings
        shared = QSettings(*shared_domain())
    _fold(flavored, shared, mark_always=True)
    return True


def fold_series_settings_once(code, flavored=None, shared=None):
    """Fold one series' old Dev per-series domain into the shared one, once.

    Per-series settings (``autobackup``, ``backup_dir``, ``list_layout``)
    live in ``KHLab / <app>-<code>``. The old split gave the Dev app its own
    ``PyReconstruct Dev-<code>`` domain, which the seed never touched, so it
    holds whatever the Dev app wrote there. Runs lazily when a series opens,
    because the per-series domains cannot be enumerated portably. Same rule
    as the global fold: copy where the shared domain lacks the key, stable
    wins where both have it, and mark the Dev domain done once it has given
    something.

    The stable app is a no-op. A series without a code has no per-series
    domain to fold. Returns True when something was copied.
    """
    if not code:
        return False
    if flavored is None:
        if settings_app() == SHARED_APP:
            return False
        from PySide6.QtCore import QSettings
        flavored = QSettings(SETTINGS_ORG, f"{settings_app()}-{code}")
    if flavored.contains(FOLD_MARKER):
        return False
    if shared is None:
        from PySide6.QtCore import QSettings
        shared = QSettings(SETTINGS_ORG, f"{SHARED_APP}-{code}")
    return bool(_fold(
        flavored, shared, mark_always=False, validate_list_layout=True
    ))
