"""Each object can carry its own smoothing window.

The rolling average window used to smooth traces was one series option
(`roll_window`, trace mode options). An object can now hold its own window in
its `obj_attrs` entry under "smooth_window", set from the object list's
`Edit attributes...` Smoothing row. `Series.getSmoothWindow` returns that
value, or the series option when the object has none, and every smoothing
path reads it: `Smooth object traces`, `Smooth traces`, and the rolling
average while scribbling.

Stored in `obj_attrs` like comments and 3D modes, the value saves in the
.jser, rides series undo and redo, follows a rename, and an older
PyReconstruct keeps it without reading it (the loader takes `obj_attrs` as a
plain dict). An object with no value smooths exactly as before.
"""
import json
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes import Series, Trace

# a short object: seven sections, so a smooth over all of it is quick
SMALL = "d03p12"

# two objects on section 52, the section the window opens on
ON_OPEN_SECTION = "d03sp14"
ALSO_ON_OPEN_SECTION = "d03p14"

SHAPES = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)


def _smoothed(points, closed, window):
    """The points `Trace.smooth` gives for this window, on a copy."""
    t = Trace("probe", (0, 0, 0), closed=closed)
    t.points = list(points)
    assert t.smooth(window=window, spacing=0.004)
    return t.points


def _biggest_trace(section, name):
    return max(section.contours[name].traces, key=lambda t: len(t.points))


def _series_block(jser):
    """The series dict in a .jser: "series" as saved now, or the older
    layout keyed by file name."""
    if "series" in jser:
        return jser["series"]
    return next(v for k, v in jser.items() if k.endswith(".ser"))


def _reopen(fp):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    return Series.openJser(fp)


# --------------------------------------------------------------------------- #
# the value and its default                                                    #
# --------------------------------------------------------------------------- #
def test_an_old_file_has_no_value_and_follows_the_option(real_series):
    series = real_series
    assert series.getAttr(SMALL, "smooth_window") is None
    assert series.getSmoothWindow(SMALL) == series.getOption("roll_window")
    assert "smooth_window" not in series.obj_attrs.get(SMALL, {})


def test_an_object_value_wins_over_the_option(real_series):
    series = real_series
    series.setAttr(SMALL, "smooth_window", 4)
    assert series.getSmoothWindow(SMALL) == 4
    assert series.getSmoothWindow("d03") == series.getOption("roll_window")


@pytest.mark.parametrize("junk", [0, -3, "4", 2.5, True, None])
def test_a_junk_value_falls_back_to_the_option(real_series, junk):
    series = real_series
    series.setAttr(SMALL, "smooth_window", junk)
    assert series.getSmoothWindow(SMALL) == series.getOption("roll_window")


# --------------------------------------------------------------------------- #
# smoothing uses it                                                            #
# --------------------------------------------------------------------------- #
def test_smooth_object_with_no_value_is_unchanged(real_series):
    """Byte for byte what the series option gives: the default path moved
    from one lookup to another and must produce the same points."""
    series = real_series
    window = series.getOption("roll_window")
    before = {}
    for snum in series.getObjectSections([SMALL]):
        section = series.loadSection(snum)
        before[snum] = [(list(t.points), t.closed) for t in section.contours[SMALL].traces]

    assert not series.smoothObject([SMALL], log_event=False)

    for snum, traces in before.items():
        section = series.loadSection(snum)
        after = [t.points for t in section.contours[SMALL].traces]
        assert after == [_smoothed(p, c, window) for p, c in traces]


def test_smooth_object_uses_the_object_value(real_series):
    series = real_series
    option = series.getOption("roll_window")
    series.setAttr(SMALL, "smooth_window", 4)
    before = {}
    for snum in series.getObjectSections([SMALL]):
        section = series.loadSection(snum)
        before[snum] = [(list(t.points), t.closed) for t in section.contours[SMALL].traces]

    assert not series.smoothObject([SMALL], log_event=False)

    differed = False
    for snum, traces in before.items():
        section = series.loadSection(snum)
        after = [t.points for t in section.contours[SMALL].traces]
        assert after == [_smoothed(p, c, 4) for p, c in traces]
        if after != [_smoothed(p, c, option) for p, c in traces]:
            differed = True
    assert differed, "a window of 4 and the option gave the same points"


