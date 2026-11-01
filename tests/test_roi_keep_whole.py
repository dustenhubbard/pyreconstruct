"""ROI mode: keep whole every object that crosses the box's edge.

With "Show all of any object that touches the box, on every section" in the
ROI mode tool's options, an object with a trace touching the box on any
section has every trace shown on every section, inside the box or not. So a
small box still shows the whole of each object that reaches it. Which traces
touch is read from the series data (centroid and radius) for every section,
with the box placed there as it is drawn there. View only.

Driven through the live `MainWindow` on the fixture series, starting on
section 52 (d03, d03p14, d03sp14).
"""
import pytest
from PySide6.QtCore import QSettings

from PyReconstruct.modules.backend.view.trace_layer import roiBoxBounds

from PyReconstruct.modules.backend.view import roi_follow as RF
from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.datatypes.series_data import ObjectData, TraceColumns

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def roi_mode_shown(monkeypatch):
    """ROI mode is hidden unless PYRECON_ROI_MODE=1; these tests drive it."""
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")


# --- the rule, on its own -------------------------------------------------------

class _TD:
    def __init__(self, cx, cy, r):
        self.centroid = (cx, cy)
        self.radius = r
        self._tform = Transform.identity()


def _plain(snum):
    """Every section drawn with no transform."""
    return Transform.identity()


class _Series:
    def __init__(self, objects):
        self.data = {"objects": objects}


def _built(traces):
    obj = ObjectData()
    obj.traces = {snum: [_TD(*t) for t in ts] for snum, ts in traces.items()}
    return obj


BOX = (0.0, 0.0, 1.0, 1.0)


def test_an_object_touching_the_box_on_any_section_is_kept():
    series = _Series({
        "near": _built({1: [(5.0, 5.0, 0.5)], 2: [(1.2, 0.5, 0.3)]}),  # touches on 2
        "far": _built({1: [(5.0, 5.0, 0.5)], 2: [(3.0, 3.0, 0.5)]}),
        "inside": _built({1: [(0.5, 0.5, 0.1)]}),
    })
    boxes = {1: BOX, 2: BOX}
    assert RF.objectsTouching(series, boxes, _plain) == {"near", "inside"}
    # a section with no box keeps nothing
    assert RF.objectsTouching(series, {1: BOX}, _plain) == {"inside"}
    assert RF.objectsTouching(series, {}, _plain) == frozenset()


def test_the_box_can_differ_by_section():
    series = _Series({"a": _built({1: [(5.0, 5.0, 0.1)]})})
    assert RF.objectsTouching(series, {1: BOX}, _plain) == frozenset()
    assert RF.objectsTouching(series, {1: (4.5, 4.5, 5.5, 5.5)}, _plain) == {"a"}


def test_store_columns_count_the_same_as_built_traces():
    import numpy as np
    arrays = {
        "snum": np.array([1, 2, 1]),
        "cx": np.array([5.0, 1.2, 0.5]),
        "cy": np.array([5.0, 0.5, 0.5]),
        "radius": np.array([0.5, 0.3, 0.1]),
        "tform": np.array([0, 0, 0]),
    }
    columns = TraceColumns(arrays, [], [], [Transform.identity()])
    series = _Series({
        "near": ObjectData(columns, 0, 2),
        "inside": ObjectData(columns, 2, 3),
    })
    assert RF.objectsTouching(series, {1: BOX, 2: BOX}, _plain) == {"near", "inside"}
    assert series.data["objects"]["near"].columnRows() is not None


# --- in the window --------------------------------------------------------------

CENTER = (13.5, 23.7)
SIZE = (0.4, 0.4)


def _options(whole, follow=""):
    return [
        [("Drag to draw it, click to move it", True),
         ("Click to place it at the set size", False)],
        SIZE[0], SIZE[1],
        [("Center", True), ("Upper-left corner", False)],
        follow,
        [("Show all of any object that touches the box, on every section", whole)],
    ]


def _set(mw, whole, follow=""):
    mw.main_window_dialogs.responses.append((_options(whole, follow), True))
    assert mw.field.setRoiBoxOptions()


def _copy_as(mw, src_name, new_name, dx):
    """Add a copy of a trace on the shown section, named new_name and moved
    dx field units east, and update the series data as a save would."""
    section = mw.field.section
    tform = section.tform
    (src,) = [t for t in section.tracesAsList() if t.name == src_name]
    copy = src.copy()
    copy.name = new_name
    copy.points = [
        tform.map(tform.map(*p)[0] + dx, tform.map(*p)[1], inverted=True)
        for p in src.points
    ]
    section.addTrace(copy)
    mw.series.data.updateSection(section, update_traces=True)
    return copy


def _shown(field):
    return sorted({t.name for t in field.section_layer.traces_in_view})


@pytest.fixture
def mw(main_window, main_window_dialogs, qapp):
    main_window.main_window_dialogs = main_window_dialogs
    assert main_window.series.current_section == 52
    # x1 crosses the box on section 52 and is far from it on section 53
    _copy_as(main_window, "d03", "x1", 0.0)
    main_window.changeSection(53)
    qapp.processEvents()
    _copy_as(main_window, "d03", "x1", 3.0)
    return main_window


def _place(mw, qapp):
    from test_roi_box import _click
    field = mw.field
    field.roi_box_size = SIZE
    mw.mouse_palette.activateModeButton("ROI mode")
    _click(field, qapp, *CENTER)


