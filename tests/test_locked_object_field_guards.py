"""Locking an object has to stop the field from changing its trace data.

The rule, and it is narrow: locking an object prevents mutations that change
quantitative data (traces added, deleted or modified) and nothing else. It must
not block selection, color or visibility.

Until this file, one refusal was carrying that guarantee for most of the field:
`Section.addSelectedTrace` drops a trace whose object is locked, so a locked
object's trace was normally never *in* `section.selected_traces`, and every
operation that reads the selection was safe by accident rather than by check.

Focus mode breaks that. It assigns `section.selected_traces` directly rather
than through `addSelectedTrace`, in `toggleFocusMode` and again in
`changeSection`, so a selection formed *after* a lock is never filtered. Both
lock entry points (the object list's Locked checkbox and the field's "Lock")
call `deselectAllTraces`, which drains the selection standing at the moment of
the lock, and neither clears `focus_mode`. Page to the next section and the
focused object's traces are selected again, locked this time.

`test_locked_traces_are_reachable_through_focus_mode` walks exactly that, on a
real `MainWindow` and a real object list, and it is the reason the rest of this
file exists. Everything below it drives one mutating field operation with a
locked object's trace selected and asserts two things: the data is unchanged,
and the user was told why. A silent refusal is its own bug; it reads as a dead
shortcut.

`test_hiding_a_locked_trace_is_allowed` and `test_copying_a_locked_trace_is_allowed`
are the other half of the rule. Neither changes a point, a name or a tag, so
neither may be refused.
"""

import pytest

pytestmark = pytest.mark.gui

# Two objects that both live on sections 52-56 of the fixture series. 52 is the
# section the window opens on.
LOCKED = "d03p14"
OTHER = "d03sp14"
NEXT_SECTION = 53


class FakeMouseEvent:
    """The three accessors the pointer handlers read off a mouse event.

    A stub rather than a `QMouseEvent`: the constructor these handlers were
    written against is deprecated in PySide6 6.5.2 and building one adds a
    warning per call for no gain. Nothing here touches the event beyond these.
    """

    def __init__(self, x, y, shift=False):
        from PySide6.QtCore import Qt

        self._x = x
        self._y = y
        self._modifiers = Qt.ShiftModifier if shift else Qt.NoModifier

    def x(self):
        return self._x

    def y(self):
        return self._y

    def modifiers(self):
        return self._modifiers


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from the field widget modules.

    `field_widget_2_trace` does `from ... import notify`, which binds the
    function in its own namespace, so patching the helper at its source has no
    effect here. The `main_window_dialogs` fixture patches `main_window`'s copy
    and not this one.

    Required, not merely convenient: offscreen, `notify` falls through to a
    console branch ending in `input()`, which raises `EOFError` under pytest's
    capture and hangs under `-s`. Every test in this file trips a refusal on
    purpose.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    notices = []
    monkeypatch.setattr(
        field_widget_2_trace, "notify", lambda message, *a, **kw: notices.append(message)
    )
    return notices


def _lock(window, name):
    """Lock an object the way the object list's checkbox does."""
    window.series.setAttr(name, "locked", True)


def _force_select(field, traces):
    """Put traces into the selection without going through `addSelectedTrace`.

    Exactly what focus mode does, and the reason a locked object's trace can be
    selected at all. `addSelectedTrace` would drop them, which is the refusal
    this work is the prerequisite for removing.
    """
    field.section.selected_traces = list(traces)


@pytest.fixture
def locked_selection(main_window, main_window_dialogs, field_notices):
    """A window whose selection holds one locked object's trace.

    Returns `(window, trace, notices)`.
    """
    field = main_window.field
    assert field.section.n == 52

    _lock(main_window, LOCKED)
    trace = field.section.contours[LOCKED][0]
    _force_select(field, [trace])

    assert main_window.series.getAttr(LOCKED, "locked") is True
    assert field.section.selected_traces == [trace]

    return main_window, trace, field_notices


REFUSAL = "Cannot modify locked objects.\nPlease unlock before modifying."


# --- the reachability question ------------------------------------------------

