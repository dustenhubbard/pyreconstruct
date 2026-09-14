"""OK on Series > Options must work on every page it holds.

The dialog calls accept(close=False) and then set() on every page. The
"Hover display columns: Configure..." row was a bare QWidget, so OK raised
AttributeError: 'QWidget' object has no attribute 'accept' and the dialog
could not close (reported from 1.23.0-beta-5 on Windows, September 2026;
present since beta-3). No test pressed OK on the whole dialog, which is how
it lived through two betas. These do.
"""
import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.dialog.hover_columns import HoverColumnsOptionWidget

pytestmark = pytest.mark.gui


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def series(series_jser):
    s = Series.openJser(str(series_jser))
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.close()


def test_every_page_speaks_the_options_protocol(qapp, series):
    dlg = AllOptionsDialog(None, series)
    missing = sorted(
        name for name, page in dlg.all_widgets.items()
        if not (callable(getattr(page, "accept", None)) and callable(getattr(page, "set", None)))
    )
    assert missing == []


def test_ok_on_untouched_options_closes_the_dialog(qapp, series):
    dlg = AllOptionsDialog(None, series)
    assert dlg.accept() is True


def test_hover_columns_wait_for_ok(qapp, series):
    dlg = AllOptionsDialog(None, series)
    page = dlg.all_widgets["hover_columns"]
    assert isinstance(page, HoverColumnsOptionWidget)
    before = series.getOption("hover_columns")

    # the inner dialog's result, as configure() records it
    page.columns = [("name", True), ("length", False)]
    page._changed = True

    # not written yet: Cancel on the outer dialog must still be able to drop it
    assert series.getOption("hover_columns") == before
    assert dlg.accept() is True
    assert series.getOption("hover_columns") == [("name", True), ("length", False)]


def test_an_unopened_configure_writes_nothing(qapp, series):
    dlg = AllOptionsDialog(None, series)
    before = series.getOption("hover_columns")
    assert dlg.accept() is True
    assert series.getOption("hover_columns") == before
