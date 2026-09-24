"""A focused trace list with no selected row must not crash "Edit attributes".

Found by the Codex click test on 2026-09-24 (artifacts/clicktest/2026-09-23-tag-sets
in the hub): after OK on Set Attributes the trace list keeps focus but loses its
selection, and the next Cmd+E raised ``TypeError: 'NoneType' object is not
iterable`` from ``TraceTableWidget.getTraces``. ``getSelected`` returns None for
an empty selection, and the ``trace_function`` wrapper handed that None to
``getTraces``. The wrapper now treats it as no traces and returns quietly, the
same as an empty field selection.
"""
import pytest

pytestmark = pytest.mark.gui


def test_focused_trace_list_with_nothing_selected_returns_quietly(main_window, monkeypatch):
    field = main_window.field
    field.openList(list_type="trace")
    table = field.table_manager.tables["trace"][0]
    table.table.clearSelection()
    table.temp_selected = None
    assert table.getSelected() is None, "the precondition: an empty selection reads as None"
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)

    assert field.traceDialog() is None
