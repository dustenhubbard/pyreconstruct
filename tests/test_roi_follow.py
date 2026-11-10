"""ROI mode: a box that follows an object through the series.

Named in the ROI mode tool's options (the selected trace's name is offered),
the box keeps its size and is centered on the object on each section, from
the series data. On a section without the object it takes its place from the
nearest section with it, ties going to the earlier one, as the zarr crop
does; it is drawn orange there and the status bar names that section. View
only: nothing is written and no undo state is made.

Driven through the live `MainWindow` on the fixture series, where d03p14 is
on sections 52 to 56 and d03 on 3 to 184.
"""
import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QColor

from PyReconstruct.modules.backend.view import roi_follow as RF
from PyReconstruct.modules.datatypes import Transform
from test_roi_import_geometry import section_with_image  # noqa: F401  (fixture)
from PyReconstruct.modules.datatypes.series_data import ObjectData, TraceColumns
from PyReconstruct.modules.gui.main import field_widget_1_base as fwb

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def roi_mode_shown(monkeypatch):
    """ROI mode is hidden unless PYRECON_ROI_MODE=1; these tests drive it."""
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")


SIZE = (0.4, 0.4)


def _options(follow="", drag=True, size=SIZE, corner=False, whole=False):
    """A response to the ROI mode options dialog."""
    return [
        [("Drag to draw it, click to move it", drag),
         ("Click to place it at the set size", not drag)],
        size[0], size[1],
        [("Center", not corner), ("Upper-left corner", corner)],
        follow,
        [("Show all of any object that touches the box, on every section", whole)],
    ]


def _follow(mw, name, size=SIZE):
    mw.main_window_dialogs.responses.append((_options(follow=name, size=size), True))
    assert mw.field.setRoiBoxOptions()


def _go(mw, qapp, snum):
    mw.changeSection(snum)
    qapp.processEvents()
    assert mw.series.current_section == snum


def _center_on(mw, name, snum):
    return RF.objectCenters(mw.series, name, mw.field.displayTform)[snum]


@pytest.fixture
def mw(main_window, main_window_dialogs, qapp, local_series_settings):
    main_window.main_window_dialogs = main_window_dialogs
    local_series_settings(main_window)
    assert main_window.series.current_section == 52
    return main_window


@pytest.fixture
def notices(monkeypatch):
    shown = []
    monkeypatch.setattr(fwb, "notify", shown.append)
    return shown


# --- the rule, on its own -------------------------------------------------------

class _TD:
    def __init__(self, cx, cy, r, tform=None):
        self.centroid = (cx, cy)
        self.radius = r
        self._tform = tform or Transform.identity()


class _Series:
    def __init__(self, objects):
        self.data = {"objects": objects}


def _shown(snum):
    """Every section drawn with no transform."""
    return Transform.identity()


def _built(traces):
    obj = ObjectData()
    obj.traces = {snum: [_TD(*t) for t in ts] for snum, ts in traces.items()}
    return obj


def test_the_center_holds_every_trace_of_the_object_on_a_section():
    series = _Series({"a": _built({
        4: [(1.0, 1.0, 0.5)],
        5: [(0.0, 0.0, 1.0), (4.0, 2.0, 1.0)],  # a branch: two traces
    })})
    assert RF.objectCenters(series, "a", _shown) == {4: (1.0, 1.0), 5: (2.0, 1.0)}
    assert RF.objectCenters(series, "missing", _shown) == {}


def test_store_columns_give_the_same_centers_as_built_traces():
    import numpy as np
    arrays = {
        "snum": np.array([9, 4, 5, 5]),
        "cx": np.array([7.0, 1.0, 0.0, 4.0]),
        "cy": np.array([7.0, 1.0, 0.0, 2.0]),
        "radius": np.array([1.0, 0.5, 1.0, 1.0]),
        "tform": np.array([0, 0, 0, 0]),
    }
    columns = TraceColumns(arrays, [], [], [Transform.identity()])
    # rows 1 to 4 are this object's; row 0 belongs to another
    series = _Series({"a": ObjectData(columns, 1, 4)})
    assert RF.objectCenters(series, "a", _shown) == {4: (1.0, 1.0), 5: (2.0, 1.0)}
    # read from the columns: no TraceData were built
    assert series.data["objects"]["a"].columnRows() is not None


