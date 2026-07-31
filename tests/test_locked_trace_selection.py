"""Selecting a locked object's trace in the 2D field.

Locking an object prevents mutations that change quantitative data (traces
added, deleted or modified) and nothing else. Selection is not one of those, so
lock must not block it.

It used to. `Section.addSelectedTrace` dropped a trace whose object was locked,
which put the field and the object list on opposite sides of the same question:
inverting the selection in the field silently skipped locked objects while
inverting it in the object list selected locked rows freely. The field was the
side that was wrong.

That refusal was also load-bearing, which is why it stayed as long as it did.
It was the only thing standing between a locked object and cut, paste
attributes, the arrow-key translate, the knife, a pointer drag and the
focus-mode split. Each of those now has a lock check of its own
(`FieldWidgetTrace.refuseLockedTraces`), and `tests/test_locked_object_field_guards.py`
drives each one with a locked trace in the selection. This file is the other
half: every way a user selects a locked object's trace now works, and the
mutating operations still refuse once it is selected the ordinary way rather
than forced into the list.

`test_hide_and_unhide_raise_no_popup` is the first thing a user would hit if
that half were wrong, which is why it is here rather than only in the guards
file.
"""

import pytest

pytestmark = pytest.mark.gui

LOCKED = "d03p14"
OTHER = "d03sp14"
REFUSAL = "Cannot modify locked objects.\nPlease unlock before modifying."


class FakeMouseEvent:
    """The three accessors the pointer handlers read off a mouse event.

    Same stub as `test_locked_object_field_guards.py`, and for the same reason:
    the `QMouseEvent` constructor these handlers were written against is
    deprecated in PySide6 6.5.2 and building one adds a warning per call.
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
    """Record what `notify` would have shown from the trace field module.

    Required rather than convenient: offscreen, `notify` falls through to a
    console branch ending in `input()`, which raises `EOFError` under pytest's
    capture. Most tests here assert the list stays empty, which is the point.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    notices = []
    monkeypatch.setattr(
        field_widget_2_trace, "notify", lambda message, *a, **kw: notices.append(message)
    )
    return notices


@pytest.fixture
def locked_window(main_window, main_window_dialogs, field_notices):
    """A window on section 52 with `LOCKED` locked and nothing selected."""
    main_window.series.setAttr(LOCKED, "locked", True)
    main_window.field.section.selected_traces = []
    assert main_window.field.section.n == 52
    return main_window, field_notices


# --- selection now works ------------------------------------------------------

def test_add_selected_trace_accepts_a_locked_object(locked_window):
    """The refusal this change removes, at its source."""
    window, notices = locked_window
    section = window.field.section
    trace = section.contours[LOCKED][0]

    section.addSelectedTrace(trace)

    assert section.selected_traces == [trace]
    assert notices == []


def test_clicking_a_locked_trace_selects_and_deselects_it(locked_window):
    """`FieldWidgetTrace.selectTrace`, which is what a click resolves to."""
    window, notices = locked_window
    field = window.field
    trace = field.section.contours[LOCKED][0]

    field.selectTrace(trace)
    assert field.section.selected_traces == [trace]

    field.selectTrace(trace)
    assert field.section.selected_traces == []
    assert notices == []


def test_pointer_release_selects_a_locked_trace(locked_window):
    """The real mouse path. `pointerRelease` carried its own `obj_locked` gate
    around the ordinary select branch, separate from `addSelectedTrace`."""
    window, notices = locked_window
    field = window.field
    trace = field.section.contours[LOCKED][0]

    field.lclick = True
    field.single_click = True
    field.is_moving_trace = False
    field.is_selecting_traces = False
    field.selected_trace = trace
    field.selected_type = "trace"
    field.pointerRelease(FakeMouseEvent(120, 120))

    assert field.section.selected_traces == [trace]
    assert notices == []


def test_select_all_includes_a_locked_object(locked_window):
    window, notices = locked_window
    field = window.field

    field.selectAllTraces()

    assert LOCKED in {t.name for t in field.section.selected_traces}
    assert notices == []


def test_invert_selection_includes_a_locked_object(locked_window):
    """The inconsistency this change closes, through the field widget.

    `tests/test_invert_hide_others.py` holds the pure-section pair:
    `test_invert_selects_locked_objects` and its object-list counterpart
    `test_object_invert_does_not_exclude_locked_rows`, which now agree.
    """
    window, notices = locked_window
    field = window.field
    field.section.selected_traces = [field.section.contours[OTHER][0]]

    field.invertTraceSelection()

    selected = {t.name for t in field.section.selected_traces}
    assert LOCKED in selected
    assert OTHER not in selected
    assert notices == []


