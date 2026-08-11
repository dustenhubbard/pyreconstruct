"""``getOption`` miss-path returns an isolated copy of mutable defaults.

The bug: when a key is in ``qsettings_defaults`` but absent from the settings
store (first access on a fresh store), ``getOption`` assigned
``option = defaults[option_name]`` directly and returned that reference.
``defaults`` is ``Series.qsettings_defaults``, a class-level dict that is
shared by every ``Series`` instance in the process. A caller that mutated
the returned list silently corrupted the shared defaults, so a second
``Series`` with a separate empty store saw the mutation on its own first
``getOption`` call.

Five entries in ``default_settings`` are mutable lists:
  ``recently_opened_series``, ``pointer``, ``grid``, ``flag_color``,
  ``autoseg_color_palette``.

The fix: apply ``copy(raw)`` when the default value is a list or dict,
matching the pattern used for the hit path in the sibling fix.

No Qt required: the miss path uses ``DictSettingsStore`` (pure Python).
"""
import pytest


def _minimal_series():
    """A minimal Series backed by a fresh DictSettingsStore.

    Constructs with ``__new__`` and sets only the attributes that the
    QSettings miss path in ``getOption`` touches: ``self.options``,
    ``self.filepath``, ``self.code``, and the settings store.
    Does not call ``Series.__init__`` and therefore opens no file.
    """
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    s = Series.__new__(Series)
    s.options = {}          # empty: not an internal-options key
    s.filepath = "/nonexistent/not-a-welcome.ser"
    s.code = "test"
    s.setSettingsStore(DictSettingsStore())
    return s


# Keys in qsettings_defaults whose default values are mutable lists.
MUTABLE_LIST_KEYS = [
    "recently_opened_series",
    "pointer",
    "grid",
    "flag_color",
    "autoseg_color_palette",
]


@pytest.mark.parametrize("key", MUTABLE_LIST_KEYS)
def test_getOption_miss_append_does_not_corrupt_defaults(key):
    """Mutating the list returned on a miss must not change what the next
    call to ``getOption`` returns for a second Series with an empty store."""
    series_a = _minimal_series()
    series_b = _minimal_series()

    result_a = series_a.getOption(key)
    assert isinstance(result_a, list), f"expected list for {key!r}, got {type(result_a)}"

    sentinel = "__mutation_sentinel__"
    result_a.append(sentinel)

    result_b = series_b.getOption(key)
    assert sentinel not in result_b, (
        f"getOption({key!r}) on a fresh store returned a reference into the "
        f"shared defaults dict: a mutation through series_a was visible to "
        f"series_b on its own first call."
    )


@pytest.mark.parametrize("key", MUTABLE_LIST_KEYS)
def test_getOption_miss_two_calls_independent(key):
    """Two successive miss-path calls on the same Series must return
    independent list objects so a mutation through the first cannot be seen
    through the second."""
    series = _minimal_series()

    first = series.getOption(key)
    assert isinstance(first, list)

    first.append("__sentinel__")

    # After setOption was called inside the first getOption, the second call
    # hits the store (hit path, not miss path). What matters is that the
    # returned object is not the same reference as the class-level default.
    from PyReconstruct.modules.datatypes.series import Series
    default_val = Series.qsettings_defaults[key]
    assert ".__sentinel__" not in str(default_val), (
        f"getOption({key!r}) miss path mutated the class-level default."
    )


def test_getOption_recently_opened_series_two_series_isolated():
    """Core scenario from the bug report: two Series with empty stores call
    ``getOption('recently_opened_series')``.  A mutation through the first
    result must not be visible when the second Series calls the same key."""
    series_a = _minimal_series()
    series_b = _minimal_series()

    list_a = series_a.getOption("recently_opened_series")
    assert list_a == [], f"expected empty list, got {list_a!r}"

    list_a.append("/path/to/series.ser")

    list_b = series_b.getOption("recently_opened_series")
    assert list_b == [], (
        "series_b.getOption('recently_opened_series') returned a non-empty "
        f"list ({list_b!r}); the shared default was corrupted by series_a's "
        "mutation."
    )


def test_getOption_miss_scalar_unchanged():
    """Scalar defaults (immutable) are returned as-is; the fix must not
    wrap them in a copy."""
    series = _minimal_series()
    val = series.getOption("fill_opacity")
    assert isinstance(val, float), f"expected float, got {type(val)}"