# a trace measured under its own alignment: raw points p, measured M(p)
MEASURED = Transform([2.0, 0.0, 1.0, 0.0, 2.0, -3.0])
# the series alignment the field draws with: D(p), sheared and moved
SHOWN = Transform([1.0, 0.5, 4.0, 0.0, 1.5, 2.0])
RAW = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def _measured(tform):
    """centroid and radius of RAW under a transform, as the series data
    stores them."""
    import numpy as np
    pts = tform.mapPointsArray(RAW)
    c = pts.mean(axis=0)
    return float(c[0]), float(c[1]), float(np.max(np.hypot(*(pts - c).T)))


def test_a_trace_measured_under_its_own_alignment_is_placed_where_it_is_drawn():
    series = _Series({"a": _built({7: [(*_measured(MEASURED), MEASURED)]})})
    snums, xmin, ymin, xmax, ymax = RF.objectExtents(series, "a", lambda s: SHOWN)

    drawn = SHOWN.mapPointsArray(RAW)
    # the square holds every drawn point, around the drawn centroid
    assert (xmin[0], ymin[0]) <= tuple(drawn.min(axis=0))
    assert (xmax[0], ymax[0]) >= tuple(drawn.max(axis=0))
    center = ((xmin[0] + xmax[0]) / 2, (ymin[0] + ymax[0]) / 2)
    assert center == pytest.approx(tuple(drawn.mean(axis=0)))
    assert RF.objectCenters(series, "a", lambda s: SHOWN)[7] == pytest.approx(center)


def test_columns_and_built_traces_move_the_same_way():
    import numpy as np
    cx, cy, r = _measured(MEASURED)
    arrays = {
        "snum": np.array([7]), "cx": np.array([cx]), "cy": np.array([cy]),
        "radius": np.array([r]), "tform": np.array([0]),
    }
    columns = TraceColumns(arrays, [], [], [MEASURED])
    stored = _Series({"a": ObjectData(columns, 0, 1)})
    built = _Series({"a": _built({7: [(cx, cy, r, MEASURED)]})})
    a = RF.objectExtents(stored, "a", lambda s: SHOWN)
    b = RF.objectExtents(built, "a", lambda s: SHOWN)
    for x, y in zip(a[1:], b[1:]):
        assert x == pytest.approx(y)


@pytest.mark.parametrize("snum, expected", [
    (5, (5, 5)), (6, (5, 5)), (7, (5, 5)), (8, (9, 9)), (1, (5, 5)), (20, (9, 9)),
])
def test_a_missing_section_takes_the_nearest_ties_to_the_earlier(snum, expected):
    centers = {5: (5, 5), 9: (9, 9)}
    center, source = RF.followCenter(centers, snum)
    assert center == expected
    assert source == (snum if snum in centers else (5 if expected == (5, 5) else 9))
    assert RF.nearestSection(centers, 7) == 5
    assert RF.followCenter({}, 3) is None


# --- in the window --------------------------------------------------------------

def test_a_pinned_alignment_follows_the_trace_as_drawn(mw, qapp):
    """The object is measured under its own alignment and the field draws it
    under the series alignment, moved 4 μm east here: the box goes where the
    trace is drawn."""
    field = mw.field
    alignments = {name: name for name in mw.series.alignments}
    alignments["pinned"] = mw.series.alignment
    mw.series.modifyAlignments(alignments)
    field.reload()
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    mw.series.setAttr("d03p14", "alignment", "pinned")
    field.section.align_locked = False
    field.section.selected_traces = []
    field.translateTform(4.0, 0.0)

    _follow(mw, "d03p14")

    assert field.roi_box_center == pytest.approx(trace.getCentroid(field.section.tform))
    # in a view around the box, the trace is drawn inside it
    field.series.window = [*(c - 1.0 for c in field.roi_box_center), 2.0, 2.0]
    field.generateView()
    assert "d03p14" in [t.name for t in field.section_layer.traces_in_view]


