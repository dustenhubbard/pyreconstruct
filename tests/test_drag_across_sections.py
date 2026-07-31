"""A pointer drag interrupted by a section change must not lose the drag.

Issue #108, "Stamp Moving to a Different Section", reports the gesture from the
user's end: hold a stamp, page to another section, and the release does nothing.
"I can hold it on a new section but not release it."

What the code does. A pointer drag is a three-event gesture. `pointerMove`
decides a drag has started, appends the carried traces to
`section.temp_hide` and starts drawing them under the cursor instead;
`pointerRelease` commits it with `section.translateTraces`. Nothing tied that
pair to one section. Page a section with the button held (the scroll wheel pages
sections, so this is one flick away) and:

  * `changeSection` empties the NEW section's `selected_traces`, so the
    translate at release had nothing to act on and moved nothing, silently;
  * `pointerRelease` cleared `temp_hide` on the section then on screen, not the
    one the drag came off, so the source section kept the dragged traces hidden;
  * a temp-hidden trace is left out of `traces_in_view`
    (`TraceLayer.generateTraceLayer`), and `getTrace` hit-tests against
    `traces_in_view`, so on returning to that section the traces were invisible
    AND unclickable until it was reloaded from disk. Work that looks deleted.

The fix ends the drag when the field changes under it, restores the traces on
the section they came off, and says so. Two routes, one per test below:
`endPendingEvents` catches it as the section changes, which covers every route
through `MainWindow.changeSection`; the check in `pointerRelease` is the
invariant behind that, for the callers that reach `FieldWidget.changeSection`
directly (`moveTo`, from the 3D scene).

What is deliberately NOT here: dropping the traces onto the new section, which
is the feature #108 asks for. That needs a decision about what the gesture
should mean (a move across sections is data leaving one section for another, and
the wheel makes it reachable by accident), and it is queued behind that
question. These tests pin the half that needs no decision: the drag never
evaporates in silence.

Driven against a real `MainWindow`, a real `FieldWidget` and a real
`TraceLayer`, over a writable copy of the fixture series.
"""

import pytest

pytestmark = pytest.mark.gui

# An object on sections 52-56 of the fixture series. 52 is the section the
# window opens on.
OBJ = "d03p14"
NEXT_SECTION = 53

CANCELLED = (
    "The traces you were dragging were put back.\n"
    "A drag has to end on the section it started on."
)


