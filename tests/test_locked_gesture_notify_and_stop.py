"""The two mouse/scissors gesture call sites of the lock guard notify-and-stop.

Corrected 2026-08-06 ("split notifyLocked", DECISIONS.md / BACKLOG.md). The
maintainer originally decided to standardize every lock-refusal path,
including `notifyLocked`, onto the notify-and-stop idiom already used by
`refuseLockedTraces`/`refuseLockedDestination`/`refuseLockedDestinations`
(`"Cannot modify locked objects.\\nPlease unlock before modifying."`),
believing `notifyLocked` had exactly two call sites that both just "ask, then
stop anyway." A dispatched fixup agent found the premise false: `notifyLocked`
has four real call sites. Two -- `TraceTableWidget.itemChanged`/`getSelected`
in `table/trace.py` -- genuinely act on "Yes" and unlock-and-proceed, by
original design (`73f54794`); see `test_data_lists_real_widget.py` for those.
The other two are the ones this file covers: `FieldWidgetMouse.scissorsPress`
and the tracing-mode gate in `FieldWidget.mousePressEvent`. Both already
discarded `notifyLocked`'s return value and stopped unconditionally, so the
"ask to unlock" dialog they popped was theater -- the fix replaces the ask
with a plain notify-and-stop, matching the other three sites' exact wording
and mechanism, with no change in outward behavior for the gesture itself
(it always refused before, and it always refuses now).
"""

import types

import pytest

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.transform import Transform
from PyReconstruct.modules.gui.main import field_widget_5_mouse
from PyReconstruct.modules.gui.main.field_widget_5_mouse import FieldWidgetMouse

REFUSAL = "Cannot modify locked objects.\nPlease unlock before modifying."

# A picked-up trace maps to these pixel coords (traceToPix is stubbed).
PIX = [(100, 900), (300, 900), (300, 700), (100, 700)]

# The fixture object test_locked_object_field_guards.py already locks on
# sections 52-56 of the checked-in series.
LOCKED = "d03p14"


class _FakePressEvent:
    """The accessors `mousePressEvent` reads off a `QMouseEvent`."""

    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y

    def buttons(self):
        from PySide6.QtCore import Qt

        return Qt.LeftButton

    def globalPos(self):
        from PySide6.QtCore import QPoint

        return QPoint(self._x, self._y)


# --------------------------------------------------------------------------
# scissorsPress: picking up a trace of a locked object.
# --------------------------------------------------------------------------

class _LockedSeriesStub:
    """`getAttr(name, "locked")` is True for every name -- enough for the
    single check `scissorsPress` makes before it would otherwise delete and
    re-pick-up the trace."""

    def getAttr(self, name, attr):
        return attr == "locked"


def _build_scissors_stub():
    trace = Trace("mytrace", (255, 0, 0), False)
    trace.points = [(100, 100), (300, 100), (300, 300), (100, 300)]

    section = Section.__new__(Section)
    section.n = 0
    section.series = _LockedSeriesStub()
    section.contours = {"mytrace": Contour("mytrace")}
    section.contours["mytrace"].append(trace)
    section.selected_traces = [trace]
    section.selected_ztraces = []
    section.selected_flags = []
    section.modified_contours = set()
    section.added_traces = []
    section.removed_traces = []
    section.tforms = {"default": Transform([1, 0, 0, 0, 1, 0])}
    section.mag = 1.0

    stub = types.SimpleNamespace()
    stub.lclick = True
    stub.rclick = False
    stub.clicked_x, stub.clicked_y = 100, 100
    stub.section = section
    stub.series = section.series
    stub.selected_trace = None
    stub.selected_type = None
    stub.is_scissoring = False
    stub.current_trace = []
    stub.section_layer = types.SimpleNamespace(
        getTrace=lambda x, y: (trace, "trace"),
        traceToPix=lambda t: list(PIX),
    )
    stub.mainwindow = types.SimpleNamespace(checkActions=lambda *a, **k: None)
    stub.calls = []
    for attr in (
        "deselectAllTraces", "generateView", "activateMouseBoundaryTimer",
        "update",
    ):
        setattr(
            stub, attr,
            (lambda name: lambda *a, **k: stub.calls.append(name))(attr),
        )
    return stub, section, trace