@pytest.mark.parametrize("size, dx, dy", [
    ((1.0, 1.0), 100, 20),
    # a small box, and a drag that takes the trace well past it
    ((0.4, 0.4), 220, 35),
])
def test_dragging_the_followed_object_moves_the_box_and_keeps_it_selected(
    mw, qapp, size, dx, dy
):
    from test_roi_box import _pix, _press_and_drag, _release
    field = mw.field
    _follow(mw, "d03p14", size=size)
    field.series.window = [*(c - 1.0 for c in field.roi_box_center), 2.0, 2.0]
    field.generateView()
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    field.section.selected_traces = [trace]
    mw.mouse_palette.activateModeButton("Pointer")
    start = _pix(field, *field.section.tform.map(*trace.points[0]))
    before = trace.getCentroid(field.section.tform)

    _press_and_drag(field, qapp, start, start + QPoint(dx, dy))
    _release(field, qapp, start + QPoint(dx, dy))

    (moved,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    after = moved.getCentroid(field.section.tform)
    assert after[0] > before[0] + 0.1
    assert field.roi_box_center == pytest.approx(after)
    assert field.section.selected_traces == [moved]
    assert "d03p14" in [t.name for t in field.section_layer.traces_in_view]

    # undo puts the trace and the box back; redo moves both again
    field.undoState()
    (back,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    assert back.getCentroid(field.section.tform) == pytest.approx(before)
    assert field.roi_box_center == pytest.approx(before)
    field.undoState(redo=True)
    assert field.roi_box_center == pytest.approx(after)


def test_the_shown_section_is_read_as_drawn_before_it_is_saved(mw, qapp):
    """An edit on the shown section moves the box at once, before the
    series data has it."""
    field = mw.field
    _follow(mw, "d03p14")
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    before = trace.getCentroid(field.section.tform)
    field.section.selected_traces = [trace]
    field.section.translateTraces(0.5, 0.0)
    field.generateView()
    assert field.roi_box_center == pytest.approx((before[0] + 0.5, before[1]))
    # the series data still has the old place until the save
    stored = RF.objectCenters(mw.series, "d03p14", field.displayTform)[52]
    assert stored == pytest.approx(before, abs=1e-5)


@pytest.mark.parametrize("end", ["pointer", "save"])
def test_a_scissors_pickup_keeps_following_an_object_on_one_section(
    mw, qapp, notices, end
):
    """Scissors holds the picked-up trace out of the section until the cut
    ends; the box keeps following it and no message says it is gone."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_roi_box import _pix
    from PyReconstruct.modules.datatypes import Trace
    field = mw.field
    square = [(13.3, 23.5), (13.7, 23.5), (13.7, 23.9), (13.3, 23.9)]
    assert field.newTrace(
        square, Trace("solo", (0, 255, 0)), points_as_pix=False, reduce_points=False,
    )
    assert mw.series.getObjectSections(["solo"]) == {52}
    _follow(mw, "solo", size=(1.0, 1.0))
    center = field.roi_box_center
    field.series.window = [12.5, 22.7, 2.0, 2.0]
    field.generateView()

    mw.mouse_palette.activateModeButton("Scissors")
    p = _pix(field, 13.3, 23.7)
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, p)
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, p)
    qapp.processEvents()
    assert field.is_scissoring
    assert not list(field.section.contours.get("solo", []))
    field.generateView()
    qapp.processEvents()
    assert field.roi_follow_name == "solo"
    assert field.roi_box_center == pytest.approx(center)

    if end == "pointer":
        mw.mouse_palette.activateModeButton("Pointer")
    else:
        mw.saveToJser()
    qapp.processEvents()
    field.generateView()
    qapp.processEvents()

    assert not field.is_scissoring
    assert list(field.section.contours.get("solo", []))
    assert field.roi_follow_name == "solo"
    assert field.roi_box_center == pytest.approx(center)
    assert notices == []


def test_a_scissors_pickup_with_a_same_name_palette_trace_keeps_the_box(
    mw, qapp, notices
):
    """The palette's template can share the object's name; only the trace
    Scissors took out of the section counts, from the pickup's own redraw."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_roi_box import _pix
    from PyReconstruct.modules.datatypes import Trace
    field = mw.field
    square = [(13.3, 23.5), (13.7, 23.5), (13.7, 23.9), (13.3, 23.9)]
    assert field.newTrace(
        square, Trace("solo", (0, 255, 0)), points_as_pix=False, reduce_points=False,
    )
    template = Trace("solo", (0, 255, 0))
    template.points = [(-4.0, -4.0), (-2.0, -4.0), (-2.0, -2.0), (-4.0, -2.0)]
    field.setTracingTrace(template)
    _follow(mw, "solo", size=(1.0, 1.0))
    center = field.roi_box_center
    field.series.window = [12.5, 22.7, 2.0, 2.0]
    field.generateView()

    mw.mouse_palette.activateModeButton("Scissors")
    p = _pix(field, 13.3, 23.7)
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, p)

    # the pickup's own redraw placed the box; nothing has drawn since
    assert field.is_scissoring
    assert field.roi_follow_name == "solo"
    assert field.roi_box_center == pytest.approx(center)

    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, p)
    mw.mouse_palette.activateModeButton("Pointer")
    qapp.processEvents()
    assert field.roi_box_center == pytest.approx(center)
    assert notices == []


