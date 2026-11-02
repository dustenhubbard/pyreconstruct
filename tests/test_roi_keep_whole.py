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


def _count_passes(monkeypatch):
    """Count the series-wide passes the field runs."""
    calls = []
    real = RF.SeriesSquares.touching
    monkeypatch.setattr(
        RF.SeriesSquares, "touching", lambda self, *a: calls.append(1) or real(self, *a)
    )
    return calls


def _count_reads(monkeypatch):
    """Count the reads of every trace in the series data."""
    calls = []
    real = RF.SeriesSquares.fromSeries.__func__
    monkeypatch.setattr(
        RF.SeriesSquares, "fromSeries",
        classmethod(lambda cls, series: calls.append(1) or real(cls, series)),
    )
    return calls


def test_the_names_are_found_once_per_box(mw, qapp, monkeypatch):
    field = mw.field
    _place(mw, qapp)
    _set(mw, whole=True)
    calls = _count_passes(monkeypatch)

    field.generateView()
    field.generateView()
    assert calls == []
    from test_roi_box import _click
    _click(field, qapp, 13.6, 23.8)  # moved: found again
    assert len(calls) == 1


@pytest.mark.parametrize("follow", ["", "d03"])
def test_paging_reuses_the_series_pass(mw, qapp, monkeypatch, follow):
    """Changing sections with no edit runs no new series-wide pass, with a
    fixed box or a followed one, and the kept objects are the same."""
    field = mw.field
    _place(mw, qapp)
    _set(mw, whole=True, follow=follow)
    keep = field.roiKeep()
    calls = _count_passes(monkeypatch)

    for snum in (52, 54, 53, 51):
        _go(mw, qapp, snum)
    assert calls == []
    _go(mw, qapp, 53)
    assert field.roiKeep() == keep


def test_one_series_pass_handles_many_objects_in_store_columns():
    """Many objects in one block of store columns take one pass, and each
    object counts only its own rows."""
    import numpy as np
    n = 5000
    arrays = {
        "snum": np.repeat(np.array([1, 2]), n),
        "cx": np.concatenate([np.arange(n) * 10.0, np.arange(n) * 10.0 + 5.0]),
        "cy": np.zeros(2 * n),
        "radius": np.full(2 * n, 0.5),
        "tform": np.zeros(2 * n, dtype=int),
    }
    columns = TraceColumns(arrays, [], [], [Transform.identity()])
    objects = {}
    for i in range(n):
        obj = ObjectData(columns, i, i + 1)  # object i: its trace on section 1
        objects[f"o{i}"] = obj
    # rows n.. (section 2) belong to no object here and are not read
    series = _Series(objects)
    box = (95.0, -1.0, 105.0, 1.0)  # around x = 100, on both sections
    found = RF.touchingSections(series, {1: box, 2: box}, _plain)
    assert found == {"o10": frozenset({1})}


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


def test_dragging_the_last_contact_out_of_the_box_lets_the_object_go(mw, qapp):
    from PySide6.QtCore import QPoint
    from test_roi_box import _pix, _press_and_drag, _release
    field = mw.field
    _place(mw, qapp)
    for dx in (0.0, 3.0):  # one triangle in the box, one 3 μm east
        assert field.newTrace(
            [(13.45 + dx, 23.65), (13.55 + dx, 23.65), (13.5 + dx, 23.75)],
            Trace("r2", (255, 0, 0)),
            points_as_pix=False, reduce_points=False,
        )
    _set(mw, whole=True)
    field.series.window = [12.9, 22.7, 4.5, 2.0]
    field.generateView()
    assert "r2" in field.roiKeep() and "r2" in _shown(field)

    (contact,) = [
        t for t in field.section.tracesAsList()
        if t.name == "r2" and t.getCentroid(field.section.tform)[0] < 14.0
    ]
    field.section.selected_traces = [contact]
    mw.mouse_palette.activateModeButton("Pointer")
    start = _pix(field, *field.section.tform.map(*contact.points[0]))
    one_um = field.pixmap_dim[0] / field.series.window[2]
    end = start + QPoint(round(2.0 * one_um), 0)
    _press_and_drag(field, qapp, start, end)
    _release(field, qapp, end)

    assert "r2" not in _fresh(mw)
    assert "r2" not in field.roiKeep()
    assert "r2" not in field.section_layer.roi_keep
    assert "r2" not in _shown(field)


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


