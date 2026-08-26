from PySide6.QtCore import QObject, Qt

from PyReconstruct.modules.gui.table import (
    ObjectTableWidget,
    TraceTableWidget,
    SectionTableWidget,
    ZtraceTableWidget,
    FlagTableWidget
)
from PyReconstruct.modules.datatypes import (
    Series,
    Section,
)

table_type_classes = {
    "object": ObjectTableWidget,
    "trace": TraceTableWidget,
    "section": SectionTableWidget,
    "ztrace": ZtraceTableWidget,
    "flag": FlagTableWidget
}

class _TabDragFilter(QObject):
    """Tears a list out of its tab group when the user drags the tab.

    Qt's own tab tear-out drags the dock by its TITLE BAR, which a tabbed
    list does not show, so the gesture did nothing. This watches the dock
    area's tab bar, and once the pointer has travelled far enough to be a
    drag rather than a click, floats that list under the cursor and asks the
    window system to carry the drag on natively (``startSystemMove``), which
    is what makes the window follow the mouse and drop where it is let go.
    """

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self._press_pos = None
        self._press_index = -1

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent, Qt

        etype = event.type()
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_index = obj.tabAt(self._press_pos)
        elif etype == QEvent.MouseMove and self._press_pos is not None:
            if not (event.buttons() & Qt.LeftButton):
                self._press_pos = None
            else:
                from PySide6.QtWidgets import QApplication

                travelled = (event.position().toPoint() - self._press_pos)
                # twice the platform's click slop: a tab click that wobbles
                # must never tear the list out
                threshold = QApplication.startDragDistance() * 2
                if max(abs(travelled.x()), abs(travelled.y())) >= threshold:
                    index, self._press_pos = self._press_index, None
                    self.manager.tearOutTab(obj, index, event.globalPosition().toPoint())
                    return True
        elif etype in (QEvent.MouseButtonRelease, QEvent.Leave):
            self._press_pos = None
        return super().eventFilter(obj, event)


