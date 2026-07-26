"""Date/time helpers, honoring the user's UTC preference.

The "utc" preference is read through the Qt-free settings seam
(`backend/settings_store.py`, M11) rather than `QSettings` directly, so
importing `modules.constants` -- and therefore `modules.datatypes` -- pulls in
no Qt. GUI callers get the `QSettingsStore` default, i.e. the same
org/app ("KHLab"/"PyReconstruct") and key this module read before.
"""

from datetime import datetime, timedelta
from typing import Optional

from PyReconstruct.modules.backend.settings_store import (
    SettingsStore,
    default_settings_store,
)

# "utc" is a global (not per-series) option; see datatypes/default_settings.py.
# Kept as a literal because importing default_settings from here would import
# the datatypes package, which imports this module.
UTC_KEY = "utc"
UTC_DEFAULT = False


def _as_bool(value) -> bool:
    """Coerce a stored settings value to a bool.

    QSettings' native backends hand booleans back as real bools or as the
    strings "true"/"false" depending on platform and format, and a store may
    return whatever was written to it, so both shapes are accepted.
    """
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "")
    if value is None:
        return UTC_DEFAULT
    return bool(value)


def utc_p(store: Optional[SettingsStore] = None) -> bool:
    """Determine if user using UTC.

    Params:
        store (SettingsStore): the settings store to read from; defaults to the
            process-wide default (`QSettings`-backed for GUI callers).
    """
    if store is None:
        store = default_settings_store()

    try:
        if not store.contains(None, UTC_KEY):
            return UTC_DEFAULT
        return _as_bool(store.value(None, UTC_KEY, bool))
    except ImportError:
        # The default store is QSettings-backed; with no Qt installed (a
        # genuinely headless run) there is no settings backend to consult, so
        # fall back to the documented default rather than failing to timestamp.
        return UTC_DEFAULT


def get_now() -> datetime:
    """Return now's datetime object."""

    return datetime.utcnow() if utc_p() else datetime.now()


def remove_days_from_today(delta_days: int):
    """Remove days from now."""

    return get_now().date() - timedelta(days=delta_days)


def getDateTime(date_str="%y-%m-%d", time_str="%H:%M"):
    
    dt = get_now()
    
    d = dt.strftime(date_str)
    t = dt.strftime(time_str)
    
    return d, t
