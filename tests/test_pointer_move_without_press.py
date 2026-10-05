"""Exercise the real pointer handlers without constructing Qt widgets."""

from types import SimpleNamespace

import pytest

from PyReconstruct.modules.gui.main.field_widget_1_base import FieldWidgetBase
from PyReconstruct.modules.gui.main.field_widget_5_mouse import FieldWidgetMouse


class _Event:
    def x(self):
        return 30

    def y(self):
        return 40


class _Field:
    pointerPress = FieldWidgetMouse.pointerPress
    pointerMove = FieldWidgetMouse.pointerMove
    isSingleClicking = FieldWidgetMouse.isSingleClicking

    def __init__(self):
        FieldWidgetBase.initAttrs(self, SimpleNamespace(getOption=lambda _: ("lasso",)), None)
        self.section = SimpleNamespace(
            selected_traces=[], selected_ztraces=[], selected_flags=[], temp_hide=[]
        )
        self.section_layer = SimpleNamespace(
            getTrace=lambda x, y: (None, None),
            traceToPix=lambda trace: [(10, 20), (20, 30)],
        )
        self.lclick = True
        self.click_time = 0
        self.calls = []

    def generateView(self, **kwargs):
        self.calls.append(("view", kwargs))

    def update(self):
        self.calls.append("update")

    def activateMouseBoundaryTimer(self):
        self.calls.append("boundary")


@pytest.mark.parametrize("missing", [False, True], ids=["none", "unset"])
@pytest.mark.parametrize("single_click", [False, True])
def test_move_without_pointer_press_changes_nothing(missing, single_click):
    field = _Field()
    field.single_click = single_click
    field.pointer_press_recorded = False
    if missing:
        field.__dict__.pop("selected_trace", None)
    else:
        field.selected_trace = None
    before = vars(field).copy()
    before["current_trace"] = field.current_trace.copy()
    before["calls"] = field.calls.copy()

    field.pointerMove(_Event())

    assert vars(field) == before
    assert field.current_trace == []
    assert not field.is_selecting_traces
    assert not field.is_moving_trace
    assert field.section.temp_hide == []
    assert field.calls == []


def test_pointer_selection_state_exists_at_initialization():
    field = SimpleNamespace()

    FieldWidgetBase.initAttrs(field, None, None)

    assert field.selected_trace is None
    assert field.selected_type is None
    assert field.pointer_press_recorded is False


