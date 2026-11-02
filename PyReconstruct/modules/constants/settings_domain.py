"""The QSettings domains: one shared store, and a small per-app overlay.

Two builds install side by side (PyReconstruct and PyReconstruct Dev). The
Dev packaging stamps PYRECON_APP_NAME (packaging/rthook_flavor.py), and that
variable still decides everything that has to differ between the two apps:
the window title, the update channel, the series ownership marker. Stored
settings are the exception. Since 2026-09-27 both apps read and write ONE
shared domain, ``PyReconstruct / PyReconstruct``, for global preferences and
``PyReconstruct / PyReconstruct-<code>`` for per-series ones, so a preference changed
in either app is what the other app sees at its next read. A user who runs
both no longer sets everything twice.

A short list of keys must stay per app (PER_APP_KEYS, PER_APP_PREFIXES):
the What's new popup state, the update-check throttle, the window position,
and the store's own bookkeeping under ``meta/``. Those route to the flavored
domain ``PyReconstruct / <settings_app()>``. For the stable app the two domains are
the same application name.

Each store copies its old KHLab values on first use. Existing destination
values win, and the old store stays intact for older builds. The organization
migration runs before the older Dev-to-shared fold.

Every settings handle in the app comes from ``settings_for(key)``; ``QSettingsStore`` (backend/settings_store.py), which
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
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar

SETTINGS_ORG = "PyReconstruct"
LEGACY_SETTINGS_ORG = "KHLab"
ORG_MIGRATION_MARKER = "meta/migrated_from_khlab"

# The application name of the shared store. Also the stable app's own name,
# which is what makes sharing free for the stable app: it reads and writes
# exactly what it always did.
SHARED_APP = "PyReconstruct"


def settings_app():
    """The application name of this flavor (``PyReconstruct Dev`` under the
    Dev bundle's environment, ``PyReconstruct`` otherwise)."""
    return os.environ.get("PYRECON_APP_NAME", SHARED_APP)


# The text between the app and the digest in the settings name of a series
# code that holds a NUL, or a path segment the Ini format or the Windows
# registry would resolve (see series_app).
NUL_CODE_MARKER = " NUL-"
PATH_CODE_MARKER = " PATH-"


def _resolves_as_path(code):
    """True when the Ini format would read ``<app>-<code>`` as a path to a
    file other than the one the name spells.

    Split on "/", the first segment follows ``<app>-`` and the last takes
    the ``.ini`` suffix, so neither can be empty, "." or "..". A segment
    between them that is one of those is resolved away: ``a//b`` and
    ``a/./b`` reach the file of ``a/b``, and ``/../PyReconstruct-x`` the
    file of ``x``. A backslash is a plain character in a Linux file name.
    """
    return any(part in ("", ".", "..") for part in code.split("/")[1:-1])


def _native_is_registry():
    """True where the native settings format is the Windows registry."""
    return sys.platform == "win32"


def _resolves_in_registry(code):
    """True when the Windows registry would open ``<app>-<code>`` as the key
    of another name.

    The name is a registry path and "\\" separates its keys. Split on
    "\\", the first segment follows ``<app>-``, so it names a key even when
    empty. An empty segment after it is dropped: ``existing\\`` and
    ``existing\\\\`` open the key of ``existing``, and ``a\\\\b`` the key of
    ``a\\b``. A "/", "." or ".." is a plain character in a key name.
    """
    return "" in code.split("\\")[1:]


def series_app(app, code):
    """The application name of one series' own settings: ``<app>-<code>``.

    The name becomes a file name in the Ini format (Linux, and the test
    suite), and no file name can hold a NUL. Given one, `QLockFile` retries
    the lock forever, so a series whose code holds a NUL would hang every
    per-series read. A code typed in Series code is refused a NUL, but one
    read from a series file is not.

    So a code with a NUL is named ``<app> NUL-<digest>``: the SHA-256 of
    the code, in 64 lowercase hex digits. A code the Ini format would
    resolve to another file (see _resolves_as_path) is named
    ``<app> PATH-<digest>`` the same way, so it no longer reads or writes
    the settings of another series, the shared store or the other app. So
    is a code the Windows registry would resolve to another key (see
    _resolves_in_registry), on Windows only: elsewhere a backslash is a
    plain character and that code keeps its name. The names have no
    separator or dot for the Ini format or the registry to read as a path,
    so each stays one file or key of its own. Every ``<app>-<code>`` name
    has "-" right after the app name, so none is spelled like them. Every
    other code names the domain it always has.
    """
    if "\0" in code:
        marker = NUL_CODE_MARKER
    elif _resolves_as_path(code) or (
        _native_is_registry() and _resolves_in_registry(code)
    ):
        marker = PATH_CODE_MARKER
    else:
        return f"{app}-{code}"
    digest = hashlib.sha256(code.encode("utf-8", "surrogatepass")).hexdigest()
    return f"{app}{marker}{digest}"


# Qt keeps parsed settings beyond a module reload during Restart.
_unreadable_settings = globals().get("_unreadable_settings", set())
_REMOVED_KEYS = "meta/removed_during_migration"
_user_actions = globals().get("_user_actions", ContextVar("settings_user_actions", default=0))


def _read_keys(settings):
    from PySide6.QtCore import QSettings

    path = settings.fileName()
    if path in _unreadable_settings:
        return None
    settings.setFallbacksEnabled(False)
    settings.sync()
    keys = settings.allKeys()
    status = settings.status()
    if status == QSettings.FormatError:
        _unreadable_settings.add(path)
    return keys if status == QSettings.NoError else None


def _removed(settings, key):
    prefixes = json.loads(settings.value(_REMOVED_KEYS, "[]"))
    return any(not prefix or key == prefix or key.startswith(prefix + "/")
               for prefix in prefixes)


def migrate_settings_once(app, legacy=None, destination=None):
    """Copy a store without replacing destination values or changing the source.

    Return True after copying, False when already complete, or None while
    pending. A parse failure stays pending until the next process, including
    an in-process Restart. Access failures can retry in the same process.
    """
    from PySide6.QtCore import QSettings

    if destination is None:
        destination = QSettings(SETTINGS_ORG, app)
    if _read_keys(destination) is None:
        return None
    if destination.contains(ORG_MIGRATION_MARKER):
        return False
    if legacy is None:
        legacy = QSettings(LEGACY_SETTINGS_ORG, app)
    keys = _read_keys(legacy)
    if keys is None:
        return None
    for key in keys:
        if (key not in (ORG_MIGRATION_MARKER, _REMOVED_KEYS)
                and not destination.contains(key) and not _removed(destination, key)):
            destination.setValue(key, legacy.value(key))
    destination.sync()
    if destination.status() != QSettings.NoError:
        return None
    destination.setValue(ORG_MIGRATION_MARKER, True)
    destination.sync()
    return True if destination.status() == QSettings.NoError else None


def _copy_pending(app):
    from PySide6.QtCore import QSettings

    destination = QSettings(SETTINGS_ORG, app)
    if _read_keys(destination) is None:
        return True
    if destination.contains(ORG_MIGRATION_MARKER):
        return False
    keys = _read_keys(QSettings(LEGACY_SETTINGS_ORG, app))
    return keys is None or bool(keys)


def _flavored_app(app):
    flavor = settings_app()
    if flavor == SHARED_APP or app.startswith(flavor):
        return None
    suffix = app[len(SHARED_APP):]
    if app == SHARED_APP or app.startswith((SHARED_APP + "-", SHARED_APP + " NUL-",
                                            SHARED_APP + " PATH-")):
        return flavor + suffix
    return None


def store_copy_pending(app):
    """Hold automatic writes until this store and its Dev input are ready."""
    from PySide6.QtCore import QSettings

    if _copy_pending(app):
        return True
    flavored = _flavored_app(app)
    if flavored is None:
        return False
    if _copy_pending(flavored):
        return True
    dev = QSettings(SETTINGS_ORG, flavored)
    keys = _read_keys(dev)
    if keys is None:
        return True
    if dev.contains(FOLD_MARKER):
        return False
    shared = QSettings(SETTINGS_ORG, app)
    eligible = _fold_values(dev, shared, validate_list_layout=app != SHARED_APP)
    return next(eligible, None) is not None


@contextmanager
def user_action():
    """Allow the settings writes that save an explicit user choice."""
    token = _user_actions.set(_user_actions.get() + 1)
    try:
        yield
    finally:
        _user_actions.reset(token)


class GuardedSettings:
    """Keep automatic writes out of a store awaiting migration.

    Remember a pending read on this handle even if another handle completes
    migration later. A fallback computed from that read is still stale.
    Only known read and configuration methods pass through to Qt.
    """

    _READS = frozenset({
        "allKeys", "applicationName", "beginGroup", "childGroups", "childKeys",
        "contains", "endGroup", "fallbacksEnabled", "fileName", "format",
        "group", "isAtomicSyncRequired", "isWritable", "organizationName",
        "scope", "setFallbacksEnabled", "status", "sync", "value",
    })

    def __init__(self, settings):
        self._settings = settings
        self._pending_read = store_copy_pending(settings.applicationName())

    def __getattr__(self, name):
        if name not in self._READS:
            raise AttributeError(f"GuardedSettings does not offer {name!r}")
        return getattr(self._settings, name)

    def _may_write(self):
        return bool(_user_actions.get()) or (
            not self._pending_read
            and not store_copy_pending(self._settings.applicationName())
        )

    def setValue(self, key, value):
        if self._may_write():
            self._settings.setValue(key, value)

    def _remember_removal(self, key):
        if not store_copy_pending(self._settings.applicationName()):
            return
        from PySide6.QtCore import QSettings

        group = self._settings.group()
        absolute = "/".join(part for part in (group, key) if part)
        root = QSettings(SETTINGS_ORG, self._settings.applicationName())
        removed = json.loads(root.value(_REMOVED_KEYS, "[]"))
        if absolute not in removed:
            removed.append(absolute)
            root.setValue(_REMOVED_KEYS, json.dumps(removed))

    def remove(self, key):
        if self._may_write():
            self._settings.remove(key)
            self._remember_removal(key)


def guarded_settings(app, migrate=True):
    from PySide6.QtCore import QSettings

    if migrate:
        migrate_settings_once(app)
        if app == SHARED_APP:
            fold_flavor_settings_once()
    return GuardedSettings(QSettings(SETTINGS_ORG, app))


def settings_for(*keys):
    """Open the routed store with the pending-copy write guard."""
    return guarded_settings(domain_for(*keys)[1])


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
#   cli_commands_added       this app's one-time PATH step for its terminal
#                            commands ran (the Linux link, on Linux)
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
    "cli_commands_added",
})

