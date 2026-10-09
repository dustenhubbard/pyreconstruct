"""The field's copies of a section match what a pass over the files wrote.

A pass over the section files (Delete, Combine and the other object list
actions) loads and writes its own copies of the sections. The field keeps
the copies it loaded before, of the section shown and the flickered-away one
(b_section), and every save writes those back (MainWindow.saveAllData). A
.jser opened from the Finder during the pass's progress dialog closes the
series, and answering the save prompt, Yes or Cancel, saved those older
copies over the pass's work. The field now reloads its copy of each section
right after the pass writes it (Series.setPassWriteHook).

What is pinned here:

  * a save during a pass keeps what the pass wrote on the section shown and
    on the flickered-away one
  * so does saving at the prompt when another series opens during an
    object Delete, Yes or Cancel, at a middle progress update or the last
  * a pass that stops part-way leaves the field's copies as the pass wrote
    them, the section it wrote can be undone, and an edit made after it is
    saved
  * an edit made after Save As, a pass, and Save As again is saved
  * an edit made in the field after the pass is still saved, and so is
    one made before a write outside a pass
"""
import pytest

from tests.test_cleanup_lists_series_switch import (  # noqa: F401  (fixture)
    SQUARE,
    _counts,
    finder,
)
from tests.test_combine_duplicates_series_switch import (
    _b_opens_during_the_combine,
    _offer_copy_from_finder,
    _plant_where_the_field_holds,
)

pytestmark = pytest.mark.gui

NAME = "STALE_COPY"


@pytest.mark.parametrize("held", ["shown", "flickered"])
def test_a_save_during_a_pass_keeps_what_it_wrote(held, main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, held)
    window.seriesModified(True)

    class Saves(NullProgressReporter):
        def set_progress(self, percent):
            if percent >= 100:
                window.saveAllData()

    window.series.setProgressReporter(Saves)
    window.series.deleteObjects([NAME])

    assert [_counts(window.series, s).get(NAME, 0) for s in snums] == [0, 0]


def test_an_edit_after_the_pass_is_saved(main_window):
    from PyReconstruct.modules.datatypes.trace import Trace
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, "shown")
    window.series.deleteObjects([NAME])
    window.field.reload()

    trace = Trace("AFTER_PASS", (255, 0, 0), closed=True)
    trace.points = list(SQUARE)
    window.field.section.addTrace(trace, log_event=False)
    window.saveAllData()

    counts = _counts(window.series, snums[0])
    assert counts.get(NAME, 0) == 0
    assert counts["AFTER_PASS"] == 1


def test_a_write_outside_a_pass_keeps_the_field_edit(main_window):
    from PyReconstruct.modules.datatypes.trace import Trace
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, "shown")
    trace = Trace("FIELD_EDIT", (255, 0, 0), closed=True)
    trace.points = list(SQUARE)
    window.field.section.addTrace(trace, log_event=False)

    other = window.series.loadSection(snums[0])
    other.align_locked = False
    other.save()
    window.saveAllData()

    assert _counts(window.series, snums[0])["FIELD_EDIT"] == 1


@pytest.mark.parametrize("answer", ["yes", "cancel"])
@pytest.mark.parametrize("held", ["shown", "flickered"])
@pytest.mark.parametrize("update", ["middle", "last"])
def test_saving_at_the_prompt_during_a_delete_keeps_it(
    update, held, answer, main_window, main_window_dialogs, tmp_path, qtbot,
    finder,  # noqa: F811
):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import (
        Series,
        SeriesClosedError,
    )
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, held)
    first = window.series
    # unsaved, so closing it asks
    window.seriesModified(True)
    window.field.section.selected_traces = list(
        window.field.section.contours[NAME]
    )
    _b_opens_during_the_combine(
        window, tmp_path, qtbot, update, _offer_copy_from_finder
    )
    main_window_dialogs.save_response = answer

    try:
        window.field.deleteObjects()
    except (SeriesClosedError, FileNotFoundError):
        # Yes closed A with a section still to delete from
        assert answer == "yes" and update == "middle"

    assert main_window_dialogs.save_prompts == 1
    if answer == "cancel":
        assert window.series is first
        assert [_counts(first, s).get(NAME, 0) for s in snums] == [0, 0]
        assert NAME not in window.field.section.contours
        return
    assert window.series is not first
    deleted = 1 if update == "middle" else 2
    a = Series.openJser(first.jser_fp, progress=NullProgressReporter)
    try:
        assert [_counts(a, s).get(NAME, 0) for s in snums] == (
            [0] * deleted + [2] * (2 - deleted)
        )
    finally:
        a.close()