def test_scissors_press_on_locked_trace_notifies_and_stops(monkeypatch):
    """The locked-object gate in `scissorsPress` must notify-and-stop rather
    than ask-to-unlock: no dialog, and the pickup (delete-then-recreate) never
    starts."""
    notices = []
    monkeypatch.setattr(
        field_widget_5_mouse, "notify",
        lambda message, *a, **kw: notices.append(message),
    )
    stub, section, trace = _build_scissors_stub()

    FieldWidgetMouse.scissorsPress(stub, None)

    assert notices == [REFUSAL]
    assert stub.is_scissoring is False
    assert stub.calls == []  # deselectAllTraces/generateView never ran
    assert trace in section.contours["mytrace"].getTraces()  # never picked up


def test_scissors_press_on_unlocked_trace_still_picks_it_up(monkeypatch):
    """Guardrail: the same gesture on an unlocked trace is unaffected -- it
    still deletes the original to begin the pickup, same as before this fix."""
    notices = []
    monkeypatch.setattr(
        field_widget_5_mouse, "notify",
        lambda message, *a, **kw: notices.append(message),
    )
    stub, section, trace = _build_scissors_stub()
    stub.series.getAttr = lambda name, attr: False  # nothing locked

    FieldWidgetMouse.scissorsPress(stub, None)

    assert notices == []
    assert stub.is_scissoring is True
    assert "deselectAllTraces" in stub.calls
    assert trace not in section.contours.get("mytrace", Contour("mytrace")).getTraces()


# --------------------------------------------------------------------------
# mousePressEvent's tracing-mode gate: pressing to draw while the object
# being traced onto is locked.
# --------------------------------------------------------------------------

def _lock(window, name):
    window.series.setAttr(name, "locked", True)


@pytest.mark.gui
def test_tracing_gate_refuses_a_locked_object(main_window, main_window_dialogs, monkeypatch):
    """Pressing to trace while `tracing_trace` names a locked object must
    notify-and-stop: `tracePress` never runs and no ask-to-unlock dialog
    appears."""
    from PyReconstruct.modules.gui.main import field_widget as field_widget_module
    from PyReconstruct.modules.gui.main.field_widget_5_mouse import CLOSEDTRACE

    notices = []
    monkeypatch.setattr(
        field_widget_module, "notify",
        lambda message, *a, **kw: notices.append(message),
    )

    window = main_window
    field = window.field
    _lock(window, LOCKED)

    field.mouse_mode = CLOSEDTRACE
    field.tracing_trace = field.section.contours[LOCKED][0]

    trace_press_calls = []
    monkeypatch.setattr(field, "tracePress", lambda *a, **k: trace_press_calls.append(1))

    field.mousePressEvent(_FakePressEvent(120, 120))

    assert notices == [REFUSAL]
    assert trace_press_calls == []


@pytest.mark.gui
def test_tracing_gate_allows_an_unlocked_object(main_window, main_window_dialogs, monkeypatch):
    """Guardrail: the same press with an unlocked tracing object reaches
    `tracePress` and raises no refusal."""
    from PyReconstruct.modules.gui.main import field_widget as field_widget_module
    from PyReconstruct.modules.gui.main.field_widget_5_mouse import CLOSEDTRACE

    notices = []
    monkeypatch.setattr(
        field_widget_module, "notify",
        lambda message, *a, **kw: notices.append(message),
    )

    window = main_window
    field = window.field
    assert window.series.getAttr(LOCKED, "locked") is not True

    field.mouse_mode = CLOSEDTRACE
    field.tracing_trace = Trace(LOCKED, (255, 0, 0), False)

    trace_press_calls = []
    monkeypatch.setattr(field, "tracePress", lambda *a, **k: trace_press_calls.append(1))

    field.mousePressEvent(_FakePressEvent(120, 120))

    assert notices == []
    assert trace_press_calls == [1]
