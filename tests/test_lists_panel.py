"""UI v1 Slice 3 — lists-left tabbed/collapsible panel (headless backbone).

These tests cover BEHAVIOR only (offscreen); the look is signed off interactively.
QSettings is isolated to a temp dir by the session-autouse fixture in conftest.py, so
the getOption/setOption round-trips never touch real user preferences.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from PyReconstruct.modules.datatypes.series import Series  # noqa: E402


def _global_series():
    """A minimal Series instance for exercising GLOBAL (computer-wide) options.

    The global getOption/setOption path only reads ``self.options`` and the class-level
    ``qsettings_defaults``; it never needs the heavy jser construction, so __new__ + an
    empty options dict is sufficient and isolated.
    """
    s = Series.__new__(Series)
    s.options = {}
    return s


def _clear(*keys):
    settings = QSettings("KHLab", "PyReconstruct")
    for k in keys:
        settings.remove(k)
    settings.sync()


# --- B1: register the two global QSettings defaults -------------------------------

def test_b1_keys_registered_global_with_defaults():
    assert Series.qsettings_defaults.get("lists_panel_collapsed") is False
    assert Series.qsettings_defaults.get("open_tables") == ["object"]


def test_b1_keys_are_global_not_per_series_or_internal():
    # not per-series
    assert "lists_panel_collapsed" not in Series.qsettings_series_defaults
    assert "open_tables" not in Series.qsettings_series_defaults
    # not an internal per-series option (so the series.py:440-444 prune never touches them)
    empty_opts = Series.getEmptyDict()["options"]
    assert "lists_panel_collapsed" not in empty_opts
    assert "open_tables" not in empty_opts


def test_b1_getOption_returns_defaults_when_unset():
    _clear("lists_panel_collapsed", "open_tables")
    s = _global_series()
    assert s.getOption("lists_panel_collapsed") is False
    assert s.getOption("open_tables") == ["object"]


def test_b1_setOption_getOption_roundtrip():
    s = _global_series()
    s.setOption("lists_panel_collapsed", True)
    assert s.getOption("lists_panel_collapsed") is True
    s.setOption("open_tables", ["object", "trace"])
    assert s.getOption("open_tables") == ["object", "trace"]


def test_b1_resolves_via_global_qsettings_not_internal_options():
    # The keys must route through the global QSettings("KHLab","PyReconstruct"),
    # not self.options. A fresh instance with empty options still resolves them.
    s = _global_series()
    assert "open_tables" not in s.options
    s.setOption("open_tables", ["object", "ztrace"])
    # value lives in global QSettings, readable by an independent instance
    other = _global_series()
    assert other.getOption("open_tables") == ["object", "ztrace"]


# --- B2: tabify the list docks into one left group + fix closeAll skip-bug --------

import PyReconstruct.modules.backend.table.manager as mgrmod  # noqa: E402


class _StubDock:
    """Stand-in for a DataTable: a no-widget object that mirrors the one behavior
    closeAll depends on — closeEvent removing itself from manager.tables[name]."""
    def __init__(self, manager, name):
        self.manager = manager
        self.name = name
        self.closed = False

    def close(self):
        self.closed = True
        self.manager.tables[self.name].remove(self)  # mirrors data_table.py:351


def test_b2_closeall_closes_every_table():
    # Reproduces the mutate-while-iterate skip-bug: closing a table removes it from
    # the same list closeAll iterates, so a plain `for t in l` skips half.
    mgr = mgrmod.TableManager.__new__(mgrmod.TableManager)
    mgr.tables = {tt: [] for tt in mgrmod.table_type_classes}
    tables = [_StubDock(mgr, "object") for _ in range(4)]
    mgr.tables["object"].extend(tables)

    mgr.closeAll()

    assert mgr.tables["object"] == [], "closeAll left tables open (skip-bug)"
    assert all(t.closed for t in tables), "not every table received close()"


def _qmainwindow():
    from PySide6.QtWidgets import QMainWindow
    return QMainWindow()


def _stub_table_classes():
    from PySide6.QtWidgets import QDockWidget, QWidget

    class StubTableDock(QDockWidget):
        def __init__(self, *args):
            super().__init__()
            self.setWidget(QWidget())

    return {k: StubTableDock for k in mgrmod.table_type_classes}


def test_b2_init_enables_dock_nesting(qapp):
    win = _qmainwindow()
    mgrmod.TableManager(None, None, None, win)
    assert win.isDockNestingEnabled() is True


def test_b2_newtable_tabifies_into_one_left_group(qapp, monkeypatch):
    from PySide6.QtCore import Qt

    monkeypatch.setattr(mgrmod, "table_type_classes", _stub_table_classes())
    win = _qmainwindow()
    mgr = mgrmod.TableManager(None, None, None, win)

    for tt in ("object", "trace", "ztrace"):
        mgr.newTable(tt)

    obj_dock = mgr.tables["object"][0]
    for tt in ("object", "trace", "ztrace"):
        d = mgr.tables[tt][0]
        assert win.dockWidgetArea(d) == Qt.LeftDockWidgetArea

    tabbed = set(win.tabifiedDockWidgets(obj_dock))
    assert mgr.tables["trace"][0] in tabbed
    assert mgr.tables["ztrace"][0] in tabbed


def test_b2_newtable_single_dock_no_crash(qapp, monkeypatch):
    from PySide6.QtCore import Qt

    monkeypatch.setattr(mgrmod, "table_type_classes", _stub_table_classes())
    win = _qmainwindow()
    mgr = mgrmod.TableManager(None, None, None, win)
    mgr.newTable("object")  # no tabify partner — must not raise
    assert win.dockWidgetArea(mgr.tables["object"][0]) == Qt.LeftDockWidgetArea


def test_b2_tab_group_survives_anchor_close(qapp, monkeypatch):
    # Closing the anchor (object) dock must not fragment the group: a later dock
    # still joins the single existing tab group via whatever dock remains.
    monkeypatch.setattr(mgrmod, "table_type_classes", _stub_table_classes())
    win = _qmainwindow()
    mgr = mgrmod.TableManager(None, None, None, win)
    for tt in ("object", "trace", "ztrace"):
        mgr.newTable(tt)

    obj = mgr.tables["object"][0]          # the anchor
    mgr.tables["object"].remove(obj)
    obj.close(); obj.setParent(None)

    mgr.newTable("flag")                   # anchors onto the remaining group

    group = set(win.tabifiedDockWidgets(mgr.tables["trace"][0]))
    assert mgr.tables["ztrace"][0] in group
    assert mgr.tables["flag"][0] in group  # one group, not fragmented
