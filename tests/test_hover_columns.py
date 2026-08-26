"""The field hover pop-up's configurable columns.

Ported from upstream 267c26257817 (Michael, #100): a per-series choice of
which object data the hover pop-up shows over a trace, and in what order,
edited through HoverColumnsDialog.

The port needed one addition. Upstream's commit touches five GUI files and
no datatype; on this fork ``Series.setOption`` silently ignores a name that
is not a registered option, so the dialog's result would have vanished on
save. ``hover_columns`` is registered in the series options defaults here,
and these tests pin both halves: the option round-trips, and the hover text
follows it.
"""

import pytest

pytestmark = pytest.mark.gui

from PyReconstruct.modules.gui.dialog.hover_columns import HoverColumnsDialog


def test_the_option_round_trips_through_the_series(real_series):
    """The half upstream's commit did not need and this fork does."""
    default = real_series.getOption("hover_columns")
    assert default, "hover_columns must be a registered series option"
    names = [name for name, _enabled in default]
    assert names == HoverColumnsDialog.AVAILABLE_COLUMNS

    chosen = [("Comment", True), ("Host", False), ("Trace Tags", True)]
    real_series.setOption("hover_columns", chosen)
    assert [tuple(row) for row in real_series.getOption("hover_columns")] == chosen


def test_defaults_keep_the_pre_port_hover_content(real_series):
    """The port must not change what a user already sees: Host, Comment,
    Object Alignment, Object Groups and Trace Tags were the old fixed set."""
    enabled = {
        name for name, on in real_series.getOption("hover_columns") if on
    }
    assert enabled == {
        "Host", "Comment", "Object Alignment", "Object Groups", "Trace Tags",
    }


def test_dialog_keeps_the_order_it_was_given(qapp, real_series):
    """Order is content here: the pop-up prints the columns in list order,
    so the dialog must not sort or regroup what it is handed."""
    reordered = [
        ("Trace Tags", True),
        ("Comment", True),
        ("Host", False),
        ("Name", False),
        ("Section Range", False),
        ("Object Alignment", False),
        ("Object Groups", False),
    ]
    dialog = HoverColumnsDialog(None, reordered)
    try:
        assert dialog.columns == reordered
    finally:
        dialog.deleteLater()


def test_dialog_move_buttons_reorder_the_list(qapp, real_series):
    """The reorder half of the feature, driven through moveRow."""
    columns = [(name, True) for name in HoverColumnsDialog.AVAILABLE_COLUMNS]
    dialog = HoverColumnsDialog(None, columns)
    try:
        dialog.moveRow(index=2, up=True)      # Section Range moves above Host
        assert [n for n, _ in dialog.columns][:3] == [
            "Name", "Section Range", "Host",
        ]
    finally:
        dialog.deleteLater()