# Key groups that are bookkeeping about one particular store rather than a
# preference: the seed marker the old split wrote, the fold marker below.
PER_APP_PREFIXES = ("meta/",)


def is_per_app_key(key):
    """True when ``key`` lives in this flavor's own store, not the shared one."""
    return key in PER_APP_KEYS or key.startswith(PER_APP_PREFIXES)


def domain_for(*keys):
    """(org, app) for ``keys``; ``settings_for`` opens the guarded store.

    Several keys can be named
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


def _fold_values(flavored, shared, validate_list_layout=False):
    """Values the Dev store can still contribute to the shared store."""
    for key in flavored.allKeys():
        if is_per_app_key(key) or shared.contains(key) or _removed(shared, key):
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
        yield key, value


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
    for key, value in _fold_values(flavored, shared, validate_list_layout):
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
        stable_copy = migrate_settings_once(SHARED_APP)
        dev_copy = migrate_settings_once(settings_app())
        if stable_copy is None or dev_copy is None:
            return False
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
    live in ``PyReconstruct / <app>-<code>``. The old split gave the Dev app its own
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
        stable_copy = migrate_settings_once(series_app(SHARED_APP, code))
        dev_copy = migrate_settings_once(series_app(settings_app(), code))
        if stable_copy is None or dev_copy is None:
            return False
        flavored = QSettings(SETTINGS_ORG, series_app(settings_app(), code))
    if flavored.contains(FOLD_MARKER):
        return False
    if shared is None:
        from PySide6.QtCore import QSettings
        shared = QSettings(SETTINGS_ORG, series_app(SHARED_APP, code))
    return bool(_fold(
        flavored, shared, mark_always=False, validate_list_layout=True
    ))
