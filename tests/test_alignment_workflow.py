"""Section navigation, shortcut remapping, and feedback during list building."""

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QProgressDialog

from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.dialog import ShortcutsDialog

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("locked", [False, True])
def test_navigation_propagates_once_and_is_undoable(main_window, cached, locked):
    field = main_window.field
    start = field.section.n
    target = next(n for n in field.series.sections if n != start)
    section = field.series.loadSection(target)
    section.align_locked = locked
    before = Transform([2, 0, 3, 0, 2, 4])
    section.tform = before
    section.save()
    if cached:
        field.changeSection(target)
        field.changeSection(start)
    field.setPropagationMode(True)
    delta = Transform([1, 0, 5, 0, 1, 7])
    field.stored_tform = delta.copy()

    field.changeSection(target)

    expected = before if locked else delta * before
    assert field.section.tform.equals(expected)
    assert field.stored_tform.equals(delta)
    assert (target in field.propagated_sections) is not locked
    field.changeSection(start)
    main_window.flickerSections()
    assert field.section.tform.equals(expected)
    if not locked:
        field.undoState()
        assert field.section.tform.equals(before)
        field.undoState(redo=True)
        assert field.section.tform.equals(expected)


def test_correlation_shortcut_can_be_remapped(main_window, local_series_settings):
    series = local_series_settings(main_window)
    dialog = ShortcutsDialog(main_window, series)
    try:
        assert "aligncorrelation_act" in dialog.act_widgets
        assert dialog.act_widgets["aligncorrelation_act"].keySequence() == QKeySequence("Ctrl+\\")
        main_window.resetShortcuts({"aligncorrelation_act": "Ctrl+Alt+F9"})
        main_window.createMenuBar()
        assert main_window.aligncorrelation_act.shortcut() == QKeySequence("Ctrl+Alt+F9")
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("fail", [False, True])
def test_section_list_progress_starts_before_filtering_and_closes(section_table, monkeypatch, fail):
    widget = section_table
    bars = []
    values = []
    original_filtered = widget.getFiltered
    original_row = widget.setRow

    def filtered():
        visible = [bar for bar in widget.mainwindow.findChildren(QProgressDialog) if bar.isVisible()]
        assert len(visible) == 1, "list preparation must already have visible feedback"
        bars.extend(visible)
        assert bars[0].value() == 0
        if fail:
            raise ValueError("list preparation failed")
        return original_filtered()

    def row(*args, **kwargs):
        values.append(bars[0].value())
        assert bars[0].isVisible()
        return original_row(*args, **kwargs)

    monkeypatch.setattr(widget, "getFiltered", filtered)
    monkeypatch.setattr(widget, "setRow", row)
    if fail:
        with pytest.raises(ValueError, match="list preparation failed"):
            widget.createTable()
    else:
        widget.createTable()
        assert values == sorted(values)
        assert max(values) > 0
    assert bars and not bars[0].isVisible()
