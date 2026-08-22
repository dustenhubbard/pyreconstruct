"""One key smooths what the focus says is selected.

Ctrl+Shift+R (remappable, carried by the field menu's "Smooth traces" row) is
dispatched by focus, the selectAll pattern: over the object list it smooths
the selected objects whole (field.smoothObject, whose object_function wrapper
reads the table's own selection), everywhere else it smooths the selected
traces on this section (field.smoothTraces). The trace list's copy of the row
stays keyless and calls the field method directly, so exactly one QAction
claims the sequence -- Qt answers an ambiguous shortcut by firing neither.
"""
import pytest

from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.gui.main.context_menu_list import get_context_menu_list_trace

pytestmark = pytest.mark.gui


def test_default_binding_exists_and_is_unique():
    assert default_settings.get("smoothtraces_act") == "Ctrl+Shift+R"
    claimants = [n for n, v in default_settings.items()
                 if isinstance(v, str) and v == "Ctrl+Shift+R"]
    assert claimants == ["smoothtraces_act"]


def test_only_the_field_row_carries_the_binding(main_window):
    field = main_window.field

    def row(entries):
        for e in entries:
            if isinstance(e, tuple) and e[0] == "smoothtraces_act":
                return e
        raise AssertionError("smoothtraces_act row missing")

    in_field = row(get_context_menu_list_trace(field, is_in_field=True))
    in_list = row(get_context_menu_list_trace(field, is_in_field=False))
    assert in_field[2] is main_window.series          # series form: remappable
    assert in_list[2] == ""                           # keyless: one claimant
    calls = []
    monkeypatch_target = main_window
    monkeypatch_target.smoothSelection = lambda: calls.append("dispatched")
    in_field[3]()                                      # routed by focus
    assert calls == ["dispatched"]
    assert in_list[3] == field.smoothTraces            # direct


def test_dispatch_routes_by_focus(main_window, monkeypatch):
    mw = main_window
    calls = []
    monkeypatch.setattr(mw.field, "smoothTraces", lambda *a, **k: calls.append("traces"))
    monkeypatch.setattr(mw.field, "smoothObject", lambda *a, **k: calls.append("object"))

    monkeypatch.setattr(mw, "getFocusWidget", lambda: mw.field)
    mw.smoothSelection()
    assert calls == ["traces"]

    mw.field.openList("object")
    table = mw.field.table_manager.tables["object"][0]
    monkeypatch.setattr(mw, "getFocusWidget", lambda: table)
    mw.smoothSelection()
    assert calls == ["traces", "object"]
