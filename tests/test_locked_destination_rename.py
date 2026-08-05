"""Renaming a trace *into* a locked object is a change to that object's data.

Every lock check in the field reads the objects the selected traces are in
right now -- `FieldWidgetTrace.refuseLockedTraces`, `trace_function` and
`object_function` all take the selection and ask whether any of those objects is
locked. None of them looks at the name being assigned.

That leaves the destination unguarded. Selecting an unlocked object's trace and
renaming it to a locked object's name passes every existing check (the source is
unlocked, which is all anyone asked) and lands a new trace in the locked object.
Adding a trace to an object is a quantitative change to it, so the lock rule in
`specs/lock-semantics.md` covers it: "locking an object prevents mutations that
would change quantitative data".

The rule is narrow on purpose and this file is careful to stay inside it. The
refusal here is triggered by the destination *name*, never by which object a
trace is drawn in, selected in, or colored as. `test_rename_into_an_unlocked_object_still_works`
is the guard against the fix widening: it is the ordinary rename, and it must
keep working with a locked object sitting elsewhere in the same series.
"""

import pytest

pytestmark = pytest.mark.gui

# Two objects that both live on sections 52-56 of the fixture series. 52 is the
# section the window opens on. Same pair `test_locked_object_field_guards.py`
# uses, for the same reason: they coexist on the section the window opens on.
LOCKED = "d03p14"
OTHER = "d03sp14"

REFUSAL = "Cannot modify locked objects.\nPlease unlock before modifying."


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from the two field widget modules.

    Both bind `notify` into their own namespace with `from ... import notify`,
    so patching the helper at its source has no effect. Required, not just
    convenient: offscreen, `notify` falls through to a console branch ending in
    `input()`, which raises `EOFError` under pytest's capture.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace, field_widget_3_object

    notices = []
    recorder = lambda message, *a, **kw: notices.append(message)
    monkeypatch.setattr(field_widget_2_trace, "notify", recorder)
    monkeypatch.setattr(field_widget_3_object, "notify", recorder)
    return notices


class FakeMouseEvent:
    """The accessors the pointer handlers read off a mouse event.

    A stub rather than a `QMouseEvent`: the constructor these handlers were
    written against is deprecated in PySide6 6.5.2. Same shape as the one in
    `test_locked_object_field_guards.py`.
    """

    def __init__(self, x, y, ctrl=False):
        from PySide6.QtCore import Qt

        self._x = x
        self._y = y
        self._modifiers = Qt.ControlModifier if ctrl else Qt.NoModifier

    def x(self):
        return self._x

    def y(self):
        return self._y

    def modifiers(self):
        return self._modifiers


class _FakeTraceDialog:
    """Stands in for `TraceDialog`, returning a chosen name as the user's input.

    The real dialog needs a modal event loop. What matters to these tests is
    only the name it hands back, which is the destination the user typed.
    """

    name = None
    is_obj_list = False

    def __init__(self, parent, *args, **kwargs):
        pass

    def exec(self):
        from PyReconstruct.modules.datatypes import Trace

        trace = Trace(type(self).name, None)
        trace.color = None
        trace.tags = None
        trace.fill_mode = (None, None)

        if type(self).is_obj_list:
            # the object list's variant returns (trace, sections)
            return (trace, None), True

        return trace, True


@pytest.fixture
def rename_dialog(monkeypatch):
    """Point both dialog call sites at `_FakeTraceDialog`.

    Returns a callable that sets the name the user is pretending to type.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace, field_widget_3_object

    monkeypatch.setattr(field_widget_2_trace, "TraceDialog", _FakeTraceDialog)
    monkeypatch.setattr(field_widget_3_object, "TraceDialog", _FakeTraceDialog)

    def choose(name, is_obj_list=False):
        _FakeTraceDialog.name = name
        _FakeTraceDialog.is_obj_list = is_obj_list

    return choose


def _select(field, traces):
    """Select traces of an unlocked object the ordinary way."""
    field.section.selected_traces.clear()
    for t in traces:
        field.section.addSelectedTrace(t)
    assert field.section.selected_traces


def _count(field, name):
    contour = field.section.contours
    return len(contour[name]) if name in contour else 0


# --- the four paths that can name a locked destination ------------------------

def test_trace_dialog_refuses_renaming_into_a_locked_object(
    main_window, main_window_dialogs, field_notices, rename_dialog
):
    """The trace attributes dialog: type a locked object's name into Name."""
    field = main_window.field
    main_window.series.setAttr(LOCKED, "locked", True)

    trace = field.section.contours[OTHER][0]
    _select(field, [trace])
    before_locked = _count(field, LOCKED)
    before_other = _count(field, OTHER)

    rename_dialog(LOCKED)
    field.traceDialog()

    assert _count(field, LOCKED) == before_locked
    assert _count(field, OTHER) == before_other
    assert trace.name == OTHER
    assert REFUSAL in field_notices


def test_paste_attributes_refuses_a_locked_destination(
    main_window, main_window_dialogs, field_notices
):
    """Ctrl+B with a locked object's trace on the clipboard.

    Copy is deliberately allowed on a locked object -- it changes nothing -- so
    the clipboard can hold a locked object's trace with no refusal anywhere
    upstream. Pasting its attributes onto an unlocked selection is what moves
    the selection into the locked object.
    """
    field = main_window.field

    field.clipboard = [field.section.contours[LOCKED][0].copy()]
    main_window.series.setAttr(LOCKED, "locked", True)

    trace = field.section.contours[OTHER][0]
    _select(field, [trace])
    before_locked = _count(field, LOCKED)

    field.pasteAttributes()

    assert _count(field, LOCKED) == before_locked
    assert trace.name == OTHER
    assert REFUSAL in field_notices


