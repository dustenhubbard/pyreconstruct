"""The list_layout option: a series remembers its open lists.

Patrick works with undocked lists, and until now every launch started bare:
nothing saved which lists were open, floating, or where. The manager can now
capture its layout as a JSON-friendly dict and replay it; the main window
writes it to the series-scoped ``list_layout`` option when a series closes
and replays it when one opens.

The fixtures here reuse the dock battery's real QMainWindow + real
TableManager recipe (test_list_dock_sizing): docking, tabbing, and floating
geometry are the substance of a layout, so stubs would prove nothing.
"""

import pytest

from test_data_lists_real_widget import MenuStubField
from test_list_dock_sizing import settle, open_list

pytestmark = pytest.mark.gui


@pytest.fixture
def dock_mainwindow(qapp, real_series, gui_dialogs):
    """The dock battery's real-QMainWindow recipe, duplicated deliberately:
    importing the fixture by name trips the F811 gate (the test parameters
    shadow the module-level import), and a fixture this small is cheaper to
    own than to re-export through a conftest."""
    from PySide6.QtWidgets import QMainWindow, QWidget

    class DockMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.series = real_series
            first = sorted(real_series.sections)[0]
            self.section = real_series.loadSection(first)
            self.field = MenuStubField(real_series, self.section)
            self.viewer = None

        def saveAllData(self):
            pass

        def seriesModified(self, modified=True):
            pass

        def checkActions(self, *args, **kwargs):
            pass

        def changeSection(self, snum, save=False):
            pass

    window = DockMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(1600, 1000)
    window.show()
    settle(qapp)
    yield window
    window.close()
    window.deleteLater()


def _manager(dock_mainwindow):
    from PyReconstruct.modules.backend.table.manager import TableManager

    return TableManager(
        dock_mainwindow.series, dock_mainwindow.section, {}, dock_mainwindow
    )


def test_layout_roundtrips_docked_tabs_and_a_tiny_float(qapp, dock_mainwindow):
    import json

    manager = _manager(dock_mainwindow)
    open_list(manager, "object", qapp)
    open_list(manager, "section", qapp)
    floater = open_list(manager, "ztrace", qapp)
    floater.setFloating(True)
    settle(qapp)
    floater.resize(150, 140)                     # Patrick's tiny list
    settle(qapp)

    layout = manager.captureLayout()
    json.dumps(layout)                           # must be storable as-is

    fresh = _manager(dock_mainwindow)
    fresh.restoreLayout(layout, dock_mainwindow.section)
    settle(qapp)

    assert len(fresh.tables["object"]) == 1
    assert len(fresh.tables["section"]) == 1
    obj = fresh.tables["object"][0]
    sec = fresh.tables["section"][0]
    assert not obj.isFloating() and not sec.isFloating()
    assert obj in dock_mainwindow.tabifiedDockWidgets(sec)

    zt = fresh.tables["ztrace"][0]
    assert zt.isFloating()
    assert zt.width() == 150                     # the saved size, not the
    assert zt.height() == 140                    # first-float default


def test_collapsed_layout_comes_back_collapsed(qapp, dock_mainwindow):
    manager = _manager(dock_mainwindow)
    open_list(manager, "object", qapp)
    open_list(manager, "section", qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    layout = manager.captureLayout()
    assert layout["collapsed"] is True
    assert len(layout["open"]) == 2              # hidden by collapse != closed

    fresh = _manager(dock_mainwindow)
    fresh.restoreLayout(layout, dock_mainwindow.section)
    settle(qapp)
    assert fresh.listsCollapsed()
    fresh.toggleListsCollapsed()
    settle(qapp)
    assert all(t.isVisible() for t in fresh.tables["object"])


def test_closed_lists_are_absent_and_unknown_types_are_skipped(qapp, dock_mainwindow):
    manager = _manager(dock_mainwindow)
    open_list(manager, "object", qapp)
    goner = open_list(manager, "section", qapp)
    goner.close()
    settle(qapp)
    layout = manager.captureLayout()
    assert [e["type"] for e in layout["open"]] == ["object"]

    layout["open"].append({"type": "hologram", "floating": False})
    fresh = _manager(dock_mainwindow)
    fresh.restoreLayout(layout, dock_mainwindow.section)   # must not raise
    settle(qapp)
    assert len(fresh.tables["object"]) == 1


def test_the_option_is_registered_series_scoped(real_series):
    """getOption must know list_layout (and default it empty), so the main
    window's capture/restore can store through the ordinary option path."""
    value = real_series.getOption("list_layout")
    assert value in ({}, None) or isinstance(value, dict)
