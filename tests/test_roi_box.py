"""The ROI box: a view-only box in field coordinates.

A click sets the box's center; its width and height are set in a dialog, or a
drag sets the center and the size together. Only
the traces whose bounds in field coordinates touch the box are drawn and can be
picked; turning the box off brings every trace back. Nothing is written to the
traces, the sections or the series, and no undo state is made.

Driven through the live `MainWindow` on the fixture series. Section 52 has
three traces: d03 (field bounds about 13.15-14.27 x 23.34-24.50) and two small
ones east of x = 14.15, d03p14 and d03sp14. Section 53, one PgUp away, has the
same three a little shifted. The default box below covers part of d03 only.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest

from PyReconstruct.modules.backend.view.trace_layer import (
    boundsOverlap,
    roiBoxBounds,
    traceInRoiBox,
)
from PyReconstruct.modules.calc import fieldPointToPixmap
from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.gui.main import field_widget_2_trace as fwt
from PyReconstruct.modules.gui.main import field_widget_3_object as fwo
from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    HOST,
    POINTER,
    ROI_BOX,
    SCISSORS,
)

pytestmark = pytest.mark.gui

# a box over the west part of d03, clear of d03p14 and d03sp14
CENTER = (13.5, 23.7)
SIZE = (0.4, 0.4)


def _pix(field, x, y):
    return QPoint(*fieldPointToPixmap(
        x, y, field.series.window, field.pixmap_dim, field.section.mag
    ))


def _click(field, qapp, x, y):
    p = _pix(field, x, y)
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, p)
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, p)
    qapp.processEvents()


def _turn_on(main_window, qapp, size=SIZE, center=CENTER):
    """Turn the box on through its menu action and place it with a click."""
    main_window.main_window_dialogs.responses.append((list(size), True))
    main_window.roibox_act.trigger()
    qapp.processEvents()
    if center is not None:
        _click(main_window.field, qapp, *center)


def _trace(section, name):
    (trace,) = [t for t in section.tracesAsList() if t.name == name]
    return trace


def _on_trace(trace, tform):
    """A field point on the trace's outline."""
    return tform.map(*trace.points[0])


@pytest.fixture
def mw(main_window, main_window_dialogs, qapp):
    main_window.main_window_dialogs = main_window_dialogs
    field = main_window.field
    assert main_window.series.current_section == 52
    assert sorted(t.name for t in field.section.tracesAsList()) == [
        "d03", "d03p14", "d03sp14"
    ]
    return main_window


# --- view-only ---------------------------------------------------------------

def test_box_writes_nothing_and_saves_no_undo_state(mw, qapp):
    """Turning the box on, moving it, resizing it and turning it off leaves
    the series unmodified, every trace as it was and the undo stack alone."""
    field = mw.field
    mw.series.modified = False
    states = field.series_states[field.section.n]
    undo_before = len(states.undo_states)
    traces_before = [
        (t.name, t.hidden, list(t.points)) for t in field.section.tracesAsList()
    ]
    settings_before = set(QSettings("KHLab", "PyReconstruct").allKeys())

    _turn_on(mw, qapp)
    _click(field, qapp, 13.6, 23.8)  # move it
    mw.main_window_dialogs.responses.append(([0.5, 0.3], True))
    mw.roiboxsize_act.trigger()
    mw.roibox_act.trigger()  # off
    qapp.processEvents()

    assert mw.series.modified is False
    assert len(states.undo_states) == undo_before
    assert not field.section.added_traces and not field.section.removed_traces
    assert [
        (t.name, t.hidden, list(t.points)) for t in field.section.tracesAsList()
    ] == traces_before
    # the size lasts the session only: no settings key was written
    assert set(QSettings("KHLab", "PyReconstruct").allKeys()) == settings_before


def test_undo_works_while_the_box_is_on(mw, qapp):
    """Unlike the hidden trace layer, the box leaves undo working."""
    field = mw.field
    _turn_on(mw, qapp)
    d03 = _trace(field.section, "d03")
    field.section.selected_traces = [d03]
    field.deleteTraces()
    assert "d03" not in [t.name for t in field.section.tracesAsList()]

    mw.undo()
    qapp.processEvents()
    assert "d03" in [t.name for t in field.section.tracesAsList()]


# --- the box lives in field coordinates --------------------------------------

