"""Series > Options fits its contents and keeps every tab reachable."""
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

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


@pytest.mark.parametrize("screen_size", [(1366, 768), (1920, 1080)])
def test_opens_at_content_width_with_every_tab_usable(qtbot, series, monkeypatch, screen_size):
    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, *screen_size)

    monkeypatch.setattr(QApplication, "primaryScreen", lambda: Screen())
    dlg = AllOptionsDialog(None, series)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.wait(1)
    assert dlg.width() < 900
    assert dlg.height() <= int(screen_size[1] * 0.85)
    width = dlg.width()
    for i in range(dlg.tabs.count()):
        dlg.tabs.setCurrentIndex(i)
        qtbot.wait(1)
        page = dlg.tabs.widget(i)
        assert page.horizontalScrollBar().maximum() == 0, dlg.tabs.tabText(i)
        bar = page.verticalScrollBar()
        bar.setValue(bar.maximum())
        bottom = page.widget().mapTo(page.viewport(), page.widget().rect().bottomLeft())
        assert bottom.y() < page.viewport().height()
        assert dlg.width() == width


def test_a_scrollbar_wider_than_the_style_extent_still_fits(qtbot, qapp, series, monkeypatch):
    # The bar can be wider than PM_ScrollBarExtent, as on macOS. A style sheet does that everywhere.
    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, 1920, 1080)

    monkeypatch.setattr(QApplication, "primaryScreen", lambda: Screen())
    old_sheet = qapp.styleSheet()
    qapp.setStyleSheet("QScrollBar:vertical { width: 40px; }")
    try:
        dlg = AllOptionsDialog(None, series)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.wait(1)
        for i in range(dlg.tabs.count()):
            dlg.tabs.setCurrentIndex(i)
            qtbot.wait(1)
            page = dlg.tabs.widget(i)
            assert page.verticalScrollBar().sizeHint().width() == 40
            assert page.horizontalScrollBar().maximum() == 0, dlg.tabs.tabText(i)
    finally:
        qapp.setStyleSheet(old_sheet)


def test_small_screen_keeps_content_accessible_by_scrolling(qtbot, series, monkeypatch):
    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, 640, 480)

    monkeypatch.setattr(QApplication, "primaryScreen", lambda: Screen())
    dlg = AllOptionsDialog(None, series)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.wait(1)
    assert dlg.width() <= 480
    assert dlg.height() <= 408
    for i in range(dlg.tabs.count()):
        dlg.tabs.setCurrentIndex(i)
        qtbot.wait(1)
        page = dlg.tabs.widget(i)
        for bar in (page.horizontalScrollBar(), page.verticalScrollBar()):
            bar.setValue(bar.maximum())
        corner = page.widget().mapTo(page.viewport(), page.widget().rect().bottomRight())
        assert corner.x() < page.viewport().width()
        assert corner.y() < page.viewport().height()
