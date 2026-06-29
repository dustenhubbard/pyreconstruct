"""Integration tests for the virtualized Object List (model + real QTableView).

The companion ``test_object_list_virtualization.py`` pins the MODEL: that its
per-cell data/flags/headers/order match the old eager population path and that
the cache stays bounded. These tests exercise the parts that only manifest with
a real ``ObjectTableView`` wired to the model and shown:

1. VIEW-LEVEL LAZINESS -- a shown QTableView over a 100k-row model builds items
   only for the rows in (and near) the viewport, not all N.
2. ROW HEIGHT -- ObjectTableView.setUniformRowHeight reproduces the old
   resizeRowsToContents() compactness (one content-fit height, applied to every
   row) in O(1), instead of the chunky 30px QTableView default.
3. THE EDIT SEAM -- a user checkbox toggle reaches the container via
   model.setData(CheckStateRole) -> container.onCheckStateChanged, and the real
   ObjectTableWidget.onCheckStateChanged Locked branch behaves as before.
4. SELECTION / COPY / EXPORT -- getSelected's row->name mapping, the view's
   Ctrl+C copy(), and export()'s CSV are byte-for-byte equivalent to the old
   QTableWidget-backed paths.
"""
import os
import shutil
from unittest import mock

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
)
from PySide6.QtCore import Qt

from PyReconstruct.modules.gui.table.object import ObjectTableWidget
from PyReconstruct.modules.gui.table.object_model import (
    ObjectTableModel,
    ObjectTableView,
)
from PyReconstruct.modules.gui.table.copy_table_widget import CopyTableWidget
from PyReconstruct.modules.gui.table.data_table import DataTable
from PyReconstruct.modules.gui.utils import sortList

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


def _locked_item(checked=False):
    item = QTableWidgetItem("")
    item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    return item


# --------------------------------------------------------------------------- #
# Synthetic source matching the container contract the model/view rely on.     #
# --------------------------------------------------------------------------- #
class _SyntheticSource:
    def __init__(self, names, columns=None):
        self._names = list(names)
        self.static_columns = ["Name"]
        self.columns = columns or [("Count", True), ("Locked", True), ("Comment", True)]
        self.build_calls = 0

    def getHeaders(self):
        return self.static_columns + [k for k, b in self.columns if b]

    def getFiltered(self):
        return sortList(self._names)

    def getItems(self, name, key):
        self.build_calls += 1
        if key == "Locked":
            return [_locked_item()]
        if key == "Name":
            return [QTableWidgetItem(name)]
        return [QTableWidgetItem(f"{name}:{key}")]


def _make_view(src, show=True, configure=True):
    """Build an ObjectTableView wired exactly as ObjectTableWidget.createTable does."""
    model = ObjectTableModel(src)
    view = ObjectTableView(src)
    view.setModel(model)
    if configure:
        view.setShowGrid(False)
        view.setAlternatingRowColors(True)
        view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        view.verticalHeader().hide()
        view.horizontalHeader().setResizeContentsPrecision(100)
        view.resizeColumnsToContents()
        view.setUniformRowHeight()
    view.resize(700, 500)
    if show:
        view.show()
        QApplication.processEvents()
    return model, view


# --------------------------------------------------------------------------- #
# 1. View-level laziness                                                       #
# --------------------------------------------------------------------------- #
def test_shown_view_builds_only_visible_rows(qapp):
    N = 100_000
    src = _SyntheticSource([f"obj_{i:06d}" for i in range(N)])
    model, view = _make_view(src)

    assert model.rowCount() == N
    # The whole point: building + showing the view over 100k rows must NOT
    # materialize anywhere near N rows. A tall window shows a few dozen rows;
    # resizeColumnsToContents samples up to the precision bound (100 rows).
    assert src.build_calls < N // 50, src.build_calls
    assert len(model._cache) <= model.CACHE_LIMIT

    # Scrolling to the bottom adds only a bounded number of fresh builds.
    before = src.build_calls
    view.scrollToBottom()
    QApplication.processEvents()
    assert src.build_calls - before < 2000, (before, src.build_calls)


