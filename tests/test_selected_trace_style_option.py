"""Series > Options sets how a selected trace is drawn.

The View tab has one radio button per selected trace style, right under the
transparent fill opacity, and under them a Glow Opacity slider (0-50%) that
shows only while the glow style is chosen. Changing either redraws the field
and stores nothing; OK stores them, Cancel redraws from the stored options.
"""
import pytest

from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.backend.view.trace_layer import SELECTED_TRACE_STYLES

pytestmark = pytest.mark.gui


@pytest.fixture
def window(main_window, local_series_settings):
    """The main window, with its series options in memory."""
    local_series_settings(main_window)
    return main_window


def _buttons(dlg):
    return dict(zip(SELECTED_TRACE_STYLES, dlg._styleButtons()))


def _slider(dlg):
    return dlg._glowSlider()


def _glow_page(dlg):
    return dlg.all_widgets["selection_glow_opacity"]


class _Redraws:
    """Count the field redraws a dialog asks for."""

    def __init__(self, field, monkeypatch):
        self.count = 0
        original = field.generateView

        def generateView(*args, **kwargs):
            self.count += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(field, "generateView", generateView)


def test_the_choice_sits_under_the_fill_opacity(qapp, window):
    dlg = AllOptionsDialog(window, window.series)
    buttons = _buttons(dlg)
    assert list(buttons) == ["standard", "outline", "glow"]
    assert buttons["standard"].isChecked()
    assert (_slider(dlg).minimum(), _slider(dlg).maximum()) == (0, 50)
    assert _slider(dlg).value() == 20

    view = dlg.tabs.widget(
        [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())].index("View")
    ).widget()
    pages = [
        view.layout().itemAt(i).layout().itemAt(0).widget()
        for i in range(view.layout().count())
    ]
    at = pages.index(dlg.all_widgets["fill_opacity"])
    assert pages[at + 1] is dlg.all_widgets["selected_trace_style"]
    assert pages[at + 2] is _glow_page(dlg)


def test_the_slider_shows_only_for_the_glow(qapp, window):
    dlg = AllOptionsDialog(window, window.series)
    buttons = _buttons(dlg)
    assert _glow_page(dlg).isHidden()
    buttons["glow"].setChecked(True)
    assert not _glow_page(dlg).isHidden()
    buttons["outline"].setChecked(True)
    assert _glow_page(dlg).isHidden()


def test_a_stored_glow_opens_with_the_slider_shown(qapp, window):
    window.series.setOption("selected_trace_style", "glow")
    dlg = AllOptionsDialog(window, window.series)
    assert _buttons(dlg)["glow"].isChecked()
    assert not _glow_page(dlg).isHidden()


@pytest.mark.parametrize("style", ["outline", "glow"])
def test_a_change_redraws_without_storing(qapp, window, monkeypatch, style):
    series = window.series
    dlg = AllOptionsDialog(window, series)
    redraws = _Redraws(window.field, monkeypatch)

    _buttons(dlg)[style].setChecked(True)
    qapp.processEvents()

    assert redraws.count == 1
    assert window.field.section_layer.selected_style_preview == (style, 20)
    assert series.getOption("selected_trace_style") == "standard"


def test_moving_the_slider_redraws_without_storing(qapp, window, monkeypatch):
    series = window.series
    dlg = AllOptionsDialog(window, series)
    _buttons(dlg)["glow"].setChecked(True)
    redraws = _Redraws(window.field, monkeypatch)

    _slider(dlg).setValue(40)
    qapp.processEvents()

    assert redraws.count == 1
    assert window.field.section_layer.selected_style_preview == ("glow", 40)
    assert series.getOption("selection_glow_opacity") == 20


def test_cancel_redraws_from_the_stored_options(qapp, window, monkeypatch):
    series = window.series
    dlg = AllOptionsDialog(window, series)
    _buttons(dlg)["glow"].setChecked(True)
    _slider(dlg).setValue(45)
    qapp.processEvents()
    redraws = _Redraws(window.field, monkeypatch)

    dlg.reject()
    qapp.processEvents()

    assert redraws.count == 1
    assert window.field.section_layer.selected_style_preview is None
    assert window.field.section_layer._selected_pens is None
    assert series.getOption("selected_trace_style") == "standard"
    assert series.getOption("selection_glow_opacity") == 20


def test_ok_stores_the_choice(qapp, window):
    series = window.series
    dlg = AllOptionsDialog(window, series)
    _buttons(dlg)["glow"].setChecked(True)
    _slider(dlg).setValue(30)

    assert dlg.accept() is True
    window.field.generateView(generate_image=False)   # what allOptions() runs

    assert series.getOption("selected_trace_style") == "glow"
    assert series.getOption("selection_glow_opacity") == 30
    layer = window.field.section_layer
    assert layer.selected_style_preview is None
    assert layer._selected_pens == ((None, 5, 0.3), (None, 2, 1))


def test_reset_defaults_previews_the_default(qapp, window, monkeypatch):
    """Reset Defaults builds new widgets at the defaults; the field must follow them."""
    series = window.series
    series.setOption("selected_trace_style", "glow")
    series.setOption("selection_glow_opacity", 45)
    dlg = AllOptionsDialog(window, series)
    redraws = _Redraws(window.field, monkeypatch)

    dlg.resetDefaults()
    qapp.processEvents()

    assert _buttons(dlg)["standard"].isChecked()
    assert _slider(dlg).value() == 20
    assert _glow_page(dlg).isHidden()
    assert redraws.count == 1
    assert window.field.section_layer.selected_style_preview == ("standard", 20)
    assert window.field.section_layer._selected_pens is None


def test_a_blended_section_previews_too(qapp, window):
    """With blending on, the B section's selected traces follow the choice."""
    series = window.series
    field = window.field
    field.changeSection(next(n for n in series.sections if n != field.section.n))
    field.blend_sections = True
    b_layer = field.b_section_layer
    dlg = AllOptionsDialog(window, series)

    _buttons(dlg)["outline"].setChecked(True)
    qapp.processEvents()

    assert b_layer.selected_style_preview == ("outline", 20)
    assert b_layer._selected_pens[0] == ((0, 0, 0), 6, 1)

    dlg.reject()
    qapp.processEvents()

    assert b_layer.selected_style_preview is None
    assert b_layer._selected_pens is None


def test_a_stored_80_shows_as_50(qapp, window):
    """The slider stops at 50%; a larger stored value is shown as 50%."""
    series = window.series
    series.setOption("selection_glow_opacity", 80)
    dlg = AllOptionsDialog(window, series)
    assert _slider(dlg).value() == 50
    assert series.getOption("selection_glow_opacity") == 80


def test_an_unknown_stored_style_shows_as_standard(qapp, window):
    window.series.setOption("selected_trace_style", "a style from a later version")
    dlg = AllOptionsDialog(window, window.series)
    assert _buttons(dlg)["standard"].isChecked()


def test_a_dialog_with_no_window_behind_it_does_not_mind(qapp, window):
    dlg = AllOptionsDialog(None, window.series)   # tests build it this way
    _buttons(dlg)["glow"].setChecked(True)
    _slider(dlg).setValue(50)
    dlg.reject()                                   # must not raise
