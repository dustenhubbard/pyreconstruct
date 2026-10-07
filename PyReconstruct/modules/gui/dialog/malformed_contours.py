import csv
import html

from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QToolTip,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QDialogButtonBox,
    QHeaderView,
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QComboBox,
    QStyledItemDelegate,
)
from PySide6.QtCore import Qt

from PyReconstruct.modules.gui.utils import undo_chord
from PyReconstruct.modules.gui.utils import notifyConfirm


# the heading once Delete has emptied a list
DELETED_LINE = "All listed traces have been deleted. You can close this window."

# the Keep cell of the duplicates list stores the row's names here
NAMES_ROLE = Qt.UserRole + 1


def _freeze(value):
    """Lists and tuples, nested, as tuples, so the value can be a key."""
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


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

        # one line above the list; the full explanation is the tooltip of
        # the "?" beside it
        self.heading = QLabel(self)
        # a button, not a label, so the keyboard can reach it too: Tab to
        # it and press Space to show the same tooltip a hover shows
        self.help_icon = QToolButton(self)
        self.help_icon.setText("?")
        self.help_icon.setAccessibleName("Explanation")
        self.help_icon.setFocusPolicy(Qt.StrongFocus)
        self.help_icon.setFixedSize(18, 18)
        self.help_icon.setCursor(Qt.WhatsThisCursor)
        self.help_icon.setStyleSheet(
            "QToolButton { border: 1px solid palette(mid); border-radius: 9px;"
            " font-weight: bold; padding: 0; }"
        )
        self.help_icon.clicked.connect(self._showExplanation)
        self._refreshHeading()

        self.table = QTableWidget(len(self.records), len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self._populate()
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

        heading_row = QHBoxLayout()
        heading_row.addWidget(self.heading)
        heading_row.addWidget(self.help_icon)
        heading_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(heading_row)
        layout.addWidget(self.table)
        layout.addWidget(buttonbox)
        self.setLayout(layout)

    def _refreshHeading(self):
        """Set the one-line heading and the "?" tooltip from the records."""
        self.heading.setText(self._summaryText())
        explanation = self._explanationText()
        # rich text, so Qt wraps the tooltip instead of drawing one long line
        self.help_icon.setToolTip("".join(
            f"<p>{html.escape(paragraph, quote=False)}</p>"
            for paragraph in explanation.split("\n\n")
        ))
        self.help_icon.setAccessibleDescription(explanation)

    def _showExplanation(self):
        """Show the "?" tooltip under the icon, for a click or a key."""
        QToolTip.showText(
            self.help_icon.mapToGlobal(self.help_icon.rect().bottomLeft()),
            self.help_icon.toolTip(),
            self.help_icon,
        )

    def _summaryText(self):
        """One short line that says what the list holds."""
        num_traces = len(self.records)
        if not num_traces:
            return DELETED_LINE
        trace_word = "trace" if num_traces == 1 else "traces"
        return f"{num_traces} {trace_word} could not be smoothed."

    def _explanationText(self):
        """Build the full explanation (the "?" tooltip) from the records."""
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
            "Select one or more rows, then use “Go to trace” to focus the "
            "field, or “Delete selected” / “Delete all” to remove them."
            if self.delete
            else "Select a row and click “Go to trace” to focus the field "
            "on that trace."
        )

        return (
            f"{num_traces} {trace_word} across {num_objs} {obj_word} "
            f"{was_were} skipped during smoothing.\n\n"
            "A trace is skipped when it cannot be smoothed, usually "
            "because it has too few points to interpolate a curve (fewer "
            "than 3). These traces were left unchanged; the Reason column "
            "explains why each one was skipped.\n\n"
            f"{action}"
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
                item = QTableWidgetItem()
                if kind == "int":
                    item.setData(Qt.DisplayRole, int(r[key]))
                elif kind == "float":
                    # store as a float so the column sorts numerically
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
            f"This can be undone ({undo_chord()}).",
            yn=True,
        ):
            return
        deleted = self.delete(records)
        self._pruneRecords(deleted or [])

    def _pruneRecords(self, deleted):
        """Remove the rows/records that were actually deleted.

            Params:
                deleted (list): the records whose rows go
        """
        if not deleted:
            return
        deleted_ids = {id(r) for r in deleted}
        deleted_traces = [
            (d["section"], d["name"], d["index"]) for d in deleted
        ]
        deleted_identities = [d.get("identity") for d in deleted]
        # two rows can name one trace, and it went once, so each distinct
        # trace shifts the rest once, and a row whose trace went goes too:
        # left in, its index named whichever trace moved into that place
        distinct = set(deleted_traces)
        for record in self._records_by_key.values():
            if "index" in record and (
                record["section"], record["name"], record["index"]
            ) in distinct:
                deleted_ids.add(id(record))
        self._countDownLookalikes(
            deleted_traces, deleted_identities, deleted_ids
        )
        # The surviving records' scan-time indexes shift when earlier traces
        # of the SAME contour on the SAME section are deleted: "Go to trace"
        # then framed a different trace than the row named, and the user
        # could delete a legitimate one believing they had inspected it
        # (found 2026-08-28). Decrement each survivor by how many deleted
        # traces sat below its index in its own contour.
        for record in self._records_by_key.values():
            if id(record) in deleted_ids or "index" not in record:
                continue
            shift = sum(
                1 for section, name, index in distinct
                if section == record["section"]
                and name == record["name"]
                and index < record["index"]
            )
            if shift:
                record["index"] -= shift
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

    def _countDownLookalikes(self, deleted_traces, deleted_identities,
                             deleted_ids):
        """Take each deleted trace off the "lookalikes" count of the rows left.

        A record counts the identical traces its scan saw and its place among
        them, and the delete path refuses a record whose count has changed. A
        delete made from this list is one the list has accounted for, so the
        survivors' counts and places follow it. Run before the index shift:
        the indexes compared here are the ones from before the delete.
        """
        counted = [
            record for record in self._records_by_key.values()
            if id(record) not in deleted_ids
            and isinstance(record.get("lookalikes"), int)
            and record.get("identity") is not None
        ]
        if not counted:
            return  # records from before the count existed
        gone = {}
        for trace, identity in zip(deleted_traces, deleted_identities):
            if identity is not None:
                gone[tuple(trace)] = _freeze(identity)
        for record in counted:
            identity = _freeze(record["identity"])
            same = [
                index for (section, name, index), key in gone.items()
                if section == record["section"]
                and name == record["name"] and key == identity
            ]
            if not same:
                continue
            record["lookalikes"] -= len(same)
            # the place among the lookalikes drops by one for each deleted
            # lookalike that sat before this trace
            own = record.get("index")
            if isinstance(record.get("lookalike_ordinal"), int) and \
                    isinstance(own, int):
                record["lookalike_ordinal"] -= sum(1 for i in same if i < own)

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