def test_object_list_edit_attributes_refuses_a_locked_destination(
    main_window, main_window_dialogs, field_notices, rename_dialog
):
    """The object list's "Edit attributes...": rename a whole object onto a locked one.

    The widest of the four. `Series.editObjectAttributes` walks every section
    the source object appears on, so this merges an entire object into the
    locked one rather than one trace on one section.
    """
    field = main_window.field
    main_window.series.setAttr(LOCKED, "locked", True)

    _select(field, [field.section.contours[OTHER][0]])
    before_locked = _count(field, LOCKED)

    rename_dialog(LOCKED, is_obj_list=True)
    field.editAttributes()

    assert _count(field, LOCKED) == before_locked
    assert _count(field, OTHER) > 0
    assert REFUSAL in field_notices


def test_focus_split_refuses_when_the_split_name_is_locked(
    main_window, main_window_dialogs, field_notices
):
    """Focus mode's split renames a trace to `<name>_split`.

    Generated rather than typed, but an object of that name can already exist
    and be locked, and then the split adds traces to it. Same rule, same
    refusal.

    Driven through `pointerRelease` rather than by calling the guard directly:
    the point is that the real gesture reaches it, and the source object here is
    unlocked, so `refuseLockedTraces` waves it through.
    """
    field = main_window.field
    trace = field.section.contours[OTHER][0]
    split_name = f"{OTHER}_split"

    # an object by the split name already exists on this section, and is locked
    existing = trace.copy()
    existing.name = split_name
    field.section.addTrace(existing, log_event=False)
    main_window.series.setAttr(split_name, "locked", True)
    before_split = _count(field, split_name)
    before_other = _count(field, OTHER)

    # the source object is unlocked, so the source-side check passes
    assert field.refuseLockedTraces([trace]) is False
    assert field_notices == []

    # focus on OTHER and click one of its own traces: the "remove from object"
    # half of the focus-mode edit, which is the rename
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(trace)
    field.toggleFocusMode()
    assert field.focus_mode == OTHER

    field.lclick = True
    field.single_click = True
    field.selected_trace = trace
    field.selected_type = "trace"
    field.is_moving_trace = False
    field.is_selecting_traces = False
    # Ctrl, not Shift: Ctrl is the focus-mode edit click as of 1.21.0. The
    # binding itself is covered in `test_focus_edit_click_ctrl.py`.
    field.pointerRelease(FakeMouseEvent(0, 0, ctrl=True))

    assert _count(field, split_name) == before_split
    assert _count(field, OTHER) == before_other
    assert trace.name == OTHER
    assert REFUSAL in field_notices


# --- merge: already closed by construction, pinned so it stays that way --------

def test_merge_attributes_destination_is_always_a_source_trace(
    main_window, main_window_dialogs, field_notices
):
    """`mergeTraces(merge_attrs_only=True)` cannot name an unchecked object.

    It renames the selection onto `to_merge[0].name`, and `to_merge` is either
    the selection itself or `restrict`, which `autoMerge` builds out of the
    selection. So the destination is always one of the traces `trace_function`
    already cleared, and this path needed no new check.

    Pinned because the fix deliberately did not touch it: if a future caller
    passes a `restrict` list from outside the selection, the destination stops
    being covered and this assertion is where that shows up.
    """
    field = main_window.field
    main_window.series.setAttr(LOCKED, "locked", True)

    # merge needs two traces of the same object on this section
    second = field.section.contours[OTHER][0].copy()
    field.section.addTrace(second, log_event=False)
    traces = field.section.contours[OTHER].getTraces()[:2]
    assert len(traces) == 2

    _select(field, traces)
    field.mergeTraces(merge_attrs_only=True)

    # the selection stayed in its own object; nothing reached the locked one
    assert set(t.name for t in field.section.selected_traces) == {OTHER}
    assert REFUSAL not in field_notices


# --- the regression that matters most -----------------------------------------

def test_rename_into_an_unlocked_object_still_works(
    main_window, main_window_dialogs, field_notices, rename_dialog
):
    """The ordinary rename, with a locked object elsewhere in the series.

    The refusal keys on the destination name and nothing else. A locked object
    that is neither the source nor the destination must not affect a rename at
    all, and the plain case must keep working or the fix is worse than the bug.
    """
    field = main_window.field
    main_window.series.setAttr(LOCKED, "locked", True)

    trace = field.section.contours[OTHER][0]
    _select(field, [trace])
    destination = "a_brand_new_object"

    rename_dialog(destination)
    field.traceDialog()

    assert _count(field, destination) == 1
    assert field_notices == []


def test_paste_attributes_into_an_unlocked_object_still_works(
    main_window, main_window_dialogs, field_notices
):
    """Ctrl+B between two unlocked objects, the everyday use of the command."""
    field = main_window.field
    main_window.series.setAttr(LOCKED, "locked", True)

    field.clipboard = [field.section.contours[OTHER][0].copy()]

    # source and destination are both unlocked; LOCKED is a bystander
    source = field.section.contours[LOCKED][0]
    main_window.series.setAttr(LOCKED, "locked", False)
    _select(field, [source])
    before = _count(field, OTHER)

    field.pasteAttributes()

    assert _count(field, OTHER) == before + 1
    assert field_notices == []
