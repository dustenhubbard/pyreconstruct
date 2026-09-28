"""A palette item can hand a new object its groups and custom columns (fork #419).

Issue #419 asks for the trace palette to fill in object list columns at the
moment an object is created, so nobody has to go back to the object list
afterwards. This covers the first step: a palette item carries object defaults,
{"groups": [...], "user_columns": {column: value}}. The palette dialog edits
them, the series saves them beside the palette rows, and the first trace of a
NEW object applies them. An object that already exists is left alone, and
section traces never carry them.
"""
import os
import shutil

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from PyReconstruct.modules.datatypes.trace import Trace, copyObjDefaults

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)


def _open(tmp_path, name="shapes1.jser"):
    src = os.path.join(FIXTURE_DIR, name)
    if not os.path.exists(src):
        pytest.skip(f"fixture {name} not found")
    fp = str(tmp_path / name)
    shutil.copyfile(src, fp)
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    return Series.openJser(fp)


# ---------------------------------------------------------------------------
# the field on Trace
# ---------------------------------------------------------------------------

def test_a_plain_trace_has_no_defaults_and_its_rows_are_unchanged():
    t = Trace("a", (1, 2, 3), True)
    assert t.obj_defaults is None
    assert len(t.getList()) == 9
    assert len(t.getList(include_name=False)) == 8


def test_copy_carries_its_own_defaults():
    t = Trace("a", (1, 2, 3), True)
    t.obj_defaults = {"groups": ["axons"], "user_columns": {"Reviewer": "KH"}}
    c = t.copy()
    assert c.obj_defaults == t.obj_defaults
    c.obj_defaults["groups"].append("other")
    assert t.obj_defaults["groups"] == ["axons"], "the copy shares no container"


@pytest.mark.parametrize("value", [None, {}, {"groups": [], "user_columns": {}}, {"groups": None}])
def test_empty_defaults_collapse_to_none(value):
    assert copyObjDefaults(value) is None


def test_copy_obj_defaults_keeps_only_what_is_set():
    assert copyObjDefaults({"groups": ["g"], "user_columns": {}}) == {"groups": ["g"]}
    assert copyObjDefaults({"user_columns": {"c": "v"}}) == {"user_columns": {"c": "v"}}


# ---------------------------------------------------------------------------
# save and load
# ---------------------------------------------------------------------------

def test_series_without_defaults_writes_no_new_key(tmp_path):
    s = _open(tmp_path)
    try:
        assert "palette_obj_defaults" not in s.getDict()
    finally:
        s.close()


def test_defaults_round_trip_beside_the_palette_rows(tmp_path):
    s = _open(tmp_path)
    try:
        pal_name, idx = s.palette_index
        item = s.palette_traces[pal_name][idx]
        item.obj_defaults = {"groups": ["axons", "checked"], "user_columns": {"Reviewer": "KH"}}
        d = s.getDict()
        from PyReconstruct.modules.constants.jser_format import SERIES_KEYS, canon_keys
        assert list(canon_keys(d, SERIES_KEYS))[-1] == "palette_obj_defaults", (
            "appended after every known key, so earlier keys keep their bytes"
        )
        per_item = d["palette_obj_defaults"][pal_name]
        assert len(per_item) == len(s.palette_traces[pal_name])
        assert per_item[idx] == item.obj_defaults
        assert all(v is None for i, v in enumerate(per_item) if i != idx)
        # the trace rows themselves did not change shape
        assert all(len(row) == 9 for row in d["palette_traces"][pal_name])

        s.save()
        s.saveJser()
        fp = s.jser_fp
    finally:
        s.close()

    from PyReconstruct.modules.datatypes.series import Series
    QApplication.instance() or QApplication(["test"])
    s2 = Series.openJser(fp)
    try:
        again = s2.palette_traces[pal_name][idx]
        assert again.obj_defaults == {"groups": ["axons", "checked"], "user_columns": {"Reviewer": "KH"}}
        others = [t for i, t in enumerate(s2.palette_traces[pal_name]) if i != idx]
        assert all(t.obj_defaults is None for t in others)
    finally:
        s2.close()


# ---------------------------------------------------------------------------
# the palette dialog
# ---------------------------------------------------------------------------