def test_two_objects_in_one_smooth_use_their_own_windows(real_series):
    series = real_series
    other = "d03sp12"
    series.setAttr(SMALL, "smooth_window", 3)
    snum = sorted(set(series.getObjectSections([SMALL])) & set(series.getObjectSections([other])))[0]
    section = series.loadSection(snum)
    small_before = [(list(t.points), t.closed) for t in section.contours[SMALL].traces]
    other_before = [(list(t.points), t.closed) for t in section.contours[other].traces]

    series.smoothObject([SMALL, other], log_event=False)

    section = series.loadSection(snum)
    assert [t.points for t in section.contours[SMALL].traces] == [
        _smoothed(p, c, 3) for p, c in small_before
    ]
    assert [t.points for t in section.contours[other].traces] == [
        _smoothed(p, c, series.getOption("roll_window")) for p, c in other_before
    ]


# --------------------------------------------------------------------------- #
# storage: save and reopen, unknown keys, rename                               #
# --------------------------------------------------------------------------- #
def test_value_survives_save_and_reopen(series_jser):
    fp = str(series_jser)
    series = _reopen(fp)
    series.setAttr(SMALL, "smooth_window", 4)
    series.save()
    series.saveJser()
    series.close()

    with open(fp) as f:
        data = json.load(f)
    ser = _series_block(data)
    assert ser["obj_attrs"][SMALL]["smooth_window"] == 4

    reopened = _reopen(fp)
    try:
        assert reopened.getAttr(SMALL, "smooth_window") == 4
        assert reopened.getSmoothWindow(SMALL) == 4
        assert reopened.getAttr("d03", "smooth_window") is None
    finally:
        reopened.close()


def test_loader_keeps_a_per_object_key_it_does_not_know(series_jser):
    """The compatibility claim, run on this build: `obj_attrs` is loaded as a
    plain dict, so a key this build never reads rides along and is written
    back. v1.23.0 loads it with the same line, which is what lets a file with
    "smooth_window" open there and come back with the value intact."""
    fp = str(series_jser)
    series = _reopen(fp)
    series.setAttr(SMALL, "a_key_from_a_newer_build", {"n": 7})
    series.save()
    series.saveJser()
    series.close()

    reopened = _reopen(fp)
    try:
        assert reopened.getAttr(SMALL, "a_key_from_a_newer_build") == {"n": 7}
        assert reopened.getSmoothWindow(SMALL) == reopened.getOption("roll_window")
        reopened.setAttr(SMALL, "comment", "touched")
        reopened.save()
        reopened.saveJser()
    finally:
        reopened.close()

    with open(fp) as f:
        data = json.load(f)
    ser = _series_block(data)
    assert ser["obj_attrs"][SMALL]["a_key_from_a_newer_build"] == {"n": 7}


def test_rename_carries_the_value(real_series):
    series = real_series
    series.setAttr("old", "smooth_window", 6)
    series.renameObjAttrs("old", "new")
    assert series.getSmoothWindow("new") == 6


def test_partial_rename_keeps_the_value_on_both(tmp_path):
    if not os.path.exists(SHAPES):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(SHAPES, fp)
    series = _reopen(fp)
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    series.data = SeriesData(series)
    series.data.refresh()

    old = next(
        n for n in series.data["objects"]
        if len(series.getObjectSections([n])) >= 2
    )
    first = sorted(series.getObjectSections([old]))[0]
    new = "renamed_part"
    series.setAttr(old, "smooth_window", 5)

    series.editObjectAttributes([old], name=new, sections=[first], log_event=False)
    series.data.refresh()
    assert old in series.data["objects"] and new in series.data["objects"]
    assert series.getSmoothWindow(old) == 5
    assert series.getSmoothWindow(new) == 5

    series.setAttr(new, "smooth_window", 8)
    assert series.getSmoothWindow(old) == 5
    series.close()


# --------------------------------------------------------------------------- #
# the dialog row                                                               #
# --------------------------------------------------------------------------- #
@pytest.fixture
def parent(qapp):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.series = SimpleNamespace(sections={0: None, 1: None})
    yield w
    w.deleteLater()


