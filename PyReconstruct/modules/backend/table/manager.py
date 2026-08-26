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
    
    def newTable(self, table_type : str, section=None):
        """Create a new object list widget."""
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