# --------------------------------------------------------------------------- #
# 2. Row height: compact + uniform (regression fix for dropped                 #
#    resizeRowsToContents)                                                      #
# --------------------------------------------------------------------------- #
def test_uniform_row_height_is_compact_and_applied(qapp):
    src = _SyntheticSource([f"obj_{i:04d}" for i in range(500)])
    model, view = _make_view(src)

    # the content-fit height of a single representative row
    view.resizeRowToContents(0)
    content_h = view.rowHeight(0)
    # re-apply uniform sizing (createTable does this after column resize)
    view.setUniformRowHeight()

    heights = [view.rowHeight(r) for r in (0, 1, 2, 100, 499)]
    assert len(set(heights)) == 1, heights                 # uniform
    assert heights[0] == content_h, (heights[0], content_h)  # content-fit, like old
    assert heights[0] < 30, heights[0]                     # compact, not the 30px default


def test_inserted_rows_inherit_uniform_height(qapp):
    src = _SyntheticSource([f"obj_{i:04d}" for i in range(50)])
    model, view = _make_view(src)
    h = view.rowHeight(0)

    row, exists = model.rowOf("obj_9999")
    assert not exists
    model.insertName("obj_9999", row)
    QApplication.processEvents()
    assert view.rowHeight(model.rowCount() - 1) == h


def test_uniform_row_height_handles_empty_model(qapp):
    src = _SyntheticSource([])
    model, view = _make_view(src)
    # must not raise and must leave a sane compact default
    assert model.rowCount() == 0
    assert 0 < view.verticalHeader().defaultSectionSize() < 30


# --------------------------------------------------------------------------- #
# 2b. Incremental column auto-widen (O(1)-per-edit mitigation)                 #
#                                                                              #
# The old QTableWidget re-ran resizeColumnsToContents() on every edit, so a    #
# longer edited/inserted value widened its column to fit. Virtualization       #
# dropped that full re-sample; growColumnsToFitRow restores the widen by       #
# measuring ONLY the changed row (O(#columns), independent of #objects). These #
# pin: it grows a column for a too-wide cell, never shrinks for a fit cell,    #
# and the per-edit path never calls the full resizeColumnsToContents().        #
# --------------------------------------------------------------------------- #
class _WidthSource:
    """Synthetic source whose Comment cell text is editable per object."""
    def __init__(self, names):
        self._names = sortList(names)
        self.static_columns = ["Name"]
        self.columns = [("Comment", True)]
        self.comments = {n: "" for n in self._names}

    def getHeaders(self):
        return ["Name", "Comment"]

    def getFiltered(self):
        return sortList([n for n in self._names if n in self.comments])

    def getItems(self, name, key):
        if key == "Comment":
            return [QTableWidgetItem(self.comments.get(name, ""))]
        return [QTableWidgetItem(name)]


def test_wide_edit_grows_only_changed_column(qapp):
    """An edit whose new value is wider than the current column grows that
    column to fit (the cell's own sizeHint), restoring the old widen behavior --
    without a full resizeColumnsToContents()."""
    src = _WidthSource(["a", "b", "c"])
    model, view = _make_view(src, show=True, configure=True)

    comment_col = view.model().columnCount() - 1
    before = view.columnWidth(comment_col)

    src.comments["b"] = "X" * 200
    row, exists = model.rowOf("b")
    assert exists
    model.refreshRow(row)
    grew = view.growColumnsToFitRow(row)

    after = view.columnWidth(comment_col)
    assert grew is True
    assert after > before
    # the column is now at least as wide as the edited cell needs (not clipped)
    assert after >= view.sizeHintForIndex(model.index(row, comment_col)).width()


def test_inserted_wide_value_grows_column(qapp):
    """Inserting a row whose value is wider than any existing column widens that
    column -- the new-object analogue of the wide-edit case."""
    src = _WidthSource(["a", "c"])
    model, view = _make_view(src, show=True, configure=True)

    comment_col = view.model().columnCount() - 1
    before = view.columnWidth(comment_col)

    # add a new object "b" carrying a long comment
    src.comments["b"] = "WIDE" * 60
    row, exists = model.rowOf("b")
    assert not exists
    model.insertName("b", row)
    grew = view.growColumnsToFitRow(row)

    assert grew is True
    assert view.columnWidth(comment_col) > before