def test_locked_traces_are_reachable_through_focus_mode(
    main_window, main_window_dialogs, field_notices
):
    """Lock in focus mode, page a section, cut: the traces must survive.

    The whole sequence, through the real widgets, in the order a user reaches
    it:

      1. select a trace in the field
      2. turn on focus mode
      3. tick Locked on that object's row in the object list
      4. page to the next section
      5. Ctrl+X

    Step 3 deselects, which is what used to make step 5 safe. Step 4 undoes it:
    `changeSection` repopulates the selection from `focus_mode` by assignment,
    and `focus_mode` still names the object that was just locked.

    Before the guard this deleted the trace and said nothing.
    """
    from PySide6.QtCore import Qt

    window = main_window
    field = window.field

    # 1. select a trace of the object
    trace = field.section.contours[LOCKED][0]
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(trace)
    assert field.section.selected_traces == [trace]

    # 2. focus mode
    field.toggleFocusMode()
    assert field.focus_mode == LOCKED

    # 3. lock it from the object list
    field.openList("object")
    table = field.table_manager.tables["object"][-1]
    column = table.horizontal_headers.index("Locked")
    row = next(
        r for r in range(table.model.rowCount())
        if table.model.nameAt(r) == LOCKED
    )
    assert table.onCheckStateChanged(row, column, Qt.CheckState.Checked) is True

    assert window.series.getAttr(LOCKED, "locked") is True
    assert field.section.selected_traces == []   # the lock deselected
    assert field.focus_mode == LOCKED            # but focus mode is untouched

    # 4. page to the next section
    field.changeSection(NEXT_SECTION)
    assert field.section.n == NEXT_SECTION

    # the selection is back, and every trace in it belongs to the locked object
    selected = field.section.selected_traces
    assert selected, "focus mode repopulated nothing; the premise has changed"
    assert set(t.name for t in selected) == {LOCKED}

    # 5. cut
    before = len(field.section.contours[LOCKED])
    assert before
    # `toggleFocusMode` copies the focused object, so the clipboard is not empty
    # here; what matters is that the cut does not replace its contents.
    clipboard_before = list(field.clipboard)
    field.cut()

    remaining = (
        len(field.section.contours[LOCKED])
        if LOCKED in field.section.contours else 0
    )
    assert remaining == before
    assert field_notices == [REFUSAL]
    assert field.clipboard == clipboard_before


# --- one test per mutating path ----------------------------------------------

def test_cut_refuses_a_locked_trace(locked_selection):
    """Ctrl+X. `getCopiedTraces(cut=True)` calls `section.deleteTraces`."""
    window, trace, notices = locked_selection
    field = window.field
    before = len(field.section.contours[LOCKED])

    field.cut()

    assert len(field.section.contours[LOCKED]) == before
    assert trace in field.section.contours[LOCKED]
    assert field.clipboard == []
    assert notices == [REFUSAL]


def test_paste_attributes_refuses_a_locked_trace(locked_selection):
    """Ctrl+B. Renames the selected traces, so it changes which object they are in."""
    window, trace, notices = locked_selection
    field = window.field
    field.clipboard = [field.section.contours[OTHER][0].copy()]
    assert field.clipboard[0].name == OTHER

    field.pasteAttributes()

    assert trace.name == LOCKED
    assert set(t.name for t in field.section.selected_traces) == {LOCKED}
    assert notices == [REFUSAL]


def test_translate_refuses_a_locked_trace(locked_selection):
    """Arrow keys. `section.translateTraces` moves every point."""
    window, trace, notices = locked_selection
    field = window.field
    before = [tuple(p) for p in trace.points]

    field.translate(0.5, 0.5)

    assert [tuple(p) for p in trace.points] == before
    assert notices == [REFUSAL]


def test_translate_still_moves_the_transform_with_nothing_selected(
    main_window, main_window_dialogs, field_notices
):
    """The guard is inside the selected-traces branch and nowhere else.

    With no selection `translate` moves the section transform instead, which is
    alignment and not trace data. Pinned so the guard cannot creep outward.
    """
    field = main_window.field
    _lock(main_window, LOCKED)
    field.section.selected_traces = []
    field.section.selected_ztraces = []
    field.section.align_locked = False
    before = field.section.tform.getList()

    field.translate(1.0, 1.0)

    assert field.section.tform.getList() != before
    assert field_notices == []


