"""The field context menu's "Series alignment" submenu, across a series undo.

The submenu is generated once per `MainWindow.createContextMenus()`, from
`series.alignments`, with one checkbox action per name (`getAlignmentsMenu` in
`gui/utils/utils.py`, which also sets a `<name>_alignment_act` attribute on the
window). Nothing recomputes it afterwards, so any operation that changes the set
of alignment names has to ask for a rebuild.

`Series.modifyAlignments` is such an operation, it is undoable (it takes
`series_states` and enumerates with `breakable=False`), and the series-wide undo
path reloaded the field and recreated the data lists without rebuilding the
menus. The result was a submenu offering an alignment the sections no longer
carried.

Selecting that entry is not a no-op. `MainWindow.changeAlignment` assigns
`series.alignment` and reloads, and `Section.tform` is
`self.tforms[self.series.alignment]`, so the read raises `KeyError`. Measured on
the fixture series before the fix: the `KeyError` surfaces first from
`field.reload() -> generateView -> generateTraceLayer`, and then again from
`FieldWidget.paintEvent -> paintText -> getTrace -> findClosest`, where
`customExcepthook` swallows it and the widget repaints. Qt logs
"QWidget::repaint: Recursive repaint detected" and the window spins raising the
same exception, indefinitely. It is a hang, not a cosmetic stale label.

The undo path is the right place to fix it because both entry points that can
change the alignment set share it, and the forward direction is already covered
at each call site (`MainWindow.modifyAlignments` calls `createContextMenus()`).
"""

import pytest

from PySide6.QtWidgets import QMenu

pytestmark = pytest.mark.gui

SUBMENU_TITLE = "Series alignment"


def submenu_entries(window):
    """The alignment names the field context menu currently offers.

    Found by title rather than by attribute: `getAlignmentsMenu` and
    `return_alignments_menu` both claim the `alignmentsmenu` attribute on the
    window, so the attribute is whichever of the two was built last.
    """
    for menu in window.field_menu.findChildren(QMenu):
        if menu.title() == SUBMENU_TITLE:
            return [action.text() for action in menu.actions()]
    raise AssertionError(f"no {SUBMENU_TITLE!r} submenu in the field menu")


def add_alignment(window, name):
    """Create `name` as a copy of the current alignment, undoably.

    The same two calls `MainWindow.modifyAlignments` makes once the dialog has
    been confirmed: the dict maps every new name to the old name it comes from,
    and every existing name maps to itself.
    """
    alignment_dict = {a: a for a in window.series.alignments}
    alignment_dict[name] = window.series.alignment
    window.series.modifyAlignments(alignment_dict, window.field.series_states)
    window.createContextMenus()


def test_series_undo_drops_the_undone_alignment_from_the_submenu(main_window):
    """Undoing the creation of an alignment removes it from the submenu.

    Driven through `MainWindow.undo()`, the real Ctrl+Z slot, rather than
    through `FieldWidget.seriesUndo` directly: `canUndo` reports
    `(True, False, True)` here (series-wide undo available, no section-only undo
    available), so `undo()` takes its `elif can_3D` branch with no prompt.
    """
    window = main_window
    before = submenu_entries(window)
    assert "undo_probe" not in before

    add_alignment(window, "undo_probe")
    assert "undo_probe" in submenu_entries(window)
    assert "undo_probe" in window.series.alignments

    assert window.field.series_states.canUndo() == (True, False, True)
    window.undo()

    assert "undo_probe" not in window.series.alignments
    assert "undo_probe" not in window.field.section.tforms
    assert submenu_entries(window) == before


def test_series_redo_puts_the_alignment_back_in_the_submenu(main_window):
    """The refresh is not one-directional: redo re-adds the name.

    Same staleness with the signs reversed. Redoing restores the alignment to
    every section, and a submenu that does not list it cannot be used to switch
    to it.
    """
    window = main_window
    add_alignment(window, "redo_probe")
    window.undo()
    assert "redo_probe" not in submenu_entries(window)

    window.undo(True)

    assert "redo_probe" in window.series.alignments
    assert "redo_probe" in submenu_entries(window)