def _drawn_center(field, name):
    """The middle of the range of an object's trace centroids, as drawn on
    the shown section, found without objectCenters."""
    import numpy as np
    cs = np.array([
        t.getCentroid(field.section.tform)
        for t in field.section.contours.get(name, ()) if t.points
    ])
    return (
        float((cs[:, 0].min() + cs[:, 0].max()) / 2),
        float((cs[:, 1].min() + cs[:, 1].max()) / 2),
    )


@pytest.fixture
def solo(mw, qapp):
    """Object "solo", one square on section 52, followed in a 0.4 μm box."""
    from PyReconstruct.modules.datatypes import Trace
    field = mw.field
    mw.series.setOption("auto_merge", False)
    mw.series.setOption("trace_mode", "poly")
    square = [(13.4, 23.6), (13.6, 23.6), (13.6, 23.8), (13.4, 23.8)]
    assert field.newTrace(
        square, Trace("solo", (255, 0, 0)), points_as_pix=False, reduce_points=False,
    )
    field.section.selected_traces = []
    template = Trace("solo", (255, 0, 0))
    template.points = [(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)]
    mw.mouse_palette.modifyPaletteButton(0, template)
    mw.mouse_palette.activatePaletteButton(0)
    _follow(mw, "solo", size=(0.4, 0.4))
    field.series.window = [12.5, 22.7, 2.0, 2.0]
    field.generateView()
    qapp.processEvents()
    return field


