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

        # allow the list docks to nest/tab into a single group (UI v1 Slice 3)
        self.mainwindow.setDockNestingEnabled(True)

        # guards open_tables persistence during programmatic teardown (closeAll)
        self._suppress_open_tables_sync = False
    
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

        # find an already-open list dock to tab the new one onto, so all list
        # types share a single left dock group (UI v1 Slice 3)
        anchor = None
        for tt in self.tables:
            if self.tables[tt]:
                anchor = self.tables[tt][0]
                break

        self.tables[table_type].append(new_table)

        self.mainwindow.addDockWidget(Qt.LeftDockWidgetArea, new_table)
        if anchor is not None:
            self.mainwindow.tabifyDockWidget(anchor, new_table)

        self._syncOpenTables(table_type, True)

    def _syncOpenTables(self, table_type : str, is_open : bool):
        """Add/remove a list type from the global open_tables option so the panel
        restores the same lists next open. Writes back a NEW list (the qsettings
        defaults are a shallow copy, so never mutate the returned list in place)."""
        if self._suppress_open_tables_sync or self.series is None:
            return
        current = list(self.series.getOption("open_tables"))
        if is_open and table_type not in current:
            current.append(table_type)
        elif not is_open and table_type in current:
            current.remove(table_type)
        else:
            return
        self.series.setOption("open_tables", current)

    def onTableClosed(self, table_type : str):
        """Called from DataTable.closeEvent after a dock removes itself; drop the
        type from open_tables only when no dock of that type remains."""
        if self.tables.get(table_type):
            return
        self._syncOpenTables(table_type, False)

    def listsPanelCollapsed(self) -> bool:
        """Whether the left lists panel is collapsed (global preference)."""
        return self.series.getOption("lists_panel_collapsed")

    def setListsPanelCollapsed(self, collapsed : bool):
        """Hide/show every list dock and persist the choice. Collapse HIDES the
        docks (it does not close them), so open_tables is untouched."""
        for tt in self.tables:
            for t in self.tables[tt]:
                t.setHidden(collapsed)
        self.series.setOption("lists_panel_collapsed", collapsed)
    
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
        """Quick shortcut to toggle curation on/off for the tables."""
        cr_on = all([table.columns["Curate"] for table in self.tables])
        for table in self.tables["object"]:
            table.columns["Curate"] = not cr_on
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
        # iterate a copy: each close() fires closeEvent, which removes the table
        # from self.tables[name] mid-iteration (data_table.py) and would skip tables.
        # suppress open_tables sync: this is programmatic teardown (e.g. series
        # switch), not the user closing lists, so the saved preference must persist.
        self._suppress_open_tables_sync = True
        try:
            for n, l in self.tables.items():
                for t in l.copy():
                    t.close()
        finally:
            self._suppress_open_tables_sync = False