def test_fit_edit_does_not_shrink_or_full_resize(qapp):
    """An edit that fits the current column neither shrinks it nor triggers the
    O(#rows) resizeColumnsToContents() -- the cost that virtualization removed.
    growColumnsToFitRow reports no growth for a fit-width edit."""
    src = _WidthSource(["a", "b", "c"])
    model, view = _make_view(src, show=True, configure=True)

    comment_col = view.model().columnCount() - 1

    # first widen the column with a long value
    src.comments["b"] = "X" * 200
    row, _ = model.rowOf("b")
    model.refreshRow(row)
    view.growColumnsToFitRow(row)
    wide = view.columnWidth(comment_col)

    # now a short edit that comfortably fits: width must stay (never shrink)
    full_resize = mock.patch.object(
        ObjectTableView, "resizeColumnsToContents", autospec=True
    )
    with full_resize as resize_spy:
        src.comments["b"] = "y"
        model.refreshRow(row)
        grew = view.growColumnsToFitRow(row)

    assert grew is False
    assert view.columnWidth(comment_col) == wide          # never shrinks
    resize_spy.assert_not_called()                         # no O(#rows) resample


def test_updateData_grows_column_without_full_resize(qapp, tmp_path):
    """End-to-end on the real ObjectTableWidget.updateData path: a comment edit
    wider than the column widens it, and updateData never calls the full
    resizeColumnsToContents().

    _RealObjectSource already implements the full source contract (and exposes
    .series / .passesFilters), so it doubles as the updateData container; we
    only attach the model/view/mainwindow updateData also touches.
    """
    series = _load_series(tmp_path)
    names = sortList(list(series.data["objects"].keys()))
    all_cols = [(k, True) for k, _ in series.getOption("object_columns")]

    obj = _RealObjectSource(series, all_cols)
    obj.updateData = ObjectTableWidget.updateData.__get__(obj, _RealObjectSource)
    obj.horizontal_headers = obj.getHeaders()

    model = ObjectTableModel(obj)
    obj.model = model
    view = ObjectTableView(obj)
    view.setModel(model)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.horizontalHeader().setResizeContentsPrecision(100)
    view.resizeColumnsToContents()
    view.resize(900, 600)
    view.show()
    QApplication.processEvents()
    obj.table = view
    obj.mainwindow = mock.Mock()

    comment_col = obj.getHeaders().index("Comment")
    before = view.columnWidth(comment_col)

    target = names[0]
    series.setAttr(target, "comment", "VERYLONGCOMMENT" * 20)

    with mock.patch.object(
        ObjectTableView, "resizeColumnsToContents", autospec=True
    ) as resize_spy:
        obj.updateData([target])

    assert view.columnWidth(comment_col) > before          # widened to fit
    resize_spy.assert_not_called()                          # stayed O(1)/edit


# --------------------------------------------------------------------------- #
# 3. The edit seam: setData -> onCheckStateChanged                             #
# --------------------------------------------------------------------------- #
class _CheckSource:
    """Synthetic source that records routed check edits and toggles state."""
    def __init__(self):
        self.static_columns = ["Name"]
        self.columns = [("Locked", True)]
        self._names = sortList(["b", "a", "c"])
        self.locked = {n: False for n in self._names}
        self.routed = []
        self.model = None

    def getHeaders(self):
        return ["Name", "Locked"]

    def getFiltered(self):
        return list(self._names)

    def getItems(self, name, key):
        if key == "Locked":
            return [_locked_item(self.locked[name])]
        return [QTableWidgetItem(name)]

    def onCheckStateChanged(self, row, col, state):
        self.routed.append((row, col, state))
        name = self.model.names[row]
        if col == 1:
            self.locked[name] = (state == Qt.CheckState.Checked)
            self.model.refreshRow(row)
            return True
        return False


def test_setdata_routes_checkbox_edit_to_handler(qapp):
    src = _CheckSource()
    model = ObjectTableModel(src)
    src.model = model
    idx = model.index(0, 1)  # row 'a', Locked column

    assert model.data(idx, Qt.CheckStateRole) == Qt.CheckState.Unchecked.value
    # Qt's delegate passes a plain int; the model coerces it to Qt.CheckState.
    accepted = model.setData(idx, Qt.CheckState.Checked.value, Qt.CheckStateRole)
    assert accepted is True
    assert src.routed == [(0, 1, Qt.CheckState.Checked)]
    assert src.locked["a"] is True
    assert model.data(idx, Qt.CheckStateRole) == Qt.CheckState.Checked.value