@pytest.mark.parametrize("tool", ["paste", "closed", "open", "stamp"])
def test_a_new_trace_inside_the_moved_box_stays_selected(mw, qapp, solo, notices, tool):
    """The new trace is outside the box's old place and inside its new one."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_roi_box import _pix
    field = solo
    (old,) = field.section.contours["solo"]
    if tool == "paste":
        field.section.selected_traces = [old]
        field.copy()
        field.section.selected_traces = []
        field.clipboard[0].points = [(x + 0.5, y) for x, y in field.clipboard[0].points]
        field.paste()
    elif tool == "stamp":
        mw.mouse_palette.activateModeButton("Stamp")
        QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, _pix(field, 14.0, 23.7))
    else:
        mw.mouse_palette.activateModeButton("Closed Trace" if tool == "closed" else "Open Trace")
        corners = [(13.9, 23.6), (14.1, 23.6), (14.1, 23.8), (13.9, 23.8)]
        for x, y in corners:
            QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, _pix(field, x, y))
        QTest.mouseClick(field, Qt.RightButton, Qt.NoModifier, _pix(field, *corners[-1]))
    qapp.processEvents()

    traces = list(field.section.contours["solo"])
    assert len(traces) == 2
    new = traces[-1]
    assert field.roi_box_center == pytest.approx(_drawn_center(field, "solo"))
    assert new in field.section.selected_traces
    assert new in field.section_layer.traces_in_view
    assert "outside the ROI mode box" not in mw.statusBar().currentMessage()
    assert notices == []


@pytest.mark.parametrize("order", [(0.0, 1.0, -1.0), (1.0, -1.0, 0.0)])
def test_a_paste_of_several_traces_keeps_each_one_inside_selected(mw, qapp, notices, order):
    """Three squares pasted in any order: the box moves once the paste is
    done, and the one that ends inside it stays selected."""
    from PyReconstruct.modules.datatypes import Trace
    field = mw.field
    mw.series.setOption("auto_merge", False)
    square = [(13.4, 23.6), (13.6, 23.6), (13.6, 23.8), (13.4, 23.8)]
    field.newTrace(square, Trace("batch", (255, 0, 0)), points_as_pix=False, reduce_points=False)
    mw.changeSection(53)
    for dx in order:
        field.newTrace(
            [(x + dx, y) for x, y in square], Trace("batch", (255, 0, 0)),
            points_as_pix=False, reduce_points=False,
        )
    field.section.selected_traces = list(field.section.contours["batch"])
    field.copy()
    assert len(field.clipboard) == 3
    mw.changeSection(52)
    _follow(mw, "batch")
    field.series.window = [12.5, 22.7, 2.0, 2.0]
    field.generateView()
    field.section.selected_traces = []

    field.paste()
    qapp.processEvents()

    traces = list(field.section.contours["batch"])
    assert len(traces) == 4
    assert field.roi_box_center == pytest.approx((13.5, 23.7))
    inside = [t for t in traces[1:] if abs(t.getCentroid(field.section.tform)[0] - 13.5) < 0.01]
    assert len(inside) == 1
    assert inside[0] in field.section_layer.traces_in_view
    assert inside[0] in field.section.selected_traces
    assert all(field.inRoiBox(t) for t in field.section.selected_traces)
    assert notices == []


def test_a_grid_places_the_followed_box_once(mw, qapp, monkeypatch):
    """A 20 by 20 grid of the followed object is one operation: the box is
    placed once, from the finished grid, and every cell is drawn."""
    from PyReconstruct.modules.calc import fieldPointToPixmap
    from PyReconstruct.modules.datatypes import Trace
    from PyReconstruct.modules.gui.main import field_widget_1_base as fwb
    field = mw.field
    mw.series.setOption("auto_merge", False)
    mw.series.setOption("sampling_frame_grid", False)
    _follow(mw, "d03p14", size=(1.0, 1.0))
    center = field.roi_box_center
    field.series.window = [center[0] - 1, center[1] - 1, 2.0, 2.0]
    field.generateView()
    template = Trace("d03p14", (255, 0, 0))
    template.points = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    p = fieldPointToPixmap(*center, field.series.window, field.pixmap_dim, field.section.mag)
    calls = []
    real = fwb.objectCenters
    monkeypatch.setattr(fwb, "objectCenters", lambda *a, **k: calls.append(1) or real(*a, **k))

    assert field.placeGrid(*p, template, 0.02, 0.02, 0.03, 0.03, 20, 20)

    assert len(calls) == 1
    traces = list(field.section.contours["d03p14"])
    assert len(traces) == 401
    assert all(t in field.section_layer.traces_in_view for t in traces)


@pytest.mark.parametrize("order", [(0.0, 1.0, -1.0), (1.0, -1.0, 0.0)])
def test_a_composite_roi_import_keeps_each_shape_inside_selected(
    mw, qapp, notices, section_with_image, tmp_path, monkeypatch, order  # noqa: F811  (fixture)
):
    """Three square outlines in one ImageJ .roi file, in any order: the
    import is one operation, so the box is placed once, from the imported
    shapes, and the one inside it stays selected. Each shape keeps its own
    undo step."""
    from PyReconstruct.modules.datatypes import Trace
    from PyReconstruct.modules.gui.main import field_widget_1_base as fwb
    from test_roi_import_geometry import _write_composite
    field = mw.field
    mw.series.setOption("auto_merge", False)
    field.section.tform = Transform.identity()
    mag = field.section.mag
    fp = _write_composite(
        tmp_path / "imported.roi", *[(100 + dx / mag, 100, 0.2 / mag) for dx in order]
    )
    # a seed of the same object where the middle square lands
    x, y = 100 * mag, 300 * mag
    field.newTrace(
        [(x, y), (x + 0.2, y), (x + 0.2, y - 0.2), (x, y - 0.2)],
        Trace("imported", (255, 0, 0)), points_as_pix=False, reduce_points=False,
    )
    (seed,) = field.section.contours["imported"]
    center = seed.getCentroid(field.section.tform)
    _follow(mw, "imported")
    field.series.window = [center[0] - 2, center[1] - 2, 4.0, 4.0]
    field.generateView()
    field.section.selected_traces = []
    calls = []
    real = fwb.objectCenters
    monkeypatch.setattr(fwb, "objectCenters", lambda *a, **k: calls.append(1) or real(*a, **k))
    mw.main_window_dialogs.file_responses.append([fp])

    mw.importROIFiles()

    assert len(calls) == 1
    traces = list(field.section.contours["imported"])
    assert len(traces) == 4
    assert field.roi_box_center == pytest.approx(center, abs=1e-5)
    middle = min(traces[1:], key=lambda t: abs(t.getCentroid(field.section.tform)[0] - center[0]))
    assert middle in field.section_layer.traces_in_view
    assert middle in field.section.selected_traces
    for _ in range(3):
        mw.undo()
    assert len(list(field.section.contours["imported"])) == 1
    assert notices == []


@pytest.mark.parametrize("trace_mode", ["poly", "pencil", "rect-release-only", "rect-small-move"])
def test_a_draw_and_its_auto_merge_are_one_operation(mw, qapp, notices, monkeypatch, trace_mode):
    """A closed trace drawn over the selected followed square merges into
    it; the box is placed once, after the merge, on the merged trace, which
    stays selected."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_roi_box import _move, _pix
    from PyReconstruct.modules.datatypes import Trace
    from PyReconstruct.modules.gui.main import field_widget_1_base as fwb
    field = mw.field
    mw.series.setOption("auto_merge", True)
    mw.series.setOption("trace_mode", "combo" if trace_mode.startswith("rect-") else trace_mode)
    mw.series.setOption("roll_average", False)
    field.newTrace(
        [(13.4, 23.6), (13.6, 23.6), (13.6, 23.8), (13.4, 23.8)],
        Trace("drawn", (255, 0, 0)), points_as_pix=False, reduce_points=False,
    )
    _follow(mw, "drawn")
    field.series.window = [12.5, 22.7, 2.0, 2.0]
    field.generateView()
    # with the ROI box on, only selected traces merge
    field.section.selected_traces = list(field.section.contours["drawn"])
    template = Trace("drawn", (255, 0, 0))
    template.points = [(-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)]
    mw.mouse_palette.modifyPaletteButton(0, template)
    mw.mouse_palette.activatePaletteButton(0)
    mw.mouse_palette.activateModeButton("Closed Trace")
    calls = []
    real = fwb.objectCenters
    monkeypatch.setattr(fwb, "objectCenters", lambda *a, **k: calls.append(1) or real(*a, **k))

    corners = [(13.5, 23.6), (13.9, 23.6), (13.9, 23.8), (13.5, 23.8)]
    if trace_mode == "poly":
        for x, y in corners:
            QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, _pix(field, x, y))
        QTest.mouseClick(field, Qt.RightButton, Qt.NoModifier, _pix(field, *corners[-1]))
    else:
        start = _pix(field, *corners[0])
        if trace_mode.startswith("rect-"):
            field.closed_trace_shape = "rect"
        QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, start)
        if trace_mode == "pencil":
            for x, y in corners[1:]:
                _move(field, qapp, _pix(field, x, y))
        elif trace_mode == "rect-small-move":
            _move(field, qapp, start + QPoint(1, 1))
        end = corners[2] if trace_mode.startswith("rect-") else corners[-1]
        QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, _pix(field, *end))
    qapp.processEvents()

    (merged,) = list(field.section.contours["drawn"])
    assert max(x for x, _ in field.section.tform.map(merged.points)) == pytest.approx(
        13.9, abs=field.series.screen_mag
    )
    assert len(calls) == 1
    assert field.roi_box_center == pytest.approx(_drawn_center(field, "drawn"))
    assert field.section.selected_traces == [merged]
    assert notices == []


