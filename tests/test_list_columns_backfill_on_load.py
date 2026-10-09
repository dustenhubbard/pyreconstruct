"""A series saved by an older build gets the new list columns when it opens.

The bug: the five ``*_columns`` options gained a default only when the matching
list first opened, because the merge lived in ``DataTable.__init__``. Before
that, Options > Lists read the stored value and did not offer a column added
since the file was written (``3D`` in the Object List, new after 1.23.0), and
OK wrote the list back without it. The merge now runs in ``Series.updateJSON``,
so every reader sees the same list from the moment the series opens.

The settings store is a ``DictSettingsStore`` throughout; these options live in
the series file, but the dialog reads other options from the store.
"""
import json
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.series import Series

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"

COLUMN_OPTIONS = [
    "object_columns",
    "trace_columns",
    "section_columns",
    "ztrace_columns",
    "flag_columns",
]

#: `object_columns` exactly as v1.23.0 wrote it: every default but "3D".
OBJECT_COLUMNS_1_23_0 = [
    ["Range", True],
    ["Count", False],
    ["Flat area", False],
    ["Volume", False],
    ["Radius", False],
    ["Host", True],
    ["Superhosts", False],
    ["Groups", True],
    ["Trace tags", False],
    ["Locked", True],
    ["Last user", True],
    ["Curate", False],
    ["Alignment", False],
    ["Comment", True],
    ["Configuration", False],
]


def _defaults(option_name):
    return [list(pair) for pair in Series.getEmptyDict()["options"][option_name]]


def _older(option_name):
    """A stored value an older build could have written for `option_name`.

    The last default is missing, the rest are reversed, and every shown/hidden
    choice is flipped, so a merge that rebuilds from the defaults, sorts, or
    resets a choice shows up.
    """
    stored = [[name, not shown] for name, shown in _defaults(option_name)[:-1]]
    return stored[::-1]


def _jser(tmp_path, options):
    """A copy of the fixture whose series carries `options`."""
    data = json.loads(FIXTURE.read_text())
    data["series"]["options"] = options
    destination = tmp_path / "older.jser"
    destination.write_text(json.dumps(data))
    return destination


def _open(jser_fp):
    series = Series.openJser(str(jser_fp), progress=NullProgressReporter)
    series.setSettingsStore(DictSettingsStore())
    series.setProgressReporter(NullProgressReporter)
    return series


def _names(columns):
    return [name for name, _ in columns]


# ---------------------------------------------------------------------------
# updateJSON, the load boundary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("option_name", COLUMN_OPTIONS)
def test_load_appends_the_missing_default_and_keeps_the_rest(option_name):
    stored = _older(option_name)
    series_data = {"options": {option_name: [list(p) for p in stored]}}
    Series.updateJSON(series_data)

    missing_name, missing_shown = _defaults(option_name)[-1]
    merged = [list(p) for p in series_data["options"][option_name]]
    assert merged == stored + [[missing_name, missing_shown]]


@pytest.mark.parametrize("option_name", COLUMN_OPTIONS)
def test_repeat_loads_add_nothing(option_name):
    series_data = {"options": {option_name: _older(option_name)}}
    Series.updateJSON(series_data)
    once = [list(p) for p in series_data["options"][option_name]]
    Series.updateJSON(series_data)
    twice = [list(p) for p in series_data["options"][option_name]]
    assert twice == once
    assert len(set(_names(twice))) == len(twice)


def test_a_hidden_3d_column_stays_hidden():
    stored = [["3D", False]] + OBJECT_COLUMNS_1_23_0
    series_data = {"options": {"object_columns": [list(p) for p in stored]}}
    Series.updateJSON(series_data)
    assert [list(p) for p in series_data["options"]["object_columns"]] == stored


def test_a_user_column_is_kept():
    """`object_columns` also holds the series' own columns; they are not defaults."""
    stored = OBJECT_COLUMNS_1_23_0 + [["My notes", True]]
    series_data = {"options": {"object_columns": [list(p) for p in stored]}}
    Series.updateJSON(series_data)
    merged = [list(p) for p in series_data["options"]["object_columns"]]
    assert merged == stored + [["3D", True]]


def test_a_malformed_value_is_left_for_getOption_to_name():
    """The load does not crash on, or quietly repair, a hand-edited bad value."""
    series_data = {"options": {"object_columns": "Range"}}
    Series.updateJSON(series_data)
    assert series_data["options"]["object_columns"] == "Range"


# ---------------------------------------------------------------------------
# a real open, and a save and reopen
# ---------------------------------------------------------------------------

def test_open_save_reopen_keeps_one_of_each(tmp_path):
    jser_fp = _jser(tmp_path, {name: _older(name) for name in COLUMN_OPTIONS})

    series = _open(jser_fp)
    try:
        first = {name: series.getOption(name) for name in COLUMN_OPTIONS}
        series.saveJser()
    finally:
        series.close()

    series = _open(jser_fp)
    try:
        for name in COLUMN_OPTIONS:
            again = series.getOption(name)
            assert [list(p) for p in again] == [list(p) for p in first[name]]
            assert _names(again) == _names(_older(name)) + [_defaults(name)[-1][0]]
    finally:
        series.close()


# ---------------------------------------------------------------------------
# Options > Lists, before any list has opened
# ---------------------------------------------------------------------------

def _offered(dialog, option_name):
    """The (label, checked) pairs a Lists page shows, read off its check boxes."""
    from PySide6.QtWidgets import QCheckBox

    page = dialog.all_widgets[option_name]
    return [(box.text(), box.isChecked()) for box in page.findChildren(QCheckBox)]


@pytest.mark.gui
@pytest.mark.parametrize("stored_3d, expected_3d", [(None, True), (False, False)])
def test_options_lists_offers_3d_before_the_object_list_opens(
    qapp, tmp_path, stored_3d, expected_3d
):
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    stored = [list(p) for p in OBJECT_COLUMNS_1_23_0]
    if stored_3d is not None:
        stored.insert(3, ["3D", stored_3d])
    series = _open(_jser(tmp_path, {"object_columns": stored}))
    try:
        dialog = AllOptionsDialog(None, series)
        offered = _offered(dialog, "object_columns")
        assert dict(offered)["3D"] is expected_3d
        expected = [tuple(p) for p in stored]
        if stored_3d is None:
            expected.append(("3D", True))
        assert offered == expected

        # OK keeps the column: it is no longer written back without it
        assert dialog.accept() is True
        assert ("3D", expected_3d) in [tuple(p) for p in series.getOption("object_columns")]
        dialog.deleteLater()
    finally:
        series.close()
