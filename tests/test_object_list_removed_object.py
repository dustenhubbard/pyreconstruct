"""An Object List row whose object is already gone must go blank, not raise.

The crash this pins, from a user's Windows error report (editing an object's
attributes with the Object List open, v1.21.2b1)::

    File ".../gui/main/field_widget_3_object.py", ... in editAttributes
    File ".../backend/table/manager.py", ... in updateObjects
    File ".../gui/table/object.py", ... in updateData
    File ".../gui/table/object_model.py", ... in removeRowAt
    File ".../gui/table/object_model.py", ... in flags
    File ".../gui/table/object_model.py", ... in _rowItems
    File ".../gui/table/object_model.py", ... in _buildItems
    File ".../gui/table/object.py", ... in getItems
    TypeError: can only join an iterable

The sequence: an attribute edit removes or renames an object, its data leaves
``series.data["objects"]`` first, and only then does the table remove the row.
``beginRemoveRows`` makes an attached view's selection model re-query the
departing row (``flags``/``data``) while its name is still in the model, so
``getItems`` computes columns for an object that no longer exists.
``SeriesData.getTags`` answered ``None`` for the unknown name and the Trace
tags column joined it. The user's own guess was "too many characters in my
tag?"; tag length had nothing to do with it.

Two fixes, both pinned here:

1. ``SeriesData.getTags`` returns an empty set for an unknown object, matching
   its annotation and every caller's set arithmetic.
2. ``ObjectTableModel._buildItems`` answers the existing "no cell here" shape
   (an empty list) for a name with no series data, instead of asking getItems
   for columns that cannot be computed. This covers the whole class: with only
   fix 1, the Flat area / Volume / Radius columns still die on
   ``round(None, 5)`` in the same scenario.

The model is exercised directly (``flags``/``data`` on the stale row) rather
than through a live view's selection model, which makes the mid-removal window
deterministic instead of depending on Qt's notification order.
"""

import os
import shutil

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.gui.table.object import ObjectTableWidget
from PyReconstruct.modules.gui.table.object_model import ObjectTableModel
from PyReconstruct.modules.gui.utils import sortList

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


class RealObjectSource:
    """The exact source contract the model needs, on real table data methods.

    Same stand-in as test_object_list_virtualization.py: GUI-free, but the
    ``getItems`` the model calls is ``ObjectTableWidget``'s real one, so the
    column computations under test are the shipped ones.
    """

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


def _all_columns_model(series):
    """Every column on, so Trace tags AND the round()ed numerics are built."""
    all_cols = [(k, True) for k, _ in series.getOption("object_columns")]
    source = RealObjectSource(series, columns=all_cols)
    return ObjectTableModel(source, None)


def test_gettags_is_an_empty_set_for_an_unknown_object(qapp, tmp_path):
    series = _load_series(tmp_path)
    assert series.data.getTags("no-such-object") == set()


def test_stale_row_goes_blank_instead_of_raising(qapp, tmp_path):
    """flags()/data() on a row whose object data is gone: blank, no raise."""
    series = _load_series(tmp_path)
    model = _all_columns_model(series)
    victim_row = 0
    victim = model.names[victim_row]

    # the mid-removal window: data gone, name still in the model
    del series.data["objects"][victim]

    for col in range(model.columnCount()):
        idx = model.index(victim_row, col)
        assert model.flags(idx) == Qt.ItemFlag.NoItemFlags
        assert model.data(idx, Qt.DisplayRole) is None


def test_removal_completes_and_survivors_still_render(qapp, tmp_path):
    """The removal itself finishes, and no blank row was left in the cache.

    The stale row's empty item list must not be cached under its row index:
    after the removal that index belongs to the next name down, which must
    render its real cells.
    """
    series = _load_series(tmp_path)
    model = _all_columns_model(series)
    victim = model.names[0]
    survivor = model.names[1]

    del series.data["objects"][victim]
    # the re-query the selection model performs during beginRemoveRows
    model.flags(model.index(0, 0))

    model.removeRowAt(0)

    assert victim not in model.names
    assert model.rowCount() == len(model.names)
    assert model.data(model.index(0, 0), Qt.DisplayRole) == survivor