def test_a_borrowed_place_matches_its_source_under_a_nonuniform_alignment(mw, qapp, notices):
    """Two traces of different sizes, measured under a pinned identity
    alignment and drawn under one that scales x by 0.1 and y by 3: section
    51 borrows exactly the place section 52 shows."""
    from PyReconstruct.modules.datatypes import Trace
    field = mw.field
    for corners in (
        [(10.0, 20.0), (14.0, 20.0), (14.0, 20.2), (10.0, 20.2)],
        [(20.0, 20.0), (20.2, 20.0), (20.2, 20.2), (20.0, 20.2)],
    ):
        t = Trace("pair", (255, 0, 0))
        t.points = corners
        field.section.addTrace(t)
        field.saveState()
    for n in mw.series.sections:
        section = field.section if n == field.section.n else mw.series.loadSection(n)
        section.tforms["pin"] = Transform.identity()
        section.tforms["shown"] = Transform([0.1, 0.0, 0.0, 0.0, 3.0, 0.0])
        section.save()
    mw.series.setAttr("pair", "alignment", "pin")
    mw.saveAllData()
    mw.createContextMenus()
    mw.changeAlignment("shown")
    _follow(mw, "pair")

    source = _drawn_center(field, "pair")
    assert field.roi_box_center == pytest.approx(source)
    mw.changeSection(51)
    qapp.processEvents()
    assert field.roi_follow_name == "pair" and field.roi_follow_from == 52
    assert field.roi_box_center == pytest.approx(source)
    assert notices == []


