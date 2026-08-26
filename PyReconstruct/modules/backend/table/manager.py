from PySide6.QtCore import Qt

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
        """The Lists pill / View menu / shortcut toggle (his stage 1,
        2026-08-25): hide every docked list, or bring back exactly the set
        the collapse hid. Floating lists are real windows now and are never
        touched. Collapsing with no docked list visible is a no-op rather
        than an empty collapsed state, so the toggle cannot get stuck."""
        if self._collapsed:
            self.expandLists()
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
        x's"). Wired at most once per tab bar; Qt reuses them, and the
        property guard keeps a rewire from stacking connections."""
        for tb in self._dockTabBars():
            tb.setTabsClosable(True)
            if not tb.property("pyrecon_close_wired"):
                tb.setProperty("pyrecon_close_wired", True)
                tb.tabCloseRequested.connect(
                    lambda i, tb=tb: self._closeTabbedList(tb, i)
                )

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
        """Re-decide every list's docked title bar; see syncDockedTitleBar."""
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