class SkippedCrossingsDialog(MalformedContoursDialog):
    """The self-crossing traces the repair left for the scissors.

    The bulk repair (Series > Clean up > Repair self-crossing traces...)
    skips a trace whose crossing separates two real loops, because only the
    user can pick the right loop. Naming them in a plain message was not
    actionable (his report, 2026-08-26): this review list keeps the window
    open while "Go to trace" walks the field to each one, and "Copy table
    list" takes the whole set to a notes app. No delete action on purpose;
    the scissors in the field are the fix.
    """

    WINDOW_TITLE = "Self-crossing traces to fix with the scissors"

    def _summaryText(self):
        count = len(self.records)
        noun = "trace" if count == 1 else "traces"
        return f"{count} self-crossing {noun} to fix with the scissors."

    def _explanationText(self):
        count = len(self.records)
        noun = "trace" if count == 1 else "traces"
        return (
            f"{count} self-crossing {noun} could not be repaired "
            "automatically: the crossing separates two real loops, and only "
            "you can pick the right one.\n\n"
            "Select a row and click \"Go to trace\" (or double-click it) to "
            "jump there, then cut out the crossing with the scissors tool. "
            "This window stays open while you work."
        )


class RepairedCrossingsDialog(MalformedContoursDialog):
    """The summary after a self-crossing repair pass.

    Lists every trace the pass repaired, with the same copy-to-clipboard and
    save-as-CSV roads as the other review lists (his ask, 2026-08-26), so a
    lab can keep a record of what a bulk pass touched. "Go to trace" works
    here too, for spot-checking the results. The whole pass is one undo.
    """

    WINDOW_TITLE = "Repaired self-crossing traces"

    def _summaryText(self):
        count = len(self.records)
        noun = "trace" if count == 1 else "traces"
        return f"Repaired {count} self-crossing {noun}."

    def _explanationText(self):
        count = len(self.records)
        noun = "trace" if count == 1 else "traces"
        return (
            f"Repaired {count} self-crossing {noun}: the crossing artifact "
            "was removed and each trace's real outline kept.\n\n"
            "Select a row and click \"Go to trace\" to spot-check a repair. "
            f"The whole pass is one undo ({undo_chord()})."
        )