def _scalpel_across(field, trace):
    """A knife stroke, in pixel coordinates, that crosses `trace`."""
    pix = field.section_layer.traceToPix(trace)
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    mid_y = (min(ys) + max(ys)) / 2
    left, right = min(xs) - 10, max(xs) + 10
    steps = 20
    return [
        (left + (right - left) * i / steps, mid_y) for i in range(steps + 1)
    ]


def test_knife_refuses_a_locked_trace(locked_selection):
    """The knife. `mousePressEvent` dispatches KNIFE before its lock branch.

    That branch also reads `tracing_trace`, the palette's name for a *new*
    trace, rather than the object being cut, so it was never the right check for
    this. `cutTrace` deletes the selected traces and replaces them with pieces.
    """
    window, trace, notices = locked_selection
    field = window.field
    before = len(field.section.contours[LOCKED])
    scalpel = _scalpel_across(field, trace)

    field.cutTrace(scalpel)

    assert len(field.section.contours[LOCKED]) == before
    assert trace in field.section.contours[LOCKED]
    assert notices == [REFUSAL]


def test_knife_cut_actually_cuts_an_unlocked_trace(
    main_window, main_window_dialogs, field_notices
):
    """The counterpart to the test above: the same stroke, unlocked, splits it.

    Without this, `test_knife_refuses_a_locked_trace` would still pass if the
    scalpel missed the trace entirely, which would make it prove nothing.
    """
    field = main_window.field
    assert main_window.series.getAttr(OTHER, "locked") is not True
    trace = field.section.contours[OTHER][0]
    _force_select(field, [trace])
    before = len(field.section.contours[OTHER])

    field.cutTrace(_scalpel_across(field, trace))

    assert len(field.section.contours[OTHER]) > before
    assert field_notices == []


def test_pointer_drag_refuses_to_move_a_locked_trace(locked_selection):
    """Dragging a selected trace with the pointer. Commits `translateTraces`."""
    window, trace, notices = locked_selection
    field = window.field
    before = [tuple(p) for p in trace.points]

    # the state `pointerPress` and `pointerMove` leave behind mid-drag
    field.lclick = True
    field.single_click = False
    field.click_time = 0            # long enough ago to not be a single click
    field.is_moving_trace = True
    # the section the drag started on. `pointerRelease` will only commit a drag
    # against this section, so the lock refusal below is only reached when the
    # release is looking at the same one (issue #108).
    field.moving_section = field.section
    field.clicked_x, field.clicked_y = 100, 100
    field.section.temp_hide = [trace]

    field.pointerRelease(FakeMouseEvent(180, 140))

    assert [tuple(p) for p in trace.points] == before
    assert field.is_moving_trace is False
    assert field.section.temp_hide == []    # the drag was cleaned up either way
    assert notices == [REFUSAL]


def test_pointer_drag_moves_an_unlocked_trace(
    main_window, main_window_dialogs, field_notices
):
    """The same release, unlocked, does move the points."""
    field = main_window.field
    trace = field.section.contours[OTHER][0]
    _force_select(field, [trace])
    before = [tuple(p) for p in trace.points]

    field.lclick = True
    field.single_click = False
    field.click_time = 0
    field.is_moving_trace = True
    field.moving_section = field.section    # the drag started here (issue #108)
    field.clicked_x, field.clicked_y = 100, 100
    field.section.temp_hide = [trace]

    field.pointerRelease(FakeMouseEvent(180, 140))

    assert [tuple(p) for p in trace.points] != before
    assert field_notices == []


def _shift_click_release(field, trace, clicked_type="trace"):
    """Drive `pointerRelease` as a shift single-click on `trace`.

    `pointerPress` would have set `selected_trace`/`selected_type` from the
    click position; set directly so the test does not depend on hit testing.
    """
    field.lclick = True
    field.single_click = True
    field.is_moving_trace = False
    field.is_selecting_traces = False
    field.selected_trace = trace
    field.selected_type = clicked_type
    field.pointerRelease(FakeMouseEvent(120, 120, shift=True))


