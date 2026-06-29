"""Regression test for mutate-while-iterating in the trace-toggle methods.

toggleHideAllTraces and toggleShowAllTraces both pruned hidden traces from the
selection with::

    for trace in self.section.selected_traces:
        if trace.hidden:
            self.section.selected_traces.remove(trace)

Removing from a list while iterating it forward skips the element after each
removed one, so two adjacent hidden traces leave the second one selected
(hidden-but-selected), which later operations then act on. Exercised against
duck-typed stubs; no real FieldWidget / Qt is required.
"""
import types

from PyReconstruct.modules.gui.main import field_widget_2_trace as fwt


class _Trace:
    def __init__(self, name, hidden):
        self.name = name
        self.hidden = hidden


def _stub(selected, **flags):
    stub = types.SimpleNamespace(
        section=types.SimpleNamespace(selected_traces=list(selected)),
        generateView=lambda *a, **k: None,
    )
    for k, v in flags.items():
        setattr(stub, k, v)
    return stub


def test_toggle_hide_all_removes_every_hidden_selected_trace():
    # two ADJACENT hidden traces then a visible one: the old loop skipped 'b'
    a, b, c = _Trace("a", True), _Trace("b", True), _Trace("c", False)
    stub = _stub([a, b, c], hide_trace_layer=False, show_all_traces=False)

    fwt.FieldWidgetTrace.toggleHideAllTraces(stub)

    assert [t for t in stub.section.selected_traces if t.hidden] == []
    assert c in stub.section.selected_traces


def test_toggle_show_all_off_removes_every_hidden_selected_trace():
    a, b, c = _Trace("a", True), _Trace("b", True), _Trace("c", False)
    # show_all_traces True -> toggles to False -> the pruning branch runs
    stub = _stub([a, b, c], show_all_traces=True, hide_trace_layer=False)

    fwt.FieldWidgetTrace.toggleShowAllTraces(stub)

    assert [t for t in stub.section.selected_traces if t.hidden] == []
    assert c in stub.section.selected_traces


def test_toggle_hide_all_keeps_visible_selection_intact():
    # no hidden traces: selection is unchanged (behavior-preserving check)
    a, b = _Trace("a", False), _Trace("b", False)
    stub = _stub([a, b], hide_trace_layer=False, show_all_traces=False)

    fwt.FieldWidgetTrace.toggleHideAllTraces(stub)

    assert stub.section.selected_traces == [a, b]
