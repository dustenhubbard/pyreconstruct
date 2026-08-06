"""A section change that fails must leave the field on the section it had.

`FieldWidget.changeSection` reads a section file and opens that section's image.
Both can fail -- most plausibly on Windows, where the section file has just been
rewritten by the save that precedes every jump from an object or trace list and
the OS may not have released it yet.

The field state must not have moved when they do. `paintText` reads
`self.section_layer` on every paint event, so a field left without one is a
field that raises on every repaint, and a repaint is not something a user can
stop asking for: the reported symptom was an unstoppable stream of error windows
and PyReconstruct having to be killed from Task Manager.

    Traceback (most recent call last):
      File "PyReconstruct\\modules\\gui\\main\\field_widget.py", line 154, in event
      File "PyReconstruct\\modules\\gui\\main\\field_widget.py", line 138, in paintEvent
      File "PyReconstruct\\modules\\gui\\main\\field_widget_6_paint.py", line 194, in paintText
    AttributeError: 'NoneType' object has no attribute 'getTrace'

The window was widest on the first section change of a session, because the swap
that opened it traded `section_layer` for `b_section_layer` and that is None
until a first change fills it.
"""
import pytest

from PySide6.QtGui import QPixmap

pytestmark = pytest.mark.gui


def _other_section(field):
    """A section number the field is not currently displaying."""
    return sorted(n for n in field.series.sections if n != field.series.current_section)[0]


def _paint(field):
    """Deliver a real paint event, the way an exposed field gets one."""
    field.render(QPixmap(max(field.width(), 1), max(field.height(), 1)))


def _assert_field_intact(field, section_num):
    """The field is whole and displaying `section_num`."""
    assert field.series.current_section == section_num
    assert field.section is not None and field.section.n == section_num
    assert field.section_layer is not None
    assert field.section_layer.section is field.section


def test_unreadable_section_file_leaves_the_field_paintable(main_window, monkeypatch):
    field = main_window.field
    start = field.series.current_section
    target = _other_section(field)

    def refuse(section_num):
        raise OSError("[WinError 32] The process cannot access the file")

    monkeypatch.setattr(field.series, "loadSection", refuse)

    with pytest.raises(OSError):
        field.changeSection(target)

    _assert_field_intact(field, start)
    _paint(field)   # raised AttributeError from paintText before the fix


def test_unopenable_image_leaves_the_field_paintable(main_window, monkeypatch):
    """The section reads, but building its view fails.

    The second of the two fallible steps, and the reason a bare try/except round
    the load alone would not be enough.
    """
    from PyReconstruct.modules.gui.main import field_widget_1_base

    field = main_window.field
    start = field.series.current_section
    target = _other_section(field)

    def refuse(section, series, **kwargs):
        raise OSError("[WinError 5] Access is denied")

    monkeypatch.setattr(field_widget_1_base, "SectionLayer", refuse)

    with pytest.raises(OSError):
        field.changeSection(target)

    _assert_field_intact(field, start)
    _paint(field)


def test_successful_change_parks_the_old_section_as_b(main_window):
    """The change itself is unaltered: the section left behind becomes B."""
    field = main_window.field
    start = field.section
    start_layer = field.section_layer
    target = _other_section(field)

    field.changeSection(target)

    _assert_field_intact(field, target)
    assert field.b_section is start
    assert field.b_section_layer is start_layer
    _paint(field)


def test_flicker_reuses_the_parked_section_without_reading_it(main_window, monkeypatch):
    """Changing back to the B section swaps; it does not re-read the file.

    This is the fast path the old ordering got for free by swapping first, and
    the one thing the reordering had to keep.
    """
    field = main_window.field
    start = field.section
    start_layer = field.section_layer
    target = _other_section(field)

    field.changeSection(target)
    moved_to = field.section
    moved_to_layer = field.section_layer

    def refuse(section_num):   # pragma: no cover - a call here is the failure
        raise AssertionError("flicker back to the B section re-read it from disk")

    monkeypatch.setattr(field.series, "loadSection", refuse)

    field.changeSection(start.n)

    assert field.section is start
    assert field.section_layer is start_layer
    assert field.b_section is moved_to
    assert field.b_section_layer is moved_to_layer
    _assert_field_intact(field, start.n)
