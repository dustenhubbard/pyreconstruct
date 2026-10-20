"""Dev builds leave repeated default rows off the mouse palette (fork #1004).

An old legacy import (fork #600) gave some palettes two extra rows of the ten
standard buttons, so a palette of 20 lab traces showed 4 rows. Until the
palette editor can remove them, a Dev build shows such a palette as 2 rows.
Only the mouse palette changes: the series keeps every button, and a save
writes the palette back as it was.

"Exact copy" compares the 9 fields `Trace.getList` holds (name, x, y, color,
closed, negative, hidden, fill mode, tags) and needs the button to have no
object defaults. A row counts when all 10 buttons match, in order, one of the
two standard rows: the 10 a new series gets (`default_traces`) or the 10 a
legacy import adds (the `blank_series` placeholder palette).
"""
import json
import shutil
from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest

from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.constants.traces import default_traces
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS
from PyReconstruct.modules.gui.palette import mouse_palette
from PyReconstruct.modules.gui.palette.default_rows import (
    isDefaultRow, legacyDefaultRow, shownButtonCount,
)


def _custom(n, start=0):
    """`n` lab-style buttons, none of them a default."""
    traces = []
    for i in range(start, start + n):
        t = Trace(f"d{i:02d}_lab", [10 + i, 20, 30])
        t.points = [(-1, -1), (1, -1), (0, 1)]
        traces.append(t)
    return traces


def _new_row():
    return [Trace.fromList(deepcopy(l)) for l in default_traces]


def _legacy_row():
    return legacyDefaultRow()


def _roundtrip(traces):
    """The traces as a save and reopen leave them: getList rows, read back."""
    rows = json.loads(json.dumps([t.getList() for t in traces]))
    return [Trace.fromList(r) for r in rows]


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------

def test_the_legacy_row_is_what_an_import_adds():
    names = [t.name for t in _legacy_row()]
    assert names == [
        "a$+", "b$+", "pink$+", "X$+", "yellow$+",
        "blue$+", "magenta$+", "red$+", "green$+", "cyan$+",
    ]


def test_dw09_shape_shows_20():
    # 20 lab traces, then two copies of the legacy row, as saved and reopened
    traces = _roundtrip(_custom(20) + _legacy_row() + _legacy_row())
    assert len(traces) == 40
    assert shownButtonCount(traces) == 20


def test_a_new_series_palette_shows_all_20():
    traces = Series.getDefaultPaletteTraces()
    assert len(traces) == 20
    assert shownButtonCount(traces) == 20


@pytest.mark.parametrize("rows", [3, 4])
def test_all_default_palettes_trim_to_20(rows):
    traces = [t for _ in range(rows) for t in _new_row()]
    assert shownButtonCount(traces) == 20
    legacy = [t for _ in range(rows) for t in _legacy_row()]
    assert shownButtonCount(_roundtrip(legacy)) == 20


def test_a_custom_last_row_hides_nothing():
    traces = _custom(20) + _legacy_row() + _custom(10, start=40)
    assert shownButtonCount(traces) == 40


def test_a_custom_button_inside_a_default_row_keeps_that_row():
    last = _legacy_row()
    last[4] = _custom(1, start=90)[0]
    traces = _custom(20) + _legacy_row() + last
    assert shownButtonCount(traces) == 40


def test_the_trim_stops_at_the_first_row_that_is_not_defaults():
    # row 2 has one custom button, row 3 is all defaults: only row 3 goes
    mixed = _legacy_row()
    mixed[0] = _custom(1, start=70)[0]
    traces = _custom(20) + mixed + _legacy_row()
    assert shownButtonCount(traces) == 30


def test_a_part_row_at_the_end_hides_nothing():
    traces = _custom(20) + _legacy_row() + _legacy_row()[:5]
    assert shownButtonCount(traces) == 35


def test_a_part_row_before_default_rows_hides_nothing():
    # 45 buttons: the last 10 are a standard row, but the rows are not whole
    traces = _custom(25) + _legacy_row() + _legacy_row()
    assert shownButtonCount(traces) == 45


@pytest.mark.parametrize("field, value", [
    ("name", "a$+2"),
    ("color", [1, 2, 3]),
    ("closed", False),
    ("negative", True),
    ("hidden", True),
    ("fill_mode", ("none", "none")),
    ("tags", {"x"}),
])
def test_each_getlist_field_takes_part(field, value):
    row = _legacy_row()
    setattr(row[0], field, value)
    assert not isDefaultRow(row)