def test_a_redraw_during_a_series_data_refresh_keeps_following(mw, qapp, notices):
    """A refresh empties the series data and lets events run while it adds
    the sections back; a redraw then must not decide the object is gone."""
    from PySide6.QtCore import QTimer
    field = mw.field
    _follow(mw, "d03p14")
    mw.changeSection(51)
    qapp.processEvents()
    field.openList("object")
    qapp.processEvents()
    QTimer.singleShot(0, lambda: mw.resize(mw.width() + 10, mw.height() + 10))
    field.table_manager.refresh()
    qapp.processEvents()

    assert "d03p14" in mw.series.data["objects"]
    assert field.roi_follow_name == "d03p14" and field.roi_follow_from == 52
    assert notices == []


def test_an_incomplete_series_data_leaves_the_box_where_it_is(mw, qapp, notices):
    field = mw.field
    _follow(mw, "d03p14")
    center = field.roi_box_center
    saved = mw.series.data.data
    mw.series.data.data = {"sections": {}, "objects": {}}
    contour = field.section.contours.pop("d03p14")
    try:
        field.generateView()
        qapp.processEvents()
        assert field.roi_follow_name == "d03p14"
        assert field.roi_box_center == center
        assert notices == []
    finally:
        mw.series.data.data = saved
        field.section.contours["d03p14"] = contour