class PixelDustDialog(MalformedContoursDialog):
    """Review tiny "pixel-dust" traces before removing them.

    A data clean-up review list: every row is a small closed trace at or below
    the pixel-area threshold the user chose. The user inspects the candidates
    (and can "Go to trace" to confirm), then deselects any legitimate small
    trace before "Delete selected" / "Delete all". Reuses all of the selection,
    navigation, deletion (undoable), and export behavior of
    MalformedContoursDialog; only the columns (a pixel-area column, plus its
    physical-area equivalent) and the heading and its explanation differ.

    The primary Area column is in pixels (px^2) so it reads in the same units as
    the threshold the user set; the "Area (um^2)" column shows the physical
    equivalent for that trace on its own section (each section's magnification
    can differ), so both the "how many pixels" and "how big physically" views are
    available at a glance.
    """

    COLUMNS = ["Object", "Section", "Area (px^2)", "Area (um^2)", "Point count",
               "Location (x, y)", "Reason"]
    WINDOW_TITLE = "Remove pixel-dust traces"

    def _columnSpecs(self):
        return [
            ("name", "str"),
            ("section", "int"),
            ("area_px", "float"),
            ("area", "float"),
            ("points", "int"),
            ("location", "loc"),
            ("reason", "str"),
        ]

    def _summaryText(self):
        num_traces = len(self.records)
        if not num_traces:
            return DELETED_LINE
        trace_word = "trace" if num_traces == 1 else "traces"
        return f"{num_traces} {trace_word} at or below the pixel-area threshold."

    def _explanationText(self):
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
            f"{num_objs} {obj_word} at or below the pixel-area threshold.\n\n"
            "The Area is shown in pixels (px^2), the same units as the "
            "threshold, with the physical area (um^2) next to it. Each "
            "section's magnification can differ, so the same pixel size is a "
            "different physical size on different sections.\n\n"
            "These are typically stray specks left by segmentation. Review the "
            "candidates below. Select a row and click “Go to trace” to inspect "
            "one, and deselect any legitimate trace you want to keep. Then use "
            "“Delete selected” or “Delete all” to remove them (can be undone).\n\n"
            "Nothing is removed until you choose to delete."
        )


class _KeepNameCombo(QComboBox):
    """A drop-down that ignores the mouse wheel.

    Several styles change a combo box's value on a wheel turn over it, so
    scrolling the list would change the picks it passed over. The wheel
    scrolls the table instead.
    """

    def wheelEvent(self, event):
        event.ignore()