@pytest.mark.parametrize("how", ["new_trace", "closed_trace_tool"])
def test_a_new_trace_its_object_keeps_whole_stays_selected(mw, qapp, how):
    """A small square just past the box's right edge: its outline misses the
    box and its centroid and radius reach it, so its object is kept whole.
    It stays selected and no message says it is outside."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_roi_box import _pix
    field = mw.field
    _go(mw, qapp, 52)
    mw.series.setOption("trace_mode", "poly")
    _place(mw, qapp)
    _set(mw, whole=True)
    field.series.window = [12.9, 23.2, 1.2, 1.0]
    field.generateView()
    corners = [(13.71, 23.65), (13.81, 23.65), (13.81, 23.75), (13.71, 23.75)]
    if how == "new_trace":
        assert field.newTrace(
            corners, Trace("near", (255, 0, 0)), points_as_pix=False, reduce_points=False,
        )
    else:
        template = Trace("near", (255, 0, 0))
        template.points = [(-0.05, -0.05), (0.05, -0.05), (0.05, 0.05), (-0.05, 0.05)]
        mw.mouse_palette.modifyPaletteButton(0, template)
        mw.mouse_palette.activatePaletteButton(0)
        mw.mouse_palette.activateModeButton("Closed Trace")
        for x, y in corners:
            QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, _pix(field, x, y))
        QTest.mouseClick(field, Qt.RightButton, Qt.NoModifier, _pix(field, *corners[-1]))
    qapp.processEvents()

    (new,) = list(field.section.contours["near"])
    assert "near" in field.roiKeep()
    assert new in field.section.selected_traces
    assert new in field.section_layer.traces_in_view
    assert "outside the ROI mode box" not in mw.statusBar().currentMessage()


def test_the_batched_pass_matches_one_object_at_a_time():
    """Built objects with traces under two measured transforms, a drawn
    transform that differs from both: the batched pass finds the same
    sections as testing each object's squares on its own."""
    import numpy as np
    rng = np.random.default_rng(7)
    shown = Transform([1.2, 0.3, 0.5, -0.1, 0.9, 1.0])
    measured = [Transform.identity(), Transform([2.0, 0.0, 1.0, 0.0, 2.0, -3.0])]
    objects = {}
    for i in range(300):
        traces = {}
        for _ in range(rng.integers(1, 4)):
            snum = int(rng.integers(1, 6))
            td = _TD(*rng.uniform(0, 20, 2), float(rng.uniform(0.05, 1.0)))
            td._tform = measured[int(rng.integers(0, 2))]
            traces.setdefault(snum, []).append(td)
        obj = ObjectData()
        obj.traces = traces
        objects[f"o{i}"] = obj
    series = _Series(objects)
    boxes = {snum: (8.0 + snum, 8.0, 10.0 + snum, 10.0) for snum in range(1, 6)}
    found = RF.touchingSections(series, boxes, lambda s: shown)

    expected = {}
    for name in objects:
        snums, xmin, ymin, xmax, ymax = RF.objectExtents(series, name, lambda s: shown)
        for k, s in enumerate(snums.tolist()):
            b = boxes[s]
            if xmin[k] <= b[2] and xmax[k] >= b[0] and ymin[k] <= b[3] and ymax[k] >= b[1]:
                expected.setdefault(name, set()).add(s)
    assert found == {k: frozenset(v) for k, v in expected.items()}
    assert found


def _square(field, name, x, y=23.7):
    assert field.newTrace(
        [(x - 0.05, y - 0.05), (x + 0.05, y - 0.05), (x + 0.05, y + 0.05), (x - 0.05, y + 0.05)],
        Trace(name, (255, 0, 0)), points_as_pix=False, reduce_points=False,
    )
    return list(field.section.contours[name])[-1]


def _pointer_drag(mw, qapp, trace, dx):
    from PySide6.QtCore import QPoint
    from test_roi_box import _pix, _press_and_drag, _release
    field = mw.field
    field.section.selected_traces = [trace]
    mw.mouse_palette.activateModeButton("Pointer")
    start = _pix(field, *field.section.tform.map(*trace.points[0]))
    end = start + QPoint(round(dx * field.pixmap_dim[0] / field.series.window[2]), 0)
    _press_and_drag(field, qapp, start, end)
    _release(field, qapp, end)


def test_a_followed_drag_finds_the_other_objects_again_at_once(mw, qapp):
    """All on section 52: the followed square moves 2 μm east, so the object
    whose contact was at the old place goes and the one at the new place is
    kept, in the view the drag itself draws."""
    field = mw.field
    _go(mw, qapp, 52)
    source = _square(field, "lead", 13.5)
    _square(field, "old", 13.5)
    old_far = _square(field, "old", 18.5)
    _square(field, "new", 15.5)
    new_far = _square(field, "new", 18.5)
    field.roi_box_on = True
    field.roi_box_center = (13.5, 23.7)
    _set(mw, whole=True, follow="lead")
    field.series.window = [12.5, 22.2, 8.0, 4.0]
    field.generateView()
    assert "old" in field.roiKeep() and "new" not in field.roiKeep()

    _pointer_drag(mw, qapp, source, 2.0)

    assert field.roi_box_center == pytest.approx(source.getCentroid(field.section.tform))
    keep = field.roiKeep()
    drawn = set(field.section_layer.traces_in_view)
    assert "new" in keep and "old" not in keep
    assert new_far in drawn and old_far not in drawn


@pytest.mark.parametrize("kind", ["shift", "scale", "shear"])
def test_a_section_transform_edit_finds_the_objects_again_at_once(mw, qapp, kind):
    """The only contact of "contact" is on the shown section; moving the
    section's transform takes it off the box in the view the edit draws."""
    field = mw.field
    _go(mw, qapp, 52)
    _square(field, "contact", 13.5)
    _square(field, "contact", 16.5)
    _go(mw, qapp, 53)
    _square(field, "contact", 16.5)
    _go(mw, qapp, 52)
    field.roi_box_on = True
    field.roi_box_center = (13.5, 23.7)
    _set(mw, whole=True)
    field.series.window = [12.5, 22.2, 6.0, 3.0]
    field.generateView()
    assert "contact" in field.roiKeep()
    field.section.align_locked = False
    field.section.selected_traces = []

    if kind == "shift":
        field.translateTform(2.0, 0.0)
    elif kind == "scale":
        field.scaleTform(1.2, 1.0)
    else:
        field.shearTform(0.2, 0.0)

    assert "contact" not in field.roiKeep()
    assert "contact" not in {t.name for t in field.section_layer.traces_in_view}


def test_an_edit_reads_one_section_again_not_the_series(mw, qapp, monkeypatch):
    field = mw.field
    _place(mw, qapp)
    _set(mw, whole=True)
    field.roiKeep()
    reads = _count_reads(monkeypatch)
    _go(mw, qapp, 52)
    _square(field, "one", 13.5)
    _go(mw, qapp, 53)
    assert "one" in field.roiKeep()
    assert reads == []
