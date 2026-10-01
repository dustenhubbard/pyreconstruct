"""A blank number box in Series > Options is refused, not saved as None.

Clearing a grid box and pressing OK stored `None` in the grid option, and the
grid tool then raised on the next click in the field. Every number box except
the scale bar's fixed length (where blank means "keep the stored length") now
asks for a number before anything is saved.
"""
import pytest

from PySide6.QtWidgets import QLineEdit

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog import quick_dialog
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

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


@pytest.fixture
def notices(monkeypatch):
    said = []
    monkeypatch.setattr(quick_dialog, "notify", lambda *a, **k: said.append(a))
    return said


def test_a_blank_grid_box_is_refused(qapp, series, notices):
    before = list(series.getOption("grid"))
    dlg = AllOptionsDialog(None, series)
    dlg.all_widgets["grid"].inputs[0].widget.setText("")

    assert dlg.accept() is False
    assert notices
    assert list(series.getOption("grid")) == before


@pytest.mark.parametrize("page", [
    "grid", "knife", "smoothing_3D", "show_flags", "fill_opacity", "find_zoom",
    "2D_step", "3D_step",
])
def test_every_number_box_on_the_page_needs_a_number(qapp, series, notices,
                                                     page):
    dlg = AllOptionsDialog(None, series)
    numbers = [
        i for i, field in enumerate(dlg.all_widgets[page].inputs)
        if field.type in ("int", "float")
    ]
    assert numbers
    for i in numbers:
        box = dlg.all_widgets[page].inputs[i].widget
        assert isinstance(box, QLineEdit)
        text = box.text()
        box.setText("")
        assert dlg.all_widgets[page].accept(close=False) is False, (page, i)
        box.setText(text)
    assert dlg.accept() is True


def test_a_blank_fixed_scale_bar_length_is_still_allowed(qapp, series,
                                                         notices):
    before = series.getOption("scale_bar_length_um")
    dlg = AllOptionsDialog(None, series)
    page = dlg.all_widgets["scale_bar"]
    box = next(f.widget for f in page.inputs if f.type == "float")
    box.setText("")

    assert dlg.accept() is True
    assert series.getOption("scale_bar_length_um") == before
