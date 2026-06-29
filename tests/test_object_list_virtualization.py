"""Equivalence + virtualization tests for the Object List rewrite.

The Object List moved from an eagerly-populated ``QTableWidget`` (one
``QTableWidgetItem`` per cell, built up front for every object) to a lazy
``ObjectTableModel`` + ``ObjectTableView``. These tests pin two things:

1. EQUIVALENCE -- the model's per-cell data, check states, flags, background
   colors, headers and row order are byte-for-byte identical to what the old
   population path produced. The reference is a real ``QTableWidget`` filled
   exactly the way ``DataTable.createTable``/``setRow`` used to fill it.
2. VIRTUALIZATION -- the model only builds items for the rows actually
   requested (a small visible window), and its item cache stays bounded, so a
   100k-object series no longer materializes 100k * #cols widget items.

The reference and the model both ultimately call ``ObjectTableWidget.getItems``,
so equivalence here is really pinning the *mapping* the model adds on top:
column expansion (Range -> Start/End, Curate -> CR/Status/User/Date), role
extraction, ordering and incremental insert/remove/refresh placement -- which
is exactly where a virtualization bug would hide.
"""
import os
import shutil

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
from PySide6.QtCore import Qt

from PyReconstruct.modules.gui.table.object import ObjectTableWidget
from PyReconstruct.modules.gui.table.object_model import ObjectTableModel
from PyReconstruct.modules.gui.utils import sortList

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)

ALL_ROLES = (Qt.DisplayRole, Qt.CheckStateRole, Qt.BackgroundRole)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


# --------------------------------------------------------------------------- #
# A GUI-free stand-in that exposes the exact source contract the model needs,  #
# reusing ObjectTableWidget's real data methods.                               #
# --------------------------------------------------------------------------- #
class RealObjectSource:
    getItems = ObjectTableWidget.getItems
    getHeaders = ObjectTableWidget.getHeaders
    passesFilters = ObjectTableWidget.passesFilters

    def __init__(self, series, columns=None):
        self.series = series
        self.static_columns = ["Name"]
        self.columns = columns if columns is not None else series.getOption("object_columns")
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


def _build_reference(source):
    """Populate a real QTableWidget exactly as the old createTable/setRow did."""
    headers = source.getHeaders()
    names = source.getFiltered()
    tw = QTableWidget(len(names), len(headers))
    tw.setHorizontalHeaderLabels(headers)
    for r, name in enumerate(names):
        col = 0
        for key in source.static_columns:
            for item in source.getItems(name, key):
                tw.setItem(r, col, item)
                col += 1
        for key, b in source.columns:
            if b:
                for item in source.getItems(name, key):
                    tw.setItem(r, col, item)
                    col += 1
    return tw, headers, names


def _assert_equivalent(model, source):
    tw, headers, names = _build_reference(source)

    # headers + shape
    assert model.rowCount() == len(names)
    assert model.columnCount() == len(headers)
    assert model.names == names
    assert [model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
            for c in range(model.columnCount())] == headers

    # row order is the sorted, filtered name list
    assert names == sortList(names)

    # every cell: text, check state, background, flags
    for r in range(len(names)):
        for c in range(len(headers)):
            idx = model.index(r, c)
            old = tw.item(r, c)
            assert (model.data(idx, Qt.DisplayRole) or "") == old.text(), (r, c)
            for role in (Qt.CheckStateRole, Qt.BackgroundRole):
                assert model.data(idx, role) == old.data(role), (r, c, role)
            assert model.flags(idx) == old.flags(), (r, c)


# --------------------------------------------------------------------------- #
# Equivalence                                                                  #
# --------------------------------------------------------------------------- #
def test_default_columns_match_old_population_path(qapp, tmp_path):
    source = RealObjectSource(_load_series(tmp_path))
    _assert_equivalent(ObjectTableModel(source), source)


def test_all_columns_with_curation_and_locked(qapp, tmp_path):
    """Enable every column (incl. Range expansion + Curate's 4-way expansion)
    and seed locked/curated/needs-curation objects so checkboxes, tristate
    flags and curation background colors are all exercised."""
    series = _load_series(tmp_path)
    all_cols = [(k, True) for k, _ in series.getOption("object_columns")]
    names = sortList(list(series.data["objects"].keys()))
    # seed a variety of states
    series.setAttr(names[0], "locked", True)
    series.setCuration([names[1]], "Curated")
    series.setCuration([names[2]], "Needs curation", "alice")
    source = RealObjectSource(series, columns=all_cols)
    _assert_equivalent(ObjectTableModel(source), source)


def test_equivalence_holds_under_regex_filter(qapp, tmp_path):
    series = _load_series(tmp_path)
    source = RealObjectSource(series)
    source.re_filters = {"s.*"}  # only names starting with 's'
    model = ObjectTableModel(source)
    assert all(n.startswith("s") for n in model.names)
    assert len(model.names) < len(series.data["objects"])
    _assert_equivalent(model, source)


