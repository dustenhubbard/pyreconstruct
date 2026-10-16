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
the same name, so its behavior is unchanged: same file, same keys, same
values as before the Dev app started sharing.

Every settings object the app opens comes from ``settings_for(key)``, which
routes by ``domain_for(key)``; ``QSettingsStore`` (backend/settings_store.py),
which carries ``Series.getOption``, addresses the shared domain directly. A
test scans the sources for any construction that bypasses this module.

Forward compatibility is the one real hazard of sharing: a nightly runs
against a store the stable build also reads, and stable coerces each value
with the type of ITS default. So a key's type or JSON shape never changes;
a shape change is a new key name, the old key is left in place, and stable
keeps reading it. tests/settings_manifest.json pins the type of every
default and the test on it fails when one moves.

Until 2026-10-03 every domain above sat under the organization ``KHLab``
instead of ``PyReconstruct``. ``copy_legacy_settings_once`` and
``copy_legacy_series_settings_once`` copy those stores across once and leave
them in place, so an older build still finds its settings.

Read at call time, not import time, so tests can flip the environment
without reimporting, and so import order against the runtime hook cannot
matter.
"""
import json
import os
from contextlib import contextmanager

SETTINGS_ORG = "PyReconstruct"

# The organization every store sat under before 2026-10-03. Read once per
# store by the copy below and never written.
LEGACY_SETTINGS_ORG = "KHLab"

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
    """(org, app) for a ``QSettings`` that reads or writes ``keys``.

    ``settings_for(key)`` opens it. Several keys can be named
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
        flavored = QSettings(SETTINGS_ORG, f"{settings_app()}-{code}")
    if flavored.contains(FOLD_MARKER):
        return False
    if shared is None:
        from PySide6.QtCore import QSettings
        shared = QSettings(SETTINGS_ORG, f"{SHARED_APP}-{code}")
    return bool(_fold(
        flavored, shared, mark_always=False, validate_list_layout=True
    ))


# Marker the legacy copy writes into a store once that store has been filled
# from its ``KHLab`` counterpart. Per-app by prefix, so the fold never carries
# it into the shared store, and one app's copy never marks another app's.
LEGACY_COPY_MARKER = "meta/copied_from_khlab"


# Stores whose copy from ``KHLab`` is known, this session, to be unfinished
# (True) or done (False), by application name. Filled by the copy and by
# legacy_copy_pending; tests clear it between cases.
_copy_pending: dict[str, bool] = {}

# Old stores whose file failed to parse in this process, by application name.
# The in-app Restart reloads every PyReconstruct.modules module in the same
# process, and Qt's parse of the file outlives that reload, so this set must
# too: a reload runs this line again with the module's old namespace, and
# keeps the set it finds there.
_unparsable_legacy: set[str] = globals().get("_unparsable_legacy", set())


def _read_legacy_keys(app, old=None):
    """The keys ``KHLab / <app>`` holds, or None when it cannot be read.

    Qt parses a settings file once per process and keeps that parse until it
    decides the file changed. A later ``QSettings`` on the same file is handed
    the first parse and reports no error, even when the parse stopped partway
    through a damaged file. Qt's test for a change is its own (size and a
    millisecond time, among others), so a file that failed to parse counts as
    unreadable for the rest of the session, changed or not; the next launch
    reads it afresh. A file that could not be opened is not parsed, so it is
    simply tried again.
    """
    from PySide6.QtCore import QSettings

    if app in _unparsable_legacy:
        return None
    if old is None:
        old = QSettings(LEGACY_SETTINGS_ORG, app)
        old.setFallbacksEnabled(False)
    keys = [key for key in old.allKeys() if key != LEGACY_COPY_MARKER]
    status = old.status()
    if status != QSettings.NoError:
        if status == QSettings.FormatError:
            _unparsable_legacy.add(app)
        return None
    return keys


def legacy_copy_pending(app):
    """True while ``PyReconstruct / <app>`` still owes a copy from ``KHLab``.

    That is: the copy failed this session, or it has not run and the new
    store carries no marker while the old one holds something or cannot be
    read. An old store that cannot be read is a copy to retry, as it is in
    the copy itself, not a store with nothing to give. While a store is
    pending, it takes only the user's own writes (``GuardedSettings``),
    because the retry never overwrites a key the new store already holds,
    and a value written in the meantime would win over the one the retry was
    meant to bring back. Never raises; when the stores cannot be read the
    answer is True, which only means such a value is not saved yet.
    """
    if app in _copy_pending:
        return _copy_pending[app]
    try:
        from PySide6.QtCore import QSettings

        new = QSettings(SETTINGS_ORG, app)
        new.setFallbacksEnabled(False)
        if new.contains(LEGACY_COPY_MARKER):
            pending = False
        else:
            keys = _read_legacy_keys(app)
            pending = keys is None or bool(keys)
    except Exception:
        return True
    _copy_pending[app] = pending
    return pending