def test_setdata_ignores_non_checkstate_roles_and_missing_handler(qapp):
    # role other than CheckStateRole is rejected, handler not invoked
    src = _CheckSource()
    model = ObjectTableModel(src)
    src.model = model
    assert model.setData(model.index(0, 1), "x", Qt.EditRole) is False
    assert src.routed == []

    # a source without onCheckStateChanged -> setData returns False, no crash
    plain = _SyntheticSource(["a", "b"])
    pmodel = ObjectTableModel(plain)
    assert pmodel.setData(pmodel.index(0, 0), 2, Qt.CheckStateRole) is False


def test_physical_checkbox_click_persists(qapp):
    """A real mouse click on the checkbox indicator routes through the delegate
    to setData even under NoEditTriggers, and persists to the source."""
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent

    src = _CheckSource()
    model = ObjectTableModel(src)
    src.model = model
    view = ObjectTableView(src)
    view.setModel(model)
    view.setEditTriggers(QAbstractItemView.NoEditTriggers)
    view.resize(400, 300)
    view.show()
    QApplication.processEvents()

    idx = model.index(0, 1)
    rect = view.visualRect(idx)
    pos = QPoint(rect.left() + 8, rect.center().y())
    vp = view.viewport()
    QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.processEvents()

    assert src.routed, "checkbox click did not route to onCheckStateChanged"
    assert src.locked["a"] is True


def test_real_locked_handler_matches_old_semantics(qapp):
    """The real ObjectTableWidget.onCheckStateChanged Locked branch sets the
    series attr, repaints, deselects traces when locking, and marks modified --
    exactly the old itemChanged Locked branch, returning True (accepted)."""
    src = _CheckSource()
    model = ObjectTableModel(src)
    src.model = model

    obj = ObjectTableWidget.__new__(ObjectTableWidget)
    obj.horizontal_headers = ["Name", "Locked"]
    obj.model = model
    obj.series = mock.Mock()
    obj.series_states = mock.Mock()
    obj.mainwindow = mock.Mock()

    result = obj.onCheckStateChanged(0, 1, Qt.CheckState.Checked)

    assert result is True
    obj.series_states.addState.assert_called_once()
    obj.series.setAttr.assert_called_once_with("a", "locked", True)
    obj.mainwindow.field.deselectAllTraces.assert_called_once()
    obj.mainwindow.seriesModified.assert_called_once_with(True)


def _make_cr_handler(locked=False):
    """Build a real ObjectTableWidget wired to a model for the CR branch.

    Mirrors test_real_locked_handler_matches_old_semantics' setup but exposes a
    "CR" column. series.getAttr (the locked check at the top of the CR branch)
    is stubbed to ``locked``; everything else is a Mock so we can assert the
    series-state calls the old itemChanged CR branch produced.
    """
    src = _CheckSource()
    model = ObjectTableModel(src)
    src.model = model

    obj = ObjectTableWidget.__new__(ObjectTableWidget)
    obj.horizontal_headers = ["Name", "CR"]
    obj.model = model
    obj.series = mock.Mock()
    obj.series.getAttr.return_value = locked
    obj.series_states = mock.Mock()
    obj.manager = mock.Mock()
    obj.mainwindow = mock.Mock()
    return obj


def test_real_cr_handler_unchecked_clears_curation(qapp):
    """Unchecked CR clears curation (setCuration([name], "")), pushes a state,
    updates the object, and marks modified -- the old Unchecked CR branch."""
    obj = _make_cr_handler()

    result = obj.onCheckStateChanged(0, 1, Qt.CheckState.Unchecked)

    assert result is True
    obj.series_states.addState.assert_called_once()
    obj.series.setCuration.assert_called_once_with(["a"], "")
    obj.manager.updateObjects.assert_called_once_with(["a"])
    obj.mainwindow.seriesModified.assert_called_once_with(True)


def test_real_cr_handler_checked_sets_curated(qapp):
    """Checked CR marks the object "Curated"."""
    obj = _make_cr_handler()

    result = obj.onCheckStateChanged(0, 1, Qt.CheckState.Checked)

    assert result is True
    obj.series_states.addState.assert_called_once()
    obj.series.setCuration.assert_called_once_with(["a"], "Curated")
    obj.manager.updateObjects.assert_called_once_with(["a"])
    obj.mainwindow.seriesModified.assert_called_once_with(True)


