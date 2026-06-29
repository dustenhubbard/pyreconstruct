"""Virtualized model/view for the Object List.

The Object List historically used a ``QTableWidget`` that materialized one
``QTableWidgetItem`` per cell up front -- for a 100k-object series that is
~100k * (#columns) widget items built and held in memory on every table
(re)creation, plus a ``resizeRowsToContents()`` pass that measures every row.

``ObjectTableModel`` + ``ObjectTableView`` replace that with a Qt model/view:
the model holds only the lightweight list of object names and produces the
``QTableWidgetItem``s for a row *on demand* (Qt only requests data for the
handful of rows actually on screen). The per-cell production reuses the
container's existing ``getItems()`` path verbatim, so the displayed data,
check states, flags and colors are identical to the old population path -- the
only thing that changes is *when* (and how few) items get built.
"""

from collections import OrderedDict

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QTableView, QApplication, QHeaderView

from PyReconstruct.modules.gui.utils import lessThan
from PyReconstruct.modules.backend.func import make_unique_id


class ObjectTableModel(QAbstractTableModel):
    """Lazy table model backed by a sorted list of object names.

    The ``container`` must provide the same surface the old population path
    used: ``getHeaders()``, ``getFiltered()``, ``getItems(name, key)``,
    ``static_columns`` and ``columns``. It may optionally provide
    ``onCheckStateChanged(row, col, state) -> bool`` to handle user check-box
    edits (returns True if the edit was accepted).
    """

    # Bound on the per-row item cache. Far larger than any realistic visible
    # window, so scrolling stays cheap, but keeps memory O(cache_limit) rather
    # than O(#objects).
    CACHE_LIMIT = 4096

    def __init__(self, container, parent=None):
        super().__init__(parent)
        self.container = container
        self.headers = container.getHeaders()
        self.names = container.getFiltered()
        # row -> list[QTableWidgetItem], kept in least-recently-used order so
        # the cache stays bounded (memory O(CACHE_LIMIT), not O(#objects)).
        self._cache = OrderedDict()

    # -- row item production (mirrors DataTable.setRow's column iteration) --

    def _buildItems(self, name):
        """Build the flat list of items for a row, exactly as setRow would."""
        items = []
        for key in self.container.static_columns:
            items.extend(self.container.getItems(name, key))
        for key, b in self.container.columns:
            if b:
                items.extend(self.container.getItems(name, key))
        return items

    def _rowItems(self, row):
        # Guard against out-of-bounds / stale indices (e.g. a QModelIndex held
        # across a row removal still reports isValid()). Callers treat an empty
        # list as "no cell here".
        if not (0 <= row < len(self.names)):
            return []
        items = self._cache.get(row)
        if items is None:
            items = self._buildItems(self.names[row])
            self._cache[row] = items
            if len(self._cache) > self.CACHE_LIMIT:
                self._cache.popitem(last=False)  # evict least-recently-used
        else:
            self._cache.move_to_end(row)  # mark most-recently-used
        return items

    def _invalidate(self, row=None):
        """Drop cached items. Row indices shift on insert/remove, so those
        operations clear the whole cache; single-row refreshes drop one row."""
        if row is None:
            self._cache.clear()
        else:
            self._cache.pop(row, None)

    # -- required QAbstractTableModel overrides --

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.names)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = index.column()
        items = self._rowItems(index.row())
        if col >= len(items):
            return None
        # Reading via item.data(role) reproduces exactly what the QTableWidget
        # rendered: DisplayRole text, CheckStateRole (only present on Locked/CR
        # items), BackgroundRole (curation colors), etc. Non-set roles return
        # None, just as an unset QTableWidgetItem role would.
        return items[col].data(role)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        col = index.column()
        items = self._rowItems(index.row())
        if col >= len(items):
            return Qt.ItemFlag.NoItemFlags
        return items[col].flags()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.CheckStateRole:
            return False
        handler = getattr(self.container, "onCheckStateChanged", None)
        if handler is None:
            return False
        return bool(handler(index.row(), index.column(), Qt.CheckState(value)))

    # -- name/row helpers used by incremental updates --

    def nameAt(self, row):
        if 0 <= row < len(self.names):
            return self.names[row]
        return None

    def rowOf(self, name):
        """Row index of ``name`` (or where it should be inserted), and whether
        it already exists. Mirrors CopyTableWidget.getRowIndex exactly: a linear
        scan using ``lessThan`` against the sorted name list, so placement is
        identical to the old table -- it just reads the lightweight name list
        instead of QTableWidget items."""
        for i, row_name in enumerate(self.names):
            if lessThan(name, row_name):
                return i, False
            if name == row_name:
                return i, True
        return len(self.names), False

    def refreshRow(self, row):
        """Re-read a single existing row's data and repaint it."""
        if not (0 <= row < len(self.names)):
            return
        self._invalidate(row)
        top_left = self.index(row, 0)
        bottom_right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(top_left, bottom_right)

    def insertName(self, name, row):
        self.beginInsertRows(QModelIndex(), row, row)
        self.names.insert(row, name)
        self._invalidate()  # row indices below the insert shift
        self.endInsertRows()

    def removeRowAt(self, row):
        if not (0 <= row < len(self.names)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.names[row]
        self._invalidate()  # row indices below the removal shift
        self.endRemoveRows()


class ObjectTableView(QTableView):
    """QTableView drop-in for the Object List.

    Exposes the small slice of the old CopyTableWidget surface the rest of the
    app relies on: a stable ``id``, Ctrl+C ``copy()`` to the clipboard, and the
    qdark column-width padding tweak.
    """

    def __init__(self, container, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = container
        self.id = make_unique_id()

    def keyPressEvent(self, event):
        ret = super().keyPressEvent(event)
        if event.key() == Qt.Key_C and (event.modifiers() & Qt.ControlModifier):
            self.copy()
        return ret

    def backspace(self):
        """Replaced per-instance by DataTable (kept for parity)."""
        return

    def copy(self):
        """Copy the selected cells to the clipboard (tab/newline delimited),
        matching CopyTableWidget.copy()."""
        indexes = sorted(self.selectedIndexes())
        if not indexes:
            return
        model = self.model()
        clipboard_str = ""
        row = indexes[0].row()
        row_list = []
        for index in indexes:
            if index.row() > row:
                clipboard_str += "\t".join(row_list) + "\n"
                row_list = []
                row = index.row()
            row_list.append(model.data(index, Qt.DisplayRole) or "")
        clipboard_str += "\t".join(row_list) + "\n"
        QApplication.clipboard().setText(clipboard_str)

    def getRowIndex(self, name):
        """Compatibility shim mirroring CopyTableWidget.getRowIndex."""
        return self.model().rowOf(name)

    def setUniformRowHeight(self):
        """Give every row one compact, content-derived height.

        The old QTableWidget called resizeRowsToContents(), which both shrank
        single-line rows below the chunky default section size (~18px vs 30px)
        and grew multi-line rows to fit. That measures every row -- exactly the
        O(#objects) cost virtualization removes -- so we cannot keep it.

        Instead we measure ONE representative row and apply its height uniformly
        via the vertical header's default section size: O(1), keeps the list as
        dense as it was before, and never materializes off-screen rows. Newly
        inserted rows inherit the same height automatically (Fixed mode).

        Trade-off vs the old per-row sizing: a cell whose text contains literal
        newlines is shown on a single line rather than grown to fit every line.
        In-app comment/column edits go through single-line inputs, so this only
        affects rare multi-line text carried in from imported (legacy) data.
        """
        model = self.model()
        vheader = self.verticalHeader()
        if model is not None and model.rowCount() > 0:
            # Perf trade-off (intentional): measure ONLY row 0 (one getItems
            # pass) and apply its height to every row. This is O(1), but a cell
            # in some OTHER row whose text spans multiple lines is rendered on a
            # single line (clipped) instead of growing that row to fit -- see the
            # multi-line note in the docstring. Measuring per row to avoid this
            # would re-introduce the O(#objects) pass virtualization removes.
            self.resizeRowToContents(0)
            row_h = self.rowHeight(0)
        else:
            # no row to measure (empty list); fall back to a compact height
            # derived from the font. A later createTable measures a real row.
            row_h = self.fontMetrics().height() + 4
        vheader.setSectionResizeMode(QHeaderView.Fixed)
        vheader.setDefaultSectionSize(row_h)

    def _applyQDarkPadding(self):
        try:
            series = getattr(self.parent().parent(), "series")
        except AttributeError:
            return
        if series.getOption("theme") == "qdark":
            for c in range(self.model().columnCount()):
                self.setColumnWidth(c, self.columnWidth(c) + 8)

    def resizeColumnsToContents(self):
        super().resizeColumnsToContents()
        self._applyQDarkPadding()

    def growColumnsToFitRow(self, row):
        """Widen any column that the cells in ``row`` no longer fit into.

        The full ``resizeColumnsToContents()`` samples up to 100 rows on every
        call (see ``setResizeContentsPrecision`` in createTable), which is what
        made the old per-edit re-measure cost ~4-7 ms. This measures ONLY the
        one row that just changed -- ``sizeHintForIndex`` on that row's cell in
        each column -- so the work is O(#columns), independent of #objects.

        It only ever GROWS a column (never shrinks), matching the visible part
        of the old behavior: an edited/added value wider than the current column
        widens the column to fit it; nothing else moves. Returns True if any
        column was grown (used by tests to confirm a fit-width edit is a no-op).
        """
        model = self.model()
        if model is None or not (0 <= row < model.rowCount()):
            return False
        grew = False
        # qdark adds 8px of padding to each column width in resizeColumnsToContents;
        # match it here so a grown column lines up with a full-rebuild width.
        try:
            series = getattr(self.parent().parent(), "series")
            pad = 8 if series.getOption("theme") == "qdark" else 0
        except AttributeError:
            pad = 0
        for c in range(model.columnCount()):
            hint = self.sizeHintForIndex(model.index(row, c)).width()
            if hint <= 0:
                continue
            needed = hint + pad
            if needed > self.columnWidth(c):
                self.setColumnWidth(c, needed)
                grew = True
        return grew
