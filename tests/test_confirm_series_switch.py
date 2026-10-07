"""A clean-up confirmed after another series opens acts on nothing.

Series > Clean up > Repair self-crossing traces and Remove empty traces each
scan series A, then ask for confirmation in the main window before they act.
The confirmation is modal, so the menus wait, but a .jser opened from the
Finder still reaches the window and opens series B under it. Accepting then
repaired or removed the matching traces in B, through the field that B now
fills. Here A and B are byte copies, so every trace A's scan found also
exists in B.

What is pinned here, for both commands: a confirmation accepted after B opens
from the Finder leaves B unchanged on disk and unmodified, and opens no list.
"""
import pytest
from shiboken6 import isValid

from test_cleanup_lists_series_switch import (
    _counts,
    _open_copy,
    _plant,
    finder,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui

# a zero-width spike off a square: one real loop, so the repair is offered
SPIKED_SQUARE = [
    (0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
    (5.0, 10.0), (5.0, 10.5), (5.0, 10.0),
    (0.0, 10.0),
]
# a closed trace on three points in a line encloses no area
FLAT = [(1.0, 1.0), (2.0, 1.0), (3.0, 1.0)]


@pytest.fixture
def confirmed_after_b_opens(
    monkeypatch, main_window, main_window_dialogs, tmp_path, qtbot,
    finder,  # noqa: F811  (the imported fixture)
):
    """Accept the main window's next confirmation only after B opens under it.

    Returns the confirmations asked.
    """
    from PyReconstruct.modules.gui.main import main_window as mw
    asked = []

    def confirm(message, *args, **kwargs):
        asked.append(message)
        _open_copy(main_window, tmp_path, qtbot, from_finder=True)
        return True

    monkeypatch.setattr(mw, "notifyConfirm", confirm)
    return asked


def _open_lists(window):
    """The clean-up lists still open on the window."""
    from PyReconstruct.modules.gui.dialog.malformed_contours import (
        MalformedContoursDialog,
    )
    return [
        d for d in window.findChildren(MalformedContoursDialog)
        if isValid(d) and d.isVisible()
    ]


@pytest.mark.parametrize("command", ["repair", "empty"])
def test_a_clean_up_confirmed_after_b_opens_leaves_b_alone(
    command, main_window, confirmed_after_b_opens
):
    window = main_window
    if command == "repair":
        name = "SWITCH_SPIKE"
        snum = _plant(window, name, SPIKED_SQUARE)
        run = window.repairSelfCrossingTraces
        word = "Repair"
    else:
        name = "SWITCH_EMPTY"
        snum = _plant(window, name, FLAT)
        run = window.removeEmptyTraces
        word = "Remove"
    first = window.series
    # B opens as a byte copy of A as saved
    saved = _counts(first, snum)
    assert saved[name] == 1

    run()

    assert len(confirmed_after_b_opens) == 1
    assert confirmed_after_b_opens[0].startswith(word)
    assert window.series is not first
    assert _counts(window.series, snum) == saved
    points = window.series.loadSection(snum).contours[name][0].points
    expected = SPIKED_SQUARE if command == "repair" else FLAT
    assert [tuple(p) for p in points] == expected
    assert not window.series.modified
    assert _open_lists(window) == []