# --------------------------------------------------------------------------- #
# rowOf placement matches the old linear scan exactly                          #
# --------------------------------------------------------------------------- #
def _old_get_row_index(names, name):
    """The exact algorithm CopyTableWidget.getRowIndex used."""
    from PyReconstruct.modules.gui.utils import lessThan
    for row_index, row_name in enumerate(names):
        if lessThan(name, row_name):
            return row_index, False
        elif name == row_name:
            return row_index, True
    return len(names), False


def test_rowOf_matches_old_linear_scan(qapp, tmp_path):
    source = RealObjectSource(_load_series(tmp_path))
    model = ObjectTableModel(source)
    probes = list(model.names) + ["aaa", "zzz", "square2", "STAR", "0", "999"]
    for name in probes:
        assert model.rowOf(name) == _old_get_row_index(model.names, name), name


# --------------------------------------------------------------------------- #
# Incremental update primitives keep the model sorted + consistent             #
# --------------------------------------------------------------------------- #
class _SyntheticSource:
    """Minimal source with cheap, instrumented item production."""
    def __init__(self, names, columns=None):
        self._names = list(names)
        self.static_columns = ["Name"]
        self.columns = columns or [("Count", True), ("Comment", True)]
        self.build_calls = 0

    def getHeaders(self):
        return self.static_columns + [k for k, b in self.columns if b]

    def getFiltered(self):
        return sortList(self._names)

    def getItems(self, name, key):
        self.build_calls += 1
        return [QTableWidgetItem(f"{name}:{key}")]


def test_incremental_insert_remove_refresh_keeps_sorted(qapp):
    src = _SyntheticSource(["a", "c", "e"])
    model = ObjectTableModel(src)
    assert model.names == ["a", "c", "e"]

    # insert "b" and "d" at their sorted positions
    for name in ("b", "d"):
        row, exists = model.rowOf(name)
        assert not exists
        model.insertName(name, row)
    assert model.names == ["a", "b", "c", "d", "e"]
    assert model.rowCount() == 5

    # remove "c"
    row, exists = model.rowOf("c")
    assert exists
    model.removeRowAt(row)
    assert model.names == ["a", "b", "d", "e"]

    # refresh an existing row -- must not change membership/order
    model.refreshRow(model.rowOf("d")[0])
    assert model.names == ["a", "b", "d", "e"]


# --------------------------------------------------------------------------- #
# Virtualization: only visible rows are built; cache stays bounded             #
# --------------------------------------------------------------------------- #
def test_only_visible_rows_are_built(qapp):
    N = 100_000
    src = _SyntheticSource([f"obj_{i:06d}" for i in range(N)])
    model = ObjectTableModel(src)

    # Constructing the model must NOT build any row items.
    assert src.build_calls == 0
    assert model.rowCount() == N

    # Render a visible window of 50 rows (as a view would).
    n_cols = model.columnCount()
    for r in range(50):
        for c in range(n_cols):
            model.data(model.index(r, c), Qt.DisplayRole)

    # Items were built for ~50 rows, not for all 100k. (getItems is called
    # once per (row, group); compare against the all-rows cost.)
    assert src.build_calls < 50 * n_cols * 4
    assert src.build_calls < N  # the key property: sub-linear in #objects
    assert len(model._cache) <= 50


def test_stale_index_does_not_crash(qapp):
    """A QModelIndex created before a row removal still reports isValid(); the
    model must not IndexError when Qt queries it after the removal."""
    src = _SyntheticSource(["a", "b", "c"])
    model = ObjectTableModel(src)
    stale = model.index(2, 0)
    model.removeRowAt(2)
    assert model.rowCount() == 2
    # data()/flags() on the now-out-of-bounds index must degrade gracefully
    assert model.data(stale, Qt.DisplayRole) is None
    assert model.flags(stale) == Qt.ItemFlag.NoItemFlags


def test_refresh_does_not_leak_cache_order(qapp):
    """Repeated single-row refreshes must keep the cache bounded and consistent
    (the old parallel order-list could accumulate stale entries)."""
    src = _SyntheticSource([f"obj_{i:04d}" for i in range(200)])
    model = ObjectTableModel(src)
    for r in range(100):
        model.data(model.index(r, 0), Qt.DisplayRole)
    for _ in range(5):
        for r in range(50):
            model.refreshRow(r)
            model.data(model.index(r, 0), Qt.DisplayRole)
    assert len(model._cache) <= model.CACHE_LIMIT


def test_item_cache_is_bounded(qapp):
    N = 50_000
    src = _SyntheticSource([f"obj_{i:06d}" for i in range(N)])
    model = ObjectTableModel(src)
    # Touch far more rows than the cache limit.
    for r in range(model.CACHE_LIMIT + 5_000):
        model.data(model.index(r, 0), Qt.DisplayRole)
    assert len(model._cache) <= model.CACHE_LIMIT