@pytest.mark.gui
def test_row_offers_the_default_first(parent):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    dlg = TraceDialog(parent, name="obj", is_obj_list=True, smooth_default=10)
    items = [dlg.smooth_input.itemText(i) for i in range(dlg.smooth_input.count())]
    assert items[0] == "Default (10)"
    assert "10" in items and "4" in items
    assert dlg.smooth_input.currentText() == "Default (10)"
    assert dlg.readSmoothChoice() == 0


@pytest.mark.gui
def test_row_is_absent_without_a_default(parent):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    dlg = TraceDialog(parent, name="obj", is_obj_list=True)
    assert dlg.smooth_input is None
    assert dlg.smooth_choice is None


@pytest.mark.gui
def test_row_shows_the_object_value(parent):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    dlg = TraceDialog(parent, name="obj", is_obj_list=True, smooth_default=10, smooth_window=7)
    assert dlg.smooth_input.currentText() == "7"
    assert dlg.readSmoothChoice() == 7


@pytest.mark.gui
def test_mixed_row_starts_blank_and_means_leave_alone(parent):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    dlg = TraceDialog(parent, name=None, is_obj_list=True, smooth_default=10, smooth_mixed=True)
    assert dlg.smooth_input.currentText() == ""
    assert dlg.readSmoothChoice() is None
    dlg.smooth_input.setCurrentText("Default (10)")
    assert dlg.readSmoothChoice() == 0


@pytest.mark.gui
def test_picked_and_typed_values_are_returned(parent, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)

    dlg = TraceDialog(parent, name="obj", is_obj_list=True, smooth_default=10)
    dlg.smooth_input.setCurrentText("4")
    (_trace, _sections), confirmed = dlg.exec()
    assert confirmed and dlg.smooth_choice == 4

    dlg = TraceDialog(parent, name="obj", is_obj_list=True, smooth_default=10)
    dlg.smooth_input.setCurrentText(" 17 ")
    dlg.exec()
    assert dlg.smooth_choice == 17


@pytest.mark.gui
@pytest.mark.parametrize("text", ["abc", "1", "0", "-4", "2.5"])
def test_a_bad_window_is_refused(parent, text, monkeypatch):
    from PyReconstruct.modules.gui.dialog import trace as trace_dialog
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog
    notices = []
    monkeypatch.setattr(trace_dialog, "notify", lambda msg, *a, **k: notices.append(msg))
    dlg = TraceDialog(parent, name="obj", is_obj_list=True, smooth_default=10)
    dlg.smooth_input.setCurrentText(text)
    accepted = []
    monkeypatch.setattr(trace_dialog.QDialog, "accept", lambda self: accepted.append(True))
    dlg.accept()
    assert not accepted
    assert notices and "smoothing window" in notices[0]


# --------------------------------------------------------------------------- #
# through the object list: undo, redo, and the smooth actions                  #
# --------------------------------------------------------------------------- #
class _ChoiceDialog:
    """Stands in for `TraceDialog`: an OK that only answers the Smoothing row."""

    choice = None
    seen = {}
    tag_choices = {}

    def __init__(self, parent, *args, **kwargs):
        type(self).seen = kwargs
        self.smooth_choice = type(self).choice

    def exec(self):
        trace = Trace(None, None)
        trace.color = None
        trace.tags = None
        trace.fill_mode = (None, None)
        return (trace, None), True


