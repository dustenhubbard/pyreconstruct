"""``getOption`` for internal-options list and dict values returns an isolated
copy, so callers that mutate the result cannot corrupt the stored setting.

The bug: ``getOption`` returned ``self.options[key]`` by reference for every
option stored in the series-internal ``options`` dict. Six of those options
are mutable containers (five ``_columns`` lists and the ``autoseg`` dict).
A caller that did ``cols = series.getOption("object_columns"); cols.append(x)``
silently modified the stored list, so the next ``getOption`` call returned
the already-mutated value. The fix: return ``copy(raw)`` when the stored value
is a list or dict.

No Qt required: the internal-options path in ``getOption`` touches neither the
settings store nor any PySide6 symbol.
"""
import pytest


def _minimal_series():
    """A minimal Series with populated internal options and a DictSettingsStore.

    Constructs with ``__new__`` and sets only the attributes that the
    internal-options path in ``getOption`` touches: ``self.options``,
    ``self.filepath`` (for ``isWelcomeSeries``), and the settings store.
    Does not call ``Series.__init__`` and therefore does not open any file.
    """
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    s = Series.__new__(Series)
    # Populate options with the exact structure getEmptyDict() produces for the
    # _columns keys and autoseg. Using literal values avoids pulling in
    # getDefaultPaletteTraces() (which requires Trace and default_traces).
    s.options = {
        "object_columns": [
            ("Range", True), ("Count", False), ("Flat area", False),
            ("Volume", False), ("Radius", False), ("Host", True),
            ("Superhosts", False), ("Groups", True), ("Trace tags", False),
            ("Locked", True), ("Last user", True), ("Curate", False),
            ("Alignment", False), ("Comment", True), ("Configuration", False),
        ],
        "trace_columns": [
            ("Index", False), ("Tags", True), ("Hidden", True),
            ("Closed", True), ("Length", True), ("Area", True),
            ("Radius", True), ("Centroid", False), ("Feret", False),
        ],
        "flag_columns": [
            ("Section", True), ("Color", True), ("Flag", True),
            ("Resolved", False), ("Last Comment", True),
        ],
        "section_columns": [
            ("Thickness", True), ("Locked", True), ("Brightness", True),
            ("Contrast", True), ("Image Source", True),
        ],
        "ztrace_columns": [
            ("Start", True), ("End", True), ("Distance", True),
            ("Groups", True), ("Alignment", True),
        ],
        "small_dist": 0.01,
        "med_dist": 0.1,
        "big_dist": 1,
        "autoseg": {},
    }
    s.filepath = "/nonexistent/not-a-welcome.ser"
    s.setSettingsStore(DictSettingsStore())
    return s


# All internal-options keys whose values are lists.
LIST_KEYS = [
    "object_columns",
    "trace_columns",
    "flag_columns",
    "section_columns",
    "ztrace_columns",
]


@pytest.mark.parametrize("key", LIST_KEYS)
def test_getOption_list_append_does_not_corrupt_store(key):
    """Appending to the value returned by ``getOption`` must not change the
    value returned by the next call."""
    series = _minimal_series()

    first = series.getOption(key)
    assert isinstance(first, list)
    original_len = len(first)

    first.append(("__sentinel__", True))

    second = series.getOption(key)
    assert len(second) == original_len, (
        f"getOption({key!r}) returned a live reference: stored list was "
        f"mutated from {original_len} items to {len(second)}"
    )


def test_getOption_dict_setitem_does_not_corrupt_store():
    """Setting a key in the value returned by ``getOption`` must not change
    the value returned by the next call."""
    series = _minimal_series()

    first = series.getOption("autoseg")
    assert isinstance(first, dict)
    assert len(first) == 0

    first["__sentinel__"] = True

    second = series.getOption("autoseg")
    assert "__sentinel__" not in second, (
        "getOption('autoseg') returned a live reference: dict mutation was "
        "visible to the next caller"
    )


def test_getOption_two_callers_hold_independent_lists():
    """Two successive calls to ``getOption`` for the same list key must return
    independent objects so that a mutation through one cannot be seen through
    the other."""
    series = _minimal_series()

    a = series.getOption("object_columns")
    b = series.getOption("object_columns")

    a.append(("__from_a__", True))

    assert not any(name == "__from_a__" for name, _ in b), (
        "two calls to getOption('object_columns') returned the same list object"
    )


@pytest.mark.parametrize("key", ["small_dist", "med_dist", "big_dist"])
def test_getOption_scalar_returned_directly(key):
    """Scalar options in self.options are not wrapped in a copy (scalars are
    immutable and the copy overhead is unnecessary)."""
    series = _minimal_series()
    value = series.getOption(key)
    assert isinstance(value, (int, float))
