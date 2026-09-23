"""Series > Options opens as a proper window: big, zoomable, with a Colors tab.

His asks from the click test (2026-09-14): a larger default size, the
autoseg colors page on its own Colors tab, and the maximize and minimize
buttons in the title bar.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog, DEFAULT_SIZE

pytestmark = pytest.mark.gui


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def series(series_jser):
    s = Series.openJser(str(series_jser))
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.close()


def _tabs(dlg):
    (tabs,) = dlg.findChildren(QTabWidget)
    return tabs


def test_the_colors_page_has_its_own_tab(qapp, series):
    dlg = AllOptionsDialog(None, series)
    tabs = _tabs(dlg)
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert "Colors" in labels
    page = dlg.all_widgets["autoseg_colors"]
    colors_tab = tabs.widget(labels.index("Colors"))
    view_tab = tabs.widget(labels.index("View"))
    assert colors_tab.isAncestorOf(page)
    assert not view_tab.isAncestorOf(page)


def test_title_bar_offers_maximize_and_minimize(qapp, series):
    dlg = AllOptionsDialog(None, series)
    flags = dlg.windowFlags()
    assert flags & Qt.WindowType.WindowMaximizeButtonHint
    assert flags & Qt.WindowType.WindowMinimizeButtonHint


def test_opens_large_but_inside_the_screen(qapp, series):
    dlg = AllOptionsDialog(None, series)
    avail = QApplication.primaryScreen().availableGeometry()
    assert dlg.width() == min(DEFAULT_SIZE[0], int(avail.width() * 0.75))
    assert dlg.height() == min(DEFAULT_SIZE[1], int(avail.height() * 0.85))
    assert dlg.width() <= avail.width() and dlg.height() <= avail.height()