@pytest.fixture
def choice_dialog(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_3_object
    monkeypatch.setattr(field_widget_3_object, "TraceDialog", _ChoiceDialog)

    def choose(choice):
        _ChoiceDialog.choice = choice
    return choose


def _select_object(field, name):
    field.section.selected_traces.clear()
    for t in field.section.contours[name]:
        field.section.addSelectedTrace(t)
    assert field.section.selected_traces


@pytest.mark.gui
def test_edit_attributes_sets_undoes_and_redoes_the_value(
    main_window, main_window_dialogs, choice_dialog
):
    """The edit walks the object's sections, so the undo step is linked to
    them and PyReconstruct asks whether to undo on all sections or this
    one. "All" is the series undo, which carries the attribute."""
    field = main_window.field
    series = main_window.series
    option = series.getOption("roll_window")
    main_window_dialogs.linked_undo_responses += ["all", "all"]

    _select_object(field, ON_OPEN_SECTION)
    choice_dialog(4)
    field.editAttributes()
    assert _ChoiceDialog.seen["smooth_default"] == option
    assert _ChoiceDialog.seen["smooth_window"] is None
    assert _ChoiceDialog.seen["smooth_mixed"] is False
    assert series.getSmoothWindow(ON_OPEN_SECTION) == 4

    main_window.undo()
    assert series.getAttr(ON_OPEN_SECTION, "smooth_window") is None
    assert series.getSmoothWindow(ON_OPEN_SECTION) == option

    main_window.undo(redo=True)
    assert series.getSmoothWindow(ON_OPEN_SECTION) == 4


@pytest.mark.gui
def test_edit_attributes_default_clears_and_blank_leaves_alone(main_window, choice_dialog):
    field = main_window.field
    series = main_window.series
    series.setAttr(ON_OPEN_SECTION, "smooth_window", 4)

    _select_object(field, ON_OPEN_SECTION)
    choice_dialog(None)
    field.editAttributes()
    assert _ChoiceDialog.seen["smooth_window"] == 4
    assert series.getAttr(ON_OPEN_SECTION, "smooth_window") == 4

    _select_object(field, ON_OPEN_SECTION)
    choice_dialog(0)
    field.editAttributes()
    assert series.getAttr(ON_OPEN_SECTION, "smooth_window") is None
    assert "smooth_window" not in series.obj_attrs.get(ON_OPEN_SECTION, {})


@pytest.mark.gui
def test_edit_attributes_seeds_a_mixed_selection_blank(main_window, choice_dialog):
    field = main_window.field
    series = main_window.series
    series.setAttr(ON_OPEN_SECTION, "smooth_window", 4)

    field.section.selected_traces.clear()
    for name in (ON_OPEN_SECTION, ALSO_ON_OPEN_SECTION):
        for t in field.section.contours[name]:
            field.section.addSelectedTrace(t)
    choice_dialog(6)
    field.editAttributes()
    assert _ChoiceDialog.seen["smooth_mixed"] is True
    assert _ChoiceDialog.seen["smooth_window"] is None
    assert series.getSmoothWindow(ON_OPEN_SECTION) == 6
    assert series.getSmoothWindow(ALSO_ON_OPEN_SECTION) == 6


@pytest.mark.gui
def test_smooth_traces_uses_the_object_value(main_window):
    field = main_window.field
    series = main_window.series
    series.setAttr(ON_OPEN_SECTION, "smooth_window", 4)
    trace = _biggest_trace(field.section, ON_OPEN_SECTION)
    expected = _smoothed(trace.points, trace.closed, 4)
    assert expected != _smoothed(trace.points, trace.closed, series.getOption("roll_window"))

    field.section.selected_traces.clear()
    field.section.addSelectedTrace(trace)
    field.smoothTraces()

    assert trace.points == expected


@pytest.mark.gui
def test_smooth_traces_without_a_value_is_unchanged(main_window):
    field = main_window.field
    series = main_window.series
    trace = _biggest_trace(field.section, ON_OPEN_SECTION)
    expected = _smoothed(trace.points, trace.closed, series.getOption("roll_window"))

    field.section.selected_traces.clear()
    field.section.addSelectedTrace(trace)
    field.smoothTraces()

    assert trace.points == expected


@pytest.mark.gui
def test_scribble_smoothing_uses_the_object_value(main_window, monkeypatch):
    """The rolling average while scribbling reads the new object's window."""
    field = main_window.field
    series = main_window.series
    series.setAttr("scribble_probe", "smooth_window", 3)
    seen = []
    real_smooth = Trace.smooth

    def spy(self, window, spacing):
        seen.append((self.name, window))
        return real_smooth(self, window, spacing)
    monkeypatch.setattr(Trace, "smooth", spy)

    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.2
    x0, y0 = wx + ww * 0.3, wy + wh * 0.3
    pts = [(x0 + side * i / 20, y0 + (side if i % 2 else 0) * 0.3) for i in range(21)]
    pts += [(x0 + side, y0 + side), (x0, y0 + side)]
    field.setTracingTrace(Trace("scribble_probe", (0, 255, 0), True))
    field.newTrace(pts, field.tracing_trace, points_as_pix=False,
                   reduce_points=False, simplify=True)

    assert ("scribble_probe", 3) in seen