def _draw(window, name):
    """Draw a trace on the section shown, as the field records one."""
    from PyReconstruct.modules.datatypes.trace import Trace
    trace = Trace(name, (255, 0, 0), closed=True)
    trace.points = list(SQUARE)
    window.field.section.addTrace(trace)
    window.field.saveState()
    window.seriesModified(True)


def _saved_count(window, snum, name):
    """How many traces of name the saved .jser holds on one section."""
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    saved = Series.openJser(window.series.jser_fp, progress=NullProgressReporter)
    try:
        return _counts(saved, snum).get(name, 0)
    finally:
        saved.close()


@pytest.mark.parametrize("held", ["shown", "flickered"])
def test_a_pass_that_stops_leaves_the_field_as_written(
    held, main_window, monkeypatch,
):
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, held)
    series = window.series
    load = series.loadSection

    def stops_at_the_second(n):
        if n == snums[1] and series.sectionPassRunning():
            raise OSError("the second section cannot be read")
        return load(n)

    monkeypatch.setattr(series, "loadSection", stops_at_the_second)
    window.field.section.selected_traces = list(
        window.field.section.contours[NAME]
    )
    with pytest.raises(OSError):
        window.field.deleteObjects()
    monkeypatch.setattr(series, "loadSection", load)

    held_copy = (
        window.field.section if held == "shown" else window.field.b_section
    )
    assert held_copy.n == snums[0]
    assert NAME not in held_copy.contours
    assert _counts(series, snums[0]).get(NAME, 0) == 0


def test_a_pass_that_stops_can_be_undone_on_the_section_it_wrote(
    main_window, main_window_dialogs, monkeypatch,
):
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, "shown")
    # the planting has no undo state: start the history after it
    window.field.clearStates()
    series = window.series
    load = series.loadSection

    def stops_at_the_second(n):
        if n == snums[1] and series.sectionPassRunning():
            raise OSError("the second section cannot be read")
        return load(n)

    monkeypatch.setattr(series, "loadSection", stops_at_the_second)
    window.field.section.selected_traces = list(
        window.field.section.contours[NAME]
    )
    with pytest.raises(OSError):
        window.field.deleteObjects()
    monkeypatch.setattr(series, "loadSection", load)

    def counts():
        window.saveAllData()
        return [_counts(series, s).get(NAME, 0) for s in snums]

    assert counts() == [0, 2]
    main_window_dialogs.linked_undo_responses = ["all", "all"]
    window.undo()
    assert counts() == [2, 2]
    assert len(window.field.section.contours[NAME]) == 2
    window.undo(redo=True)
    assert counts() == [0, 2]


def test_an_edit_after_a_pass_that_stops_is_saved(main_window, monkeypatch):
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, "shown")
    series = window.series
    load = series.loadSection

    def stops_at_the_second(n):
        if n == snums[1] and series.sectionPassRunning():
            raise OSError("the second section cannot be read")
        return load(n)

    monkeypatch.setattr(series, "loadSection", stops_at_the_second)
    window.field.section.selected_traces = list(
        window.field.section.contours[NAME]
    )
    with pytest.raises(OSError):
        window.field.deleteObjects()
    monkeypatch.setattr(series, "loadSection", load)

    _draw(window, "USER_EDIT")
    window.saveToJser()

    assert not series.modified
    assert _counts(series, snums[0])["USER_EDIT"] == 1
    assert _saved_count(window, snums[0], "USER_EDIT") == 1


def test_an_edit_after_save_as_and_a_pass_is_saved(
    main_window, main_window_dialogs, tmp_path,
):
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, "shown")
    first_fp = window.series.jser_fp

    def hide_and_unhide():
        for hide in (True, False):
            window.series.hideObjects([NAME], hide, window.field.series_states)
            window.field.reload()

    for _ in range(5):
        hide_and_unhide()
    other = tmp_path / "other" / "other.jser"
    other.parent.mkdir()
    main_window_dialogs.file_responses.append(str(other))
    window.saveAsToJser()
    hide_and_unhide()
    main_window_dialogs.file_responses.append(first_fp)
    window.saveAsToJser()
    assert window.series.jser_fp == first_fp

    _draw(window, "USER_EDIT")
    window.saveToJser()

    assert not window.series.modified
    assert _counts(window.series, snums[0])["USER_EDIT"] == 1
    assert _saved_count(window, snums[0], "USER_EDIT") == 1