def test_a_changed_point_is_custom():
    row = _new_row()
    row[3].points = [(x * 2, y) for x, y in row[3].points]
    assert not isDefaultRow(row)


def test_object_defaults_make_a_button_custom():
    row = _new_row()
    row[9].obj_defaults = {"groups": ["spines"]}
    assert not isDefaultRow(row)


def test_a_row_out_of_order_is_custom():
    row = _new_row()
    row[0], row[1] = row[1], row[0]
    assert not isDefaultRow(row)


def test_a_row_mixing_the_two_standards_is_custom():
    row = _new_row()[:5] + _legacy_row()[5:]
    assert not isDefaultRow(row)


# ---------------------------------------------------------------------------
# the mouse palette
# ---------------------------------------------------------------------------

def _dw09_palette():
    return _custom(20) + _legacy_row() + _legacy_row()


def _open_with(mw, traces, index=0, name="palette1"):
    """Put `traces` on the series as its current palette and rebuild the
    mouse palette, the way opening that series does."""
    s = mw.series
    s.palette_traces = {name: traces}
    s.palette_index = [name, index]
    mw.mouse_palette.reset()
    mw.changeTracingTrace(mw.mouse_palette.selectedTrace())


@pytest.mark.gui
def test_dev_build_shows_two_rows_of_a_dw09_palette(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=10)
    buttons = mw.mouse_palette.palette_buttons
    assert len(buttons) == 20
    assert [b.trace.name for b in buttons] == [t.name for t in _custom(20)]
    assert buttons[10].isChecked()
    # the series keeps every button
    assert len(mw.series.palette_traces["palette1"]) == 40


@pytest.mark.gui
def test_dev_build_shows_a_new_series_palette_whole(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, Series.getDefaultPaletteTraces())
    assert len(mw.mouse_palette.palette_buttons) == 20


@pytest.mark.gui
def test_stable_build_shows_all_40(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: False)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    buttons = mw.mouse_palette.palette_buttons
    assert len(buttons) == 40
    assert buttons[35].isChecked()
    assert mw.field.tracing_trace.name == "blue$+"