def test_the_selected_trace_is_offered_to_follow(mw, qapp, monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_7_view as fwv
    field = mw.field
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    field.section.selected_traces = [trace]
    seen = []

    def get(parent, structure, title, *args, **kwargs):
        seen.append(structure)
        return None, False

    monkeypatch.setattr(fwv.QuickDialog, "get", staticmethod(get))
    field.setRoiBoxOptions()

    (structure,) = seen
    (combo,) = [
        i for row in structure for i in row if isinstance(i, tuple) and i[0] == "combo"
    ]
    assert combo[0] == "combo" and combo[2] == "d03p14"
    assert "d03p14" in combo[1] and "d03" in combo[1]


def test_following_centers_the_box_on_the_object_on_every_section(mw, qapp):
    field = mw.field
    _follow(mw, "d03p14")
    assert field.roi_box_on and field.roi_follow_name == "d03p14"
    assert field.roiBox() == (*_center_on(mw, "d03p14", 52), *SIZE)
    assert "d03p14" in [t.name for t in field.section_layer.traces_in_view]

    _go(mw, qapp, 55)
    assert field.roi_box_center == _center_on(mw, "d03p14", 55)
    assert field.roi_follow_from == 55
    field.updateStatusBar()
    text = mw.status_readout.text()
    assert "ROI mode 0.4 x 0.4 μm, following d03p14" in text
    assert "not on this section" not in text


@pytest.mark.parametrize("snum, source", [(58, 56), (51, 52), (3, 52)])
def test_a_section_without_the_object_borrows_the_nearest_place(mw, qapp, snum, source):
    field = mw.field
    _follow(mw, "d03p14")
    _go(mw, qapp, snum)

    assert field.roi_box_center == _center_on(mw, "d03p14", source)
    assert field.roi_follow_from == source
    field.updateStatusBar()
    assert (
        f"following d03p14 (not on this section; placed as on section {source})"
        in mw.status_readout.text()
    )


def _pixels(field, rgb):
    image = field.grab().toImage()
    color = QColor(*rgb).rgb()
    return sum(
        image.pixel(x, y) == color
        for x in range(0, image.width(), 2)
        for y in range(0, image.height(), 2)
    )


def test_a_borrowed_place_is_drawn_orange(mw, qapp):
    field = mw.field
    _follow(mw, "d03p14", size=(1.0, 1.0))
    field.series.window = [*(c - 1.0 for c in field.roi_box_center), 2.0, 2.0]
    field.generateView()
    assert _pixels(field, (255, 165, 0)) == 0

    _go(mw, qapp, 57)
    field.series.window = [*(c - 1.0 for c in field.roi_box_center), 2.0, 2.0]
    field.generateView()
    assert _pixels(field, (255, 165, 0)) > 0


def test_placing_the_box_with_the_tool_or_turning_it_off_ends_following(mw, qapp):
    from test_roi_box import _click
    field = mw.field
    _follow(mw, "d03p14")
    mw.mouse_palette.activateModeButton("ROI mode")
    _click(field, qapp, 13.5, 23.7)
    assert field.roi_follow_name is None
    assert abs(field.roi_box_center[0] - 13.5) < 0.05

    _follow(mw, "d03p14")
    field.toggleRoiBox()
    assert not field.roi_box_on and field.roi_follow_name is None

    # a blank name in the options ends following and keeps the box
    _follow(mw, "d03p14")
    center = field.roi_box_center
    _follow(mw, "")
    assert field.roi_box_on and field.roi_follow_name is None
    assert field.roi_box_center == center


def test_an_object_no_section_has_stops_following_with_a_message(mw, qapp, notices):
    field = mw.field
    _follow(mw, "d03p14")
    center = field.roi_box_center
    # gone from the series data and from the shown section
    data = mw.series.data["objects"].pop("d03p14")
    contour = field.section.contours.pop("d03p14")
    try:
        field.generateView()
        qapp.processEvents()
    finally:
        mw.series.data["objects"]["d03p14"] = data
        field.section.contours["d03p14"] = contour
    assert field.roi_follow_name is None and field.roi_box_on
    assert field.roi_box_center == center
    assert notices == ["No section has d03p14 now, so the ROI mode box stopped following it."]


def test_following_writes_nothing_and_saves_no_undo_state(mw, qapp):
    field = mw.field
    mw.series.modified = False
    states = field.series_states[field.section.n]
    undo_before = len(states.undo_states)
    settings_before = set(QSettings("KHLab", "PyReconstruct").allKeys())

    _follow(mw, "d03p14")
    _go(mw, qapp, 53)
    _go(mw, qapp, 52)
    field.toggleRoiBox()

    assert mw.series.modified is False
    assert len(field.series_states[52].undo_states) == undo_before
    assert set(QSettings("KHLab", "PyReconstruct").allKeys()) == settings_before