class _KeepNameDelegate(QStyledItemDelegate):
    """The drop-down in a duplicates row's Keep cell.

    The pick is stored as the cell's own text, so it travels with its row
    through a column sort and reaches the copied table as it is; the
    drop-down is only the editor over it, kept open on every row.
    """

    PLACEHOLDER = "Pick a name"

    def createEditor(self, parent, option, index):
        combo = _KeepNameCombo(parent)
        combo.addItems(index.data(NAMES_ROLE) or [])
        combo.setPlaceholderText(self.PLACEHOLDER)
        combo.setCurrentIndex(-1)
        combo.currentIndexChanged.connect(
            lambda _i, c=combo: self.commitData.emit(c)
        )
        return combo

    def setEditorData(self, editor, index):
        name = index.data(Qt.DisplayRole) or ""
        editor.blockSignals(True)
        editor.setCurrentIndex(editor.findText(name) if name else -1)
        editor.blockSignals(False)

    def setModelData(self, editor, model, index):
        name = editor.currentText() if editor.currentIndex() >= 0 else ""
        model.setData(index, name, Qt.EditRole)


class DuplicateTracesDialog(MalformedContoursDialog):
    """Review duplicate traces and combine each structure into one trace.

    Each row is one group from Series.findDuplicateTraces: a structure traced
    more than once, under one name or under several. The Keep cell is a
    drop-down of the row's names. A row with one name has it picked; a row
    with more than one starts with none, because which name is right is a
    question about the data, and a row with no name picked is never combined.

    "Combine selected" and "Combine all" hand the picked rows to the
    ``combine`` callback, after a confirmation. Combining keeps one trace
    under the picked name with the tags of the others and deletes the rest
    (Series.combineDuplicateTraces). The base class's Delete buttons never
    appear: this dialog passes no ``delete`` callback up.
    """

    COLUMNS = ["Keep", "Traced as", "Section", "Traces", "Overlap",
               "Location (x, y)"]
    WINDOW_TITLE = "Duplicates"
    DEFAULT_SORT_COLUMN = 2  # "Section"
    KEEP_COLUMN = 0

    def __init__(self, mainwindow: QWidget, records: list, navigate=None,
                 combine=None):
        """Create the duplicates list.

            Params:
                mainwindow (QWidget): the parent window
                records (list): groups from Series.findDuplicateTraces
                navigate (callable): optional navigate(section_num, obj_name,
                    index) callback for "Go to trace"
                combine (callable): optional combine(choices) callback taking
                    ``(group, keep)`` tuples as
                    Series.combineDuplicateTraces does and returning the
                    tuples it combined. The Combine buttons are only shown
                    when it is provided.
        """
        self.combine = combine
        super().__init__(mainwindow, records, navigate=navigate, delete=None)
        self.resize(760, 440)
        self.table.setItemDelegateForColumn(
            self.KEEP_COLUMN, _KeepNameDelegate(self.table)
        )
        self._openKeepEditors()
        self.table.itemChanged.connect(self._syncCombineButtons)
        self._syncCombineButtons()

    def _openKeepEditors(self):
        """Put a drop-down over every row's Keep cell."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.KEEP_COLUMN)
            if item is not None:
                self.table.openPersistentEditor(item)

    def _populate(self):
        """Fill the table from the groups."""
        self._records_by_key = {}
        for row, group in enumerate(self.records):
            self._records_by_key[row] = group
            names = list(group["names"])
            keep = QTableWidgetItem(names[0] if len(names) == 1 else "")
            keep.setData(Qt.UserRole, row)
            keep.setData(NAMES_ROLE, names)
            section = QTableWidgetItem()
            section.setData(Qt.DisplayRole, int(group["section"]))
            count = QTableWidgetItem()
            count.setData(Qt.DisplayRole, int(group["count"]))
            ratio = QTableWidgetItem()
            ratio.setData(Qt.DisplayRole, round(float(group["ratio"]), 8))
            cells = [
                keep,
                QTableWidgetItem(", ".join(names)),
                section,
                count,
                ratio,
                QTableWidgetItem(self._format_location(group.get("location"))),
            ]
            for col, item in enumerate(cells):
                item.setTextAlignment(Qt.AlignCenter)
                if col != self.KEEP_COLUMN:
                    item.setToolTip(item.text())
                self.table.setItem(row, col, item)

    def _keepAtRow(self, row):
        """The name picked in a row, or "" when none is."""
        item = self.table.item(row, self.KEEP_COLUMN)
        return item.text() if item is not None else ""

    def _choicesForRows(self, rows):
        """(group, keep) for each of the rows with a name picked, and how
        many rows had none."""
        choices = []
        unpicked = 0
        for row in rows:
            group = self._recordAtRow(row)
            if group is None:
                continue
            keep = self._keepAtRow(row)
            if keep:
                choices.append((group, keep))
            else:
                unpicked += 1
        return choices, unpicked

    def choices(self):
        """Return (group, keep) for every row with a name picked."""
        return self._choicesForRows(range(self.table.rowCount()))[0]

    def _selectedRows(self):
        return sorted(
            index.row() for index in self.table.selectionModel().selectedRows()
        )

    def _addExtraButtons(self):
        """Add the two Combine buttons when there is a callback for them."""
        self.combine_selected_button = None
        self.combine_all_button = None
        if not self.combine:
            return
        self.combine_selected_button = QPushButton("Combine selected", self)
        self.combine_selected_button.setToolTip(
            "Combine each selected row into one trace under the name picked "
            "(can be undone)"
        )
        self.combine_selected_button.clicked.connect(self.combineSelected)
        self.extra_buttons.append((self.combine_selected_button, False))

        self.combine_all_button = QPushButton("Combine all", self)
        self.combine_all_button.setToolTip(
            "Combine every row with a name picked into one trace under that "
            "name (can be undone)"
        )
        self.combine_all_button.clicked.connect(self.combineAll)
        self.extra_buttons.append((self.combine_all_button, False))

    def _syncCombineButtons(self, *_args):
        """Enable each Combine button only while it has a picked row to act on."""
        if self.combine_all_button is None:
            return
        self.combine_all_button.setEnabled(bool(self.choices()))
        self.combine_selected_button.setEnabled(
            bool(self._choicesForRows(self._selectedRows())[0])
        )

    def _updateRowActionButtons(self):
        """Also refresh the Combine buttons, which follow the selection too."""
        super()._updateRowActionButtons()
        self._syncCombineButtons()

    def combineSelected(self):
        """Combine the selected rows that have a name picked."""
        self._combineRows(self._selectedRows())

    def combineAll(self):
        """Combine every row that has a name picked."""
        self._combineRows(range(self.table.rowCount()))

    def _combineRows(self, rows):
        """Confirm, combine the picked rows, and prune the ones combined."""
        if not self.combine:
            return
        choices, unpicked = self._choicesForRows(rows)
        if not choices:
            return
        count = len(choices)
        noun = "row" if count == 1 else "rows"
        unpicked_note = ""
        if unpicked:
            was = "row was" if unpicked == 1 else "rows were"
            unpicked_note = (
                f"\n\n{unpicked} {was} left alone because no name is picked."
            )
        if not notifyConfirm(
            f"Combine {count} {noun}?\n\n"
            "In each row, PyReconstruct keeps one trace under the name you "
            "picked, adds the tags of the other traces to it, and deletes "
            f"the others.{unpicked_note}\n\n"
            f"This can be undone ({undo_chord()}).",
            yn=True,
        ):
            return
        applied = self.combine(choices) or []
        self._pruneCombined(applied)

    def _pruneCombined(self, applied):
        """Drop the combined rows, and shift the traces of the rows left.

        A combine deletes every trace of a group but the one kept, so a later
        trace of the same object on the same section moves up in its contour.
        Each remaining member's index follows, so "Go to trace" still frames
        the trace in its row. Traces in two groups are never the same
        trace, so no remaining row loses a member here.
        """
        if not applied:
            return
        from PyReconstruct.modules.datatypes.series import Series
        combined_ids = {id(group) for group, _keep in applied}
        removed = []
        for group, keep in applied:
            kept = Series.duplicateKeptMember(group["members"], keep)
            removed.extend(
                (m["section"], m["name"], m["index"])
                for m in group["members"] if m is not kept
            )
        for group in self._records_by_key.values():
            if id(group) in combined_ids:
                continue
            for member in group["members"]:
                shift = sum(
                    1 for section, name, index in removed
                    if section == member["section"]
                    and name == member["name"] and index < member["index"]
                )
                member["index"] -= shift
        for row in range(self.table.rowCount() - 1, -1, -1):
            item = self.table.item(row, 0)
            if item is None:
                continue
            key = item.data(Qt.UserRole)
            group = self._records_by_key.get(key)
            if group is not None and id(group) in combined_ids:
                self.table.removeRow(row)
                del self._records_by_key[key]
        self.records = list(self._records_by_key.values())
        self._refreshHeading()
        self._updateRowActionButtons()

    def _memberToShow(self, row):
        """The member "Go to trace" frames: the one kept, once a name is
        picked, and the row's first trace until then."""
        group = self._recordAtRow(row)
        if group is None:
            return None
        keep = self._keepAtRow(row)
        if keep:
            from PyReconstruct.modules.datatypes.series import Series
            kept = Series.duplicateKeptMember(group["members"], keep)
            if kept is not None:
                return kept
        return group["members"][0]

    def _navigateToRow(self, row):
        """Focus the field on a row's trace (see _memberToShow)."""
        if not self.navigate:
            return
        member = self._memberToShow(row)
        if member is None:
            return
        self.navigate(member["section"], member["name"], member["index"])

    def _summaryText(self):
        num_rows = len(self.records)
        if not num_rows:
            return "Every row has been combined. You can close this window."
        structures = "structure" if num_rows == 1 else "structures"
        return f"{num_rows} {structures} traced more than once."

    def _explanationText(self):
        """Explain what a row is and what combining it does."""
        num_rows = len(self.records)
        if not num_rows:
            return "Every row has been combined.\n\nYou can close this window."

        num_sections = len({g["section"] for g in self.records})
        structures = "structure" if num_rows == 1 else "structures"
        sections = "section" if num_sections == 1 else "sections"
        return (
            f"{num_rows} {structures} traced more than once, across "
            f"{num_sections} {sections}. Each row is one structure, whether "
            "its traces share a name or not.\n\n"
            "Pick the name to keep in each row. Combining a row keeps one "
            "trace under that name, adds the tags of the other traces to it, "
            "and deletes the others. A row with one name has it picked "
            "already. A row with more than one is left alone until you pick "
            "one.\n\n"
            "Select a row and click “Go to trace” to see it in the field.\n\n"
            # the column shows Series.findDuplicateTraces' "ratio", the lowest
            # of the pairs that joined the group. Groups chain, so two traces
            # in one row can overlap less than that. A pair that passes
            # Trace.pointsMatch scores 1.0 without its area being measured.
            "Overlap is how alike the scan found two traces, from 0 to 1, "
            "and the “Overlap threshold” you chose sets how alike two traces "
            "must be to share a row. Higher means more alike. 1 means the "
            "scan could not tell them apart, but two traces at 1 can still "
            "differ slightly. The column shows the lowest Overlap among the "
            "pairs that put the traces in one row. If A overlaps B and B "
            "overlaps C, all three are one row, and A and C can overlap less "
            "than the number shown.\n\n"
            "Nothing changes until you combine, and combining can be undone "
            f"({undo_chord()})."
        )
