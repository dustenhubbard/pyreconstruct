"""Which trace palette buttons a Dev build leaves off the mouse palette.

An old legacy import (fork #600) gave some palettes two extra rows of the
standard buttons, so 20 lab traces showed as 4 rows. Until the palette editor
can remove them (fork #1004), a Dev build does not show trailing rows that are
exact copies of a standard row. Only the mouse palette changes: the series,
the palette editor, exports and saves keep every button.

A button is an exact copy when its `Trace.getList` row (name, points, color,
closed, negative, hidden, fill mode, tags) equals the standard button's and it
has no object defaults. A row is a standard row when its 10 buttons are, in
order, the 10 a new series gets (`default_traces`) or the 10 a legacy import
adds (the placeholder palette in `blank_series`).
"""
from copy import deepcopy

from PyReconstruct.modules.constants import blank_series
from PyReconstruct.modules.constants.traces import default_traces
from PyReconstruct.modules.datatypes import Trace

ROW = 10  # the mouse palette lays out 10 buttons per row
KEEP = 20  # never show fewer buttons than this

_reference_rows = None


def legacyDefaultRow() -> list:
    """The 10 buttons a legacy import adds, read the way the import reads them."""
    from lxml import etree
    from PyReconstruct.modules.datatypes_legacy.classes.contour import Contour
    from PyReconstruct.modules.datatypes_legacy.utils.reconstruct_reader import (
        extract_series_contour_attributes,
    )
    root = etree.fromstring(blank_series.encode())
    nodes = [node for node in root if node.tag == "Contour"][:ROW]
    return [
        Trace.fromXMLObj(Contour(**extract_series_contour_attributes(node)))
        for node in nodes
    ]


def _plain(value):
    """Lists for tuples, all the way down, so a row read from a file compares
    equal to one built in memory."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _referenceRows() -> list:
    global _reference_rows
    if _reference_rows is None:
        new = [Trace.fromList(deepcopy(row)) for row in default_traces]
        _reference_rows = [
            [_plain(t.getList()) for t in new],
            [_plain(t.getList()) for t in legacyDefaultRow()],
        ]
    return _reference_rows


def isDefaultRow(traces : list) -> bool:
    """True when `traces` is 10 buttons that are, in order, a standard row."""
    if len(traces) != ROW or any(t.obj_defaults for t in traces):
        return False
    rows = [_plain(t.getList()) for t in traces]
    return any(rows == reference for reference in _referenceRows())


def shownButtonCount(traces : list) -> int:
    """How many of a palette's buttons the mouse palette shows in a Dev build.

    From the end, whole rows of 10 past the first 20 buttons go while they
    are standard rows. The first row that is not stops it, and so does a
    last row that is not full.
    """
    count = len(traces)
    if count % ROW:
        return count
    while count > KEEP and isDefaultRow(traces[count - ROW:count]):
        count -= ROW
    return count