def test_real_cr_handler_partial_assigns_when_confirmed(qapp):
    """PartiallyChecked CR opens the assign-to dialog; when the user confirms,
    curation is set to "Needs curation" with the entered assignee."""
    obj = _make_cr_handler()

    with mock.patch(
        "PyReconstruct.modules.gui.table.object.QInputDialog.getText",
        return_value=("alice", True),
    ):
        result = obj.onCheckStateChanged(0, 1, Qt.CheckState.PartiallyChecked)

    assert result is True
    obj.series_states.addState.assert_called_once()
    obj.series.setCuration.assert_called_once_with(["a"], "Needs curation", "alice")
    obj.manager.updateObjects.assert_called_once_with(["a"])
    obj.mainwindow.seriesModified.assert_called_once_with(True)


def test_real_cr_handler_partial_cancel_reverts(qapp):
    """PartiallyChecked CR with the dialog cancelled reverts the row and makes
    no series change (returns False) -- the "not confirmed" branch. addState was
    already pushed (matching the old behavior), but no curation/modified call."""
    obj = _make_cr_handler()

    with mock.patch(
        "PyReconstruct.modules.gui.table.object.QInputDialog.getText",
        return_value=("", False),
    ):
        result = obj.onCheckStateChanged(0, 1, Qt.CheckState.PartiallyChecked)

    assert result is False
    obj.series.setCuration.assert_not_called()
    obj.manager.updateObjects.assert_not_called()
    obj.mainwindow.seriesModified.assert_not_called()


def test_real_cr_handler_rejects_locked_object(qapp):
    """A CR toggle on a locked object is rejected: it notifies, refreshes the
    row, re-renders via the manager, and returns False without touching
    curation or pushing a state."""
    obj = _make_cr_handler(locked=True)

    with mock.patch(
        "PyReconstruct.modules.gui.table.object.notify"
    ) as notify_mock:
        result = obj.onCheckStateChanged(0, 1, Qt.CheckState.Checked)

    assert result is False
    notify_mock.assert_called_once()
    obj.manager.updateObjects.assert_called_once_with(["a"])
    obj.series_states.addState.assert_not_called()
    obj.series.setCuration.assert_not_called()
    obj.mainwindow.seriesModified.assert_not_called()


# --------------------------------------------------------------------------- #
# 4. getSelected mapping / copy() / export() equivalence vs old QTableWidget   #
# --------------------------------------------------------------------------- #
def _build_old_widget(src):
    """Populate a real QTableWidget exactly as the old createTable/setRow did."""
    headers = src.getHeaders()
    names = src.getFiltered()
    tw = CopyTableWidget(None, len(names), len(headers))
    tw.setHorizontalHeaderLabels(headers)
    for r, name in enumerate(names):
        col = 0
        for key in src.static_columns:
            for item in src.getItems(name, key):
                tw.setItem(r, col, item)
                col += 1
        for key, b in src.columns:
            if b:
                for item in src.getItems(name, key):
                    tw.setItem(r, col, item)
                    col += 1
    return tw, names


def _select_rows(table, model, rows):
    """Deterministically select whole rows (consecutive selectRow() would
    clear the prior row under ExtendedSelection)."""
    from PySide6.QtCore import QItemSelectionModel
    sm = table.selectionModel()
    sm.clearSelection()
    flag = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for r in rows:
        sm.select(model.index(r, 0), flag)