class FakeMouseEvent:
    """The accessors the pointer handlers read off a mouse event.

    A stub rather than a `QMouseEvent`: the constructor these handlers were
    written against is deprecated in PySide6 6.5.2 and building one adds a
    warning per call for no gain.
    """

    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y

    def modifiers(self):
        from PySide6.QtCore import Qt

        return Qt.NoModifier


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from the field widget modules.

    Both copies: `field_widget_5_mouse` raises the cancellation, and
    `field_widget_2_trace` raises the lock refusal. Each module does
    `from ... import notify`, binding the function in its own namespace, so
    patching the helper at its source would miss both.

    Required, not merely convenient: offscreen, `notify` falls through to a
    console branch ending in `input()`, which raises `EOFError` under pytest's
    capture and hangs under `-s`.
    """
    from PyReconstruct.modules.gui.main import (
        field_widget_2_trace,
        field_widget_5_mouse,
    )

    notices = []
    for module in (field_widget_2_trace, field_widget_5_mouse):
        monkeypatch.setattr(
            module, "notify", lambda message, *a, **kw: notices.append(message)
        )
    return notices


def _visible_trace(field):
    """Return a trace of OBJ that is currently drawn in the field.

    Picked out of `traces_in_view` rather than by index, so the visibility
    assertions below are about the drag and not about where the window happens
    to be looking.
    """
    field.generateView(update=False)
    for trace in field.section_layer.traces_in_view:
        if trace.name == OBJ:
            return trace
    pytest.fail(f"no trace of {OBJ} is in view on section {field.section.n}")


def _start_drag(field, trace):
    """Press on `trace` and move, exactly as a user starts a drag.

    Returns the pixel point pressed. The trace is selected first because that is
    what makes `pointerMove` read the gesture as a move rather than a lasso, and
    because it is what the user has just done.
    """
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(trace)
    assert field.section.selected_traces == [trace]

    pix_x, pix_y = field.section_layer.traceToPix(trace)[0]

    field.lclick = True
    field.single_click = True
    field.pointerPress(FakeMouseEvent(pix_x, pix_y))
    assert field.selected_trace is trace, "the press did not land on the trace"

    # past the single-click window, which is what tells `pointerMove` this is a
    # drag and not a click
    field.single_click = False
    field.click_time = 0
    field.pointerMove(FakeMouseEvent(pix_x + 30, pix_y + 20))

    # asserted in terms that hold before the fix as well, so that a test built
    # on this helper fails on its own subject rather than in here
    assert field.is_moving_trace is True
    assert trace in field.section.temp_hide

    return pix_x, pix_y


def test_dragged_traces_leave_the_view_while_carried(main_window, main_window_dialogs, field_notices):
    """The premise, stated once: a carried trace is hidden and unclickable.

    Not the bug. This is the mechanism the bug rode on, and every visibility
    assertion below depends on it being true.
    """
    field = main_window.field
    trace = _visible_trace(field)

    _start_drag(field, trace)

    field.generateView(update=False)
    assert trace not in field.section_layer.traces_in_view
    assert field_notices == []


def test_paging_a_section_mid_drag_ends_the_drag_and_says_so(
    main_window, main_window_dialogs, field_notices
):
    """The reported gesture. Paging with the button held must not go silent."""
    window = main_window
    field = window.field
    source = field.section
    assert source.n == 52

    trace = _visible_trace(field)
    points_before = [tuple(p) for p in trace.points]
    _start_drag(field, trace)

    # page a section the way the wheel does: MainWindow.changeSection, which
    # calls endPendingEvents first
    window.changeSection(NEXT_SECTION)
    assert field.section.n == NEXT_SECTION

    # the user was told rather than left guessing
    assert field_notices == [CANCELLED]

    # the traces came back on the section they came off
    assert source.temp_hide == []
    assert [tuple(p) for p in trace.points] == points_before
    assert trace in source.contours[OBJ].getTraces()

    # and the drag is over
    assert field.is_moving_trace is False
    assert field.moving_section is None

    # and the release that follows is a no-op rather than a second surprise
    field.pointerRelease(FakeMouseEvent(400, 300))
    assert [tuple(p) for p in trace.points] == points_before
    assert field_notices == [CANCELLED]


def test_the_source_section_is_drawable_again_after_paging_mid_drag(
    main_window, main_window_dialogs, field_notices
):
    """Come back to the section dragged from: the traces are still there.

    This is the half that read as deleted work. `temp_hide` is not persisted, so
    nothing was ever lost on disk, but the section stays cached as `b_section`
    and `changeSection` reuses that object rather than reloading it, so the
    stale `temp_hide` survived the round trip.
    """
    window = main_window
    field = window.field
    source = field.section

    trace = _visible_trace(field)
    _start_drag(field, trace)

    window.changeSection(NEXT_SECTION)
    window.changeSection(52)

    assert field.section is source, "section 52 was reloaded; the premise changed"
    assert trace in field.section_layer.traces_in_view
    assert field.section_layer.getTrace(
        *field.section_layer.traceToPix(trace)[0]
    ) == (trace, "trace")


def test_release_after_a_direct_section_change_restores_rather_than_commits(
    main_window, main_window_dialogs, field_notices
):
    """The invariant at the commit, for the callers that skip endPendingEvents.

    `FieldWidget.changeSection` on its own, which is what `moveTo` from the 3D
    scene calls. The release is the first code to notice, and it must refuse
    there rather than translate a selection that belongs to another section.
    """
    field = main_window.field
    source = field.section

    trace = _visible_trace(field)
    points_before = [tuple(p) for p in trace.points]
    _start_drag(field, trace)

    field.changeSection(NEXT_SECTION)          # no endPendingEvents on this path
    assert field.is_moving_trace is True       # the drag is still live
    assert field.section.n == NEXT_SECTION

    landed = field.section
    landed_before = {
        name: [[tuple(p) for p in t.points] for t in contour.getTraces()]
        for name, contour in landed.contours.items()
    }

    field.pointerRelease(FakeMouseEvent(400, 300))

    assert field_notices == [CANCELLED]
    assert field.is_moving_trace is False

    # nothing moved, on either section
    assert [tuple(p) for p in trace.points] == points_before
    assert source.temp_hide == []
    assert {
        name: [[tuple(p) for p in t.points] for t in contour.getTraces()]
        for name, contour in landed.contours.items()
    } == landed_before


def test_a_drag_that_stays_on_one_section_still_moves_the_traces(
    main_window, main_window_dialogs, field_notices
):
    """The guardrail. The ordinary drag is untouched by any of the above."""
    field = main_window.field
    trace = _visible_trace(field)
    points_before = [tuple(p) for p in trace.points]

    pix_x, pix_y = _start_drag(field, trace)
    field.pointerRelease(FakeMouseEvent(pix_x + 30, pix_y + 20))

    assert [tuple(p) for p in trace.points] != points_before
    assert field.is_moving_trace is False
    assert field.section.temp_hide == []
    assert field_notices == []
    assert trace in field.section_layer.traces_in_view
