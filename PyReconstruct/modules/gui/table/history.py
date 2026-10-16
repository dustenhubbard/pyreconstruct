from PySide6.QtWidgets import (
    QDockWidget, QWidget, QTableWidgetItem, QAbstractItemView, QLabel, QVBoxLayout
)
from PySide6.QtCore import Qt

from .copy_table_widget import CopyTableWidget

from PyReconstruct.modules.datatypes import LogSet, Log
from PyReconstruct.modules.datatypes.log import splitRow


def _count(n, noun):
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def setAsideText(n : int) -> str:
    """Say that n lines of the history were set aside and are still on disk.

    Shared by the history views and the notice when a series opens.
    """
    return (
        f"{_count(n, 'line')} of this series' history could not be read and "
        f"{'is' if n == 1 else 'are'} not shown. The series file still holds "
        f"{'it' if n == 1 else 'them'}."
    )


def historyNotice(log_set : LogSet) -> str:
    """Say what the reader did not show as written, or "" if nothing.

    Lines set aside are counted for the whole series: a row that will not
    parse names no object a view could filter it by. Rebuilt rows are counted
    among the rows shown.
    """
    parts = []
    if log_set.skipped_rows:
        parts.append(setAsideText(len(log_set.skipped_rows)))
    rebuilt_ids = {id(log) for log in log_set.rebuilt_logs}
    rebuilt = sum(id(log) in rebuilt_ids for log in log_set.all_logs)
    if rebuilt:
        parts.append(
            f"{_count(rebuilt, 'row')} {'was' if rebuilt == 1 else 'were'} "
            "rebuilt from an entry an older version split across lines. "
            "Line breaks show as _."
        )
    return " ".join(parts)


class HistoryTableWidget(QDockWidget):

    def __init__(self, log_set : LogSet, mainwindow : QWidget, obj_names : list = None):
        """Create a text widget to display history"""
        super().__init__(mainwindow)
        self.mainwindow = mainwindow

        self.setFloating(True)
        self.setAllowedAreas(Qt.NoDockWidgetArea)
        self.setWindowTitle("History")
        # closing destroys it: nothing tracks or reshows these, so without
        # this every history view left a hidden dock holding the whole
        # materialized series log until the app exited (found 2026-08-28)
        self.setAttribute(Qt.WA_DeleteOnClose)

        # filter the logs
        self.filterLogs(log_set, obj_names)
        
        # create the table
        self.createTable(log_set)

        self.resize(self.sizeHint())

        self.show()
    
    def filterLogs(self, log_set : LogSet, obj_names : list):
        """Remove logs unrelated to objects of interest."""
        if not obj_names:
            return
        
        i = 0
        while i < len(log_set.all_logs):
            log = log_set.all_logs[i]
            if log.obj_name not in obj_names:
                log_set.all_logs.pop(i)
            else:
                i += 1

    def setRow(self, r : int, log : Log):
        """Set the data for a row.
        
            Params:
                r (int): the row index
                snum (int): the section number
        """
        # splitRow, not split(", "): a quoted user or object name holds ", "
        # and must stay one cell
        # (and no strip: an empty event leaves the row ending in ", ")
        date, time, (user, _), (obj_name, _), sections, event = splitRow(
            str(log)
        )
        for c, s in enumerate((date, time, user, obj_name, sections, event)):
            self.table.setItem(r, c, QTableWidgetItem(s))
    
    def createTable(self, log_set : LogSet):
        """Create the table widget."""
        # establish table headers
        self.horizontal_headers = ["Date", "Time", "User", "Object", "Sections", "Event"]

        self.table = CopyTableWidget(self, len(log_set.all_logs), len(self.horizontal_headers))
        notice = historyNotice(log_set)
        if notice:
            self.notice = QLabel(notice, self)
            self.notice.setWordWrap(True)
            container = QWidget(self)
            layout = QVBoxLayout(container)
            layout.addWidget(self.notice)
            layout.addWidget(self.table)
            self.setWidget(container)
        else:
            self.notice = None
            self.setWidget(self.table)

        # format table
        self.table.setShowGrid(False)  # no grid
        self.table.setAlternatingRowColors(True)  # alternate row colors
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # cannot be edited
        self.table.setHorizontalHeaderLabels(self.horizontal_headers)  # titles
        self.table.verticalHeader().hide()  # no veritcal header
        
        # fill in section data
        for r, log in enumerate(reversed(log_set.all_logs)):
            self.setRow(r, log)
        
        # format the table
        self.table.resizeColumnsToContents()