def store_copy_pending(app):
    """True while ``PyReconstruct / <app>`` is still owed values from ``KHLab``.

    The shared stores (``PyReconstruct`` and ``PyReconstruct-<code>``) are
    owed them by their own copy and by the Dev fold (``shared_copy_pending``);
    any other store, such as the Dev app's own, only by its own copy.
    """
    if app == SHARED_APP or app.startswith(f"{SHARED_APP}-"):
        return shared_copy_pending(app[len(SHARED_APP):])
    return legacy_copy_pending(app)


# How many ``user_action`` blocks are open. Settings are written on the GUI
# thread only.
_user_actions = 0


@contextmanager
def user_action():
    """Mark the settings writes inside as the user's own choice.

    While a store is owed its copy from ``KHLab``, it takes no other write
    (``GuardedSettings``): the copy never replaces a key the store already
    holds, so a value the program saved on its own would win over the one the
    copy brings. A choice the user makes is newer than anything the copy can
    bring, so it is saved as usual. Wrap only the writes of what the user
    chose: a default read on a miss inside the block is still not saved
    (``Series.getOption``).
    """
    global _user_actions
    _user_actions += 1
    try:
        yield
    finally:
        _user_actions -= 1


def may_write(settings):
    """Whether a write to ``settings`` goes through now: always inside a
    ``user_action``, otherwise only once its store owes no copy. Never
    raises."""
    if _user_actions:
        return True
    try:
        if settings.organizationName() != SETTINGS_ORG:
            return True
        return not store_copy_pending(settings.applicationName())
    except Exception:
        return False


class GuardedSettings:
    """A ``QSettings`` whose writes wait while its store is owed its copy.

    Every settings object the app writes through is one of these
    (``settings_for``, and ``QSettingsStore`` for ``Series.setOption``), so
    one rule holds every write that is not the user's (``may_write``): a
    writer nobody listed cannot fill a key the copy still has to bring.
    The copy and the fold in this module write through plain ``QSettings``.

    Only the reads in ``READS`` pass straight through. Every call that can
    change the store is checked here: ``setValue``, ``remove``, ``clear``, and
    an array write (``beginWriteArray``, ``setArrayIndex``, ``endArray``, the
    last of which stores the array's size). Anything else is not offered, so
    a mutator added to Qt later fails loudly instead of writing past the
    check. Wraps rather than subclasses, so the ``QSettings`` class is looked
    up when a store is opened, not when this module is imported.
    """

    READS = frozenset({
        "allKeys", "applicationName", "beginGroup", "childGroups",
        "childKeys", "contains", "endGroup", "fallbacksEnabled", "fileName",
        "format", "group", "isAtomicSyncRequired", "isWritable",
        "organizationName", "scope", "status", "sync", "value",
    })

    def __init__(self, settings):
        self._settings = settings
        # one entry per open array: whether its calls reach the store. A read
        # array always does; a write array only if it was allowed to begin
        self._arrays = []

    def __getattr__(self, name):
        if name in GuardedSettings.READS:
            return getattr(self._settings, name)
        raise AttributeError(
            f"GuardedSettings does not offer {name!r}; a call that can change "
            "the store needs its own check here"
        )

    def setValue(self, key, value):
        if self._writing() and may_write(self._settings):
            self._settings.setValue(key, value)

    def remove(self, key):
        if self._writing() and may_write(self._settings):
            self._settings.remove(key)

    def clear(self):
        if may_write(self._settings):
            self._settings.clear()

    def beginReadArray(self, prefix):
        self._arrays.append(True)
        return self._settings.beginReadArray(prefix)

    def beginWriteArray(self, prefix, size=-1):
        allowed = self._writing() and may_write(self._settings)
        self._arrays.append(allowed)
        if allowed:
            self._settings.beginWriteArray(prefix, size)

    def setArrayIndex(self, i):
        if self._writing():
            self._settings.setArrayIndex(i)

    def endArray(self):
        if self._arrays.pop() if self._arrays else True:
            self._settings.endArray()

    def _writing(self):
        """False inside a write array that was refused, whose calls all wait."""
        return not self._arrays or self._arrays[-1]


def settings_for(*keys):
    """The store for ``keys`` (``domain_for``), with its writes guarded."""
    from PySide6.QtCore import QSettings

    return GuardedSettings(QSettings(*domain_for(*keys)))


def per_app_copy_pending():
    """True while this app's own store still owes its copy from ``KHLab``.

    The per-app keys (window position, What's new state, update bookkeeping)
    live there and never pass through the fold, so only that store's own copy
    matters for them.
    """
    return legacy_copy_pending(settings_app())


