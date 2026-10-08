"""Series > Options sets how see-through the highlight around a selected trace is.

The slider sits on the View tab right under the transparent fill opacity, runs
0-50% and starts at the stored `selection_highlight_opacity`. Moving it redraws
the field with the new highlight and stores nothing; OK stores it, Cancel puts the
field back to the stored value.
"""
import pytest

from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

pytestmark = pytest.mark.gui


def _field(dlg):
    return dlg.all_widgets["selection_highlight_opacity"].inputs[0]


def _slider(dlg):
    return _field(dlg).widget.slider


class _Redraws:
    """Count the field redraws a dialog asks for."""

    def __init__(self, field, monkeypatch):
        self.count = 0
        original = field.generateView

        def generateView(*args, **kwargs):
            self.count += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(field, "generateView", generateView)


def test_the_slider_sits_under_the_fill_opacity(qapp, main_window):
    dlg = AllOptionsDialog(main_window, main_window.series)
    field = _field(dlg)
    assert field.type == "slider"
    assert (_slider(dlg).minimum(), _slider(dlg).maximum()) == (0, 50)
    assert _slider(dlg).tickInterval() == 10
    assert _slider(dlg).value() == main_window.series.getOption("selection_highlight_opacity")

    view = dlg.tabs.widget(
        [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())].index("View")
    ).widget()
    pages = [
        view.layout().itemAt(i).layout().itemAt(0).widget()
        for i in range(view.layout().count())
    ]
    at = pages.index(dlg.all_widgets["fill_opacity"])
    assert pages[at + 1] is dlg.all_widgets["selection_highlight_opacity"]


def test_moving_the_slider_redraws_without_storing(qapp, main_window, monkeypatch):
    series = main_window.series
    stored = series.getOption("selection_highlight_opacity")
    target = 40 if stored != 40 else 10
    dlg = AllOptionsDialog(main_window, series)
    redraws = _Redraws(main_window.field, monkeypatch)

    _slider(dlg).setValue(target)
    qapp.processEvents()

    assert redraws.count >= 1
    assert main_window.field.section_layer.highlight_opacity_preview == target
    assert main_window.field.section_layer._highlight_opacity == pytest.approx(target / 100)
    assert series.getOption("selection_highlight_opacity") == stored


def test_cancel_redraws_with_the_stored_value(qapp, main_window, monkeypatch):
    series = main_window.series
    stored = series.getOption("selection_highlight_opacity")
    dlg = AllOptionsDialog(main_window, series)
    _slider(dlg).setValue(45 if stored != 45 else 10)
    qapp.processEvents()
    redraws = _Redraws(main_window.field, monkeypatch)

    dlg.reject()
    qapp.processEvents()

    assert redraws.count == 1
    assert main_window.field.section_layer.highlight_opacity_preview is None
    assert main_window.field.section_layer._highlight_opacity == pytest.approx(stored / 100)
    assert series.getOption("selection_highlight_opacity") == stored


def test_ok_stores_the_value(qapp, main_window):
    series = main_window.series
    stored = series.getOption("selection_highlight_opacity")
    target = 25 if stored != 25 else 35
    dlg = AllOptionsDialog(main_window, series)
    _slider(dlg).setValue(target)

    assert dlg.accept() is True
    main_window.field.generateView(generate_image=False)   # what allOptions() runs

    assert series.getOption("selection_highlight_opacity") == target
    assert main_window.field.section_layer.highlight_opacity_preview is None
    assert main_window.field.section_layer._highlight_opacity == pytest.approx(target / 100)


def test_reset_defaults_puts_the_slider_at_20(qapp, main_window):
    series = main_window.series
    series.setOption("selection_highlight_opacity", 45)
    dlg = AllOptionsDialog(main_window, series)
    assert _slider(dlg).value() == 45

    dlg.resetDefaults()

    assert _slider(dlg).value() == 20


def test_reset_defaults_previews_the_default(qapp, main_window, monkeypatch):
    """Reset Defaults builds a new slider at 20%; the field must follow it."""
    series = main_window.series
    series.setOption("selection_highlight_opacity", 20)
    dlg = AllOptionsDialog(main_window, series)
    _slider(dlg).setValue(40)
    qapp.processEvents()
    redraws = _Redraws(main_window.field, monkeypatch)

    dlg.resetDefaults()
    qapp.processEvents()

    assert _slider(dlg).value() == 20
    assert redraws.count >= 1
    assert main_window.field.section_layer.highlight_opacity_preview == 20
    assert main_window.field.section_layer._highlight_opacity == pytest.approx(0.2)


def test_a_blended_section_previews_too(qapp, main_window):
    """With blending on, the B section's selected traces follow the slider."""
    series = main_window.series
    field = main_window.field
    stored = series.getOption("selection_highlight_opacity")
    target = 0 if stored != 0 else 30
    field.changeSection(next(n for n in series.sections if n != field.section.n))
    field.blend_sections = True
    b_layer = field.b_section_layer
    dlg = AllOptionsDialog(main_window, series)

    _slider(dlg).setValue(target)
    qapp.processEvents()

    assert b_layer.highlight_opacity_preview == target
    assert b_layer._highlight_opacity == pytest.approx(target / 100)

    dlg.reject()
    qapp.processEvents()

    assert b_layer.highlight_opacity_preview is None
    assert b_layer._highlight_opacity == pytest.approx(stored / 100)


def test_a_stored_80_shows_and_draws_as_50(qapp, main_window):
    """The slider stops at 50%; a larger stored value is shown and drawn as 50%."""
    series = main_window.series
    series.setOption("selection_highlight_opacity", 80)
    main_window.field.generateView(generate_image=False)

    assert main_window.field.section_layer._highlight_opacity == pytest.approx(0.5)

    dlg = AllOptionsDialog(main_window, series)
    assert _slider(dlg).value() == 50
    assert _field(dlg).widget.text() == "50%"
    assert series.getOption("selection_highlight_opacity") == 80


def test_a_dialog_with_no_window_behind_it_does_not_mind(qapp, main_window):
    dlg = AllOptionsDialog(None, main_window.series)   # tests build it this way
    _slider(dlg).setValue(50)
    dlg.reject()                                        # must not raise