def _accept(monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)


def test_palette_dialog_shows_groups_and_column_rows(tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        s.object_groups.add("axons", "star")
        s.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
        s.addUserCol("Stage", ["draft", "final"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        item.obj_defaults = {"groups": ["axons"], "user_columns": {"Stage": "draft"}}

        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        assert dlg.groups_input.getEntries() == ["axons"]
        # one row, seeded from the item's defaults
        assert dlg.columns_input.getValues() == {"Stage": "draft"}
        _, col, val = dlg.columns_input.rows[0]
        assert [col.itemText(i) for i in range(col.count())] == ["", "Reviewer", "Stage"]
        assert [val.itemText(i) for i in range(val.count())] == ["", "draft", "final"]
        # picking another column refills the values
        col.setCurrentText("Reviewer")
        assert [val.itemText(i) for i in range(val.count())] == ["", "KH", "DH"]
        dlg.close()

        plain = TraceDialog(None, [item], is_palette=True)
        assert plain.groups_input is None and plain.columns_input is None
        plain.close()
    finally:
        s.close()


def test_column_rows_add_and_remove_like_groups(tmp_path):
    from PyReconstruct.modules.gui.dialog.helper import ColumnValueInput
    from PySide6.QtWidgets import QWidget, QVBoxLayout

    QApplication.instance() or QApplication(["test"])
    host = QWidget()
    host.setLayout(QVBoxLayout())
    w = ColumnValueInput(host, {"A": ["1", "2"], "B": ["x"]})
    host.layout().addWidget(w)
    assert len(w.rows) == 1 and w.getValues() == {}
    w.add()
    w.rows[0][1].setCurrentText("A"); w.rows[0][2].setCurrentText("2")
    w.rows[1][1].setCurrentText("B"); w.rows[1][2].setCurrentText("x")
    assert w.getValues() == {"A": "2", "B": "x"}
    w.remove()                      # the last row by default
    assert w.getValues() == {"A": "2"} and len(w.rows) == 1
    w.remove()                      # the last row clears instead of vanishing
    assert len(w.rows) == 1 and w.getValues() == {}


def test_palette_dialog_returns_the_defaults(tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        s.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        _, col, val = dlg.columns_input.rows[0]
        col.setCurrentText("Reviewer"); val.setCurrentText("DH")
        _accept(monkeypatch)
        t, confirmed = dlg.exec()
        assert confirmed
        assert t.obj_defaults == {"user_columns": {"Reviewer": "DH"}}

        dlg2 = TraceDialog(None, [item], is_palette=True, series=s)
        t2, _ = dlg2.exec()
        assert t2.obj_defaults is None
    finally:
        s.close()


def test_headings_carry_tooltips(tmp_path):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    from PySide6.QtWidgets import QLabel

    s = _open(tmp_path)
    try:
        s.addUserCol("Reviewer", ["KH"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        tips = {w.text(): w.toolTip() for w in dlg.findChildren(QLabel)}
        dlg.close()
        assert tips["Trace Tags:"].startswith("Labels stored on each trace")
        assert tips["Object Groups:"].startswith("Groups a new object joins")
        assert tips["Custom Columns:"].startswith("Values for the object list's custom columns")
    finally:
        s.close()


def test_palette_button_stores_what_the_dialog_returns(tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.palette import buttons as B

    s = _open(tmp_path)
    try:
        s.addUserCol("Reviewer", ["KH"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]

        class Manager:
            series = s
            def paletteButtonChanged(self, b): self.changed = b

        answer = Trace("item", (1, 2, 3), True)
        answer.points = list(item.points)
        answer.tags = set()
        answer.fill_mode = ("none", "none")
        answer.obj_defaults = {"groups": ["axons"]}

        class FakeDialog:
            tag_choices = {}
            def __init__(self, *a, **k):
                assert k.get("series") is s, "the button must hand the series to the dialog"
            def exec(self):
                return answer, True

        monkeypatch.setattr(B, "TraceDialog", FakeDialog)
        btn = B.PaletteButton.__new__(B.PaletteButton)
        btn.manager = Manager()
        btn.trace = item
        monkeypatch.setattr(btn, "setTrace", lambda t: None)
        B.PaletteButton.openDialog(btn)
        assert btn.trace.obj_defaults == {"groups": ["axons"]}
    finally:
        s.close()


# ---------------------------------------------------------------------------
# drawing the first trace of a new object
# ---------------------------------------------------------------------------

pytestmark_gui = pytest.mark.gui


def _square(series, offset=0.3):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


@pytest.mark.gui
def test_first_trace_of_a_new_object_gets_the_defaults(main_window):
    field = main_window.field
    series = main_window.series
    series.addUserCol("Reviewer", ["KH", "DH"], log_event=False)

    item = Trace("brand_new_obj", (0, 255, 0), True)
    item.obj_defaults = {"groups": ["axons"], "user_columns": {"Reviewer": "KH"}}
    assert "axons" not in series.object_groups.getGroupList()

    field.setTracingTrace(item)
    assert field.tracing_trace.obj_defaults == item.obj_defaults, "the tracing copy carries them"
    field.newTrace(_square(series), field.tracing_trace, points_as_pix=False,
                   reduce_points=False, log_event=False)

    assert "axons" in series.object_groups.getObjectGroups("brand_new_obj")
    assert series.groups_visibility.get("axons") is True
    assert series.getAttr("brand_new_obj", "user_columns") == {"Reviewer": "KH"}
    drawn = field.section.contours["brand_new_obj"][0]
    assert drawn.obj_defaults is None, "section traces never carry the defaults"


@pytest.mark.gui
def test_an_existing_object_is_left_alone(main_window):
    field = main_window.field
    series = main_window.series
    series.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
    existing = sorted(series.data["objects"])[0]
    series.setAttr(existing, "user_columns", {"Reviewer": "DH"})
    groups_before = set(series.object_groups.getObjectGroups(existing))

    item = Trace(existing, (0, 255, 0), True)
    item.obj_defaults = {"groups": ["axons"], "user_columns": {"Reviewer": "KH"}}
    field.setTracingTrace(item)
    field.newTrace(_square(series, 0.5), field.tracing_trace, points_as_pix=False,
                   reduce_points=False, log_event=False)

    assert series.getAttr(existing, "user_columns") == {"Reviewer": "DH"}
    assert set(series.object_groups.getObjectGroups(existing)) == groups_before


@pytest.mark.gui
def test_second_trace_of_the_same_new_object_does_not_reapply(main_window):
    field = main_window.field
    series = main_window.series
    item = Trace("brand_new_obj2", (0, 255, 0), True)
    item.obj_defaults = {"groups": ["axons"]}
    field.setTracingTrace(item)
    field.newTrace(_square(series, 0.2), field.tracing_trace, points_as_pix=False,
                   reduce_points=False, log_event=False)
    series.object_groups.remove("axons", "brand_new_obj2")
    field.newTrace(_square(series, 0.6), field.tracing_trace, points_as_pix=False,
                   reduce_points=False, log_event=False)
    assert "axons" not in series.object_groups.getObjectGroups("brand_new_obj2"), (
        "defaults apply once, when the object is created"
    )


def _row_order(dlg):
    """Top-to-bottom order of the dialog's labeled rows, by label text."""
    from PySide6.QtWidgets import QLabel
    dlg.show()
    QApplication.processEvents()
    labels = [w for w in dlg.findChildren(QLabel) if w.isVisible() and w.text()]
    labels.sort(key=lambda w: w.mapTo(dlg, w.rect().topLeft()).y())
    return [w.text() for w in labels]


def test_palette_dialog_puts_tags_below_radius_and_above_groups(tmp_path):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        s.addUserCol("Reviewer", ["KH"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        order = _row_order(dlg)
        dlg.close()
        i_stamp = order.index("Stamp radius (microns):")
        i_tags = order.index("Trace Tags:")
        i_groups = order.index("Object Groups:")
        i_header = order.index("Custom Columns:")
        assert i_stamp < i_tags < i_groups < i_header, order
    finally:
        s.close()


def test_trace_dialog_puts_tags_below_fill():
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    QApplication.instance() or QApplication(["test"])
    t = Trace("t", (1, 2, 3), True)
    t.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
    dlg = TraceDialog(None, [t])
    order = _row_order(dlg)
    dlg.close()
    assert order.index("Fill:") < order.index("Trace Tags:"), order
    assert "Object Groups:" not in order, "groups belong to palette buttons only"


def test_object_dialog_puts_tags_below_fill_and_above_the_range(tmp_path):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    from PySide6.QtWidgets import QWidget

    s = _open(tmp_path)
    try:
        parent = QWidget()
        parent.series = s
        dlg = TraceDialog(parent, name="obj", tags=set(), is_obj_list=True)
        order = _row_order(dlg)
        dlg.close()
        assert order.index("Fill:") < order.index("Trace Tags:") < order.index("From section"), order
    finally:
        s.close()


def test_no_custom_columns_means_no_custom_columns_header(tmp_path):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        assert not s.user_columns, "fixture premise: no custom columns"
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        order = _row_order(dlg)
        dlg.close()
        assert "Object Groups:" in order
        assert "Custom Columns:" not in order, order
    finally:
        s.close()


def test_edit_all_palettes_keeps_every_items_defaults(tmp_path, monkeypatch):
    """The palette editor rebuilds every palette from its cells on OK. The
    cells hold no defaults, so they must be carried across, including through
    a tab rename."""
    from PyReconstruct.modules.gui.dialog import trace_palette as tp
    from PyReconstruct.modules.gui.dialog.quick_dialog import QuickTabDialog

    s = _open(tmp_path)
    try:
        pal_name, idx = s.palette_index
        s.palette_traces[pal_name][idx].obj_defaults = {"groups": ["axons"]}
        s.palette_traces[pal_name][idx + 1].obj_defaults = {"user_columns": {"C": "v"}}

        dlg = tp.TracePaletteDialog(None, s)
        # rename the tab through editTab's own path, then accept untouched
        monkeypatch.setattr(tp.QInputDialog, "getText", lambda *a, **k: ("renamed", True))

        class RightClick:
            def buttons(self): return tp.Qt.RightButton
            def pos(self): return dlg.tab_widget.tabBar().tabRect(
                dlg.tab_widget.currentIndex()).center()

        monkeypatch.setattr(QuickTabDialog, "mousePressEvent", lambda self, e: None, raising=False)
        dlg.editTab(RightClick())
        assert "renamed" in dlg.inputs and pal_name not in dlg.inputs

        def fake_exec(self):
            response = {"current_tab_text": "renamed"}
            for name, palette in s.palette_traces.items():
                key = "renamed" if name == pal_name else name
                flat = []
                for t in palette:
                    c = t.copy(); c.resize(1)
                    flat += [t.name, t.color, c.points, ", ".join(sorted(t.tags)),
                             t.fill_mode[0], t.fill_mode[1], t.getRadius()]
                response[key] = flat
            return response, True

        monkeypatch.setattr(QuickTabDialog, "exec", fake_exec)
        _, confirmed = dlg.exec()
        assert confirmed
        assert s.palette_traces["renamed"][idx].obj_defaults == {"groups": ["axons"]}
        assert s.palette_traces["renamed"][idx + 1].obj_defaults == {"user_columns": {"C": "v"}}
        others = [t for i, t in enumerate(s.palette_traces["renamed"]) if i not in (idx, idx + 1)]
        assert all(t.obj_defaults is None for t in others)
    finally:
        s.close()


def test_paste_with_shape_keeps_the_buttons_defaults(tmp_path):
    from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette

    class Button:
        def __init__(self, trace): self.trace = trace
        def setTrace(self, t): self.trace = t

    class Palette:
        pass

    s = _open(tmp_path)
    try:
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        item.obj_defaults = {"groups": ["axons"]}
        pal = Palette()
        pal.series = s
        s.palette_index[1] = 0
        pal.palette_buttons = [Button(item)]
        pal.modifyPaletteButton = lambda bpos, t: MousePalette.modifyPaletteButton(pal, bpos, t)
        pal.paletteButtonChanged = lambda b: None

        section_trace = Trace("other", (9, 9, 9), True)
        section_trace.points = [(5, 5), (7, 5), (7, 7), (5, 7)]
        MousePalette.pasteAttributesToButton(pal, section_trace, use_shape=True)
        assert pal.palette_buttons[0].trace.obj_defaults == {"groups": ["axons"]}
    finally:
        s.close()


def test_a_value_that_is_no_longer_an_option_is_not_offered(tmp_path, monkeypatch):
    """One rule with objects: a value that is no longer one of the column's
    options is not shown on the button, and OK does not keep it."""
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        s.addUserCol("Stage", ["final"], log_event=False)     # "draft" removed
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        item.obj_defaults = {"user_columns": {"Stage": "draft"}}
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        _, col, val = dlg.columns_input.rows[0]
        assert [val.itemText(i) for i in range(val.count())] == ["", "final"]
        _accept(monkeypatch)
        t, confirmed = dlg.exec()
        assert confirmed
        assert t.obj_defaults is None
    finally:
        s.close()

def test_a_value_for_a_deleted_column_is_dropped(tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        s.addUserCol("Stage", ["final"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        item.obj_defaults = {"user_columns": {"Gone": "x", "Stage": "final"}}
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        _accept(monkeypatch)
        t, _ = dlg.exec()
        assert t.obj_defaults == {"user_columns": {"Stage": "final"}}
    finally:
        s.close()


# ---------------------------------------------------------------------------
# custom column rename and delete follow the palette buttons
# ---------------------------------------------------------------------------

def _button_with_column(s, col, value):
    pal_name, idx = s.palette_index
    item = s.palette_traces[pal_name][idx]
    item.obj_defaults = {"groups": ["axons"], "user_columns": {col: value}}
    return item


def test_renaming_a_column_renames_it_on_palette_buttons(tmp_path):
    s = _open(tmp_path)
    try:
        s.addUserCol("Stage", ["draft", "final"], log_event=False)
        item = _button_with_column(s, "Stage", "draft")
        s.editUserCol("Stage", "Phase", ["draft", "final"], log_event=False)
        assert item.obj_defaults == {"groups": ["axons"], "user_columns": {"Phase": "draft"}}
    finally:
        s.close()


def test_deleting_a_column_removes_it_from_palette_buttons(tmp_path):
    s = _open(tmp_path)
    try:
        s.addUserCol("Stage", ["draft"], log_event=False)
        item = _button_with_column(s, "Stage", "draft")
        s.removeUserCol("Stage", log_event=False)
        assert item.obj_defaults == {"groups": ["axons"]}
        # a button left with nothing collapses to None
        item.obj_defaults = {"user_columns": {"Other": "x"}}
        s.addUserCol("Other", ["x"], log_event=False)
        s.removeUserCol("Other", log_event=False)
        assert item.obj_defaults is None
    finally:
        s.close()


@pytest.mark.gui
def test_a_rename_reaches_the_trace_being_drawn(main_window):
    """The field draws from a copy of the button, so the rename has to reach
    that copy too, or the next new object gets nothing for the column."""
    field = main_window.field
    series = main_window.series
    series.addUserCol("Stage", ["draft", "final"], log_event=False)
    pal_name, idx = series.palette_index
    button = series.palette_traces[pal_name][idx]
    button.name = "renamed_col_obj"
    button.obj_defaults = {"user_columns": {"Stage": "draft"}}
    main_window.changeTracingTrace(button)

    series.editUserCol("Stage", "Phase", ["draft", "final"], log_event=False)
    field.syncTracingDefaults()
    assert field.tracing_trace.obj_defaults == {"user_columns": {"Phase": "draft"}}

    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.3, wy + wh * 0.3
    field.newTrace([(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)],
                   field.tracing_trace, points_as_pix=False, reduce_points=False, log_event=False)
    assert series.getAttr("renamed_col_obj", "user_columns") == {"Phase": "draft"}


@pytest.mark.gui
def test_a_deleted_column_is_never_applied(main_window):
    """A value saved for a column the series no longer has is skipped."""
    field = main_window.field
    series = main_window.series
    item = Trace("deleted_col_obj", (0, 255, 0), True)
    item.obj_defaults = {"user_columns": {"Gone": "x"}}
    field.setTracingTrace(item)
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.5, wy + wh * 0.5
    field.newTrace([(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)],
                   field.tracing_trace, points_as_pix=False, reduce_points=False, log_event=False)
    assert "Gone" not in (series.getAttr("deleted_col_obj", "user_columns") or {})


def test_removing_an_option_clears_it_from_palette_buttons(tmp_path):
    """One rule: a value that is no longer an option is cleared from objects
    and palette buttons alike."""
    s = _open(tmp_path)
    try:
        s.addUserCol("Stage", ["draft", "final"], log_event=False)
        item = _button_with_column(s, "Stage", "draft")
        s.editUserCol("Stage", "Stage", ["final"], log_event=False)
        assert item.obj_defaults == {"groups": ["axons"]}
        # a value still offered is kept
        item.obj_defaults = {"user_columns": {"Stage": "final"}}
        s.editUserCol("Stage", "Stage", ["final", "review"], log_event=False)
        assert item.obj_defaults == {"user_columns": {"Stage": "final"}}
    finally:
        s.close()


@pytest.mark.gui
def test_a_value_that_is_not_an_option_is_never_applied(main_window):
    field = main_window.field
    series = main_window.series
    series.addUserCol("Stage", ["final"], log_event=False)
    item = Trace("stale_value_obj", (0, 255, 0), True)
    item.obj_defaults = {"user_columns": {"Stage": "draft"}}
    field.setTracingTrace(item)
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.4, wy + wh * 0.4
    field.newTrace([(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)],
                   field.tracing_trace, points_as_pix=False, reduce_points=False, log_event=False)
    assert "Stage" not in (series.getAttr("stale_value_obj", "user_columns") or {})


def test_rename_drops_a_value_that_is_not_an_option(tmp_path):
    s = _open(tmp_path)
    try:
        s.addUserCol("Stage", ["final"], log_event=False)
        item = _button_with_column(s, "Stage", "draft")      # already stale
        s.editUserCol("Stage", "Phase", ["final"], log_event=False)
        assert item.obj_defaults == {"groups": ["axons"]}
    finally:
        s.close()


@pytest.mark.gui
@pytest.mark.parametrize("edit", ["rename", "delete", "remove_option"])
def test_undo_of_a_column_edit_restores_palette_buttons(main_window, edit):
    """A column edit is a series undo step. Undo must bring the buttons'
    values back along with the column and the objects, and the drawing copy
    with them."""
    field = main_window.field
    series = main_window.series
    series.addUserCol("Stage", ["draft", "final"], log_event=False)
    pal_name, idx = series.palette_index
    button = series.palette_traces[pal_name][idx]
    button.obj_defaults = {"user_columns": {"Stage": "draft"}}
    main_window.changeTracingTrace(button)

    field.series_states.addState()
    field.series_states.recordPaletteDefaults()    # as the column menus do
    if edit == "rename":
        series.editUserCol("Stage", "Phase", ["draft", "final"], log_event=False)
    elif edit == "delete":
        series.removeUserCol("Stage", log_event=False)
    else:
        series.editUserCol("Stage", "Stage", ["final"], log_event=False)
    field.syncTracingDefaults()
    assert button.obj_defaults != {"user_columns": {"Stage": "draft"}}

    field.seriesUndo()
    assert "Stage" in series.user_columns
    assert button.obj_defaults == {"user_columns": {"Stage": "draft"}}
    assert field.tracing_trace.obj_defaults == {"user_columns": {"Stage": "draft"}}

    field.seriesUndo(redo=True)
    assert button.obj_defaults != {"user_columns": {"Stage": "draft"}}


@pytest.mark.gui
def test_an_unrelated_undo_keeps_a_later_palette_button_edit(main_window):
    """Palette button edits make no undo state. An undo of some other series
    action must not roll a button edit made after it back."""
    field = main_window.field
    series = main_window.series
    pal_name, idx = series.palette_index
    button = series.palette_traces[pal_name][idx]
    button.obj_defaults = None

    field.series_states.addState()
    series.addUserCol("Other", ["x"], log_event=False)
    button.obj_defaults = {"groups": ["axons"]}          # as the dialog does

    field.seriesUndo()
    assert "Other" not in series.user_columns
    assert button.obj_defaults == {"groups": ["axons"]}
