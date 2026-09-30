"""Edit radius shows the radius in the frame it applies it in, and refuses bad values.

Before the fix, on a section with a 1.2x transform the prompt showed the
untransformed radius while `Section.editTraceRadius` applied the value in the
transformed frame, so pressing OK without touching it shrank the trace by 1/1.2.
A radius of 0 collapsed the trace onto its centroid and a negative one reflected it.
"""
import pytest
from PySide6.QtWidgets import QInputDialog

from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.main import field_widget_2_trace as fw


BAD_RADII = ["0", "-0", "-1", "-0.5", "nan", "inf", "-inf", "abc", ""]


def _setup(window, monkeypatch, answer=None):
    field = window.field
    section = field.section
    section.tform = Transform([1.2, 0, 0, 0, 1.2, 0])
    field.generateView()
    trace = next(t for t in section.tracesAsList() if len(t.points) >= 3)
    window.series.setAttr(trace.name, "locked", False)
    section.selected_traces = [trace]

    seen = {}

    def fake_get_text(parent, title, label, text="", **kw):
        seen["prefill"] = text
        return (text if answer is None else answer), True

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))
    notified = []
    monkeypatch.setattr(fw, "notify", lambda *a, **k: notified.append(a))
    return field, trace, seen, notified


def test_prefill_is_the_on_screen_radius(main_window, monkeypatch):
    field, trace, seen, _ = _setup(main_window, monkeypatch)
    shown = trace.getRadius(field.section.tform)

    field.editTraceRadius()

    assert float(seen["prefill"]) == pytest.approx(shown, abs=1e-6)


def test_untouched_ok_leaves_the_trace_alone(main_window, monkeypatch):
    field, trace, _, notified = _setup(main_window, monkeypatch)
    before = list(trace.points)

    field.editTraceRadius()

    assert trace.points == before
    assert notified == []


def test_new_radius_is_applied_on_screen(main_window, monkeypatch):
    field, trace, _, notified = _setup(main_window, monkeypatch, answer="2")

    field.editTraceRadius()

    assert notified == []
    assert trace.getRadius(field.section.tform) == pytest.approx(2, abs=1e-6)


@pytest.mark.parametrize("text", BAD_RADII)
def test_bad_radius_is_refused_with_a_message(main_window, monkeypatch, text):
    field, trace, _, notified = _setup(main_window, monkeypatch, answer=text)
    before = list(trace.points)

    field.editTraceRadius()

    assert trace.points == before, f"{text!r} must not change the trace"
    assert notified, f"{text!r} should be refused with a message"


@pytest.mark.parametrize("rad", [0.0, -1.0, float("nan"), float("inf")])
def test_section_refuses_bad_radius_before_touching_a_trace(main_window, rad):
    section = main_window.field.section
    trace = next(t for t in section.tracesAsList() if len(t.points) >= 3)
    before = list(trace.points)
    count = len(section.tracesAsList())

    with pytest.raises(ValueError):
        section.editTraceRadius([trace], rad)

    assert trace.points == before
    assert len(section.tracesAsList()) == count


@pytest.mark.parametrize("text", ["nan", "inf"])
def test_object_radius_ignores_non_finite_values(main_window, monkeypatch, text):
    field, trace, _, _ = _setup(main_window, monkeypatch, answer=text)
    before = list(trace.points)

    field.editRadius()

    assert trace.points == before