def test_focus_mode_split_refuses_a_locked_trace(locked_selection):
    """Shift-click on a trace of the focused object renames it to <obj>_split.

    A rename moves the trace out of the object, which is a deletion as far as
    that object's quantitative data is concerned. `obj_locked` was computed a
    few lines above this branch and then only used by the other one.
    """
    window, trace, notices = locked_selection
    field = window.field
    field.focus_mode = LOCKED

    _shift_click_release(field, trace)

    assert trace.name == LOCKED
    assert f"{LOCKED}_split" not in field.section.contours
    assert notices == [REFUSAL]


def test_focus_mode_incorporate_refuses_a_locked_trace(locked_selection):
    """Shift-click on a trace of a *different* object incorporates it.

    Renames the clicked trace into the focused object, so the clicked object
    loses a trace. Locking the clicked object has to stop it.
    """
    window, _trace, notices = locked_selection
    field = window.field

    # focus a different, unlocked object; the clicked trace is the locked one
    field.focus_mode = OTHER
    clicked = field.section.contours[LOCKED][0]
    field.clipboard = [field.section.contours[OTHER][0].copy()]

    _shift_click_release(field, clicked)

    assert clicked.name == LOCKED
    assert notices == [REFUSAL]


def test_a_mixed_selection_is_refused_whole(
    main_window, main_window_dialogs, field_notices
):
    """One locked object in the selection refuses the operation for all of it.

    Not an arbitrary choice: `trace_function`, `object_function` and
    `deleteContours` all already answer a mixed selection this way, and none of
    them has a partial mode. Applying the edit to the unlocked part would leave
    the user with half of what they asked for and no indication of which half.
    """
    field = main_window.field
    _lock(main_window, LOCKED)
    locked_trace = field.section.contours[LOCKED][0]
    unlocked_trace = field.section.contours[OTHER][0]
    _force_select(field, [locked_trace, unlocked_trace])

    locked_before = len(field.section.contours[LOCKED])
    unlocked_before = len(field.section.contours[OTHER])

    field.cut()

    assert len(field.section.contours[LOCKED]) == locked_before
    assert len(field.section.contours[OTHER]) == unlocked_before
    assert field_notices == [REFUSAL]


# --- what lock must NOT block -------------------------------------------------

def test_hiding_a_locked_trace_is_allowed(locked_selection):
    """Hide and unhide are visibility, so lock has no business refusing them.

    Invisible today only because a locked trace cannot normally be selected.
    The moment selection is allowed this would have become a spurious "Cannot
    modify locked objects" popup on a menu entry that changes no data.
    `hideOtherTraces` already sidesteps `trace_function` for this reason; this
    makes the pair consistent with it.
    """
    window, trace, notices = locked_selection
    field = window.field
    assert trace.hidden is False

    field.hideTraces()

    assert trace.hidden is True
    assert notices == []

    # `Section.hideTraces` clears the selection, so the trace has to be selected
    # again before it can be unhidden. Pre-existing behavior, unrelated to lock.
    _force_select(field, [trace])
    field.hideTraces(hide=False)

    assert trace.hidden is False
    assert notices == []


def test_copying_a_locked_trace_is_allowed(locked_selection):
    """Ctrl+C reads the selection and changes nothing, so it is not refused."""
    window, trace, notices = locked_selection
    field = window.field
    before = len(field.section.contours[LOCKED])

    field.copy()

    assert len(field.section.contours[LOCKED]) == before
    assert [t.name for t in field.clipboard] == [LOCKED]
    assert notices == []


def test_deleting_a_locked_trace_was_already_refused(locked_selection):
    """`deleteTraces` goes through `trace_function`, which already checked.

    Here to pin the message the new guards were matched to, and to catch the
    decorator refactor dropping the check it already had.
    """
    window, trace, notices = locked_selection
    field = window.field
    before = len(field.section.contours[LOCKED])

    field.deleteTraces()

    assert len(field.section.contours[LOCKED]) == before
    assert notices == [REFUSAL]