@pytest.mark.gui
def test_an_index_on_a_hidden_button_shows_the_last_one(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    mp = mw.mouse_palette
    assert len(mp.palette_buttons) == 20
    assert mp.palette_buttons[19].isChecked()
    assert sum(b.isChecked() for b in mp.palette_buttons) == 1
    assert mp.label.text() == "d19_lab"
    assert mw.field.tracing_trace.name == "d19_lab"
    # nothing is written to the series
    assert mw.series.palette_index == ["palette1", 35]


@pytest.mark.gui
def test_clicking_a_button_then_moves_the_index(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    mw.mouse_palette.activatePaletteButton(4)
    assert mw.series.palette_index == ["palette1", 4]
    assert mw.field.tracing_trace.name == "d04_lab"


@pytest.mark.gui
def test_editing_the_shown_button_changes_that_button(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    mp = mw.mouse_palette
    t = mp.palette_buttons[19].trace.copy()
    t.name = "d19_{01}"
    mp.modifyPaletteButton(19, t)
    mp.incrementPalette(True)  # active button only
    assert mw.series.palette_traces["palette1"][19].name == "d19_{02}"
    assert mw.series.palette_traces["palette1"][35].name == "blue$+"


def _cut_a_trace(mw, qapp):
    """Draw a square and pick it up with the scissors."""
    field = mw.field
    wx, wy, ww, wh = mw.series.window
    side = min(ww, wh) * 0.2
    x0, y0 = wx + ww * 0.3, wy + wh * 0.3
    square = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    field.newTrace(square, Trace("cut_me", (0, 255, 0), True),
                   points_as_pix=False, reduce_points=False)
    trace = [t for t in field.section.tracesAsList() if t.name == "cut_me"][0]
    mw.mouse_palette.activateModeButton("Scissors")
    qapp.processEvents()
    assert field.mouse_mode == SCISSORS
    x, y = [int(round(v)) for v in field.section_layer.traceToPix(trace)[0]]
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    qapp.processEvents()
    assert field.is_scissoring


@pytest.mark.gui
@pytest.mark.parametrize("ending", ["finish", "cancel"])
def test_a_scissors_cut_ends_on_the_shown_button(main_window, qapp, monkeypatch, ending):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    _cut_a_trace(mw, qapp)
    if ending == "finish":
        mw.field.lineRelease(override=True)
    else:
        mw.field.cancelScissors()
    qapp.processEvents()
    assert not mw.field.is_scissoring
    assert mw.field.tracing_trace.name == "d19_lab"
    assert mw.series.palette_index == ["palette1", 35]


@pytest.mark.gui
def test_syncing_defaults_reads_the_shown_button(main_window, monkeypatch):
    # a custom column edit or a series undo syncs the trace being drawn
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    traces = _dw09_palette()
    defaults = {"groups": ["spines"], "user_columns": {"Stage": "draft"}}
    traces[19].obj_defaults = deepcopy(defaults)
    _open_with(mw, traces, index=35)
    assert mw.field.tracing_trace.obj_defaults == defaults
    mw.field.syncTracingDefaults()
    assert mw.field.tracing_trace.name == "d19_lab"
    assert mw.field.tracing_trace.obj_defaults == defaults


class _OkUnchanged:
    """The palette editor, closed with OK and nothing changed."""
    def __init__(self, *args):
        pass

    def exec(self):
        return {}, True


@pytest.mark.gui
def test_ok_in_the_palette_editor_keeps_a_hidden_index(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    monkeypatch.setattr(mouse_palette, "TracePaletteDialog", _OkUnchanged)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    mp = mw.mouse_palette
    mp.modifyAllPaletteButtons()
    assert mw.series.palette_index == ["palette1", 35]
    assert mp.palette_buttons[19].isChecked()
    assert sum(b.isChecked() for b in mp.palette_buttons) == 1
    assert mp.label.text() == "d19_lab"
    assert mw.field.tracing_trace.name == "d19_lab"


@pytest.mark.gui
def test_ok_in_the_palette_editor_keeps_a_shown_index(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    monkeypatch.setattr(mouse_palette, "TracePaletteDialog", _OkUnchanged)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=7)
    mw.mouse_palette.modifyAllPaletteButtons()
    assert mw.series.palette_index == ["palette1", 7]
    assert mw.mouse_palette.palette_buttons[7].isChecked()
    assert mw.field.tracing_trace.name == "d07_lab"


def _shortcut(mw, keys):
    seq = QKeySequence(keys)
    matches = [a for a in mw.findChildren(QAction) if a.shortcut() == seq]
    assert len(matches) == 1, keys
    return matches[0]


@pytest.mark.gui
def test_palette_shortcuts_reach_the_shown_buttons(main_window, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw = main_window
    _open_with(mw, _dw09_palette(), index=35)
    _shortcut(mw, "Shift+0").trigger()
    assert mw.series.palette_index == ["palette1", 19]
    assert mw.mouse_palette.palette_buttons[19].isChecked()
    _shortcut(mw, "1").trigger()
    assert mw.series.palette_index == ["palette1", 0]
    assert mw.field.tracing_trace.name == "d00_lab"


def _saved_series(path):
    with open(path) as f:
        return json.load(f)["series"]


@pytest.mark.gui
def test_a_save_writes_the_whole_palette_back(
    main_window, main_window_dialogs, tmp_path, monkeypatch
):
    mw = main_window
    main_window_dialogs.save_response = "yes"

    # the palette as an older build writes it
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: False)
    _open_with(mw, _dw09_palette(), index=35)
    mw.series.modified = True
    mw.saveToJser()
    before = _saved_series(mw.series.jser_fp)
    first = tmp_path / "again" / "copy.jser"
    first.parent.mkdir()
    shutil.copy(mw.series.jser_fp, first)

    # opened and saved again in a Dev build, with nothing changed
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mw.openSeries(jser_fp=str(first), query_prev=False)
    assert len(mw.mouse_palette.palette_buttons) == 20
    assert mw.mouse_palette.palette_buttons[19].isChecked()
    assert mw.field.tracing_trace.name == "d19_lab"
    mw.series.modified = True
    mw.saveToJser()
    after = _saved_series(mw.series.jser_fp)

    assert len(after["palette_traces"]["palette1"]) == 40
    assert json.dumps(after["palette_traces"]) == json.dumps(before["palette_traces"])
    assert after.get("palette_obj_defaults") == before.get("palette_obj_defaults")
    assert after["palette_index"] == before["palette_index"] == ["palette1", 35]
