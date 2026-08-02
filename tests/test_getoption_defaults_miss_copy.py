"""``getOption`` never hands out a class-level default by reference.

The bug: when an option is absent from the series' own settings store,
``getOption`` falls through to ``option = defaults[option_name]`` and returns
that object. ``Series.qsettings_defaults`` is a shallow ``.copy()`` of
``default_settings``, so a list value in it is one object shared by the whole
process. Five defaults are mutable containers::

    pointer, grid, flag_color, autoseg_color_palette, recently_opened_series

and ``recently_opened_series`` has callers that mutate what they were handed:
``MainWindow.addToRecentSeries`` calls ``remove``, ``insert`` and ``pop`` on it,
and ``getOpenRecentMenu`` calls ``remove`` for paths that no longer exist. So a
series whose store has never held the key could rewrite the shipped default and
a second series, with its own separate empty store, would read it back.

Not observable in the running app today only because ``createMenuBar`` reads the
key and writes it straight back, which populates the store before anything
mutates the returned list. That is a masking accident, not a fix: the first
caller to reach the fall-through with a mutation still corrupts the default.

The fix: ``Series._fromDefaults`` returns a shallow copy for list and dict
values, and every read out of the defaults dicts goes through it.

No Qt required. Every path exercised here uses ``DictSettingsStore``.
"""
import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.backend.settings_store import DictSettingsStore


#: Every mutable container in ``default_settings``. Enumerated by reading the
#: dict rather than by filtering it at runtime, so a new mutable default that
#: nobody thought about here shows up as a failure of the guard test below.
MUTABLE_DEFAULTS = [
    "pointer",
    "grid",
    "flag_color",
    "autoseg_color_palette",
    "recently_opened_series",
]


@pytest.fixture(autouse=True)
def restore_shared_defaults():
    """Put the process-wide defaults back, whatever the test did to them.

    Without this, a run against the unfixed code leaves the mutated list in
    ``default_settings`` for every test that comes after it in the session.
    """
    saved = {k: list(default_settings[k]) for k in MUTABLE_DEFAULTS}
    yield
    for k, v in saved.items():
        default_settings[k][:] = v
        Series.qsettings_defaults[k][:] = v


def _series_with_empty_store():
    """A Series with no internal options and its own empty settings store.

    Built with ``__new__``: the global-scope path in ``getOption`` reads only
    ``self.options`` and the injected store, so ``__init__`` (which opens files)
    is not needed and would only add a filesystem dependency.
    """
    series = Series.__new__(Series)
    series.options = {}
    series.setSettingsStore(DictSettingsStore())
    return series


def test_two_series_with_empty_stores_cannot_see_each_others_recents():
    """The bug as reported. One series mutates the list it got from the
    fall-through; a second series with a separate empty store must not see it."""
    first = _series_with_empty_store()
    second = _series_with_empty_store()

    recents = first.getOption("recently_opened_series")
    assert recents == []

    # exactly what MainWindow.addToRecentSeries does to the returned list
    recents.insert(0, "/nonexistent/leaked.jser")

    assert second.getOption("recently_opened_series") == [], (
        "a mutation through one Series' miss-path return reached a second "
        "Series with its own empty store: getOption returned the shared "
        "default list by reference"
    )


def test_miss_path_return_is_not_the_shared_default_object():
    """Identity check, for every mutable default, independent of any caller."""
    series = _series_with_empty_store()

    for key in MUTABLE_DEFAULTS:
        returned = series.getOption(key)
        assert returned is not default_settings[key], (
            f"getOption({key!r}) returned the object stored in default_settings"
        )
        assert returned is not Series.qsettings_defaults[key], (
            f"getOption({key!r}) returned the object stored in "
            f"Series.qsettings_defaults"
        )
        assert returned == default_settings[key], (
            f"getOption({key!r}) copy does not equal the default it came from"
        )


def test_get_default_return_is_not_the_shared_default_object():
    """``get_default=True`` reads the same dicts and had the same defect."""
    series = _series_with_empty_store()

    for key in MUTABLE_DEFAULTS:
        returned = series.getOption(key, True)
        assert returned is not default_settings[key], (
            f"getOption({key!r}, get_default=True) returned the shared default"
        )


def test_miss_path_still_writes_the_default_into_the_store():
    """The copy must not change what the fall-through stores: a miss still
    seeds the series' own store with the default, and the next read comes back
    equal."""
    series = _series_with_empty_store()

    assert series.getOption("grid") == default_settings["grid"]
    assert series._settingsStore().contains(None, "grid")
    assert series.getOption("grid") == default_settings["grid"]


def test_no_unlisted_mutable_defaults():
    """Guard: if someone adds a mutable default, this file has to know about it,
    because the copy above is shallow and a nested default would need more."""
    found = sorted(
        k for k, v in default_settings.items() if isinstance(v, (list, dict))
    )
    assert found == sorted(MUTABLE_DEFAULTS), (
        f"the set of mutable entries in default_settings changed: {found}"
    )
    for key in found:
        assert not any(
            isinstance(item, (list, dict, set)) for item in default_settings[key]
        ), (
            f"default_settings[{key!r}] is nested, so the shallow copy in "
            f"Series._fromDefaults is no longer sufficient"
        )
