"""The ROI box: a view-only box in field coordinates.

A click sets the box's center; its width and height are set in a dialog. Only
the traces whose bounds in field coordinates touch the box are drawn and can be
picked; turning the box off brings every trace back. Nothing is written to the
traces, the sections or the series, and no undo state is made.

Driven through the live `MainWindow` on the fixture series. Section 52 has
three traces: d03 (field bounds about 13.15-14.27 x 23.34-24.50) and two small
ones east of x = 14.15, d03p14 and d03sp14. Section 53, one PgUp away, has the
same three a little shifted. The default box below covers part of d03 only.
"""
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.backend.view.trace_layer import (
    boundsOverlap,
    roiBoxBounds,
    traceInRoiBox,
)
from PyReconstruct.modules.calc import fieldPointToPixmap
from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.gui.main.field_widget_5_mouse import POINTER, ROI_BOX

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
    assert "ROI box 5 x 5 μm: click to place" in mw.status_readout.text()

    _click(field, qapp, *CENTER)
    field.updateStatusBar()
    text = mw.status_readout.text()
    assert "ROI box 5 x 5 μm" in text and "click to place" not in text

    mw.roibox_act.trigger()
    field.updateStatusBar()
    assert "ROI box" not in mw.status_readout.text()
