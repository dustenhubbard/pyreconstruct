"""`MainWindow.undo()` through the linked-undo prompt, headlessly.

`undo()` has a three-way branch it takes when `SeriesStates.canUndo()` reports
`(True, True, True)`: a series-wide undo is available, a section-only undo is
available, and the two are linked because the current section's undo state was
recorded as part of the series state. Only the user knows which they meant, so
the branch asks: "All sections", "Only this section", or "Cancel".

The prompt was a `QMessageBox(self)` constructed inside the method. Offscreen
that is a permanent stall, not a slow dialog, and it is the one dialog shape
`main_window_dialogs` could not reach: the fixture rebinds the module-level
names `main_window.py` imported and replaces the `QMessageBox` statics, and an
instance built inside a method is neither. So no `gui` test could call `undo()`
for any operation that also left a section-only undo. Deleting an object is
such an operation, and so is every other series-wide edit that touches the
section the user is looking at, which is most of them.

The prompt is now `linkedUndoNotify` in `gui/utils/utils.py`, guarded by
`user_is_present()` like `saveNotify` and `unsavedNotify` beside it, and the
fixture scripts it through `recorder.linked_undo_responses`.

The tests below reach the branch the same way the user does: select an object's
traces on the current section and delete the object from the series. Measured
on the fixture series, that one action leaves `canUndo() == (True, True, True)`,
which the tests assert as a precondition so that a future change to the state
manager fails here loudly rather than quietly stopping the tests from covering
anything.
"""

import pytest

pytestmark = pytest.mark.gui

# An object in the fixture series with traces on 182 of its 198 sections,
# including the section the window opens on.
OBJECT = "d03"


@pytest.fixture
def window(main_window):
    """`main_window` with the progress dialog swapped for a no-op reporter.

    `Series.deleteObjects` and `SeriesStates.undoState` both call
    `enumerateSections`, which builds a `QtProgressReporter` wrapping a real
    `QProgressDialog`. Patching `mw.getProgbar` (what `main_window_dialogs`
    does) does not reach it, because `QtProgressReporter` imports `getProgbar`
    itself. `Series.setProgressReporter` is the seam the data model exposes for
    exactly this.
    """
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def sections_carrying(series, name):
    """The numbers of the sections that hold at least one trace of `name`."""
    return [
        snum
        for snum, section in series.enumerateSections(show_progress=False)
        if name in section.contours and len(section.contours[name])
    ]


def delete_object_from_series(window):
    """Do what the user does: select the object, then "Delete" it.

    `FieldWidget.deleteObjects` is wrapped by `object_function`, which reads the
    names off the focused object list or, with no list focused, off
    `section.selected_traces`. Selecting the traces is therefore the whole of
    the input; the field menu's Delete entry is bound straight to this method.
    """
    section = window.field.section
    section.selected_traces = list(section.contours[OBJECT])
    window.field.deleteObjects()


def assert_prompt_reached(window):
    """Assert the state that makes `undo()` take the linked branch."""
    can_3D, can_2D, linked = window.field.series_states.canUndo()
    assert (can_3D, can_2D, linked) == (True, True, True), (
        "deleting an object no longer leaves both a series undo and a linked "
        f"section-only undo (canUndo returned {(can_3D, can_2D, linked)}), so "
        "this test is no longer exercising the linked-undo prompt"
    )


def test_undo_all_sections_restores_the_object_everywhere(
    window, main_window_dialogs
):
    """Answering "All sections" undoes the delete across the whole series."""
    before = sections_carrying(window.series, OBJECT)
    assert len(before) > 1, "fixture object must span more than one section"

    delete_object_from_series(window)
    assert sections_carrying(window.series, OBJECT) == []
    assert_prompt_reached(window)

    main_window_dialogs.linked_undo_responses.append("all")

    window.undo()

    assert main_window_dialogs.linked_undo_prompts == 1, (
        "undo() did not reach the linked-undo prompt"
    )
    assert sections_carrying(window.series, OBJECT) == before
    assert window.field.series_states.canUndo()[0] is False


def test_undo_only_this_section_leaves_the_other_sections_deleted(
    window, main_window_dialogs
):
    """Answering "Only this section" undoes the delete on one section alone.

    This is the answer the whole prompt exists for, and the one no headless
    test could reach before: the offscreen fallback in `linkedUndoNotify`
    returns "all", so a guard on its own would never exercise it. The scripted
    queue is what makes it reachable.
    """
    current = window.series.current_section
    before = sections_carrying(window.series, OBJECT)
    assert current in before, "the fixture object must be on the open section"

    delete_object_from_series(window)
    assert sections_carrying(window.series, OBJECT) == []
    assert_prompt_reached(window)

    main_window_dialogs.linked_undo_responses.append("section")

    window.undo()

    assert main_window_dialogs.linked_undo_prompts == 1

    # `act2D` restores the open section in memory and marks the series dirty;
    # it does not write. Saving is what the user's next section change or Ctrl+S
    # does, and measuring after it is what distinguishes "restored here" from
    # "restored nowhere".
    assert len(window.field.section.contours[OBJECT]) > 0, (
        "the section-only undo did not restore the object on the open section"
    )
    window.saveAllData()
    assert sections_carrying(window.series, OBJECT) == [current], (
        "a section-only undo restored traces on sections other than the open "
        "one"
    )
    # Narrowing the scope dissolves the series state rather than spending it:
    # `SeriesStates.undoSection` drops any *breakable* state the section was
    # part of, so the delete stops being one series-wide action and becomes the
    # per-section events it was made of. Nothing lands on the redo stack, which
    # is the observable difference from the "all sections" answer above.
    series_states = window.field.series_states
    assert len(series_states.undos) == 0
    assert len(series_states.redos) == 0


def test_undo_cancel_changes_nothing(window, main_window_dialogs):
    """An unanswered prompt cancels, and cancelling leaves the delete standing.

    The empty queue is the point: a test that reaches this prompt without
    meaning to gets a no-op it can see, not a silently chosen scope.
    """
    delete_object_from_series(window)
    assert_prompt_reached(window)

    window.undo()

    assert main_window_dialogs.linked_undo_prompts == 1
    assert sections_carrying(window.series, OBJECT) == []
    assert_prompt_reached(window)


def test_offscreen_fallback_undoes_all_sections(window, monkeypatch):
    """With the fixture stub out of the way, the real prompt falls back to "all".

    The `window` fixture pulls `main_window_dialogs` in transitively, so this
    test puts the real `linkedUndoNotify` back on `main_window` and lets
    `undo()` call through to `gui/utils/utils.py`. Under
    `QT_QPA_PLATFORM=offscreen` `user_is_present()` is False and the helper
    returns "all" without constructing a `QMessageBox` at all. That this test
    terminates is the assertion the bug was about.
    """
    from PyReconstruct.modules.gui.main import main_window as mw
    from PyReconstruct.modules.gui.utils import utils

    monkeypatch.setattr(mw, "linkedUndoNotify", utils.linkedUndoNotify)
    assert utils.user_is_present() is False, (
        "run this suite with QT_QPA_PLATFORM=offscreen"
    )

    before = sections_carrying(window.series, OBJECT)

    delete_object_from_series(window)
    assert_prompt_reached(window)

    window.undo()

    assert sections_carrying(window.series, OBJECT) == before
