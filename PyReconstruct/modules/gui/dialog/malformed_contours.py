import csv
import html

from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QPushButton,
    QDialogButtonBox,
    QHeaderView,
    QAbstractItemView,
    QApplication,
    QFileDialog,
)
from PySide6.QtCore import Qt

from PyReconstruct.modules.gui.utils import notifyConfirm


class MalformedContoursDialog(QDialog):
    """Report traces skipped during object smoothing.

    Each row is one trace that could not be smoothed (typically too few
    points to interpolate a curve). The dialog shows enough context to track
    each one down: the object, the section, how many points the trace had,
    where it sits, and why it was skipped. Selecting a row and clicking
    "Go to trace" (or double-clicking the row) focuses the field on it, and
    the list can be copied or exported for triage.
    """

    COLUMNS = ["Object", "Section", "Point count", "Location (x, y)", "Reason"]
    WINDOW_TITLE = "Traces skipped during smoothing"
    # column the table is sorted by when it opens; subclasses that put a
    # different column at index 1 override it to keep the sort meaningful
    DEFAULT_SORT_COLUMN = 1
    # whether the user can re-sort by clicking a column header. A subclass that
    # puts a widget in a cell has to turn this off: setCellWidget binds a widget
    # to a row NUMBER, and sorting moves the items between rows without taking
    # the widgets with them, so the widgets end up on the wrong records.
    SORTABLE = True

    def _columnSpecs(self):
        """Return (record-key, kind) pairs, one per column in COLUMNS.

        kind is one of "str", "int", "float", "loc" and controls how the cell
        value is stored (numeric kinds sort numerically). Subclasses override
        this together with COLUMNS to show different fields.
        """
        return [
            ("name", "str"),
            ("section", "int"),
            ("points", "int"),
            ("location", "loc"),
            ("reason", "str"),
        ]

    def __init__(self, mainwindow: QWidget, records: list, navigate=None,
                 delete=None):
        """Create the skipped-traces dialog.

            Params:
                mainwindow (QWidget): the parent window
                records (list): list of dicts, each with keys "name",
                    "section", "points", "location" ((x, y) or None), "reason"
                    and "trace" (the Trace object, used for deletion)
                navigate (callable): optional navigate(section_num, obj_name,
                    index) callback used to focus the field on a
                    double-clicked row
                delete (callable): optional delete(records) callback that
                    removes the given records from the series and returns the
                    records actually deleted; the Delete buttons are only shown
                    when it is provided
        """
        super().__init__(mainwindow)
        # destroy (don't merely hide) on close so repeated runs don't leave
        # hidden dialog children parented to the main window
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.mainwindow = mainwindow
        self.records = records
        self.navigate = navigate
        self.delete = delete

        self.setWindowTitle(self.WINDOW_TITLE)
        self.resize(660, 420)

        self.heading = QLabel(self._headingText(), self)
        self.heading.setWordWrap(True)
        self.heading_row = self._buildHeadingRow()

        self.table = QTableWidget(len(self.records), len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self._populate()
        if self.SORTABLE:
            self.table.setSortingEnabled(True)
            self.table.sortItems(self.DEFAULT_SORT_COLUMN)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._onDoubleClick)

        self.goto_button = QPushButton("Go to trace", self)
        self.goto_button.setToolTip(
            "Focus the field on the selected trace"
        )
        self.goto_button.setEnabled(False)
        self.goto_button.clicked.connect(self.goToSelectedContour)

        copy_button = QPushButton("Copy table list", self)
        copy_button.setToolTip(
            "Copy the table of skipped traces above to the clipboard "
            "(tab-separated, including the column headers)"
        )
        copy_button.clicked.connect(self.copyToClipboard)

        save_button = QPushButton("Save table as CSV…", self)
        save_button.setToolTip(
            "Save the table of skipped traces above to a CSV file"
        )
        save_button.clicked.connect(self.saveCSV)

        # destructive actions, only when a delete callback is provided
        self.delete_selected_button = None
        self.delete_all_button = None
        if self.delete:
            self.delete_selected_button = QPushButton("Delete selected", self)
            self.delete_selected_button.setToolTip(
                "Delete the selected trace(s) from the series (can be undone)"
            )
            self.delete_selected_button.setEnabled(False)
            self.delete_selected_button.clicked.connect(
                self.deleteSelectedContours
            )

            self.delete_all_button = QPushButton("Delete all", self)
            self.delete_all_button.setToolTip(
                "Delete every trace listed above from the series "
                "(can be undone)"
            )
            self.delete_all_button.setEnabled(bool(self.records))
            self.delete_all_button.clicked.connect(self.deleteAllContours)

        # subclass hook, run before the selection signal is connected so
        # anything it adds is already there the first time the slot fires
        self.extra_buttons = []  # (button, needs_a_selected_row)
        self._addExtraButtons()

        # connected after the buttons exist so the slot can safely touch them
        self.table.itemSelectionChanged.connect(self._updateRowActionButtons)

        buttonbox = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttonbox.rejected.connect(self.reject)
        buttonbox.addButton(self.goto_button, QDialogButtonBox.ActionRole)
        for button, _ in self.extra_buttons:
            buttonbox.addButton(button, QDialogButtonBox.ActionRole)
        buttonbox.addButton(copy_button, QDialogButtonBox.ActionRole)
        buttonbox.addButton(save_button, QDialogButtonBox.ActionRole)
        if self.delete:
            buttonbox.addButton(
                self.delete_selected_button, QDialogButtonBox.ActionRole
            )
            buttonbox.addButton(
                self.delete_all_button, QDialogButtonBox.ActionRole
            )

        layout = QVBoxLayout()
        layout.addLayout(self.heading_row)
        layout.addWidget(self.table)
        layout.addWidget(buttonbox)
        self.setLayout(layout)

    def _buildHeadingRow(self):
        """The heading, plus a hover "?" carrying the long explanation.

        A wall of text above a table is skipped rather than read, and it pushes
        the table itself off the top of a small window. So the heading is one or
        two sentences -- what the rows are and what to do with them -- and
        whatever else is worth saying goes in _headingDetail, reached by hovering
        the "?" beside it.
        """
        row = QHBoxLayout()
        row.addWidget(self.heading, 1)

        detail = self._headingDetail()
        self.heading_help = None
        if detail:
            self.heading_help = QLabel("?", self)
            self.heading_help.setToolTip(self._richDetail(detail))
            self.heading_help.setAlignment(Qt.AlignCenter)
            self.heading_help.setFixedSize(18, 18)
            self.heading_help.setCursor(Qt.WhatsThisCursor)
            self.heading_help.setStyleSheet(
                "border: 1px solid palette(mid);"
                "border-radius: 9px;"
                "font-weight: bold;"
            )
            # top-aligned so it sits beside the first line of a wrapped heading
            row.addWidget(self.heading_help, 0, Qt.AlignTop)

        return row

    @staticmethod
    def _richDetail(detail):
        """A detail string as rich text, so the tooltip wraps it.

        QToolTip word-wraps rich text only. A plain-text tooltip is laid out as
        given, so each paragraph of these details rendered as one line running
        off the side of the screen. (QLabel.setWordWrap does not help: it wraps
        the label's own text, which here is a single "?".) Escaping first keeps
        the text literal, then the paragraph breaks are put back as markup.

            Params:
                detail (str): the plain-text explanation, "" for none
            Returns:
                (str) rich text, or "" so callers can still test for emptiness
        """
        if not detail:
            return ""
        escaped = html.escape(detail, quote=False)
        return "<qt>" + escaped.replace("\n", "<br>") + "</qt>"

    def _refreshHeading(self):
        """Rebuild the heading and its "?" from the records as they now stand."""
        self.heading.setText(self._headingText())
        if self.heading_help is not None:
            detail = self._headingDetail()
            self.heading_help.setToolTip(self._richDetail(detail))
            # the detail can run out with the rows it described
            self.heading_help.setVisible(bool(detail))

    def _headingText(self):
        """Build the heading text from the current records."""
        num_traces = len(self.records)
        if not num_traces:
            return (
                "All listed traces have been deleted.\n\n"
                "You can close this window."
            )

        num_objs = len({r["name"] for r in self.records})
        trace_word = "trace" if num_traces == 1 else "traces"
        obj_word = "object" if num_objs == 1 else "objects"
        was_were = "was" if num_traces == 1 else "were"

        action = (
            "Select rows, then “Go to trace”, “Delete selected” or "
            "“Delete all”."
            if self.delete
            else "Select a row and click “Go to trace”."
        )

        return (
            f"{num_traces} {trace_word} across {num_objs} {obj_word} "
            f"{was_were} skipped during smoothing. {action}"
        )

    def _headingDetail(self):
        """Why a trace is skipped, and what was and was not changed."""
        if not self.records:
            return ""
        return (
            "A trace is skipped when it cannot be smoothed, usually because "
            "it has too few points to interpolate a curve (fewer than 3). The "
            "Reason column explains each one.\n\n"
            "These traces were left exactly as they were. Smoothing ran on "
            "every other trace of the objects listed."
        )

    def _populate(self):
        """Fill the table from the records."""
        # Qt may hand back a *copy* of a stored Python object, so identity
        # through item data is unreliable. Stash a stable int key per row and
        # resolve it back to the real record via this map; the key travels with
        # the row through re-sorting.
        self._records_by_key = {}
        specs = self._columnSpecs()
        for row, r in enumerate(self.records):

            self._records_by_key[row] = r

            for col, (key, kind) in enumerate(specs):
                if kind == "int":
                    item = QTableWidgetItem()
                    item.setData(Qt.DisplayRole, int(r[key]))
                elif kind == "float":
                    # store as a float so the column sorts numerically
                    item = QTableWidgetItem()
                    item.setData(Qt.DisplayRole, round(float(r[key]), 8))
                elif kind == "loc":
                    item = QTableWidgetItem(self._format_location(r.get(key)))
                else:  # "str"
                    item = QTableWidgetItem(str(r[key]))
                # a stable per-row key on the first column, resolved back to the
                # real record by _recordAtRow; it travels with the row on sort
                if col == 0:
                    item.setData(Qt.UserRole, row)
                item.setTextAlignment(Qt.AlignCenter)
                # show the full cell value on hover; columns are stretched to
                # fit the window, so wider values (e.g. the Reason) truncate
                item.setToolTip(item.text())
                self.table.setItem(row, col, item)

    @staticmethod
    def _format_location(loc):
        """Render a location tuple for display ('—' when there are no points)."""
        if not loc:
            return "—"
        return f"({loc[0]}, {loc[1]})"

    def _addExtraButtons(self):
        """Subclass hook: append (button, needs_selection) to extra_buttons.

        Nothing here by default. A button appended with needs_selection True is
        disabled while no row is selected, exactly like "Go to trace".
        """
        return

    def _updateRowActionButtons(self):
        """Enable selection-dependent buttons only while a row is selected."""
        has_selection = self.table.selectionModel().hasSelection()
        self.goto_button.setEnabled(has_selection)
        if self.delete_selected_button is not None:
            self.delete_selected_button.setEnabled(has_selection)
        for button, needs_selection in self.extra_buttons:
            if needs_selection:
                button.setEnabled(has_selection)

    def _recordAtRow(self, row):
        """Return the record for the given table row (or None)."""
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return self._records_by_key.get(item.data(Qt.UserRole))

    def _navigateToRow(self, row):
        """Focus the field on the trace in the given table row."""
        if not self.navigate:
            return
        record = self._recordAtRow(row)
        if record is None:
            return
        self.navigate(record["section"], record["name"], record["index"])

    def goToSelectedContour(self):
        """Focus the field on the currently selected trace."""
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self._navigateToRow(rows[0].row())

    def _onDoubleClick(self, row, _col):
        """Focus the field on the double-clicked trace."""
        self._navigateToRow(row)

    def _selectedRecords(self):
        """Return the records for the currently selected rows."""
        records = []
        for index in self.table.selectionModel().selectedRows():
            record = self._recordAtRow(index.row())
            if record is not None:
                records.append(record)
        return records

    def deleteSelectedContours(self):
        """Delete the traces for the currently selected rows."""
        self._deleteRecords(self._selectedRecords())

    def deleteAllContours(self):
        """Delete every trace listed in the dialog."""
        self._deleteRecords(list(self.records))

    def _deleteRecords(self, records):
        """Confirm, delete the given records, and prune the rows that went."""
        if not self.delete or not records:
            return
        count = len(records)
        noun = "trace" if count == 1 else "traces"
        if not notifyConfirm(
            f"Delete {count} {noun} from the series?\n\n"
            "This can be undone (Ctrl+Z).",
            yn=True,
        ):
            return
        deleted = self.delete(records)
        self._pruneRecords(deleted or [])

    def _pruneRecords(self, deleted):
        """Remove the rows/records that were actually deleted."""
        if not deleted:
            return
        deleted_ids = {id(r) for r in deleted}
        # remove bottom-up so earlier row indices stay valid
        for row in range(self.table.rowCount() - 1, -1, -1):
            item = self.table.item(row, 0)
            if item is None:
                continue
            key = item.data(Qt.UserRole)
            record = self._records_by_key.get(key)
            if record is not None and id(record) in deleted_ids:
                self.table.removeRow(row)
                del self._records_by_key[key]
        self.records = list(self._records_by_key.values())
        self._refreshHeading()
        if self.delete_all_button is not None:
            self.delete_all_button.setEnabled(bool(self.records))
        self._updateRowActionButtons()

    def _rows_for_export(self):
        """Return the report as a list of rows (header first).

        Reads the table in its current visual order so the export matches what
        the user sees, including any column sort they have applied.
        """
        rows = [list(self.COLUMNS)]
        for row in range(self.table.rowCount()):
            cells = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                cells.append("" if item is None else item.text())
            rows.append(cells)
        return rows

    def copyToClipboard(self):
        """Copy the report to the clipboard as tab-separated text."""
        rows = self._rows_for_export()
        text = "\n".join("\t".join(cell for cell in row) for row in rows)
        QApplication.clipboard().setText(text)

    def saveCSV(self):
        """Save the report to a CSV file the user chooses."""
        fp, _ = QFileDialog.getSaveFileName(
            self,
            "Save skipped traces",
            "skipped_traces.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not fp:
            return
        with open(fp, "w", newline="") as f:
            csv.writer(f).writerows(self._rows_for_export())


class PixelDustDialog(MalformedContoursDialog):
    """Review tiny "pixel-dust" traces before removing them.

    A data clean-up review list: every row is a small closed trace at or below
    the area threshold the user chose. The user inspects the candidates (and can
    "Go to trace" to confirm), then deselects any legitimate small trace before
    "Delete selected" / "Delete all". Reuses all of the selection, navigation,
    deletion (undoable), and export behavior of MalformedContoursDialog; only
    the columns (an Area column) and the explanatory heading differ.
    """

    COLUMNS = ["Object", "Section", "Area (um^2)", "Point count",
               "Location (x, y)", "Reason"]
    WINDOW_TITLE = "Remove pixel-dust traces"

    def _columnSpecs(self):
        return [
            ("name", "str"),
            ("section", "int"),
            ("area", "float"),
            ("points", "int"),
            ("location", "loc"),
            ("reason", "str"),
        ]

    def _headingText(self):
        """Explain the pixel-dust review and how to act on it."""
        num_traces = len(self.records)
        if not num_traces:
            return (
                "All listed traces have been deleted.\n\n"
                "You can close this window."
            )

        num_objs = len({r["name"] for r in self.records})
        trace_word = "trace" if num_traces == 1 else "traces"
        obj_word = "object" if num_objs == 1 else "objects"

        return (
            f"{num_traces} small (pixel-dust) {trace_word} across "
            f"{num_objs} {obj_word} at or below the area threshold. "
            "Deselect anything you want to keep, then delete."
        )

    def _headingDetail(self):
        """What pixel dust is, and that nothing is removed without asking."""
        if not self.records:
            return ""
        return (
            "Pixel dust is a stray speck, usually left behind by "
            "segmentation, small enough that it cannot be a real structure at "
            "the area threshold you chose.\n\n"
            "Nothing is removed until you choose to delete. Select a row and "
            "click “Go to trace” to inspect one in the field before deciding, "
            "and deselect any legitimate small trace you want to keep. Then "
            "use “Delete selected” or “Delete all”.\n\n"
            "Deleting is one undoable operation (Ctrl+Z)."
        )


class DuplicateTracesDialog(MalformedContoursDialog):
    """Review groups of duplicate traces and combine each into a single trace.

    Each row is a group of traces on one section that overlap each other: one
    structure traced more than once. The names may agree, which is the
    unambiguous case, or differ, which is what happens when two people trace the
    same structure -- both are shown here, because to the person reading the list
    they are the same question.

    That question is which trace to keep. The Keep column is a drop-down of the
    group's own object names, and "Combine selected" / "Combine all" reduce each
    group to the chosen trace, which takes on the tags of every trace it
    absorbed. The default choice is the trace with the most points; it is only a
    default, because which name is right is a judgment about the data rather than
    about geometry.
    """

    COLUMNS = ["Objects", "Keep", "Section", "Traces", "Overlap",
               "Area (um^2)", "Point count", "Location (x, y)", "Reason"]
    WINDOW_TITLE = "Duplicate traces"
    DEFAULT_SORT_COLUMN = 2  # "Section"
    # the Keep column holds a combo box per row; see MalformedContoursDialog
    SORTABLE = False
    KEEP_COLUMN = 1

    def __init__(self, mainwindow: QWidget, records: list, navigate=None,
                 combine=None):
        """Create the duplicate-groups list.

        Takes a ``combine`` callback rather than the base class's ``delete``:
        combining is not deletion, it keeps one of the traces and moves the tags
        of the rest onto it, so the Delete buttons would describe it wrongly.

            Params:
                mainwindow (QWidget): the parent window
                records (list): group records from Series.findDuplicateTraces
                navigate (callable): optional navigate(section_num, obj_name,
                    index) callback, used by the "Go to" buttons
                combine (callable): optional combine(groups) callback that
                    combines the given groups and returns the groups actually
                    combined; the Combine buttons are only shown when it is
                    provided
        """
        self.combine = combine
        # which member of the selected group "Go to next trace" frames next,
        # keyed by the record itself (by id) rather than by row number: rows
        # shift when _pruneRecords removes one, and a cursor left on a row index
        # would then belong to a different group
        self._member_cursor = {}
        super().__init__(mainwindow, records, navigate=navigate, delete=None)

    def _columnSpecs(self):
        return [
            ("names_text", "str"),
            ("keep", "str"),  # replaced by a combo box in _populate
            ("section", "int"),
            ("count", "int"),
            ("ratio", "float"),
            ("total_area", "float"),
            ("points", "int"),
            ("location", "loc"),
            ("reason", "str"),
        ]

    def _populate(self):
        """Fill the table, then put a Keep drop-down on every row."""
        super()._populate()
        self.keep_boxes = {}  # row -> QComboBox
        for row in range(self.table.rowCount()):
            record = self._recordAtRow(row)
            if record is None:
                continue
            box = QComboBox(self)
            box.addItems(record["names"])
            box.setCurrentText(record["keep"])
            box.setToolTip(
                "The object whose trace survives when this group is combined. "
                "Defaults to the trace with the most points."
            )
            # the record is what combining reads, so the choice is written
            # straight back onto it rather than read off the widget later
            box.currentTextChanged.connect(
                lambda name, r=record: r.__setitem__("keep", name)
            )
            self.keep_boxes[row] = box
            self.table.setCellWidget(row, self.KEEP_COLUMN, box)

    def _addExtraButtons(self):
        """Add "Go to next trace", and the two Combine buttons when allowed."""
        self.goto_next_button = QPushButton("Go to next trace", self)
        self.goto_next_button.setToolTip(
            "Frame the next trace of the selected group, so the traces of one "
            "group can be compared in the same field view"
        )
        self.goto_next_button.setEnabled(False)
        self.goto_next_button.clicked.connect(self.goToNextMemberContour)
        self.extra_buttons.append((self.goto_next_button, True))

        self.combine_selected_button = None
        self.combine_all_button = None
        if self.combine:
            self.combine_selected_button = QPushButton("Combine selected", self)
            self.combine_selected_button.setToolTip(
                "Reduce each selected group to the trace named in its Keep "
                "column, which takes on the tags of the rest (can be undone)"
            )
            self.combine_selected_button.setEnabled(False)
            self.combine_selected_button.clicked.connect(
                self.combineSelectedGroups
            )
            self.extra_buttons.append((self.combine_selected_button, True))

            self.combine_all_button = QPushButton("Combine all", self)
            self.combine_all_button.setToolTip(
                "Combine every group listed above, each to its own Keep "
                "choice (can be undone)"
            )
            self.combine_all_button.setEnabled(bool(self.records))
            self.combine_all_button.clicked.connect(self.combineAllGroups)
            self.extra_buttons.append((self.combine_all_button, False))

    def goToNextMemberContour(self):
        """Frame the next trace of the selected group, wrapping around."""
        if not self.navigate:
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        record = self._recordAtRow(rows[0].row())
        if record is None:
            return
        members = record["members"]
        # the first press moves off the trace "Go to trace" frames, which is the
        # kept member rather than members[0]
        key = id(record)
        cursor = self._member_cursor.get(key)
        if cursor is None:
            kept = self._keptMemberIndex(record)
            cursor = kept
        cursor = (cursor + 1) % len(members)
        self._member_cursor[key] = cursor
        member = members[cursor]
        self.navigate(record["section"], member["name"], member["index"])

    def _keptMemberIndex(self, record):
        """Index in ``record["members"]`` of the trace combining would keep.

        "Go to trace" frames that member, since the group record's own
        name/index describe it, so cycling starts there rather than at
        members[0]. The rule lives in Series._keptMember and is asked for rather
        than restated: the Keep column names an object, and one object can hold
        several traces in the group.
        """
        from PyReconstruct.modules.datatypes.series import Series

        kept = Series._keptMember(record["members"], record["keep"])
        if kept is None:
            return 0
        return next(
            i for i, m in enumerate(record["members"]) if m is kept
        )

    def _selectedGroups(self):
        """The group records of the selected rows."""
        groups = []
        for index in self.table.selectionModel().selectedRows():
            record = self._recordAtRow(index.row())
            if record is not None:
                groups.append(record)
        return groups

    def combineSelectedGroups(self):
        """Combine the selected groups after confirming."""
        self._combineGroups(self._selectedGroups())

    def combineAllGroups(self):
        """Combine every group listed."""
        self._combineGroups(list(self.records))

    def _combineGroups(self, groups):
        """Confirm, combine, and drop the rows that were combined."""
        if not self.combine or not groups:
            return

        count = len(groups)
        group_word = "group" if count == 1 else "groups"
        traces = sum(g["count"] for g in groups)
        if not notifyConfirm(
            f"Combine {count} {group_word} ({traces} traces) into "
            f"{count} {'trace' if count == 1 else 'traces'}?\n\n"
            "Each group is reduced to the trace named in its Keep column, "
            "which takes on the tags of the traces removed.\n\n"
            "This can be undone (Ctrl+Z).",
            yn=True,
        ):
            return

        combined = self.combine(groups)
        self._pruneRecords(combined)

    def _headingText(self):
        """One line: how many groups, and what to do with them."""
        num_groups = len(self.records)
        if not num_groups:
            return (
                "No duplicate groups left.\n\n"
                "You can close this window."
            )

        group_word = "group" if num_groups == 1 else "groups"
        traces = sum(r["count"] for r in self.records)
        action = (
            "Choose which object to keep in each row, then combine."
            if self.combine
            else "Select a row and click “Go to trace”."
        )
        return (
            f"{num_groups} {group_word} of overlapping traces "
            f"({traces} traces in total). {action}"
        )

    def _headingDetail(self):
        """What a group is, what combining does, and how to read the columns."""
        if not self.records:
            return ""

        detail = (
            "A group is a set of traces on one section that overlap each "
            "other: one structure traced more than once. The names may agree, "
            "or differ, which is what happens when two people trace the same "
            "structure. Grouping follows the overlaps, so a chain of three "
            "traces is one group rather than three pairs.\n\n"
            "Keep is a drop-down of that group's own object names. It starts "
            "on the trace with the most points, which is usually the more "
            "careful tracing, but which name is right is a judgment about the "
            "data: the objects can carry different hosts, groups or curation.\n\n"
            "Overlap is the lowest measured overlap ratio inside the group "
            "(1 means two traces have the same points). Area is the summed "
            "physical area (um^2) of the group's traces, and Point count is "
            "the kept trace's.\n\n"
            "Select a row and use “Go to trace” and “Go to next trace” to see "
            "each trace of a group in the same field view before deciding."
        )
        if self.combine:
            detail += (
                "\n\nCombining keeps the chosen trace and removes the rest; "
                "the survivor takes on their tags. Nothing changes until you "
                "combine, and combining is one undoable operation (Ctrl+Z)."
            )
        else:
            detail += "\n\nNothing in the series has been changed."
        return detail
