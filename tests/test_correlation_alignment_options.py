"""Alignment refusal and cutoff options through real Qt widgets."""
import numpy as np
import pytest
from scipy.ndimage import shift
from PIL import Image

from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.dialog import all_options
from PyReconstruct.modules.gui.main import field_widget_4_data as fw

from test_correlate_masked import ambiguous_pattern, tissue

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def isolated_options(main_window, local_series_settings):
    local_series_settings(main_window)


def prepare_field(main_window, monkeypatch, current, previous):
    field = main_window.field
    start = field.section.n
    other = next(n for n in sorted(field.series.sections) if n != start)
    field.changeSection(other)
    field.changeSection(start)
    field.section.align_locked = False
    field.section.tform = Transform([1, 0, 3, 0, 1, 4])
    field.saveState()
    field.propagate_tform = True
    field.stored_tform = Transform.identity()
    monkeypatch.setattr(field.section_layer, "generateImageArray",
                        lambda *args, **kwargs: current)
    monkeypatch.setattr(field.b_section_layer, "generateImageArray",
                        lambda *args, **kwargs: previous)
    messages = []
    monkeypatch.setattr(fw, "notify", messages.append)
    return field, messages


def test_weak_match_leaves_transform_history_and_propagation_unchanged(
    main_window, monkeypatch,
):
    field, messages = prepare_field(main_window, monkeypatch, tissue(1), tissue(2))
    before = field.section.tform.copy()
    states = field.series_states[field.section.n]
    undo_count = len(states.undo_states)
    field.corrAlign()
    assert field.section.tform.equals(before)
    assert field.stored_tform.equals(Transform.identity())
    assert len(states.undo_states) == undo_count
    assert messages == ["No reliable correlation match. The section was not moved."]


def test_masked_alignment_uses_options_and_can_be_undone(main_window, monkeypatch):
    previous = tissue()
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    previous[:, 20:40] = 20
    current[:, 48:68] = 20
    previous[15:30] = 220
    current[45:60] = 220
    field, messages = prepare_field(main_window, monkeypatch, current, previous)
    field.series.setOption("correlation_dark_cutoff", 25)
    field.series.setOption("correlation_bright_cutoff", 215)
    before = field.section.tform.copy()
    dx = 7 / field.scaling * field.section.mag
    dy = 4 / field.scaling * field.section.mag
    field.corrAlign()
    expected = before * Transform([1, 0, dx, 0, 1, dy])
    assert field.section.tform.equals(expected)
    assert field.stored_tform.equals(Transform([1, 0, dx, 0, 1, dy]))
    assert not messages
    field.undoState()
    assert field.section.tform.equals(before)


def test_cutoff_options_save_cancel_and_reset(main_window, qtbot):
    series = main_window.series
    dialog = all_options.AllOptionsDialog(main_window, series)
    qtbot.addWidget(dialog)
    inputs = dialog.all_widgets["correlation_alignment"].inputs
    assert [item.widget.text() for item in inputs] == ["5", "250"]
    inputs[0].widget.setText("25")
    inputs[1].widget.setText("215")
    assert dialog.accept()
    assert series.getOption("correlation_dark_cutoff") == 25
    assert series.getOption("correlation_bright_cutoff") == 215

    dialog = all_options.AllOptionsDialog(main_window, series)
    qtbot.addWidget(dialog)
    assert [item.widget.text() for item in
            dialog.all_widgets["correlation_alignment"].inputs] == ["25", "215"]
    dialog.resetDefaults()
    assert [item.widget.text() for item in
            dialog.all_widgets["correlation_alignment"].inputs] == ["5", "250"]
    dialog.reject()
    assert series.getOption("correlation_dark_cutoff") == 25
    assert series.getOption("correlation_bright_cutoff") == 215


@pytest.mark.parametrize("dark,bright", [("200", "50"), ("100", "100")])
def test_cutoff_options_refuse_reversed_or_equal_limits(
    main_window, qtbot, monkeypatch, dark, bright,
):
    series = main_window.series
    messages = []
    monkeypatch.setattr(all_options, "notify", messages.append)
    dialog = all_options.AllOptionsDialog(main_window, series)
    qtbot.addWidget(dialog)
    inputs = dialog.all_widgets["correlation_alignment"].inputs
    inputs[0].widget.setText(dark)
    inputs[1].widget.setText(bright)
    assert dialog.accept() is False
    assert series.getOption("correlation_dark_cutoff") == 5
    assert series.getOption("correlation_bright_cutoff") == 250
    assert messages == ["The dark cutoff must be lower than the bright cutoff."]


def test_alignment_ignores_display_brightness_and_contrast(
    main_window, monkeypatch, tmp_path,
):
    field = main_window.field
    series = field.series
    previous = tissue()
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    Image.fromarray(previous).save(tmp_path / "previous.png")
    Image.fromarray(current).save(tmp_path / "current.png")
    series.src_dir = str(tmp_path)
    current_n = field.section.n
    previous_n = next(n for n in sorted(series.sections) if n != current_n)
    for number, name, brightness in [
        (current_n, "current.png", 100), (previous_n, "previous.png", -100),
    ]:
        section = series.loadSection(number)
        section.src = name
        section.mag = 1
        section.align_locked = False
        section.tform = Transform.identity()
        section.brightness = brightness
        section.contrast = 100
        section.save()
    field.reload()
    field.changeSection(previous_n)
    field.changeSection(current_n)
    field.reloadImage()
    assert field.section_layer.image_found
    assert field.b_section_layer.image_found
    series.window = [0, 0, 96, 80]
    field.pixmap_dim = (96, 80)
    field.scaling = 1
    messages = []
    monkeypatch.setattr(fw, "notify", messages.append)
    field.corrAlign()
    assert not messages
    assert field.section.tform.equals(Transform([1, 0, 7, 0, 1, 4]))


@pytest.mark.parametrize("pattern", ["gradient", "stripes", "tiles"])
def test_ambiguous_match_leaves_transform_history_and_propagation_unchanged(
    main_window, monkeypatch, pattern,
):
    image = np.repeat(ambiguous_pattern(pattern)[:, :, None], 3, axis=2)
    field, messages = prepare_field(main_window, monkeypatch, image, image)
    # Preserve an existing recorded translation as well as the section state.
    field.stored_tform = Transform([1, 0, 2, 0, 1, -3])
    before = field.section.tform.copy()
    states = field.series_states[field.section.n]
    undo_count = len(states.undo_states)
    propagated = field.propagated_sections.copy()
    field.corrAlign()
    assert field.section.tform.equals(before)
    assert field.stored_tform.equals(Transform([1, 0, 2, 0, 1, -3]))
    assert len(states.undo_states) == undo_count
    assert field.propagated_sections == propagated
    assert messages == ["No reliable correlation match. The section was not moved."]
