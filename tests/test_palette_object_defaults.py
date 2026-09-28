"""A palette item can hand a new object its groups and custom columns (fork #419).

Kristen asked for the trace palette to fill object list columns at the moment
an object is created, so nobody has to go back to the object list afterwards.
Step one, built here without waiting on her: a palette item carries object
defaults, {"groups": [...], "user_columns": {column: value}}. The palette
dialog edits them, the series saves them beside the palette rows, and the
first trace of a NEW object applies them. An object that already exists is
left alone, and section traces never carry them.
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


def test_palette_dialog_shows_groups_and_a_row_per_column(tmp_path, monkeypatch):
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
        assert dlg.groups_input is not None
        assert dlg.groups_input.getEntries() == ["axons"]
        assert sorted(dlg.column_inputs) == ["Reviewer", "Stage"]
        assert dlg.column_inputs["Stage"].currentText() == "draft"
        assert dlg.column_inputs["Reviewer"].currentText() == ""
        combo = dlg.column_inputs["Reviewer"]
        assert [combo.itemText(i) for i in range(combo.count())] == ["", "KH", "DH"]
        dlg.close()

        # no series: no rows, as every other caller of the palette dialog has it
        plain = TraceDialog(None, [item], is_palette=True)
        assert plain.groups_input is None and plain.column_inputs == {}
        plain.close()
    finally:
        s.close()


def test_palette_dialog_returns_the_defaults(tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    s = _open(tmp_path)
    try:
        s.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
        item = Trace("item", (1, 2, 3), True)
        item.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        dlg = TraceDialog(None, [item], is_palette=True, series=s)
        dlg.column_inputs["Reviewer"].setCurrentText("DH")
        _accept(monkeypatch)
        t, confirmed = dlg.exec()
        assert confirmed
        assert t.obj_defaults == {"user_columns": {"Reviewer": "DH"}}

        # everything cleared: None, not an empty dict
        dlg2 = TraceDialog(None, [item], is_palette=True, series=s)
        t2, _ = dlg2.exec()
        assert t2.obj_defaults is None
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


def test_palette_dialog_puts_tags_just_above_groups(tmp_path):
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
        i_tags = order.index("Tags:")
        i_groups = order.index("New objects join groups:")
        i_col = order.index("Reviewer:")
        assert i_stamp < i_tags < i_groups < i_col, order
    finally:
        s.close()


def test_trace_dialog_keeps_tags_beside_the_name():
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    QApplication.instance() or QApplication(["test"])
    t = Trace("t", (1, 2, 3), True)
    t.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
    dlg = TraceDialog(None, [t])
    order = _row_order(dlg)
    dlg.close()
    assert order.index("Tags:") < order.index("Fill:"), order
