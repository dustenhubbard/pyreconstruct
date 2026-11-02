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
from PyReconstruct.modules.datatypes.series_data import ObjectData, TraceColumns
from PyReconstruct.modules.gui.main import field_widget_1_base as fwb

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def roi_mode_shown(monkeypatch):
    """ROI mode is hidden unless PYRECON_ROI_MODE=1; these tests drive it."""
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")


SIZE = (0.4, 0.4)


def _options(follow="", drag=True, size=SIZE, corner=False):
    """A response to the ROI mode options dialog."""
    return [
        [("Drag to draw it, click to move it", drag),
         ("Click to place it at the set size", not drag)],
        size[0], size[1],
        [("Center", not corner), ("Upper-left corner", corner)],
        follow,
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
def mw(main_window, main_window_dialogs, qapp):
    main_window.main_window_dialogs = main_window_dialogs
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
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    field.section.tforms["pinned"] = field.section.tform.copy()
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


def test_dragging_the_followed_object_moves_the_box_with_it(mw, qapp):
    from test_roi_box import _pix, _press_and_drag, _release
    field = mw.field
    _follow(mw, "d03p14", size=(1.0, 1.0))
    field.series.window = [*(c - 1.0 for c in field.roi_box_center), 2.0, 2.0]
    field.generateView()
    (trace,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    field.section.selected_traces = [trace]
    mw.mouse_palette.activateModeButton("Pointer")
    start = _pix(field, *field.section.tform.map(*trace.points[0]))
    before = trace.getCentroid(field.section.tform)

    _press_and_drag(field, qapp, start, start + QPoint(100, 20))
    _release(field, qapp, start + QPoint(100, 20))

    (moved,) = [t for t in field.section.tracesAsList() if t.name == "d03p14"]
    assert moved.getCentroid(field.section.tform)[0] > before[0] + 0.1
    assert field.roi_box_center == pytest.approx(moved.getCentroid(field.section.tform))
    assert "d03p14" in [t.name for t in field.section_layer.traces_in_view]


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
    combo = [i for row in structure for i in row if isinstance(i, tuple)][-1]
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
    data = mw.series.data["objects"].pop("d03p14")
    try:
        field.generateView()
        qapp.processEvents()
    finally:
        mw.series.data["objects"]["d03p14"] = data
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
