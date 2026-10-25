"""In a short window the right-side palette groups keep clear of each other.

The tool column, the brightness/contrast sliders and the section buttons all
default to the field's right edge, stacked top to bottom. In a short window
the column reached down into the other two: the sliders lay over the last
tools, and the section buttons covered the bottom of the column, so clicks
there went to the wrong widget. A group at its default spot now moves left
of the column when it would touch it. Field sizes are the ones measured on
macOS for 1280 x 720 and 1280 x 668 windows.
"""
import pytest
from PySide6.QtCore import QRect

from PyReconstruct.modules.gui.palette import mouse_palette as mp

pytestmark = pytest.mark.gui


def _united(widgets):
    rect = QRect()
    for w in widgets:
        rect = rect.united(w.geometry())
    return rect


def _groups(palette):
    tools = _united([b for b, _, _ in palette.mode_buttons.values()])
    sliders = _united([w for pair in palette.bc_widgets for w in pair])
    section = _united(palette.inc_buttons)
    return tools, sliders, section


@pytest.fixture
def palette(main_window, monkeypatch):
    """The palette at its default positions, nothing saved."""
    monkeypatch.setattr(mp, "load_palette_positions", lambda settings: {})
    main_window.mouse_palette.reset()
    return main_window.mouse_palette


def _fit(main_window, palette, width, height):
    main_window.field.setGeometry(0, 30, width, height)
    palette.resize()


@pytest.mark.parametrize("height", [662, 610])
def test_short_window_groups_do_not_overlap(main_window, palette, height):
    _fit(main_window, palette, 1280, height)
    tools, sliders, section = _groups(palette)
    assert not tools.intersects(sliders), (tools, sliders)
    assert not tools.intersects(section), (tools, section)
    assert not sliders.intersects(section), (sliders, section)
    # and all of it is still inside the field
    field = main_window.field.geometry()
    for rect in (tools, sliders, section):
        assert field.contains(rect), (field, rect)


def test_tall_window_keeps_the_default_layout(main_window, palette):
    _fit(main_window, palette, 1920, 1022)
    _, sliders, section = _groups(palette)
    # the plain fraction of the bounds, as before: the field's right edge
    for group, rect in (("bc", sliders), ("inc", section)):
        x1, x2, _, _ = palette.getBounds()[group]
        assert rect.x() == int(0.99 * (x2 - x1) + x1), group


def test_a_dragged_group_stays_where_it_was_put(main_window, palette):
    _fit(main_window, palette, 1280, 662)
    # dragged to just under its default spot, still against the column
    palette.bc_y = 0.79
    palette.resize()
    x1, x2, _, _ = palette.getBounds()["bc"]
    _, sliders, _ = _groups(palette)
    assert sliders.x() == int(0.99 * (x2 - x1) + x1)


def test_a_drag_starts_from_where_the_group_is_drawn(main_window, palette):
    _fit(main_window, palette, 1280, 662)
    _, before, _ = _groups(palette)
    palette.moveButton(0, 0, "bc")   # a press that has not moved yet
    palette.resize()
    _, after, _ = _groups(palette)
    assert abs(after.x() - before.x()) <= 1, (before, after)
    assert abs(after.y() - before.y()) <= 1, (before, after)