def test_box_stays_put_across_section_changes(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    center = field.roi_box_center

    mw.incrementSection()  # PgUp
    qapp.processEvents()

    assert mw.series.current_section == 53
    assert field.roi_box_center == center
    assert [t.name for t in field.section_layer.traces_in_view] == ["d03"]


def test_inside_is_field_bounds_with_the_section_transform():
    """A trace is inside when its transformed bounds touch the box, the same
    bounds Trace.getBounds(tform) gives."""
    trace = Trace("t", (255, 0, 0))
    trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    shift = Transform([1, 0, 10, 0, 1, 10])

    assert traceInRoiBox(trace, shift, (10.5, 10.5, 0.2, 0.2))
    # the untransformed spot is not where the trace is in the field
    assert not traceInRoiBox(trace, shift, (0.5, 0.5, 0.2, 0.2))
    # touching an edge counts
    assert traceInRoiBox(trace, shift, (11.1, 10.5, 0.2, 0.2))
    assert not traceInRoiBox(trace, shift, (11.2, 10.5, 0.2, 0.2))
    # off means every trace is inside
    assert traceInRoiBox(trace, shift, None)


def test_inside_matches_get_bounds_on_every_fixture_trace(mw):
    field = mw.field
    tform = field.section.tform
    for box in [(*CENTER, *SIZE), (14.4, 24.1, 0.1, 0.1), (11.0, 25.0, 0.2, 0.2)]:
        for trace in field.section.tracesAsList():
            expected = boundsOverlap(trace.getBounds(tform), roiBoxBounds(box))
            assert traceInRoiBox(trace, tform, box) == expected


# --- drawing -------------------------------------------------------------------

def test_only_traces_inside_are_drawn_and_drawn_whole(mw, qapp):
    field = mw.field
    tform = field.section.tform
    _turn_on(mw, qapp)

    assert [t.name for t in field.section_layer.traces_in_view] == ["d03"]
    image = field.section_layer.trace_layer.toImage()

    def alpha_at(x, y):
        p = _pix(field, x, y)
        return image.pixelColor(p.x(), p.y()).alpha()

    # an outside trace is not drawn
    sp = _trace(field.section, "d03sp14")
    assert alpha_at(*_on_trace(sp, tform)) == 0

    # the inside trace is drawn whole, outside the box too
    d03 = _trace(field.section, "d03")
    xmin, ymin, xmax, ymax = roiBoxBounds((*CENTER, *SIZE))
    far = [
        tform.map(*p) for p in d03.points
        if not (xmin <= tform.map(*p)[0] <= xmax and ymin <= tform.map(*p)[1] <= ymax)
    ]
    assert far, "d03 should reach outside the box"
    assert alpha_at(*far[0]) > 0


def test_turning_off_restores_every_trace(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    assert len(field.section_layer.traces_in_view) == 1

    mw.roibox_act.trigger()
    qapp.processEvents()

    assert not field.roi_box_on and field.roiBox() is None
    assert field.mouse_mode == POINTER
    assert sorted(t.name for t in field.section_layer.traces_in_view) == [
        "d03", "d03p14", "d03sp14"
    ]


def test_new_trace_is_kept_and_shown_only_if_inside(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    base = field.tracing_trace.copy()
    base.name = "roi_new"

    def square(cx, cy, r=0.05):
        return [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]

    for center in (CENTER, (15.5, 25.0)):  # inside, outside
        field.newTrace(
            square(*center), base, points_as_pix=False, reduce_points=False
        )

    new = [t for t in field.section.tracesAsList() if t.name == "roi_new"]
    assert len(new) == 2  # both kept
    in_view = [t for t in field.section_layer.traces_in_view if t.name == "roi_new"]
    assert len(in_view) == 1
    assert field.inRoiBox(in_view[0])


def test_hide_all_wins_over_the_box(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    field.toggleHideAllTraces()
    image = field.field_pixmap.toImage()
    blank = field.section_layer.image_layer.toImage()
    assert image == blank  # no trace drawn, the inside one included

    field.selectAllTraces()
    assert field.section.selected_traces == []

    field.toggleHideAllTraces()
    assert [t.name for t in field.section_layer.traces_in_view] == ["d03"]


# --- picking -------------------------------------------------------------------

def test_click_and_lasso_do_not_pick_outside_traces(mw, qapp):
    field = mw.field
    tform = field.section.tform
    _turn_on(mw, qapp)
    mw.mouse_palette.activateModeButton("Pointer")
    sp = _trace(field.section, "d03sp14")

    _click(field, qapp, *_on_trace(sp, tform))
    assert sp not in field.section.selected_traces

    # a lasso around the whole view
    w, h = field.pixmap_dim
    field.selectTraces(field.section_layer.getTraces(
        [(1, 1), (w - 2, 1), (w - 2, h - 2), (1, h - 2)]
    ), [])
    assert [t.name for t in field.section.selected_traces] == ["d03"]

    # handed an outside trace directly, the field still refuses it
    field.section.selected_traces = []
    field.selectTrace(sp)
    field.selectTraces([sp], [])
    assert field.section.selected_traces == []


def test_box_with_no_trace_inside_picks_nothing(mw, qapp):
    """No trace in view must not mean 'search the whole section'."""
    field = mw.field
    tform = field.section.tform
    _turn_on(mw, qapp, center=(11.0, 25.0))
    assert field.section_layer.traces_in_view == []
    sp = _trace(field.section, "d03sp14")

    p = _pix(field, *_on_trace(sp, tform))
    assert field.section_layer.getTrace(p.x(), p.y()) == (None, None)

    mw.mouse_palette.activateModeButton("Pointer")
    _click(field, qapp, *_on_trace(sp, tform))
    assert field.section.selected_traces == []


def test_find_closest_with_an_empty_list_checks_no_trace(mw):
    """findClosest itself: an empty list is no trace to check, and only None
    searches the whole section."""
    section = mw.field.section
    sp = _trace(section, "d03sp14")
    x, y = _on_trace(sp, section.tform)

    assert section.findClosest(x, y, radius=0.5, traces_in_view=None) == (sp, "trace")
    _, kind = section.findClosest(x, y, radius=0.5, traces_in_view=[])
    assert kind != "trace"


def test_without_the_box_an_empty_view_list_still_searches_the_section(mw):
    """The box-off pick is unchanged: findClosest was always handed None, not
    an empty list, when no trace had been drawn in view."""
    field = mw.field
    tform = field.section.tform
    sp = _trace(field.section, "d03sp14")
    field.section_layer.traces_in_view = []

    p = _pix(field, *_on_trace(sp, tform))
    trace, kind = field.section_layer.getTrace(p.x(), p.y())
    assert kind == "trace" and trace is not None


def test_select_all_invert_and_find_skip_outside_traces(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)

    field.selectAllTraces()
    assert [t.name for t in field.section.selected_traces] == ["d03"]

    field.section.selected_traces = []
    field.invertTraceSelection()
    assert [t.name for t in field.section.selected_traces] == ["d03"]

    field.section.selected_traces = []
    field.findContour("d03sp14")
    assert field.section.selected_traces == []
    field.findTrace("d03sp14")
    assert field.section.selected_traces == []
    field.findTrace("d03")
    assert [t.name for t in field.section.selected_traces] == ["d03"]


def test_placing_the_box_deselects_traces_outside_it(mw, qapp):
    field = mw.field
    field.selectAllTraces()
    assert len(field.section.selected_traces) == 3

    _turn_on(mw, qapp)

    assert [t.name for t in field.section.selected_traces] == ["d03"]


# --- turning on, size, mouse mode ------------------------------------------------

def test_turn_on_then_click_sets_center_and_later_clicks_move_it(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp, center=None)

    assert field.mouse_mode == ROI_BOX
    assert field.roi_box_on and field.roiBox() is None
    assert len(field.section_layer.traces_in_view) == 3  # nothing hidden yet

    _click(field, qapp, *CENTER)
    cx, cy = field.roi_box_center
    one_pixel = field.series.window[2] / field.pixmap_dim[0]  # field units
    assert abs(cx - CENTER[0]) <= one_pixel and abs(cy - CENTER[1]) <= one_pixel

    _click(field, qapp, 14.4, 24.1)
    cx, cy = field.roi_box_center
    assert abs(cx - 14.4) <= one_pixel and abs(cy - 24.1) <= one_pixel

    # any other mouse mode works normally, and clicks no longer move the box
    mw.mouse_palette.activateModeButton("Pointer")
    _click(field, qapp, *CENTER)
    assert abs(field.roi_box_center[0] - 14.4) <= one_pixel

    # Move ROI box goes back to the box's mode
    mw.moveroibox_act.trigger()
    assert field.mouse_mode == ROI_BOX


def test_size_defaults_to_5_by_5_and_is_kept_for_the_session(mw, qapp):
    field = mw.field
    assert field.roi_box_size == (5.0, 5.0)

    _turn_on(mw, qapp, size=(2.5, 1.0))
    assert field.roiBox() == (*field.roi_box_center, 2.5, 1.0)

    mw.roibox_act.trigger()  # off
    assert field.roi_box_size == (2.5, 1.0)

    # a cancelled size dialog leaves the box off
    mw.roibox_act.trigger()
    assert not field.roi_box_on


def test_shortcut_is_b_and_used_nowhere_else(mw):
    assert default_settings["roibox_act"] == "B"
    others = [
        k for k, v in default_settings.items()
        if k.endswith("_act") and k != "roibox_act" and v == "B"
    ]
    assert others == []
    assert mw.roibox_act.shortcut().toString() == "B"


def test_status_bar_says_the_box_is_on_and_its_size(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp, size=(5, 5), center=None)
    field.updateStatusBar()
    assert "ROI box 5 x 5 μm: click or drag to place" in mw.status_readout.text()

    _click(field, qapp, *CENTER)
    field.updateStatusBar()
    text = mw.status_readout.text()
    assert "ROI box 5 x 5 μm" in text and "to place" not in text

    mw.roibox_act.trigger()
    field.updateStatusBar()
    assert "ROI box" not in mw.status_readout.text()


# --- round 2: one selection rule ----------------------------------------------

def _outside_copy(section, name="d03", dx=3.0):
    """Add a copy of a trace moved dx field units east, well outside the box."""
    tform = section.tform
    (src,) = [t for t in section.tracesAsList() if t.name == name]
    copy = src.copy()
    copy.points = [
        tform.map(tform.map(*p)[0] + dx, tform.map(*p)[1], inverted=True)
        for p in src.points
    ]
    section.addTrace(copy)
    return copy


@pytest.fixture
def notices(monkeypatch):
    """The messages notify would have shown from the field."""
    shown = []
    monkeypatch.setattr(fwt, "notify", shown.append)
    monkeypatch.setattr(fwo, "notify", shown.append)
    return shown


def test_focus_mode_selects_only_inside_traces_and_keeps_that_on_pgup(mw, qapp):
    """Focus mode selects the object's traces inside the box only, on this
    section and on the next one after PgUp."""
    field = mw.field
    outside_52 = _outside_copy(field.section)
    sec53 = mw.series.loadSection(53)
    _outside_copy(sec53)
    sec53.save()
    field.generateView()

    _turn_on(mw, qapp)
    mw.mouse_palette.activateModeButton("Pointer")
    field.section.selected_traces = [
        t for t in field.section.tracesAsList()
        if t.name == "d03" and t is not outside_52
    ]
    field.toggleFocusMode()
    assert field.section.selected_traces
    assert outside_52 not in field.section.selected_traces
    assert all(field.inRoiBox(t) for t in field.section.selected_traces)

    mw.incrementSection()  # PgUp
    qapp.processEvents()
    assert mw.series.current_section == 53
    names = [t.name for t in field.section.tracesAsList()]
    assert names.count("d03") == 2
    assert len(field.section.selected_traces) == 1
    assert all(field.inRoiBox(t) for t in field.section.selected_traces)


def test_new_trace_outside_the_box_is_kept_not_selected_and_named(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    base = field.tracing_trace.copy()
    base.name = "roi_out"
    r = 0.05
    field.newTrace(
        [(15.5 - r, 25 - r), (15.5 + r, 25 - r), (15.5 + r, 25 + r), (15.5 - r, 25 + r)],
        base, points_as_pix=False, reduce_points=False,
    )
    (new,) = [t for t in field.section.tracesAsList() if t.name == "roi_out"]
    assert new not in field.section.selected_traces
    assert "outside the ROI box" in mw.statusBar().currentMessage()

    field.copy()
    assert all(t.name != "roi_out" for t in (field.clipboard or []))


def test_box_moved_with_a_name_selected_keeps_only_inside_traces(mw, qapp):
    """Every redraw keeps the rule, whatever filled the selection."""
    field = mw.field
    outside = _outside_copy(field.section)
    _turn_on(mw, qapp)
    field.section.selected_traces = [
        t for t in field.section.tracesAsList() if t.name == "d03"
    ]
    field.generateView()
    assert outside not in field.section.selected_traces
    assert [t.name for t in field.section.selected_traces] == ["d03"]


# --- round 2: auto-merge -------------------------------------------------------

def test_auto_merge_leaves_a_trace_outside_the_box(mw, qapp):
    """With "Only merge selected traces" off, a new trace inside the box that
    overlaps a same-name trace outside it does not merge that trace away."""
    field = mw.field
    mw.series.setOption("auto_merge", True)
    mw.series.setOption("auto_merge_selected_only", False)
    base = field.tracing_trace.copy()
    base.name = "roi_m"
    base.closed = True
    field.setTracingTrace(base)

    # outside: x 13.8-14.0, past the box's east edge at 13.7
    field.newTrace(
        [(13.8, 23.6), (14.0, 23.6), (14.0, 23.8), (13.8, 23.8)],
        field.tracing_trace, points_as_pix=False, reduce_points=False,
    )
    field.section.selected_traces = []
    _turn_on(mw, qapp)
    outside = [t for t in field.section.tracesAsList() if t.name == "roi_m"]
    assert len(outside) == 1 and not field.inRoiBox(outside[0])

    # inside, and overlapping the outside one
    field.newTrace(
        [(13.6, 23.65), (13.9, 23.65), (13.9, 23.75), (13.6, 23.75)],
        field.tracing_trace, points_as_pix=False, reduce_points=False,
    )
    field.autoMerge()

    assert len([t for t in field.section.tracesAsList() if t.name == "roi_m"]) == 2
    assert outside[0] in field.section.tracesAsList()


# --- round 2: no stale picking state -------------------------------------------

def test_hidden_layer_leaves_no_stale_traces_in_view(mw, qapp):
    """With H on, moving the box leaves nothing to pick from the last draw."""
    field = mw.field
    tform = field.section.tform
    _turn_on(mw, qapp)
    assert [t.name for t in field.section_layer.traces_in_view] == ["d03"]

    field.toggleHideAllTraces()
    _click(field, qapp, 11.0, 25.0)  # move the box away from every trace
    assert field.section_layer.traces_in_view == []

    d03 = _trace(field.section, "d03")
    p = _pix(field, *_on_trace(d03, tform))
    assert field.section_layer.getTrace(p.x(), p.y()) == (None, None)

    # scissors on d03 starts no cut
    field.setMouseMode(SCISSORS)
    _click(field, qapp, *_on_trace(d03, tform))
    assert not field.is_scissoring
    assert d03 in field.section.tracesAsList()


def test_hide_all_with_the_box_off_picks_nothing(mw, qapp):
    """With H on and the box off, a pick finds nothing, as on main: a trace
    of a hidden group is not picked by a search of the whole section."""
    field = mw.field
    tform = field.section.tform
    sp = _trace(field.section, "d03sp14")
    mw.series.object_groups.add("roi_hidden", "d03sp14")
    mw.series.groups_visibility["roi_hidden"] = False
    field.generateView()
    assert sp not in field.section_layer.traces_in_view

    field.toggleHideAllTraces()
    assert not field.roi_box_on
    p = _pix(field, *_on_trace(sp, tform))
    assert field.section_layer.getTrace(p.x(), p.y()) == (None, None)

    # scissors on the hidden trace starts no cut
    field.setMouseMode(SCISSORS)
    _click(field, qapp, *_on_trace(sp, tform))
    assert not field.is_scissoring
    assert sp in field.section.tracesAsList()


def test_a_cached_candidate_is_checked_against_the_current_box(mw, qapp):
    """A trace in the last draw's list is not picked once the box has moved
    off it, even before the next draw."""
    field = mw.field
    tform = field.section.tform
    _turn_on(mw, qapp)
    d03 = _trace(field.section, "d03")
    assert field.section_layer.traces_in_view == [d03]

    field.section_layer.roi_box = (11.0, 25.0, *SIZE)  # moved, not redrawn
    p = _pix(field, *_on_trace(d03, tform))
    assert field.section_layer.getTrace(p.x(), p.y()) == (None, None)


# --- round 2: name-wide commands -----------------------------------------------

def test_delete_from_sections_refuses_while_the_box_is_on(mw, qapp, notices, monkeypatch):
    field = mw.field
    asked = []

    class _Dialog:
        def __init__(self, *a, **k):
            asked.append(1)

        def get(self):
            return {52, 53}, True

    monkeypatch.setattr(fwt, "CopyToSectionsDialog", _Dialog)
    _outside_copy(field.section)
    _turn_on(mw, qapp)
    field.section.selected_traces = [_trace_inside(field, "d03")]

    field.deleteTracesFromSections()

    assert notices == ["Turn off the ROI box first."]
    assert asked == []
    assert [t.name for t in field.section.tracesAsList()].count("d03") == 2


def _trace_inside(field, name):
    (trace,) = [
        t for t in field.section.tracesAsList()
        if t.name == name and field.inRoiBox(t)
    ]
    return trace


def test_create_copy_of_object_refuses_while_the_box_is_on(mw, qapp, notices):
    field = mw.field
    _turn_on(mw, qapp)
    field.section.selected_traces = [_trace(field.section, "d03")]
    objects_before = set(mw.series.data["objects"])

    field.copyObjects()

    assert notices == ["Turn off the ROI box first."]
    assert set(mw.series.data["objects"]) == objects_before


def test_every_field_object_command_refuses_but_3d(mw, qapp, notices, monkeypatch):
    """Every object command reached from the field acts on whole objects, so
    each refuses while the box is on; the 3D ones are left alone."""
    field = mw.field
    _turn_on(mw, qapp)
    field.section.selected_traces = [_trace(field.section, "d03")]
    added = []
    monkeypatch.setattr(mw, "addTo3D", added.append)

    # removeAllTags first: it opens no dialog, so without the refusal the
    # test fails at once instead of waiting on a modal
    for fn in (
        field.removeAllTags, field.editAttributes, field.smoothObject, field.editComment,
        field.editAlignment, field.editRadius, field.editShape, field.hideObj,
        field.hideOtherObjects, field.addToGroup, field.removeFromGroup,
        field.removeFromAllGroups, field.viewHistory,
        field.createZtrace, field.deleteObjects, field.copyObjects,
        field.bulkCurateAssign, field.lockObjects, field.setPaletteButtonFromObj,
        field.splitObject, field.displayHostTree, field.setHosts,
        field.clearHosts, field.reapplyAutosegColors,
        lambda: field.bulkCurate("Curated"),
        lambda: field.setUserCol("c", "o"),
    ):
        notices.clear()
        fn()
        assert notices == ["Turn off the ROI box first."], fn

    notices.clear()
    field.addTo3D()
    assert notices == [] and added == [["d03"]]


def test_calibrate_pixel_size_refuses_while_the_box_is_on(mw, qapp, notices, monkeypatch):
    """Calibration reads every trace of the selected names and rewrites the
    series pixel size, so it waits for the box to be off."""
    from PySide6.QtWidgets import QInputDialog

    field = mw.field
    _outside_copy(field.section)
    _turn_on(mw, qapp)
    field.section.selected_traces = [_trace_inside(field, "d03")]
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *a, **k: asked.append(1) or ("2.0", True)
    ))
    mag = field.section.mag
    mw.checkActions()
    assert mw.calibrate_act.isEnabled()

    mw.calibrate_act.trigger()

    assert notices == ["Turn off the ROI box first."]
    assert asked == []
    assert field.section.mag == mag


def test_host_gesture_refuses_and_drops_its_pending_trace(mw, qapp, notices):
    """The Host tool sets a series-wide host, so each click refuses while the
    box is on, and a trace picked before the box came on is let go."""
    field = mw.field
    tform = field.section.tform
    _turn_on(mw, qapp)
    field.setMouseMode(HOST)
    d03 = _trace(field.section, "d03")

    _click(field, qapp, *_on_trace(d03, tform))
    assert notices == ["Turn off the ROI box first."]
    assert field.hosted_trace is None

    # a gesture begun before the box came on
    notices.clear()
    field.hosted_trace = _trace(field.section, "d03sp14")
    field.current_trace = [(0, 0)]
    _click(field, qapp, *_on_trace(d03, tform))
    assert notices == ["Turn off the ROI box first."]
    assert field.hosted_trace is None and field.current_trace == []
    assert mw.series.getObjHosts("d03sp14") == []


SERIES_WIDE_ACTIONS = [
    "hidealltraces_act",
    "unhidealltraces_act",
    "duplicates_act",
    "removepixeldust_act",
    "removeempty_act",
    "repairselfcrossings_act",
    "recolorallfrompalette_act",
    "setmag_act",
    "importfromseries_act",
    "importfromzarrlabels_act",
    "updatecuration_act",
]


@pytest.mark.parametrize("act", SERIES_WIDE_ACTIONS)
def test_series_wide_menu_commands_refuse_while_the_box_is_on(mw, qapp, notices, act):
    """Each menu command that reads or writes traces across the series
    refuses before it asks anything or changes a trace."""
    field = mw.field
    _turn_on(mw, qapp)
    recorder = mw.main_window_dialogs
    dialogs_before = list(recorder.dialogs)
    traces_before = [
        (t.name, t.hidden, t.color, list(t.points))
        for t in field.section.tracesAsList()
    ]
    mag = field.section.mag
    mw.checkActions()
    action = getattr(mw, act)
    assert action.isEnabled()

    action.trigger()
    qapp.processEvents()

    assert notices == ["Turn off the ROI box first."]
    assert recorder.dialogs == dialogs_before and recorder.notices == []
    assert field.section.mag == mag
    assert [
        (t.name, t.hidden, t.color, list(t.points))
        for t in field.section.tracesAsList()
    ] == traces_before


def test_object_list_commands_are_not_limited_by_the_box(mw, qapp, notices, monkeypatch):
    """With the object list focused, its own selection is used, box or not."""
    field = mw.field
    _turn_on(mw, qapp)

    class _List:
        table = QWidget()

        def getSelected(self):
            return ["d03"]

    monkeypatch.setattr(fwo, "ObjectTableWidget", _List)
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: _List())
    seen = []
    monkeypatch.setattr(
        fwo.FieldWidgetObject, "viewHistory",
        fwo.FieldWidgetObject.object_function(False, False)(
            lambda self, names: seen.append(names)
        ),
    )
    _List.table.verticalScrollBar = lambda: _Bar()

    field.viewHistory()
    assert notices == [] and seen == [["d03"]]


class _Bar:
    def value(self):
        return 0

    def setValue(self, v):
        pass


def test_section_wide_field_commands_refuse_while_the_box_is_on(mw, qapp, notices):
    field = mw.field
    outside = _trace(field.section, "d03sp14")
    outside.hidden = True
    _turn_on(mw, qapp)
    field.section.selected_traces = [_trace(field.section, "d03")]

    field.unhideAllTraces()
    assert outside.hidden
    field.hideOtherTraces()
    assert not _trace(field.section, "d03p14").hidden
    assert notices == ["Turn off the ROI box first."] * 2


def test_field_series_wide_visibility_rows_are_off_while_the_box_is_on(mw, qapp):
    field = mw.field
    field.visibility_snapshot = {"d03": {}}
    # the object rows are live with a selection
    field.section.selected_traces = [_trace(field.section, "d03")]
    mw.checkActions()
    assert mw.hideallobj_act.isEnabled() and mw.restorevisibility_act.isEnabled()

    _turn_on(mw, qapp)
    mw.checkActions()
    assert not mw.hideallobj_act.isEnabled()
    assert not mw.showallobj_act.isEnabled()
    assert not mw.restorevisibility_act.isEnabled()

    assert field.section.selected_traces  # d03 is inside
    mw.roibox_act.trigger()  # off
    mw.checkActions()
    assert mw.hideallobj_act.isEnabled() and mw.showallobj_act.isEnabled()


# --- round 2: Find -------------------------------------------------------------

def test_find_does_not_frame_a_trace_outside_the_box(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    field.section.selected_traces = [_trace(field.section, "d03")]
    window = list(field.series.window)

    field.findTrace("d03sp14")
    assert list(field.series.window) == window
    field.findContour("d03sp14")
    assert list(field.series.window) == window
    assert [t.name for t in field.section.selected_traces] == ["d03"]


def test_find_frames_only_the_inside_traces_of_a_contour(mw, qapp):
    field = mw.field
    outside = _outside_copy(field.section)
    _turn_on(mw, qapp)

    field.findContour("d03")

    x, y, w, h = field.series.window
    oxmin, _, oxmax, _ = outside.getBounds(field.section.tform)
    assert x + w < oxmin  # the moved copy is not framed
    assert outside not in field.section.selected_traces


# --- round 2: merged with the selected trace style ---------------------------

def test_trace_layer_keeps_both_initializations():
    layer = TraceLayer(None, None)
    assert layer.roi_box is None
    assert layer.selected_style_preview is None


# --- drag to set the center and size -------------------------------------------

def _move(field, qapp, p):
    """Move the mouse to pixel point p with the left button held."""
    QApplication.sendEvent(field, QMouseEvent(
        QEvent.MouseMove, QPointF(p), QPointF(field.mapToGlobal(p)),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier
    ))
    qapp.processEvents()


def _press_and_drag(field, qapp, start, end, past_click=True):
    """Press at pixel point start and move to end with the button held.

    past_click puts the press outside the field's single-click window
    (isSingleClicking), as a user's drag is."""
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, start)
    if past_click:
        field.click_time -= field.max_click_time + 1
    _move(field, qapp, end)


def _release(field, qapp, p):
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, p)
    qapp.processEvents()


def _drag(field, qapp, start, end):
    _press_and_drag(field, qapp, start, end)
    _release(field, qapp, end)


def _one_pixel(field):
    return field.series.window[2] / field.pixmap_dim[0]  # field units


def _yellow_pixels(field):
    image = field.grab().toImage()
    yellow = QColor(255, 255, 0).rgb()
    return sum(
        image.pixel(x, y) == yellow
        for x in range(0, image.width(), 2)
        for y in range(0, image.height(), 2)
    )


def test_a_click_sets_the_center_and_keeps_the_size(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp, center=None)

    _click(field, qapp, *CENTER)

    cx, cy = field.roi_box_center
    assert abs(cx - CENTER[0]) <= _one_pixel(field)
    assert abs(cy - CENTER[1]) <= _one_pixel(field)
    assert field.roi_box_size == SIZE


def test_movement_inside_the_click_window_is_a_click(mw, qapp):
    """The field's own click-versus-drag rule (isSingleClicking): a press
    released inside the single-click window is a click even if it moved. The
    center is the press point and the size is unchanged."""
    field = mw.field
    _turn_on(mw, qapp, center=None)
    start = _pix(field, *CENTER)
    end = start + QPoint(25, 15)

    _press_and_drag(field, qapp, start, end, past_click=False)
    _release(field, qapp, end)

    cx, cy = field.roi_box_center
    assert abs(cx - CENTER[0]) <= _one_pixel(field)
    assert abs(cy - CENTER[1]) <= _one_pixel(field)
    assert field.roi_box_size == SIZE


def test_drag_sets_center_and_size_in_field_units(mw, qapp):
    """Under a window and a section mag that are not the defaults, the box is
    the rectangle between the two field points, not pixels times a constant."""
    field = mw.field
    w = field.pixmap_dim[0]
    h = field.pixmap_dim[1]
    field.series.window = [12.9, 23.1, 2.0, 2.0 * h / w]
    field.section.mag = 0.0123
    field.generateView()
    traces_before = [list(t.points) for t in field.section.tracesAsList()]
    _turn_on(mw, qapp, center=None)

    _drag(field, qapp, _pix(field, 13.2, 23.9), _pix(field, 13.8, 23.5))

    one_pixel = _one_pixel(field)
    cx, cy = field.roi_box_center
    bw, bh = field.roi_box_size
    assert abs(cx - 13.5) <= one_pixel and abs(cy - 23.7) <= one_pixel
    assert abs(bw - 0.6) <= 2 * one_pixel and abs(bh - 0.4) <= 2 * one_pixel
    assert field.roiBox() == (cx, cy, bw, bh)

    # no other tool acted on the drag
    assert field.current_trace == [] and not field.is_selecting_traces
    assert [list(t.points) for t in field.section.tracesAsList()] == traces_before

    # the dragged size is the size from here on: a click keeps it
    _click(field, qapp, *CENTER)
    assert field.roi_box_size == (bw, bh)


@pytest.mark.parametrize("corners", [
    ((13.2, 23.9), (13.8, 23.5)),  # down and right
    ((13.8, 23.5), (13.2, 23.9)),  # up and left
    ((13.2, 23.5), (13.8, 23.9)),  # up and right
    ((13.8, 23.9), (13.2, 23.5)),  # down and left
])
def test_drag_works_in_any_direction(mw, qapp, corners):
    field = mw.field
    _turn_on(mw, qapp, center=None)

    _drag(field, qapp, _pix(field, *corners[0]), _pix(field, *corners[1]))

    one_pixel = _one_pixel(field)
    cx, cy = field.roi_box_center
    bw, bh = field.roi_box_size
    assert abs(cx - 13.5) <= one_pixel and abs(cy - 23.7) <= one_pixel
    assert abs(bw - 0.6) <= 2 * one_pixel and abs(bh - 0.4) <= 2 * one_pixel


def test_drag_draws_a_preview_without_changing_the_box(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp, center=None)
    yellow_before = _yellow_pixels(field)

    end = _pix(field, 13.8, 23.5)
    _press_and_drag(field, qapp, _pix(field, 13.2, 23.9), end)

    assert field.roiBox() is None and field.roi_box_size == SIZE
    assert _yellow_pixels(field) > yellow_before

    _release(field, qapp, end)
    assert field.roiBox() is not None


def test_escape_cancels_a_drag(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    box_before = field.roiBox()

    end = _pix(field, 14.3, 24.4)
    _press_and_drag(field, qapp, _pix(field, 13.2, 23.9), end)
    assert field.roi_box_drag_end is not None
    QTest.keyClick(field, Qt.Key_Escape)
    qapp.processEvents()
    assert field.roi_box_drag_start is None and field.roi_box_drag_end is None

    _release(field, qapp, end)
    assert field.roiBox() == box_before


def test_release_outside_the_field_ends_the_drag_at_the_edge(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp, center=None)
    start = _pix(field, *CENTER)

    _drag(field, qapp, start, QPoint(field.pixmap_dim[0] + 200, start.y() - 30))

    cx, _ = field.roi_box_center
    bw, _ = field.roi_box_size
    window = field.series.window
    assert abs((cx + bw / 2) - (window[0] + window[2])) <= _one_pixel(field)


def test_drag_writes_nothing_and_saves_no_undo_state(mw, qapp, monkeypatch):
    field = mw.field
    _turn_on(mw, qapp)
    mw.series.modified = False
    states = field.series_states[field.section.n]
    undo_before = len(states.undo_states)
    # every settings write during the drag, to QSettings (the suite's
    # isolated class) or to the series' settings store
    writes = []
    monkeypatch.setattr(
        QSettings, "setValue", lambda self, key, value: writes.append(key)
    )
    store = mw.series._settingsStore()
    monkeypatch.setattr(
        store, "set_value", lambda code, key, value: writes.append(key)
    )

    _drag(field, qapp, _pix(field, 13.2, 23.9), _pix(field, 13.8, 23.5))
    assert field.roi_box_size != SIZE  # the drag was a drag

    assert mw.series.modified is False
    assert len(states.undo_states) == undo_before
    assert not field.section.added_traces and not field.section.removed_traces
    assert writes == []


def test_section_change_mid_drag_clears_the_preview(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    box_before = field.roiBox()

    end = _pix(field, 14.3, 24.4)
    _press_and_drag(field, qapp, _pix(field, 13.2, 23.9), end)
    assert field.roi_box_drag_end is not None

    mw.incrementSection()  # PgUp with the button held
    qapp.processEvents()
    assert field.section.n != 52
    assert field.roi_box_drag_start is None and field.roi_box_drag_end is None

    _move(field, qapp, end + QPoint(10, 10))
    _release(field, qapp, end + QPoint(10, 10))
    assert field.roiBox() == box_before


class _Pinch:
    """The accessors `gestureEvent` reads off a `QPinchGesture`."""

    def __init__(self, state, x, y, scale):
        self._state, self._center, self._scale = state, QPointF(x, y), scale

    def state(self):
        return self._state

    def centerPoint(self):
        return self._center

    def totalScaleFactor(self):
        return self._scale


class _GestureEvent:
    def __init__(self, pinch):
        self._pinch = pinch

    def gesture(self, kind):
        return self._pinch


def test_a_pinch_mid_drag_ends_it_with_the_box_as_it_was(mw, qapp):
    field = mw.field
    _turn_on(mw, qapp)
    box_before = field.roiBox()

    end = _pix(field, 14.3, 24.4)
    _press_and_drag(field, qapp, _pix(field, 13.2, 23.9), end)
    for state, scale in (
        (Qt.GestureState.GestureStarted, 1.0),
        (Qt.GestureState.GestureUpdated, 1.5),
        (Qt.GestureState.GestureFinished, 1.5),
    ):
        field.gestureEvent(_GestureEvent(_Pinch(state, 200, 150, scale)))
    assert field.roi_box_drag_start is None and field.roi_box_drag_end is None

    _release(field, qapp, end)
    assert field.roiBox() == box_before


def test_the_context_menu_mid_drag_ends_it_with_the_box_as_it_was(mw, qapp, monkeypatch):
    field = mw.field
    _turn_on(mw, qapp)
    box_before = field.roiBox()
    previews = []
    monkeypatch.setattr(
        mw.field_menu, "exec",
        lambda *a, **kw: previews.append(field.roi_box_drag_end)
    )

    end = _pix(field, 14.3, 24.4)
    _press_and_drag(field, qapp, _pix(field, 13.2, 23.9), end)
    QTest.mousePress(field, Qt.RightButton, Qt.NoModifier, end)
    qapp.processEvents()
    assert previews == [None]  # no preview under the open menu

    QTest.mouseRelease(field, Qt.RightButton, Qt.NoModifier, end)
    _release(field, qapp, end)
    assert field.roiBox() == box_before


def _undo_mid_drag(mw, qapp, redo):
    """Start a drag, run Undo (or Redo), then move and release. The box must
    keep its center and size and the preview must be gone."""
    field = mw.field
    box_before = field.roiBox()

    end = _pix(field, 14.3, 24.4)
    _press_and_drag(field, qapp, _pix(field, 13.2, 23.9), end)
    assert field.roi_box_drag_end is not None

    mw.undo(redo=redo)
    qapp.processEvents()
    assert field.roi_box_drag_start is None and field.roi_box_drag_end is None

    _move(field, qapp, end + QPoint(10, 10))
    _release(field, qapp, end + QPoint(10, 10))
    assert field.roiBox() == box_before


@pytest.mark.parametrize("redo", [False, True], ids=["undo", "redo"])
def test_undo_with_the_trace_layer_hidden_mid_drag_ends_it(mw, qapp, redo):
    """With H on, undoState returns before endPendingEvents, so Undo itself
    has to end the drag."""
    field = mw.field
    field.deleteTraces([_trace(field.section, "d03p14")])
    field.saveState()  # a section undo state
    if redo:
        mw.undo()
    _turn_on(mw, qapp)
    field.toggleHideAllTraces()
    assert field.hide_trace_layer
    assert field.series_states.canUndo(redo=redo)[1]

    _undo_mid_drag(mw, qapp, redo)


@pytest.mark.parametrize("redo", [False, True], ids=["undo", "redo"])
def test_series_wide_undo_mid_drag_ends_it(mw, qapp, redo):
    """A series-wide Undo goes through seriesUndo, which never reaches
    endPendingEvents."""
    field = mw.field
    field.series_states.addState()
    if redo:
        mw.undo()
    _turn_on(mw, qapp)
    can_3D, can_2D, _ = field.series_states.canUndo(redo=redo)
    assert can_3D and not can_2D

    _undo_mid_drag(mw, qapp, redo)