def test_opening_series_clears_pointer_selection_state(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_1_base as base

    field = _Field()
    section = object()
    series = SimpleNamespace(
        current_section=1,
        sections={1: "section"},
        getOption=lambda _: None,
        loadSection=lambda _: section,
        isWelcomeSeries=lambda: True,
    )
    field.selected_trace = object()
    field.selected_type = "trace"
    field.pointer_press_recorded = True
    field.clearStates = lambda: None
    field.series_states = {section: object()}
    field.createZarrLayer = lambda: None
    field.setCursor = lambda _: None
    monkeypatch.setattr(base, "SectionLayer", lambda *args: None)
    monkeypatch.setattr(base, "TableManager", lambda *args: None)
    monkeypatch.setattr(base, "QCursor", lambda *args: None)

    FieldWidgetBase.createField(field, series)

    assert field.selected_trace is None
    assert field.selected_type is None
    assert field.pointer_press_recorded is False


def test_dropped_press_then_real_press_starts_lasso(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_5_mouse as mouse

    field = _Field()
    field.lclick = True
    field.pointer_press_recorded = False
    field.single_click = True
    now = [100.0]
    field.click_time = now[0]
    monkeypatch.setattr(mouse.time, "time", lambda: now[0])
    lookups = []

    def get_trace(x, y):
        lookups.append((x, y))
        return None, None

    field.section_layer.getTrace = get_trace
    before = vars(field).copy()
    before["current_trace"] = field.current_trace.copy()
    before["calls"] = field.calls.copy()

    field.pointerMove(_Event())

    assert vars(field) == before
    assert field.current_trace == []
    assert not field.is_selecting_traces
    assert not field.is_moving_trace
    assert field.calls == []
    assert lookups == []

    field.pointerPress(_Event())
    assert field.pointer_press_recorded is True
    assert field.selected_trace is None
    assert lookups == [(30, 40)]
    field.single_click = False
    now[0] += field.max_click_time + 1

    field.pointerMove(_Event())

    assert field.is_selecting_traces
    assert not field.is_moving_trace
    assert field.current_trace == [(30, 40)]
    assert field.calls == ["boundary", "update"]


def test_press_on_selected_trace_then_move_starts_drag():
    field = _Field()
    trace = SimpleNamespace(color=(255, 0, 0), closed=True)
    field.section.selected_traces = [trace]
    field.section_layer.getTrace = lambda x, y: (trace, "trace")

    field.pointerPress(_Event())
    field.pointerMove(_Event())

    assert field.selected_trace is trace
    assert field.selected_type == "trace"
    assert field.pointer_press_recorded is True
    assert field.is_moving_trace
    assert field.moving_section is field.section
    assert field.section.temp_hide == [trace]
    assert field.moving_traces == [([(10, 20), (20, 30)], (255, 0, 0), True)]
    assert field.calls == [("view", {"update": False}), "update"]


def test_single_click_move_keeps_collecting_possible_lasso_points():
    field = _Field()
    trace = SimpleNamespace(color=(255, 0, 0), closed=True)
    field.section.selected_traces = [trace]
    field.section_layer.getTrace = lambda x, y: (trace, "trace")
    field.single_click = True

    field.pointerPress(_Event())
    field.pointerMove(_Event())

    assert field.current_trace == [(30, 40)]
    assert not field.is_moving_trace
    assert not field.is_selecting_traces
    assert field.calls == []


def test_normal_pointer_click_still_selects_trace():
    field = _Field()
    trace = SimpleNamespace(color=(255, 0, 0), closed=True)
    field.section_layer.getTrace = lambda x, y: (trace, "trace")
    field.single_click = True
    field.zarr_layer = None
    selected = []
    field.selectTrace = selected.append

    field.pointerPress(_Event())
    assert field.pointer_press_recorded is True
    FieldWidgetMouse.pointerRelease(field, _Event())

    assert field.pointer_press_recorded is False
    assert selected == [trace]
    assert field.current_trace == []
    assert field.calls == ["update"]


@pytest.mark.parametrize("single_click", [False, True])
def test_press_on_empty_space_then_move_preserves_lasso(single_click):
    field = _Field()
    field.single_click = single_click

    field.pointerPress(_Event())
    field.pointerMove(_Event())

    assert field.current_trace == [(30, 40)]
    assert field.is_selecting_traces is (not single_click)
    assert field.calls == ([] if single_click else ["boundary", "update"])


def test_existing_lasso_continues_without_a_selected_trace():
    field = _Field()
    field.pointerPress(_Event())
    field.is_selecting_traces = True
    field.current_trace = [(10, 20)]

    field.pointerMove(_Event())

    assert field.current_trace == [(10, 20), (30, 40)]
    assert field.calls == ["update"]


def test_existing_move_continues_without_a_selected_trace():
    field = _Field()
    field.selected_trace = None
    field.pointer_press_recorded = True
    field.is_moving_trace = True

    field.pointerMove(_Event())

    assert field.is_moving_trace
    assert field.calls == ["update"]


def test_pointer_release_without_left_button_clears_recorded_press():
    field = _Field()
    field.pointerPress(_Event())
    field.lclick = False

    FieldWidgetMouse.pointerRelease(field, _Event())

    assert field.pointer_press_recorded is False
    assert field.calls == ["update"]


def test_tool_switch_clears_recorded_press(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_5_mouse as mouse

    field = _Field()
    field.pointerPress(_Event())
    pending = []
    field.endPendingEvents = lambda: pending.append(field.pointer_press_recorded)
    field.setCursor = lambda _: None
    monkeypatch.setattr(mouse, "QCursor", lambda *args: None)

    FieldWidgetMouse.setMouseMode(field, mouse.POINTER)
    field.pointerMove(_Event())

    assert pending == [True]
    assert field.pointer_press_recorded is False
    assert field.mouse_mode == mouse.POINTER
    assert field.current_trace == []
    assert field.calls == []


def test_ending_pending_events_preserves_recorded_lasso_press():
    from PyReconstruct.modules.gui.main.field_widget_7_view import FieldWidgetView

    field = _Field()
    field.pointerPress(_Event())
    field.is_selecting_traces = True
    field.current_trace = [(10, 20)]
    field.cancelTraceMove = lambda: FieldWidgetMouse.cancelTraceMove(field)

    FieldWidgetView.endPendingEvents(field)
    field.pointerMove(_Event())

    assert field.pointer_press_recorded is True
    assert field.current_trace == [(10, 20), (30, 40)]
    assert field.calls == ["update"]
