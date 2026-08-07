"""Dismissing the flag list's colour filter picker must change nothing.

It used to set the filter to **black**, on every platform, including when the
user pressed Cancel. Two independent defects in four lines of
``FlagTableWidget.setColorFilter``:

1. It called the static ``QColorDialog.getColor()``. On macOS that does not
   open a Qt dialog at all -- Qt hands the request to the platform theme, which
   shows the shared system "Colors" panel, and closing that panel returns an
   invalid ``QColor``. This is the same defect fixed for the trace swatch; see
   ``tests/test_color_picker_dismissal.py``.

2. Worse, and platform-independent: the dismissal guard was ``if not c:
   return``. ``QColor`` defines no ``__bool__``, so ``bool(QColor())`` is
   ``True`` even when ``isValid()`` is ``False`` -- verified in a running
   interpreter, not reasoned about. The guard therefore never fired. Execution
   fell straight through to ``(c.red(), c.green(), c.blue())``, which on an
   invalid ``QColor`` is ``(0, 0, 0)``.

So Cancel did not leave the filter alone; it filtered the list to black flags.
``color_filter`` is consumed at ``if self.color_filter and tuple(flag.color) !=
self.color_filter`` and ``is_color = bool(self.color_filter)``, and ``(0, 0, 0)``
is a truthy tuple, so the filter read as *active*. Flags are rarely pure black,
so the visible result was a flag list that emptied itself when the user
cancelled a dialog, with a filter they never chose and had to find
"Remove color filter" to clear.

The tests below call ``setColorFilter`` against a minimal ``QWidget`` stub
rather than a live ``FlagTableWidget``, because the ``use_selected=False``
branch touches only ``self.color_filter`` and ``self.createTable()``; standing
up a real table would add a series, a manager and a menubar to a test about
four lines of dialog handling.
"""

import pytest

# No `importorskip("pytestqt")`: see tests/conftest.py's collection guard.
pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QWidget

from PyReconstruct.modules.gui.table import flag as flag_module
from PyReconstruct.modules.gui.table.flag import FlagTableWidget

RED = (255, 0, 0)
BLUE = (0, 0, 255)


class _Table(QWidget):
    """The surface ``setColorFilter(use_selected=False)`` actually touches."""

    def __init__(self, color_filter=None):
        super().__init__()
        self.color_filter = color_filter
        self.tables_created = 0

    def createTable(self):
        self.tables_created += 1


def _stub_dialog(monkeypatch, *, accept, chosen=None):
    """Stand in for the dialog ``setColorFilter`` constructs.

    ``getColor`` is overridden as a trap: if the code routes back through the
    static -- the call that opens the system panel on macOS -- it is recorded
    and returns the invalid ``QColor`` a dismissed panel returns, so the test
    fails on the real regression instead of hanging on a modal loop.
    """

    class _StubColorDialog(QColorDialog):
        static_calls = []
        execs = []

        def setOption(self, option, on=True):
            """Model cocoa discarding the seed when native is switched off.

            See ``tests/test_color_picker_dismissal.py`` for the measurement
            and for why this has to be modelled: the offscreen platform the
            suite runs on has no native dialog, so there the flip is a no-op
            and a wrong ordering is invisible.
            """
            super().setOption(option, on)
            if on and option == QColorDialog.ColorDialogOption.DontUseNativeDialog:
                super().setCurrentColor(QColor(Qt.white))

        def exec(self):
            type(self).execs.append(
                {
                    "options": self.options(),
                    "parent": self.parent(),
                    "currentColor": self.currentColor().getRgb()[:3],
                }
            )
            if not accept:
                self.done(QDialog.DialogCode.Rejected)
                return QDialog.DialogCode.Rejected
            if chosen is not None:
                self.setCurrentColor(QColor(*chosen))
            self.done(QDialog.DialogCode.Accepted)
            return QDialog.DialogCode.Accepted

        @staticmethod
        def getColor(*a, **k):
            _StubColorDialog.static_calls.append(a)
            return QColor()

    monkeypatch.setattr(flag_module, "QColorDialog", _StubColorDialog)
    return _StubColorDialog


# --- the bug: a dismissed picker wrote black -------------------------------


def test_cancelled_picker_leaves_an_existing_filter_alone(qapp, monkeypatch):
    stub = _stub_dialog(monkeypatch, accept=False)
    table = _Table(color_filter=RED)

    FlagTableWidget.setColorFilter(table, use_selected=False)

    assert table.color_filter == RED, (
        "cancelling the picker overwrote the colour filter"
    )
    assert not stub.static_calls
    assert table.tables_created == 0, "a cancelled picker rebuilt the table"


def test_cancelled_picker_does_not_invent_a_filter(qapp, monkeypatch):
    """The one that emptied the list: no filter in, no filter out."""
    stub = _stub_dialog(monkeypatch, accept=False)
    table = _Table(color_filter=None)

    FlagTableWidget.setColorFilter(table, use_selected=False)

    assert table.color_filter is None, (
        f"cancelling the picker set a colour filter of {table.color_filter}; "
        "black here filters the flag list down to black flags, which reads as "
        "an empty list the user never asked for"
    )
    assert not stub.static_calls
    assert table.tables_created == 0


# --- and the accept path still works ---------------------------------------


def test_accepted_picker_sets_the_filter(qapp, monkeypatch):
    _stub_dialog(monkeypatch, accept=True, chosen=BLUE)
    table = _Table(color_filter=RED)

    FlagTableWidget.setColorFilter(table, use_selected=False)

    assert table.color_filter == BLUE
    assert table.tables_created == 1


def test_picker_opens_on_the_current_filter(qapp, monkeypatch):
    """Non-native, parented, and seeded with the filter being changed."""
    stub = _stub_dialog(monkeypatch, accept=True, chosen=BLUE)
    table = _Table(color_filter=RED)

    FlagTableWidget.setColorFilter(table, use_selected=False)

    assert len(stub.execs) == 1
    opened = stub.execs[0]
    assert opened["options"] & QColorDialog.ColorDialogOption.DontUseNativeDialog
    assert opened["parent"] is table
    assert opened["currentColor"] == RED, (
        "the picker did not open on the filter it is editing -- set "
        "DontUseNativeDialog before seeding the colour, not after"
    )