def test_getselected_row_to_name_mapping_matches_reference(qapp):
    """The new mapping (selectedIndexes row -> model.nameAt) reproduces the old
    (selectedIndexes row -> item(row,0).text()), including per-cell duplication
    for a full-row selection and the selection ORDER."""
    src = _SyntheticSource([f"obj_{i:03d}" for i in range(20)])
    tw, names = _build_old_widget(src)
    model, view = _make_view(src, show=True, configure=True)

    # select the same two whole rows in both
    _select_rows(tw, tw.model(), (2, 5))
    _select_rows(view, model, (2, 5))

    old_names = [tw.item(i.row(), 0).text() for i in tw.selectedIndexes()]
    new_names = [model.nameAt(i.row()) for i in view.selectedIndexes()]
    assert new_names == old_names  # the equivalence that matters

    # A full-row selection duplicates each name once per *selectable* column.
    # The Locked checkbox cell is built ItemIsUserCheckable|ItemIsEnabled
    # WITHOUT ItemIsSelectable, so it is excluded from selectedIndexes() in
    # both paths -- the model faithfully propagates that flag.
    selectable = [c for c in range(model.columnCount())
                  if model.flags(model.index(2, c)) & Qt.ItemFlag.ItemIsSelectable]
    assert 0 < len(selectable) < model.columnCount()  # Locked is excluded
    assert old_names.count(names[2]) == len(selectable)
    assert old_names.count(names[5]) == len(selectable)
    assert set(old_names) == {names[2], names[5]}


def test_copy_output_matches_copytablewidget(qapp, monkeypatch):
    src = _SyntheticSource([f"obj_{i:03d}" for i in range(10)])
    tw, names = _build_old_widget(src)
    model, view = _make_view(src, show=True, configure=True)

    captured = {}

    class _Clip:
        def setText(self, t):
            captured["t"] = t

    # avoid depending on a system clipboard under the offscreen platform
    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: _Clip()))

    # multi-row selection exercises copy()'s per-row tab/newline grouping
    _select_rows(tw, tw.model(), (3, 7))
    _select_rows(view, model, (3, 7))

    tw.copy()
    old_clip = captured.get("t")
    view.copy()
    new_clip = captured.get("t")

    assert new_clip == old_clip
    assert old_clip  # non-empty


# --- export() equivalence on the real fixture, all columns enabled ---------- #
class _RealObjectSource:
    getItems = ObjectTableWidget.getItems
    getHeaders = ObjectTableWidget.getHeaders
    passesFilters = ObjectTableWidget.passesFilters

    def __init__(self, series, columns):
        self.series = series
        self.static_columns = ["Name"]
        self.columns = columns
        self.re_filters = {".*"}
        self.tag_filters = set()
        self.group_filters = set()
        self.config_filters = {"closed": True, "open": True, "mixed": True}
        self.cr_status_filter = {"Blank": True, "Needs curation": True, "Curated": True}
        self.cr_user_filters = set()
        self.user_col_filters = {}
        self.host_filters = set()
        self.direct_hosts_only = False
        self.curate_column = None

    def getFiltered(self):
        return sortList([n for n in self.series.data["objects"] if self.passesFilters(n)])


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def test_export_csv_matches_old_path(qapp, tmp_path, monkeypatch):
    """ObjectTableWidget.export (model-backed) writes the same CSV bytes as the
    old DataTable.export (QTableWidget-backed) over identical data."""
    series = _load_series(tmp_path)
    all_cols = [(k, True) for k, _ in series.getOption("object_columns")]
    # seed varied curation/locked state so checkbox + colored cells are exercised
    names = sortList(list(series.data["objects"].keys()))
    series.setAttr(names[0], "locked", True)
    series.setCuration([names[1]], "Curated")
    if len(names) > 2:
        series.setCuration([names[2]], "Needs curation", "alice")

    src = _RealObjectSource(series, all_cols)

    # OLD path: real QTableWidget + DataTable.export
    tw, _ = _build_old_widget(src)
    old_fp = str(tmp_path / "old.csv")
    old_obj = DataTable.__new__(DataTable)
    old_obj.table = tw
    old_obj.name = "object"
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.data_table.FileDialog.get",
        staticmethod(lambda *a, **k: old_fp),
    )
    old_obj.export()

    # NEW path: model + ObjectTableWidget.export
    new_fp = str(tmp_path / "new.csv")
    new_obj = ObjectTableWidget.__new__(ObjectTableWidget)
    new_obj.model = ObjectTableModel(src)
    new_obj.name = "object"
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.object.FileDialog.get",
        staticmethod(lambda *a, **k: new_fp),
    )
    new_obj.export()

    with open(old_fp) as f:
        old_csv = f.read()
    with open(new_fp) as f:
        new_csv = f.read()

    assert new_csv == old_csv
    # sanity: the export actually produced the expected shape
    assert old_csv.splitlines()[0].split(",")[0] == "Name"
    assert len(old_csv.splitlines()) == len(src.getFiltered()) + 1
