"""The knife must not lose the object it was pointed at.

Two failures, reported together as "deletion option for the cutting tool":

  * **A cut that cannot be computed deleted the object anyway.** `cutTrace`
    calls `cutTraces`, then `section.deleteTraces` unconditionally, then
    recreates one trace per returned piece. Nothing looked at the result before
    the delete, so a result with nothing in it meant the object was gone and
    nothing came back. It returned True, so the field treated it as a completed
    edit, and no message was shown. A freehand outline that crosses itself
    reaches this: `cut_closed_traces` cannot difference an invalid polygon.

  * **A second mouse button part way through a cut abandoned it and opened the
    field menu.** `mousePressEvent`'s "favor right click" branch clears
    `current_trace` and drops `lclick`, and the context-menu branch below it does
    not exclude the knife, so a drawing tablet's barrel button threw away the
    stroke and put a menu under a still-moving pen, one release away from
    "Delete selected". That is the gesture the report describes.

Both are driven here on a real `MainWindow`, through the real
`mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent` and the real
`cutTrace`, over the fixture series. The refusals are asserted to be visible:
a silent refusal reads as a broken tool, and the whole complaint is about work
disappearing without being told.

`local_series_settings` is not optional. The new option lives in the global
scope, and `Series.getOption` writes a default back when a key is absent, so
without the injected store a run of this file would leave a key in the
developer's real `QSettings`.
"""

import pytest

pytestmark = pytest.mark.gui

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import KNIFE, POINTER


# an object that exists on section 52 of the fixture series, the section the
# window opens on. The same one `test_locked_object_field_guards` cuts.
CUTTABLE = "d03sp14"

BOWTIE = "test_bowtie"

LOCK_REFUSAL = "Cannot modify locked objects.\nPlease unlock before modifying."
SELF_INTERSECTION_REFUSAL = (
    "A selected trace crosses itself and cannot be cut.\n"
    "The object was left unchanged."
)


class FakeMouseEvent:
    """What the mouse handlers read off an event, and nothing more.

    A stub rather than a `QMouseEvent`: the constructor these handlers were
    written against is deprecated in PySide6 6.5.2 and building one adds a
    warning per call for no gain. `buttons()` is the one that matters here,
    because `get_clicked` reads it (not `button()`), which is why a press
    arriving while the pen is down reports both buttons.
    """

    def __init__(self, x, y, buttons):
        self._x, self._y, self._buttons = x, y, buttons

    def x(self):
        return self._x

    def y(self):
        return self._y

    def buttons(self):
        return self._buttons

    def globalPos(self):
        from PySide6.QtCore import QPoint

        return QPoint(self._x, self._y)

    def modifiers(self):
        from PySide6.QtCore import Qt

        return Qt.NoModifier


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from `field_widget_2_trace`.

    That module does `from ... import notify`, binding the function in its own
    namespace, so patching the helper at its source has no effect. Required
    rather than convenient: offscreen, `notify` falls through to a console branch
    ending in `input()`, which raises under pytest's capture and hangs under
    `-s`, and every refusal below trips it on purpose.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    notices = []
    monkeypatch.setattr(
        field_widget_2_trace,
        "notify",
        lambda message, *a, **kw: notices.append(message),
    )
    return notices


@pytest.fixture
def knife_window(main_window, main_window_dialogs, local_series_settings, monkeypatch):
    """A window in knife mode whose field menu is recorded rather than shown.

    Yields `(window, menu_execs)`. `field_menu.exec` spins a modal loop with no
    user to dismiss it offscreen, so it has to be replaced; recording the calls
    is also the assertion the interruption tests need.
    """
    local_series_settings(main_window)
    main_window.field.setMouseMode(KNIFE)

    execs = []
    monkeypatch.setattr(
        main_window.field_menu, "exec", lambda *a, **kw: execs.append(a)
    )

    return main_window, execs


def _scalpel_across(field, trace):
    """A knife stroke, in pixel coordinates, that crosses `trace`."""
    pix = field.section_layer.traceToPix(trace)
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    mid_y = (min(ys) + max(ys)) / 2
    left, right = min(xs) - 10, max(xs) + 10
    steps = 20
    return [(left + (right - left) * i / steps, mid_y) for i in range(steps + 1)]


