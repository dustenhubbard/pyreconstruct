"""One-time corrections to stored settings the program wrote for itself.

`Series.getOption` persists a default the first time an option is read: the
miss branch does ``option = defaults[option_name]`` followed by
``self.setOption(option_name, option)``. So every machine that has ever
launched the app already has a value stored for every option it has read, put
there by a read rather than by anybody deciding anything.

That is what this module exists for. Changing a default in
`datatypes/default_settings.py` reaches nobody who already has the app,
because a stored value always beats a default -- and the stored value is not
a choice, it is a copy of the old default. A migration that overwrites it is
correcting the program's own bookkeeping, not overriding a user.

The distinction is the whole design, so it is enforced rather than described:

* each migration runs **once per machine** and records that it has, so a user
  who changes the setting afterwards is never overwritten. The record is the
  presence of a marker key in the same settings scope as the option, so it
  survives exactly as long as the option does;
* the option is written **before** the marker. A write that fails leaves no
  marker and is retried next launch, rather than being recorded as done;
* nothing here raises. These run on the startup path, and a settings
  correction that could stop the app from opening is worse than a stale
  setting. Same contract as the launch-time update check.

Migrations write through the settings seam (`backend/settings_store.py`)
rather than `QSettings` directly, so this module imports no Qt and tests can
drive it against `DictSettingsStore`.
"""

from typing import Optional

from PyReconstruct.modules.backend.settings_store import (
    SettingsStore,
    default_settings_store,
)


#: The option corrected below. A global (machine-wide) setting, so it lives in
#: the ``code=None`` scope -- the same scope as ``update_channel`` and the
#: ``last_update_check_epoch`` stamp, and emphatically not a per-series value.
#: Kept as a literal rather than imported from `datatypes.default_settings`,
#: which would pull the datatypes package into a backend module.
UPDATE_CHECK_KEY = "update_check_on_startup"

#: Marker recording that the correction has run on this machine. Sits beside
#: the option in the same scope, and is named so that somebody reading their
#: own settings can see what happened: the on-by-default was applied here.
#: Deliberately *not* an entry in `default_settings` -- it is bookkeeping, not
#: a preference, and an option would be persisted by the first read of it.
UPDATE_CHECK_DEFAULT_APPLIED_KEY = "update_check_on_startup_default_applied"


def _reads_as_off(value) -> bool:
    """Whether a stored value means the launch-time check is off.

    `QSettings` backends hand booleans back as real bools or as the strings
    "true"/"false" depending on platform and format, and an injected store
    returns whatever was written to it, so both shapes are accepted. A missing
    or null value counts as off: the migration's job is to heal a value that
    does not read as on, and the option's own default is on.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("false", "0", "no", "")
    return not bool(value)


def apply_update_check_on_startup_default(
    store: Optional[SettingsStore] = None,
) -> bool:
    """Turn the launch-time update check on, once, on a machine that has it off.

    ``update_check_on_startup`` shipped ``False``, and `Series.getOption`
    wrote that ``False`` into the settings of every machine that has ever
    opened the app, as a side effect of reading it. Flipping the default alone
    therefore changes nothing for anybody who already has the app. This runs
    once and writes ``True`` over that inherited ``False``.

    What happens in each state, all four of them deliberate:

    * **marker already present** -- return immediately, whatever the option
      says. This is the case that protects a user who turned the check off
      after the migration ran: their ``False`` is a decision and is never
      touched again.
    * **stored value reads as off** -- write ``True``, set the marker. The
      only case that changes anything.
    * **stored value already reads as on** -- write nothing, set the marker.
      A no-op that still records itself, so it cannot run later.
    * **nothing stored at all** -- write nothing, set the marker. A machine
      with no stored value has never read the option, so it gets ``True`` from
      the default anyway; writing here would be a settings entry nobody needs,
      and worse, it would be indistinguishable from the inherited ``False``
      case if the marker were ever lost. Marking a fresh install done is what
      makes a later "off" permanent on it too.

    Idempotent by construction: the marker is checked first and set last, so a
    second call in the same session, or on the next launch, does nothing.

    Never raises. Settings that cannot be read or written (a read-only
    preferences directory, no Qt behind the default store) leave the migration
    unrecorded, so it is simply retried next launch. A background correction
    must not be able to stop the app from opening.

        Params:
            store (SettingsStore): where to read and write; defaults to the
                process-wide store, which is `QSettings`-backed for GUI
                callers.

        Returns:
            (bool) True if the option was written, False otherwise -- including
            every no-op case and every failure. Informational; callers on the
            startup path ignore it.
    """
    try:
        if store is None:
            store = default_settings_store()

        # Presence is the record, whatever the stored value is. A hand-edited
        # marker cannot cause a second write over somebody's deliberate "off".
        if store.contains(None, UPDATE_CHECK_DEFAULT_APPLIED_KEY):
            return False

        wrote = False
        if store.contains(None, UPDATE_CHECK_KEY):
            if _reads_as_off(store.value(None, UPDATE_CHECK_KEY, bool)):
                store.set_value(None, UPDATE_CHECK_KEY, True)
                wrote = True

        # Last, always: a failure above must leave this unset so the next
        # launch retries rather than recording an unfinished migration.
        store.set_value(None, UPDATE_CHECK_DEFAULT_APPLIED_KEY, True)
        return wrote
    except Exception:
        return False