def test_off_a_trace_far_from_the_box_is_hidden(mw, qapp):
    _place(mw, qapp)
    assert "x1" not in _shown(mw.field)
    assert mw.field.roiKeep() is None


def test_on_an_object_that_crosses_the_box_elsewhere_is_shown_whole(mw, qapp):
    field = mw.field
    _place(mw, qapp)
    _set(mw, whole=True)

    assert "x1" in field.roiKeep() and "d03" in field.roiKeep()
    assert "x1" in _shown(field)
    (far,) = [t for t in field.section.tracesAsList() if t.name == "x1"]
    assert field.inRoiBox(far)
    field.updateStatusBar()
    assert "ROI mode 0.4 x 0.4 μm, whole objects" in mw.status_readout.text()

    # the option off again hides it
    _set(mw, whole=False)
    assert "x1" not in _shown(field)


def test_a_followed_box_keeps_whole_what_it_touches_where_it_is(mw, qapp):
    field = mw.field
    _set(mw, whole=True, follow="d03")
    keep = field.roiKeep()
    assert "d03" in keep
    # every kept object touches the followed box on some section
    centers = RF.objectCenters(mw.series, "d03", field.displayTform)
    for name in keep:
        boxes = {
            snum: (c[0] - 0.2, c[1] - 0.2, c[0] + 0.2, c[1] + 0.2)
            for snum in mw.series.sections
            for c in [RF.followCenter(centers, snum)[0]]
        }
        assert RF.objectsTouching(mw.series, boxes, field.displayTform) >= {name}


def test_the_names_are_found_once_per_box(mw, qapp, monkeypatch):
    field = mw.field
    _place(mw, qapp)
    _set(mw, whole=True)
    calls = []
    real = RF.objectsTouching
    from PyReconstruct.modules.gui.main import field_widget_1_base as fwb
    monkeypatch.setattr(fwb, "objectsTouching", lambda *a: calls.append(1) or real(*a))

    field.generateView()
    field.generateView()
    assert calls == []
    from test_roi_box import _click
    _click(field, qapp, 13.6, 23.8)  # moved: found again
    assert len(calls) == 1


def _go(mw, qapp, snum):
    mw.changeSection(snum)
    qapp.processEvents()


def _fresh(mw):
    """The kept objects found from scratch for the box as it is now."""
    field = mw.field
    bounds = roiBoxBounds(field.roiBox())
    boxes = {snum: bounds for snum in mw.series.sections}
    return RF.objectsTouching(mw.series, boxes, field.displayTform)


def test_deleting_the_only_contact_lets_the_object_go(mw, qapp):
    field = mw.field
    _place(mw, qapp)
    _set(mw, whole=True)
    assert "x1" in field.roiKeep()

    _go(mw, qapp, 52)
    (contact,) = [t for t in field.section.tracesAsList() if t.name == "x1"]
    field.section.selected_traces = [contact]
    field.deleteTraces()
    _go(mw, qapp, 53)

    assert "x1" not in _fresh(mw)
    assert "x1" not in field.roiKeep()
    assert "x1" not in _shown(field)


def test_a_new_contact_shows_the_object_elsewhere(mw, qapp):
    field = mw.field
    _copy_as(mw, "d03", "x2", 3.0)  # far from the box on 53
    _place(mw, qapp)
    _set(mw, whole=True)
    assert "x2" not in field.roiKeep()

    _go(mw, qapp, 52)
    assert field.newTrace(
        [(13.45, 23.65), (13.55, 23.65), (13.5, 23.75)],
        Trace("x2", (255, 0, 0)),
        points_as_pix=False, reduce_points=False,
    )
    _go(mw, qapp, 53)

    assert "x2" in _fresh(mw)
    assert "x2" in _shown(field)

    # an undo of the new trace lets the object go again
    _go(mw, qapp, 52)
    field.undoState()
    _go(mw, qapp, 53)
    assert "x2" not in _fresh(mw)
    assert "x2" not in _shown(field)


def test_a_pinned_alignment_counts_where_the_trace_is_drawn(mw, qapp):
    """x1 is measured under its own alignment and drawn under the series
    alignment, moved 10 μm east: a box on the drawn trace keeps it whole."""
    field = mw.field
    _go(mw, qapp, 52)
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "x1"]
    field.section.tforms["pinned"] = field.section.tform.copy()
    mw.series.setAttr("x1", "alignment", "pinned")
    field.section.align_locked = False
    field.section.selected_traces = []
    field.translateTform(10.0, 0.0)
    field.roi_box_on = True
    field.roi_box_center = trace.getCentroid(field.section.tform)
    field.roi_box_size = (0.4, 0.4)
    _set(mw, whole=True)

    assert field.inRoiBox(trace)
    assert "x1" in field.roiKeep()


def test_keeping_whole_writes_nothing_and_saves_no_undo_state(mw, qapp):
    field = mw.field
    mw.series.modified = False
    states = field.series_states[field.section.n]
    undo_before = len(states.undo_states)
    settings_before = set(QSettings("KHLab", "PyReconstruct").allKeys())

    _place(mw, qapp)
    _set(mw, whole=True)
    field.toggleRoiBox()

    assert mw.series.modified is False
    assert len(states.undo_states) == undo_before
    assert set(QSettings("KHLab", "PyReconstruct").allKeys()) == settings_before