def _add_self_intersecting_trace(field):
    """Put a closed trace whose outline crosses itself into the section.

    The two diagonals of the bounding box of an existing object, taken in an
    order that crosses in the middle, so it sits where the field is looking and
    `Polygon(...).is_valid` is False. This is the shape freehand tracing makes
    when a stroke doubles back over itself.
    """
    points = [tuple(p) for p in field.section.contours[CUTTABLE][0].points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    bowtie = Trace(BOWTIE, (0, 255, 0), closed=True)
    bowtie.points = [(x0, y0), (x1, y1), (x1, y0), (x0, y1)]

    from shapely.geometry import Polygon

    assert not Polygon(bowtie.points).is_valid, "the fixture stopped being a bowtie"

    field.section.addTrace(bowtie, log_event=False)
    field.section.selected_traces = [bowtie]

    return bowtie


def _select(field, name):
    trace = field.section.contours[name][0]
    field.section.selected_traces = [trace]
    return trace


# --- a cut that cannot be computed --------------------------------------------

def test_a_self_intersecting_trace_is_refused_rather_than_deleted(
    knife_window, field_notices
):
    """The reported loss. This used to leave the contour empty and return True."""
    window, _ = knife_window
    field = window.field
    bowtie = _add_self_intersecting_trace(field)

    result = field.cutTrace(_scalpel_across(field, bowtie))

    assert result is False
    assert len(field.section.contours[BOWTIE]) == 1
    assert field.section.contours[BOWTIE][0] is bowtie, "the trace was replaced"
    assert field_notices == [SELF_INTERSECTION_REFUSAL]


def test_the_refusal_leaves_the_points_untouched(knife_window, field_notices):
    """Not merely "a trace is still there": the same points are still there.

    A refusal that quietly rewrote the geometry would pass the test above.
    """
    window, _ = knife_window
    field = window.field
    bowtie = _add_self_intersecting_trace(field)
    before = [tuple(p) for p in bowtie.points]

    field.cutTrace(_scalpel_across(field, bowtie))

    assert [tuple(p) for p in field.section.contours[BOWTIE][0].points] == before


def test_a_normal_trace_is_still_cut(knife_window, field_notices):
    """The guardrail. Without it every test above would pass on a knife that
    refused everything."""
    window, _ = knife_window
    field = window.field
    trace = _select(field, CUTTABLE)
    before = len(field.section.contours[CUTTABLE])

    result = field.cutTrace(_scalpel_across(field, trace))

    assert result is True
    assert len(field.section.contours[CUTTABLE]) > before
    assert field_notices == []


def test_a_knife_click_with_no_drag_leaves_the_section_alone(
    knife_window, field_notices
):
    """A press and release with no movement between them.

    `knifePress` seeds `current_trace` with one point, so the cut line is a
    single point and `cutTraces` hands the selection straight back. That used to
    delete every selected trace and recreate it, which logged a modification and
    consumed a mouse-palette increment for a gesture that did nothing. The trace
    object surviving by identity is the assertion: a delete-and-recreate makes a
    new one.
    """
    window, _ = knife_window
    field = window.field
    trace = _select(field, CUTTABLE)
    before = len(field.section.contours[CUTTABLE])
    pix = field.section_layer.traceToPix(trace)

    from PySide6.QtCore import Qt

    field.mousePressEvent(FakeMouseEvent(*pix[0], Qt.LeftButton))
    field.mouseReleaseEvent(FakeMouseEvent(*pix[0], Qt.NoButton))

    assert len(field.section.contours[CUTTABLE]) == before
    assert field.section.contours[CUTTABLE][0] is trace
    assert field_notices == []


def test_a_threshold_that_discards_every_piece_refuses_the_cut(
    knife_window, field_notices
):
    """The other way the cut can come back with nothing, and the last line of
    defense in `cutTrace`.

    "% original trace" discards any piece smaller than that share of the
    original area. At 100 every piece is smaller, so the cut computes and then
    throws all of its own output away. The delete used to have happened already,
    which is a whole object gone at the end of an operation that succeeded.
    """
    window, _ = knife_window
    field = window.field
    window.series.setOption("knife_del_threshold", 100.0)
    trace = _select(field, CUTTABLE)
    before = len(field.section.contours[CUTTABLE])

    result = field.cutTrace(_scalpel_across(field, trace))

    assert result is False
    assert len(field.section.contours[CUTTABLE]) == before
    assert field.section.contours[CUTTABLE][0] is trace
    assert field_notices == [
        "The cut could not be completed.\nThe object was left unchanged."
    ]


# --- locking still wins, and says so ------------------------------------------

def test_a_locked_object_is_refused_with_a_visible_notice(knife_window, field_notices):
    """Lock guards trace data, and the knife deletes traces.

    The refusal has to be visible for the same reason the rest of this file
    exists. `refuseLockedTraces` is the one idiom for it.
    """
    window, _ = knife_window
    field = window.field
    window.series.setAttr(CUTTABLE, "locked", True)
    trace = _select(field, CUTTABLE)
    before = len(field.section.contours[CUTTABLE])

    result = field.cutTrace(_scalpel_across(field, trace))

    assert result is False
    assert len(field.section.contours[CUTTABLE]) == before
    assert trace in field.section.contours[CUTTABLE]
    assert field_notices == [LOCK_REFUSAL]


def test_a_locked_object_is_refused_before_the_geometry_is_examined(
    knife_window, field_notices
):
    """Order, pinned by the message. A locked *and* self-intersecting trace must
    be refused for being locked, so that the new check cannot be reached with a
    locked object and cannot end up reporting geometry to someone whose real
    problem is the lock."""
    window, _ = knife_window
    field = window.field
    bowtie = _add_self_intersecting_trace(field)
    window.series.setAttr(BOWTIE, "locked", True)

    field.cutTrace(_scalpel_across(field, bowtie))

    assert field_notices == [LOCK_REFUSAL]
    assert len(field.section.contours[BOWTIE]) == 1


# --- a second button part way through a cut -----------------------------------

@pytest.mark.parametrize("secondary", ["with the pen still down", "on its own"])
def test_a_secondary_press_does_not_cancel_a_cut_in_progress(knife_window, secondary):
    """The gesture from the report.

    Both shapes a barrel press can arrive in. `get_clicked` reads
    `event.buttons()`, so a press while the pen is down usually reports left and
    right together, but a tablet that stops reporting the tip for one event
    reports the secondary button alone. The second case is the reason `lclick` is
    forced back on: `knifeRelease` reads it to decide whether to cut.
    """
    from PySide6.QtCore import Qt

    window, execs = knife_window
    field = window.field

    field.mousePressEvent(FakeMouseEvent(100, 100, Qt.LeftButton))
    field.mouseMoveEvent(FakeMouseEvent(120, 120, Qt.LeftButton))
    field.mouseMoveEvent(FakeMouseEvent(140, 140, Qt.LeftButton))
    drawn = list(field.current_trace)
    assert len(drawn) == 3

    buttons = (
        Qt.LeftButton | Qt.RightButton
        if secondary == "with the pen still down"
        else Qt.RightButton
    )
    field.mousePressEvent(FakeMouseEvent(150, 150, buttons))

    assert field.current_trace == drawn, "the stroke was thrown away"
    assert field.lclick is True, "the cut would not commit on release"
    assert execs == [], "a context menu opened over the object being cut"


def test_a_cut_interrupted_by_a_secondary_press_still_completes(
    knife_window, field_notices
):
    """The whole gesture, end to end: the stroke survives *and* it cuts.

    The test above proves the state is intact. This one proves the cut the user
    drew actually happens, which is the thing they lost.
    """
    from PySide6.QtCore import Qt

    window, execs = knife_window
    field = window.field
    trace = _select(field, CUTTABLE)
    before = len(field.section.contours[CUTTABLE])
    scalpel = _scalpel_across(field, trace)

    field.mousePressEvent(FakeMouseEvent(*scalpel[0], Qt.LeftButton))
    for point in scalpel[1:10]:
        field.mouseMoveEvent(FakeMouseEvent(*point, Qt.LeftButton))

    # the barrel button, half way across the object
    field.mousePressEvent(
        FakeMouseEvent(*scalpel[10], Qt.LeftButton | Qt.RightButton)
    )

    for point in scalpel[10:]:
        field.mouseMoveEvent(FakeMouseEvent(*point, Qt.LeftButton))
    field.mouseReleaseEvent(FakeMouseEvent(*scalpel[-1], Qt.NoButton))

    assert execs == []
    assert len(field.section.contours[CUTTABLE]) > before, "the cut was lost"
    assert field_notices == []


def test_clearing_the_option_restores_the_older_behavior(knife_window):
    """The control the report asked for, proved to control something.

    Unchecked, a secondary press abandons the stroke and opens the field menu,
    which is what the tool did before.
    """
    from PySide6.QtCore import Qt

    window, execs = knife_window
    window.series.setOption("knife_ignore_secondary_click", False)
    field = window.field

    field.mousePressEvent(FakeMouseEvent(100, 100, Qt.LeftButton))
    field.mouseMoveEvent(FakeMouseEvent(120, 120, Qt.LeftButton))
    field.mousePressEvent(FakeMouseEvent(130, 130, Qt.LeftButton | Qt.RightButton))

    assert field.current_trace == []
    assert len(execs) == 1


def test_a_right_click_with_no_cut_in_progress_still_opens_the_field_menu(knife_window):
    """The guard is narrow: no stroke, no gesture to protect."""
    from PySide6.QtCore import Qt

    window, execs = knife_window
    field = window.field
    assert field.current_trace == []

    field.mousePressEvent(FakeMouseEvent(100, 100, Qt.RightButton))

    assert len(execs) == 1


def test_a_right_click_in_another_tool_still_opens_the_field_menu(knife_window):
    """And it is the knife's, not every tool's. The pointer's lasso leaves points
    in `current_trace` too, and right-clicking with the pointer must still reach
    the menu."""
    from PySide6.QtCore import Qt

    window, execs = knife_window
    field = window.field
    field.setMouseMode(POINTER)
    field.current_trace = [(100, 100), (110, 110)]

    field.mousePressEvent(FakeMouseEvent(120, 120, Qt.RightButton))

    assert len(execs) == 1


# --- the option is reachable where the report asked for it --------------------

def test_the_knife_dialog_reads_and_writes_the_new_option(
    main_window, main_window_dialogs, local_series_settings
):
    """Right-click the Knife button, which is `MainWindow.modifyKnife`.

    Pins the response indices as well as the option: `QuickDialog` numbers
    widgets rather than rows, so appending a checkbox to this dialog is exactly
    the kind of edit that silently writes one option's value into another.
    """
    local_series_settings(main_window)
    series = main_window.series
    assert series.getOption("knife_ignore_secondary_click") is True

    main_window_dialogs.responses.append(
        (
            [
                2.5,                                        # % original trace
                [("Smooth cuts", True)],                    # smooth cuts
                7,                                          # smoothing window
                [("Ignore the other mouse buttons", False)],
            ],
            True,
        )
    )

    main_window.modifyKnife()

    assert main_window_dialogs.dialogs == ["Knife"]
    assert series.getOption("knife_del_threshold") == 2.5
    assert series.getOption("roll_knife_average") is True
    assert series.getOption("roll_knife_window") == 7
    assert series.getOption("knife_ignore_secondary_click") is False


def test_the_options_dialog_round_trips_the_new_option(
    main_window, main_window_dialogs, local_series_settings
):
    """`Series ▸ Options...`, Knife panel: the second surface for the same key.

    Built against the real widget, so the assertion covers the label the user
    reads as well as the value. That panel's closure also reads its response by
    index, and the new checkbox is the second widget in it, so this pins the
    threshold and the checkbox against swapping places.
    """
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    series = local_series_settings(main_window)
    dialog = AllOptionsDialog(None, series)

    try:
        widget = dialog.all_widgets["knife"]
        assert widget.accept(close=False)  # fills `responses` from the real rows

        responses = list(widget.responses)
        assert responses[1][0] == ("Ignore other mouse buttons while cutting", True)

        responses[1] = [("Ignore other mouse buttons while cutting", False)]
        widget.responses = tuple(responses)
        widget.set()

        assert series.getOption("knife_ignore_secondary_click") is False
        assert series.getOption("knife_del_threshold") == 1.0

    finally:
        dialog.deleteLater()
