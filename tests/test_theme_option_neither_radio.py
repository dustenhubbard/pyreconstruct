"""Regression: the Options-dialog theme setter must not crash when the stored
theme is neither "default" nor "qdark" (both radios unselected).

``theme`` is a global QSettings-backed option shared across series, so a value
written by some other build (e.g. a named theme the 1.20.x dialog doesn't know)
leaves both radios unchecked. The setter bound ``theme`` only inside if/elif,
so ``accept()`` -> ``set()`` raised ``UnboundLocalError`` and took down the
whole dialog. The fix seeds ``theme`` with the current value first.

The real setter is a closure created in ``createWidgets``; the only handle on it
is the constructed dialog's theme widget, so the dialog is built against a real
fixture series, then its ``series`` is swapped for a stub to keep the assertion
hermetic (no QSettings writes to disk).
"""
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


class _ThemeStub:
    """A minimal series exposing just the theme get/set the closure calls."""

    def __init__(self, current):
        self._theme = current
        self.writes = []

    def getOption(self, name, *a, **k):
        assert name == "theme"
        return self._theme

    def setOption(self, name, value):
        assert name == "theme"
        self.writes.append(value)
        self._theme = value


def _theme_widget(qapp, tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    dlg = AllOptionsDialog(None, series)
    return dlg, dlg.all_widgets["theme"]


def test_neither_radio_selected_preserves_current_theme(qapp, tmp_path):
    dlg, w = _theme_widget(qapp, tmp_path)
    try:
        dlg.series = _ThemeStub("studio")     # a theme the dialog doesn't know
        w.responses = ([("default", False), ("dark", False)],)  # neither radio on
        w.set()                                # must not raise UnboundLocalError
        assert dlg.series.writes == ["studio"]  # current theme kept, not clobbered
    finally:
        dlg.deleteLater()


def test_selecting_a_radio_still_sets_that_theme(qapp, tmp_path):
    """Guard the fix didn't shadow the normal path."""
    dlg, w = _theme_widget(qapp, tmp_path)
    try:
        dlg.series = _ThemeStub("default")
        w.responses = ([("default", False), ("dark", True)],)   # dark selected
        w.set()
        assert dlg.series.writes == ["qdark"]
    finally:
        dlg.deleteLater()
