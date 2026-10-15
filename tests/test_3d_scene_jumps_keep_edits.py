"""Edits survive any run of 3D-scene jumps and a save.

A double-click on an object in the 3D scene moves the field with
`FieldWidget.moveTo`. That called the field's own `changeSection`, which keeps
one section besides the one on screen (the B, flickered-away, section) and
drops the older of the two when it loads a third. Paging goes through
`MainWindow.changeSection`, which saves both before the field moves; the jump
did not, so the section two jumps back went out of memory with its edits
unsaved, and the next save never saw them.

Driven against a real `MainWindow` and `FieldWidget` over a writable copy of
the fixture series. Each sequence draws a trace on some sections and jumps
between others, then saves, and every drawn trace must be on disk.
"""
import pytest

from PyReconstruct.modules.datatypes import Trace

pytestmark = pytest.mark.gui

NAME = "jump_keeps_edits"
SQUARE = [(100, 300), (200, 300), (200, 200), (100, 200)]

# "draw" draws on the section on screen; an int is a jump to the nth section
# that is not the one the window opens on
SEQUENCES = {
    "draw_jump_jump": ["draw", 0, 1],
    "jump_draw_jump": [0, "draw", 1],
    "jump_draw_jump_jump": [0, "draw", 1, 2],
    "draw_on_every_stop": ["draw", 0, "draw", 1, "draw", 2, "draw", 3],
    "back_to_a_section_drawn_on": ["draw", 0, "draw", 1, 2, 0, "draw", 3],
}


def _draw(field):
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(SQUARE, field.tracing_trace, closed=True)


def _count(section):
    return len(section.contours.get(NAME, []))


@pytest.mark.parametrize("steps", SEQUENCES.values(), ids=SEQUENCES.keys())
def test_3d_jumps_then_save_keep_every_edit(main_window, steps):
    field, series = main_window.field, main_window.series
    start = series.current_section
    others = [n for n in sorted(series.sections) if n != start]

    drawn = {}
    for step in steps:
        if step == "draw":
            _draw(field)
            drawn[field.section.n] = drawn.get(field.section.n, 0) + 1
        else:
            # the double-click in custom_plotter.leftButtonClickEvent
            field.moveTo(others[step], 0, 0)
            assert field.section.n == others[step]

    main_window.saveAllData()

    on_disk = {n: _count(series.loadSection(n)) for n in drawn}
    assert on_disk == drawn