def test_find_trace_zooms_to_and_selects_a_locked_trace(locked_window):
    """"Find in field" / double-click in the trace list. `findTrace` had its own
    locked check, which framed the trace and then selected nothing."""
    window, notices = locked_window
    field = window.field
    window_before = list(window.series.window)

    field.findTrace(LOCKED)

    assert [t.name for t in field.section.selected_traces] == [LOCKED]
    assert list(window.series.window) != window_before
    assert notices == []


def test_find_trace_still_skips_a_hidden_trace(locked_window):
    """The visibility half of `findTrace`'s condition is not what changed: a
    trace nobody can see is still framed without being selected."""
    window, notices = locked_window
    field = window.field
    field.section.contours[LOCKED][0].setHidden(True)

    field.findTrace(LOCKED)

    assert field.section.selected_traces == []


# --- the non-mutating operations, on an ordinarily selected locked trace ------

def test_hide_and_unhide_raise_no_popup(locked_window):
    """The first thing a user would hit. Hiding is visibility, not data.

    `refuseLockedTraces` is deliberately absent from `hideTraces` (it takes
    `visibility_trace_function`); without that, allowing selection would have
    turned the everyday Ctrl+H into a "Cannot modify locked objects" popup.
    """
    window, notices = locked_window
    field = window.field
    trace = field.section.contours[LOCKED][0]
    field.selectTrace(trace)

    field.hideTraces()
    assert trace.hidden is True
    assert notices == []

    # `Section.hideTraces` clears the selection, so select again to unhide.
    field.section.selected_traces = [trace]
    field.hideTraces(hide=False)
    assert trace.hidden is False
    assert notices == []


def test_copy_and_zoom_and_3d_accept_a_locked_trace(locked_window, monkeypatch):
    """Copy, and adding the object to the 3D scene, both read and change nothing.

    The 3D entry point is stubbed at `MainWindow.addTo3D`: building the real
    scene opens a vtk window. What is under test is `object_function`, which
    resolves the object names from the field's trace selection and, at
    `update_objects=False`, does not check lock.
    """
    window, notices = locked_window
    field = window.field
    trace = field.section.contours[LOCKED][0]
    field.selectTrace(trace)

    field.copy()
    assert [t.name for t in field.clipboard] == [LOCKED]

    added = []
    monkeypatch.setattr(window, "addTo3D", lambda names: added.append(list(names)))
    field.addTo3D()
    assert added == [[LOCKED]]

    assert notices == []


# --- and the mutating ones still refuse ---------------------------------------

MUTATING = [
    ("cut", lambda f: f.cut()),
    ("pasteAttributes", lambda f: f.pasteAttributes()),
    ("translate", lambda f: f.translate(0.5, 0.5)),
    ("deleteTraces", lambda f: f.deleteTraces()),
    ("mergeTraces", lambda f: f.mergeTraces()),
    ("smoothTraces", lambda f: f.smoothTraces()),
    ("traceDialog", lambda f: f.traceDialog()),
    ("editAttributes", lambda f: f.editAttributes()),
]


@pytest.mark.parametrize("label,operation", MUTATING, ids=[c[0] for c in MUTATING])
def test_mutating_operations_still_refuse_once_selection_is_allowed(
    locked_window, monkeypatch, label, operation
):
    """The point of the audit, as an assertion.

    Each of these used to be safe only because a locked object's trace could not
    reach `section.selected_traces`. Here the trace is selected the way a user
    selects it, and every one still refuses and says so.
    """
    from PyReconstruct.modules.gui.main import field_widget_3_object

    window, notices = locked_window
    monkeypatch.setattr(
        field_widget_3_object, "notify", lambda message, *a, **kw: notices.append(message)
    )

    field = window.field
    trace = field.section.contours[LOCKED][0]
    field.clipboard = [field.section.contours[OTHER][0].copy()]
    field.selectTrace(trace)
    assert field.section.selected_traces == [trace]

    before = ([tuple(p) for p in trace.points], trace.name, len(field.section.contours[LOCKED]))

    operation(field)

    after = ([tuple(p) for p in trace.points], trace.name, len(field.section.contours[LOCKED]))
    assert after == before, f"{label} changed a locked object's trace data"
    assert notices == [REFUSAL], f"{label} refused without telling the user"