def test_every_alignment_the_submenu_offers_after_an_undo_can_be_selected(
    main_window
):
    """The invariant that matters: nothing offered is unselectable.

    Asserting on the submenu contents alone would pass a fix that rebuilt the
    menu from something other than the sections' own transforms. This selects
    each entry and reads `Section.tform`, which is the exact lookup that raised
    `KeyError` before.
    """
    window = main_window
    add_alignment(window, "selectable_probe")
    window.undo()

    original = window.series.alignment
    try:
        for name in submenu_entries(window):
            window.changeAlignment(name)
            assert window.series.alignment == name
            assert window.field.section.tform is not None
    finally:
        # a failure here leaves `series.alignment` set to a name the sections do
        # not have, and every subsequent paint (including the fixture's own
        # teardown) would raise on it, turning one failure into a hang
        if window.series.alignment not in window.field.section.tforms:
            window.series.alignment = original
            window.field.reload()


def test_selecting_a_stale_submenu_entry_raises(main_window):
    """Why a stale entry is not cosmetic, pinned without relying on undo.

    The staleness is built by hand here (create an alignment, rebuild the menus,
    then drop it from the sections and *do not* rebuild), which is exactly the
    state the series-wide undo used to leave behind. Selecting it then reaches
    `Section.tform` through `field.reload()` and raises.

    Note that a name that never existed raises `AttributeError` earlier, at
    `getattr(self, f"{name}_alignment_act")`. Only a name that once had an action
    gets as far as the transform lookup, which is why the stale case is the one
    worth pinning and why the fix belongs in the undo path rather than in a guard
    inside `changeAlignment` (a guard there would silently swallow a legitimate
    switch).
    """
    window = main_window
    valid = window.series.alignment
    add_alignment(window, "stale_probe")

    alignment_dict = {
        a: a for a in window.series.alignments if a != "stale_probe"
    }
    window.series.modifyAlignments(alignment_dict, window.field.series_states)

    assert "stale_probe" not in window.field.section.tforms
    assert "stale_probe" in submenu_entries(window)

    with pytest.raises(KeyError):
        window.changeAlignment("stale_probe")

    # leave the field renderable: the failed switch had already assigned the
    # name, and every later paint would raise on it
    window.series.alignment = valid
    window.field.reload()


def test_a_series_undo_that_leaves_the_alignments_alone_rebuilds_nothing(
    main_window, monkeypatch
):
    """The rebuild is conditional, and this is the condition.

    `createContextMenus()` recreates the whole field menu (~200 actions) and the
    label menu, and almost no series-wide undo touches the alignments. Hiding
    every trace is a representative one: series-wide, undoable, and irrelevant
    to the alignment names.

    Calls `field.seriesUndo()` rather than `MainWindow.undo()` because this
    operation leaves a section-only undo available too, and `undo()` answers that
    with a `QMessageBox(self).exec()` that offscreen Qt never dismisses. The
    wiring from `undo()` to `seriesUndo()` is pinned by the test below.
    """
    window = main_window
    calls = []
    monkeypatch.setattr(
        window, "createContextMenus", lambda *a, **k: calls.append(1)
    )

    window.series.hideAllTraces(True, series_states=window.field.series_states)
    assert window.field.series_states.canUndo()[0] is True

    window.field.seriesUndo()

    assert calls == []


def test_main_window_undo_routes_the_series_wide_case_through_seriesUndo(
    main_window, monkeypatch
):
    """`MainWindow.undo`'s series-wide branch calls `FieldWidget.seriesUndo`.

    It used to inline the same three statements, leaving `seriesUndo` with no
    callers at all, which is why a refresh added to `seriesUndo` alone would not
    have reached the user. Pinning the wiring keeps the two from drifting apart
    again.
    """
    window = main_window
    calls = []
    monkeypatch.setattr(
        window.field, "seriesUndo", lambda redo=False: calls.append(redo)
    )

    add_alignment(window, "wiring_probe")
    assert window.field.series_states.canUndo() == (True, False, True)

    window.undo()

    assert calls == [False]
