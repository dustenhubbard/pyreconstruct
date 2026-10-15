"""A section's brightness and contrast survive being shown.

The palette's sliders run on a square-root scale: a slider at `s` means a
value of `round((s/100) ** 2 * 100)`. `MousePalette.updateBC` puts the slider
where the section's value says, and the slider's `valueChanged` is wired to
`setBrightness`/`setContrast`. So when the slider had to move, the refresh
came back as an edit, squared and rounded: a section at 99 was shown with the
slider at 99, and the slider wrote back 98. Many values do not survive that
trip (33, 70, 99 and their negatives among them), and paging to a section, a
jump from the 3D scene, or one press of a brightness key could each rewrite
them. The next save put the changed value in the file.

Driven against a real `MainWindow` and its real sliders over a writable copy
of the fixture series.
"""
import pytest

pytestmark = pytest.mark.gui

# (brightness, contrast); most of these change under a square and a round
VALUES = [(99, 99), (-99, 33), (70, -47), (98, 50), (0, 99)]


def _set_on_disk(series, n, b, c):
    section = series.loadSection(n)
    section.brightness = b
    section.contrast = c
    section.save()


def _bc(section):
    return section.brightness, section.contrast


@pytest.mark.parametrize("route", ["3d_jump", "page"])
@pytest.mark.parametrize("bc", VALUES, ids=[f"{b}_{c}" for b, c in VALUES])
def test_showing_a_section_then_saving_keeps_its_bc(main_window, route, bc):
    field, series = main_window.field, main_window.series
    start = series.current_section
    dest = next(n for n in sorted(series.sections) if n != start)
    _set_on_disk(series, dest, *bc)
    # the sliders start where the section on screen puts them
    assert _bc(field.section) == (0, 0)

    if route == "3d_jump":
        # the double-click in custom_plotter.leftButtonClickEvent
        field.moveTo(dest, 0, 0)
    else:
        main_window.changeSection(dest)
    assert field.section.n == dest

    assert _bc(field.section) == bc
    main_window.saveAllData()
    assert _bc(series.loadSection(dest)) == bc


def test_a_brightness_key_lands_on_the_next_value(main_window):
    field = main_window.field
    field.setBrightness(34)
    main_window.editImage("brightness", "down")
    assert field.section.brightness == 33


def test_dragging_a_slider_still_sets_the_value(main_window):
    field, palette = main_window.field, main_window.mouse_palette
    (_, b_slider), (_, c_slider) = palette.bc_widgets

    b_slider.setValue(70)
    c_slider.setValue(-50)

    assert _bc(field.section) == (49, -25)