class TableManager():

    def __init__(self, series : Series, section : Section, series_states, mainwindow):
        """Create the object table manager.
        
            Params:
                series (Series): the series object
                series_states (SeriesStates): the series states object for the series
                mainwindow (MainWindow): the parent main window object
        """
        self.tables = dict(
            [(tt, []) for tt in table_type_classes]
        )
        self.series = series
        self.section = section
        self.mainwindow = mainwindow
        self.series_states = series_states
        self._tab_drag_filter = _TabDragFilter(self)
        # the docked lists hidden by the collapse toggle, in hide order;
        # non-empty IS the collapsed state
        self._collapsed = []
    
    def newTable(self, table_type : str, section=None):
        """Create a new object list widget."""
        # opening a list while the lists are collapsed reveals them first, so
        # the new list can tab onto a visible anchor and is actually seen
        if self._collapsed:
            self.expandLists()

        if table_type == "trace":
            args = (
                self.series,
                section,
                self.mainwindow,
                self
            )
        else:
            args = (
                self.series,
                self.mainwindow,
                self
            )
        
        new_table = table_type_classes[table_type](*args)
        self.tables[table_type].append(new_table)

        anchor = self._dockedAnchor(new_table)
        if hasattr(self.mainwindow, "setTabPosition"):
            # tabs along the top of the list area, not Qt's bottom default
            # (his call, 2026-08-25)
            from PySide6.QtWidgets import QTabWidget
            self.mainwindow.setTabPosition(
                Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea,
                QTabWidget.TabPosition.North,
            )
        self.mainwindow.addDockWidget(Qt.LeftDockWidgetArea, new_table)
        if anchor is not None:
            self.mainwindow.tabifyDockWidget(anchor, new_table)
            new_table.show()
            new_table.raise_()
        self._wireTabBars()
        self._syncTitleBars()

    def _dockedAnchor(self, new_table):
        """Find a visible docked list for a new list to tab onto.

        Every list docks into the same area; letting Qt split the area
        squeezes each list to ~180px once a few are open. Tabbing onto an
        existing list gives every list the full area instead. Floating and
        closed lists are not anchors, so a new list still docks plainly when
        no usable anchor exists. Users can still drag a tab out to split.
        """
        if not hasattr(self.mainwindow, "tabifyDockWidget"):
            return None
        for tables in self.tables.values():
            for table in tables:
                if (
                    table is not new_table
                    and not table.isFloating()
                    and table.isVisible()
                    and self.mainwindow.dockWidgetArea(table) == Qt.LeftDockWidgetArea
                ):
                    return table
        return None
    
    def listsCollapsed(self):
        """True while the collapse toggle is hiding the docked lists."""
        return bool(self._collapsed)

    def toggleListsCollapsed(self):
        """The sidebar pill / View menu / shortcut toggle (his stage 1,
        2026-08-25): hide every docked list, or bring back exactly the set
        the collapse hid. Floating lists are real windows now and are never
        touched. Collapsing with no docked list visible is a no-op rather
        than an empty collapsed state, so the toggle cannot get stuck.

        With NO list open at all -- a freshly opened series -- the toggle
        opens the object list instead of doing nothing (his call,
        2026-08-26): it is the list people reach for first, and a button
        that appears dead on a new series is worse than an opinion.
        """
        if self._collapsed:
            self.expandLists()
        elif not any(self.tables.values()):
            self.newTable("object")
        else:
            self.collapseLists()

    def collapseLists(self):
        docked = [
            t for tables in self.tables.values() for t in tables
            if not t.isFloating() and t.isVisible()
        ]
        for t in docked:
            t.hide()
        self._collapsed = docked

    def expandLists(self):
        # a list closed while hidden removed itself from self.tables
        # (DataTable.closeEvent); only survivors come back
        alive = {t for tables in self.tables.values() for t in tables}
        for t in self._collapsed:
            if t in alive:
                t.show()
        self._collapsed = []
        # Qt may mint a fresh tab bar for the restored group
        self._wireTabBars()
        self._syncTitleBars()

    def _dockTabBars(self):
        """The dock area's own tab bars. QMainWindow creates them as its
        direct children; every other QTabBar in the app (inside dialogs, the
        3D scene) has a deeper parent, which is what the parent check
        excludes."""
        if not hasattr(self.mainwindow, "findChildren"):
            return []
        from PySide6.QtWidgets import QTabBar
        return [tb for tb in self.mainwindow.findChildren(QTabBar)
                if tb.parent() is self.mainwindow]

    def _wireTabBars(self):
        """Give every dock tab an X (his call, 2026-08-25: "tabs but with
        x's") and a double-click that floats its list, the deliberate sibling
        of dragging the tab out. Wired at most once per tab bar; Qt reuses
        them, and the property guard keeps a rewire from stacking
        connections."""
        from PySide6.QtCore import Qt as _Qt

        for tb in self._dockTabBars():
            # Re-applied every pass, NOT guarded: Qt resets these on the tab
            # bar it reuses as docks come and go, which is how the close
            # buttons went missing and came back (his report, 2026-08-26).
            # Only the signal connections are one-shot, below.
            tb.setTabsClosable(True)
            tb.setContextMenuPolicy(_Qt.CustomContextMenu)
            if not tb.property("pyrecon_close_wired"):
                tb.setProperty("pyrecon_close_wired", True)
                tb.tabCloseRequested.connect(
                    lambda i, tb=tb: self._closeTabbedList(tb, i)
                )
                tb.tabBarDoubleClicked.connect(
                    lambda i, tb=tb: self._floatTabbedList(tb, i)
                )
                tb.customContextMenuRequested.connect(
                    lambda pos, tb=tb: self._tabContextMenu(tb, pos)
                )
                # dragging a tab out: ours, not Qt's. A tabbed list hides its
                # title bar, and Qt tears a dock out BY that title bar, so
                # there is nothing left for it to drag (his report,
                # 2026-08-26, twice). The filter below does the tear-out and
                # hands the rest of the drag to the window system.
                tb.installEventFilter(self._tab_drag_filter)

    def _floatTabbedList(self, tab_bar, index):
        """Float the list behind a double-clicked tab."""
        table = self._tableForTab(tab_bar, index)
        if table is not None:
            table.setFloating(True)

    def _tableForTab(self, tab_bar, index):
        """The list behind a dock tab, matched by the pointer in tabData
        (tab TEXT collides when two lists of one type are open)."""
        import shiboken6
        ptr = tab_bar.tabData(index)
        for tables in self.tables.values():
            for table in tables:
                if shiboken6.getCppPointer(table)[0] == ptr:
                    return table
        return None

    def tearOutTab(self, tab_bar, index, global_pos):
        """Float the list behind ``index`` and let the system carry the drag.

        The window becomes a real one immediately (not on mouse release, the
        ordinary float's rule): startSystemMove needs a native window to
        move, and the user is mid-gesture.
        """
        table = self._tableForTab(tab_bar, index)
        if table is None:
            return
        table.setFloating(True)
        table._becomeRealWindow()
        # Qt applies the list's LAST floating geometry to the fresh float in
        # queued events, which yanked the window to wherever it floated last
        # (his report, 2026-08-26: a wild jump). Drain those first, THEN put
        # the window under the cursor, near the title bar's left end so the
        # gesture reads as dragging the window by its title.
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        table.move(
            global_pos.x() - min(90, table.width() // 4),
            global_pos.y() - 10,
        )
        handle = table.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def _tabContextMenu(self, tab_bar, pos):
        """Right-click on a tab: float or close its list (his ask,
        2026-08-25). Returned for the tests; popped up for the user."""
        index = tab_bar.tabAt(pos)
        if index < 0:
            return None
        table = self._tableForTab(tab_bar, index)
        if table is None:
            return None
        from PySide6.QtWidgets import QMenu
        menu = QMenu(tab_bar)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.addAction("Undock this list", lambda: table.setFloating(True))
        menu.addAction("Close this list", table.close)
        menu.popup(tab_bar.mapToGlobal(pos))
        return menu

    def _closeTabbedList(self, tab_bar, index):
        """Close the list behind a dock tab's X.

        A dock tab bar stores its dock widget's C++ pointer in tabData;
        matching on that instead of the tab TEXT survives two lists of the
        same type, whose titles are identical."""
        import shiboken6
        ptr = tab_bar.tabData(index)
        for tables in self.tables.values():
            for table in list(tables):
                if shiboken6.getCppPointer(table)[0] == ptr:
                    table.close()
                    self._syncTitleBars()
                    return

    def _syncTitleBars(self):
        """Re-decide every list's docked title bar; see syncDockedTitleBar.

        Re-wires the tab bars on the way through: Qt discards and rebuilds a
        dock area's QTabBar as docks come and go, and a rebuilt bar arrives
        with no close buttons and none of our handlers (his report,
        2026-08-26: the tab X vanished, then came back). Wiring is
        idempotent, so running it here is cheap insurance.
        """
        self._wireTabBars()
        for tables in self.tables.values():
            for table in tables:
                if hasattr(table, "syncDockedTitleBar"):
                    table.syncDockedTitleBar()

    def captureLayout(self):
        """The open lists as a JSON-friendly dict, for the list_layout option.

        Collapsed lists count as open (the collapse is part of the layout);
        a closed list is simply absent. Geometry only matters for floating
        lists; docked ones rejoin the tab group on restore.
        """
        entries = []
        for ttype, tables in self.tables.items():
            for t in tables:
                if not t.isVisible() and t not in self._collapsed:
                    continue
                g = t.geometry()
                entries.append({
                    "type": ttype,
                    "floating": bool(t.isFloating()),
                    "geometry": [g.x(), g.y(), g.width(), g.height()],
                })
        return {"open": entries, "collapsed": self.listsCollapsed()}

    def restoreLayout(self, layout, section=None):
        """Reopen the lists a captureLayout dict describes.

        Floating lists come back at their saved geometry; the first-float
        default size is suppressed so a deliberately tiny list stays tiny.
        Unknown types (a future flavor's layout) are skipped, never an error.
        """
        for entry in (layout or {}).get("open", []):
            ttype = entry.get("type")
            if ttype not in self.tables:
                continue
            self.newTable(ttype, section=section if ttype == "trace" else None)
            table = self.tables[ttype][-1]
            if entry.get("floating"):
                table._float_size_applied = True
                table.setFloating(True)
                geometry = entry.get("geometry")
                if geometry and len(geometry) == 4:
                    table.setGeometry(*geometry)
        if (layout or {}).get("collapsed"):
            self.collapseLists()

    def refreshColumnWidths(self):
        """Re-measure every open list's columns.

        A theme switch changes fonts and cell padding, but the lists kept
        the widths measured under the OLD theme, so dark-theme text crowded
        its columns (his report, 2026-08-26; measured: a fresh dark list
        wants 99/53/45 where a switched one kept 91/36/28). The main window
        calls this after applying a theme.
        """
        for tables in self.tables.values():
            for table in tables:
                view = getattr(table, "table", None)
                if view is not None:
                    view.resizeColumnsToContents()

    def _markViewerStale(self, obj_names=None, ztrace_names=None, all_objects=False):
        """Mark meshes in the open 3D scene whose 2D data was just edited.

        The scene regenerates stale meshes the next time its window is
        focused (or through its Scene > Refresh edited objects action).

            Params:
                obj_names (iterable): the names of the modified objects
                ztrace_names (iterable): the names of the modified ztraces
                all_objects (bool): True if every scene object from the series
                    should be marked (series-wide operations)
        """
        viewer = getattr(self.mainwindow, "viewer", None)
        if viewer is None or viewer.is_closed:
            return
        if all_objects:
            viewer.markAllStale()
        else:
            viewer.markStale(obj_names, ztrace_names)

    def updateObjects(self, obj_names : list = None, clear_tracking=True):
        """Update the object info for the OBJECT AND TRACE LISTS ONLY.

            Params:
                obj_names (list): the list objects to update
        """
        if obj_names is None:
            # if the transform was modified, update all traces on section
            if self.section.tformsModified(scaling_only=True):
                obj_names = self.section.contours.keys()
            else:
                obj_names = self.section.getAllModifiedNames()

        self._markViewerStale(obj_names=obj_names)

        for table in self.tables["object"] + self.tables["trace"]:

            table.updateData(obj_names)

        if clear_tracking:
            self.section.clearTracking()
    
    def updateSections(self, section_numbers : list = None):
        """Update ONLY THE SECTION LIST for multiple sections.
        
            Params:
                section_numbers (list): the list of section numbers"""
        if section_numbers is None:
            section_numbers = [self.section.n]
        
        for table in self.tables["section"]:
            for snum in section_numbers:
                table.updateData(snum)
    
    def updateZtraces(self, ztrace_names : list = None, clear_tracking=True):
        """Update ONLY THE ZTRACE LIST.
        
            Params:
                ztrace_names (list): the list of ztrace names to update
        """
        if ztrace_names is None:
            ztrace_names = self.series.modified_ztraces

        self._markViewerStale(ztrace_names=ztrace_names)

        for table in self.tables["ztrace"]:
            table.updateData(ztrace_names)

        if clear_tracking:
            self.series.clearTracking()
    
    def updateFlags(self, section : Section = None, clear_tracking=True):
        """Update ONLY THE FLAG LIST for a specific section."""
        if section is None:
            section = self.section
        
        for table in self.tables["flag"]:
            table.updateData(section)
    
    def updateAll(self, clear_tracking=True):
        """Update the tables from the series data (SeriesData and tracking).
        
            Params:
                section (Section): the section object
        """
        self.updateObjects(clear_tracking=clear_tracking)
        self.updateSections()
        self.updateZtraces(clear_tracking=clear_tracking)
        self.updateFlags()
    
    def changeSection(self, section : Section):
        """Change the current section."""
        self.section = section
        for table in self.tables["trace"]:
            self.recreateTable(table)
    
    def toggleCuration(self):
        """Quick shortcut to toggle curation on/off for the object lists.

        Never reachable until the Help search made every menubar command
        runnable, at which point its first real invocation crashed: it
        iterated `self.tables` (a dict keyed by table type, so that yields
        strings) and indexed `columns` like a dict (it is a list of
        (name, shown) pairs -- see ObjectTableWidget, which reads it via
        dict(self.columns)).
        """
        obj_tables = self.tables["object"]
        cr_on = bool(obj_tables) and all(
            dict(table.columns)["Curate"] for table in obj_tables
        )
        for table in obj_tables:
            table.columns = [
                (name, (not cr_on) if name == "Curate" else shown)
                for name, shown in table.columns
            ]
            self.recreateTable(table)
    
    def recreateTable(self, table):
        """Updates a table with the current data.
        
            Params:
                table: the table to update
        """
        if type(table) is TraceTableWidget:
            table.createTable(self.section)
        else:
            table.createTable()
    
    def recreateTables(self, refresh_data=False):
        """Update all tables.
        
            Params:
                refresh_data (bool): True if SeriesData should be refreshed
        """
        self.mainwindow.saveAllData()
        if refresh_data:
            self.series.data.refresh()

        # recreateTables is used by series-wide operations (alignment changes,
        # imports, series undo) whose modified names are unknown -- flag every
        # scene mesh for regeneration
        self._markViewerStale(all_objects=True)

        for n, l in self.tables.items():
            for t in l:
                self.recreateTable(t)
    
    def updateObjCols(self):
        """Update the columns in the object lists."""
        for table in self.tables["object"]:
            table.updateObjCols()
    
    def hasFocus(self):
        """Check if one of the tables is focused."""
        for table_type in self.tables:
            for data_table in self.tables[table_type]:
                if data_table.table.hasFocus():
                    return data_table
        return None
    
    def refresh(self):
        """Reload all of the section data.
        
        (Sort of redundant, but here for clarity)
        """
        self.recreateTables(refresh_data=True)
    
    def closeAll(self):
        """Close all tables."""
        for n, l in self.tables.items():
            for t in l:
                t.close()