def shared_copy_pending(suffix=""):
    """True while the shared store ``PyReconstruct / PyReconstruct<suffix>``
    is still owed values from ``KHLab``.

    It is owed them by its own copy and, in a flavored build, by the fold of
    that flavor's store, which waits for the flavor's copy. Until both are
    done, a value the program writes on its own (a default read on a miss,
    the username it picks at launch, a list it rebuilds from what it read)
    would block the stored one, so those wait (``user_action``). ``suffix``
    is ``""`` for the global store and ``"-<code>"`` for a series' store.
    """
    return any(
        legacy_copy_pending(app) for app in _this_app_and_shared(suffix)
    )


class LegacyCopyResult(dict):
    """The keys a legacy copy wrote, by application name, plus whether it
    finished.

    ``complete`` is False while any store still needs a retry: its old store
    could not be read, or its new store could not be written or marked. The
    Dev fold waits for a complete copy. Folding first would let a Dev value
    fill a shared key the stable value was still to fill, or mark an empty
    Dev store as folded, and a later retry could undo neither.
    """

    complete = True


def _copy_legacy_domain(app, mark_always):
    """Copy ``KHLab / <app>`` into ``PyReconstruct / <app>``, once.

    Every key the old store holds and the new one lacks is copied, ``meta/``
    bookkeeping included, so a Dev store that was already folded stays marked
    as folded. A key the new store already holds is left alone. The old store
    is only read: an older build that still addresses it finds everything it
    left there.

    Once the copy has been written, LEGACY_COPY_MARKER goes into the new store
    and later calls return at once. That is what makes it happen once: a value
    changed or removed in the new store afterwards is never brought back from
    the old one. When the old store cannot be read, or the new one cannot be
    written or marked, the call reports failure and the next one tries again.
    A marker already in the new store counts only once a sync confirms it is
    on disk.

    ``mark_always`` writes the marker even when the old store is empty. The
    global stores want that; a per-series store does not, so opening a
    series with no old settings never creates a store holding only a marker.
    Returns the keys that were copied, or None when the copy did not finish.

    Both stores are read with fallbacks off, so only what was stored for
    this application counts. With fallbacks on, ``allKeys()`` on macOS also
    lists the whole global NSUserDefaults domain, and on every platform it
    would pull in organization-wide and system-wide files.
    """
    from PySide6.QtCore import QSettings

    new = QSettings(SETTINGS_ORG, app)
    new.setFallbacksEnabled(False)
    if new.contains(LEGACY_COPY_MARKER):
        # A marker whose write failed earlier this session is still visible
        # in memory. Trust it only once a sync says it reached the disk.
        new.sync()
        if new.status() == QSettings.NoError:
            return []
    old = QSettings(LEGACY_SETTINGS_ORG, app)
    old.setFallbacksEnabled(False)
    keys = _read_legacy_keys(app, old)
    if keys is None:
        return None
    if not keys and not mark_always:
        return []
    copied = []
    for key in keys:
        if new.contains(key):
            continue
        new.setValue(key, old.value(key))
        copied.append(key)
    if copied:
        # the values are on disk before the marker that says they are
        new.sync()
        if new.status() != QSettings.NoError:
            return None
    new.setValue(LEGACY_COPY_MARKER, True)
    new.sync()
    if new.status() != QSettings.NoError:
        # the marker may not have landed; say so, so the fold waits
        return None
    return copied


def _this_app_and_shared(suffix=""):
    """Application names of the stores this app reads, each once."""
    names = [f"{SHARED_APP}{suffix}", f"{settings_app()}{suffix}"]
    return list(dict.fromkeys(names))


def _copy_legacy_domains(apps, mark_always):
    """Run the copy for each of ``apps``; never raises."""
    result = LegacyCopyResult()
    for app in apps:
        try:
            keys = _copy_legacy_domain(app, mark_always=mark_always)
        except Exception:
            keys = None
        _copy_pending[app] = keys is None
        if keys is None:
            result.complete = False
        elif keys:
            result[app] = keys
    return result


def copy_legacy_settings_once():
    """First launch after the move from ``KHLab``: copy the global stores.

    Covers the shared store and, in a flavored build, that flavor's own
    store. Runs before the Dev fold, which then works on the copied stores,
    and only when ``complete`` is True on the result. Never raises: a
    settings carry-over must not stop the app from opening. Returns a
    LegacyCopyResult: the keys copied, by application name.
    """
    return _copy_legacy_domains(_this_app_and_shared(), mark_always=True)


def copy_legacy_series_settings_once(code):
    """Copy one series' ``KHLab`` per-series stores the first time it opens.

    Per-series stores cannot be listed portably, so this runs when a series
    opens, before its first per-series read. Same rule as the global copy,
    and the per-series fold waits for ``complete`` the same way. A series
    without a code has no per-series store. Never raises. Returns a
    LegacyCopyResult.
    """
    if not code:
        return LegacyCopyResult()
    return _copy_legacy_domains(
        _this_app_and_shared(f"-{code}"), mark_always=False
    )
