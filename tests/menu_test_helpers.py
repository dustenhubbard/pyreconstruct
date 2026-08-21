"""Shared stubs for building the context menus with no Qt loop.

These lived in test_context_menu_frequency.py until the stable line dropped
that file (it pinned the fork's menu organization, which this line does not
use). The stubs themselves are organization-neutral: they build whatever the
live builders return, and several shortcut tests depend on them.
"""

from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_obj,
    get_context_menu_list_trace,
    get_field_menu_list,
)


class _Anything:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


def _series():
    return _Anything(user_columns={}, alignments=set(), groups_visibility={})


class _FieldStub(_Anything):
    """A field stub whose entity submenus really are the shared builders."""

    def __init__(self, series=None):
        super().__init__(series=series or _series())

    def getTraceMenu(self, is_in_field=True, list_ops=None, find_in_field=None):
        return get_context_menu_list_trace(
            self, is_in_field, list_ops=list_ops, find_in_field=find_in_field
        )

    def getObjMenu(self, list_ops=None, is_in_field=True):
        return get_context_menu_list_obj(
            self, list_ops=list_ops, is_in_field=is_in_field
        )

    def getZtraceMenu(self, list_ops=None):
        from PyReconstruct.modules.gui.main.field_widget_2_trace import FieldWidgetTrace
        return FieldWidgetTrace.getZtraceMenu(self, list_ops=list_ops)


def _main_window_stub(series=None):
    series = series or _series()
    return _Anything(series=series, field=_FieldStub(series))


def _field_menu(series=None):
    return get_field_menu_list(_main_window_stub(series))


def _kbds(menu):
    out = {}
    for entry in menu:
        if isinstance(entry, tuple):
            out[entry[0]] = entry[2]
        elif isinstance(entry, dict):
            out.update(_kbds(entry["opts"]))
    return out


def _act_names(menu):
    out = []
    for entry in menu:
        if isinstance(entry, tuple):
            out.append(entry[0])
        elif isinstance(entry, dict):
            out += _act_names(entry["opts"])
    return out


def _rows(menu):
    out = []
    for entry in menu:
        if entry is None:
            out.append("-----")
        elif isinstance(entry, tuple):
            out.append(entry[1])
        elif isinstance(entry, dict):
            out.append(f"{entry['text']} >")
            out += [f"    {r}" for r in _rows(entry["opts"])]
        else:
            out.append("<QAction>")
    return out
