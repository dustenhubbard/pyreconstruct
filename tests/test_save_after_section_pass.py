"""A save never writes back the field's copy of a section a pass rewrote.

A pass over the section files (Delete, Combine and the other object list
actions) loads and writes its own copies of the sections. The field keeps
the copies it loaded before, of the section shown and the flickered-away one
(b_section), until the pass ends and reloads it. A .jser opened from the
Finder during the pass's progress dialog closes the series, and answering
the save prompt, Yes or Cancel, saves it through MainWindow.saveAllData,
which wrote those older copies over the pass's work.

What is pinned here:

  * a save during a pass keeps what the pass wrote on the section shown and
    on the flickered-away one
  * so does saving at the prompt when another series opens during an
    object Delete, Yes or Cancel
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
def test_saving_at_the_prompt_during_a_delete_keeps_it(
    held, answer, main_window, main_window_dialogs, tmp_path, qtbot,
    finder,  # noqa: F811
):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    window = main_window
    snums = _plant_where_the_field_holds(window, NAME, held)
    first = window.series
    # unsaved, so closing it asks
    window.seriesModified(True)
    window.field.section.selected_traces = list(
        window.field.section.contours[NAME]
    )
    _b_opens_during_the_combine(
        window, tmp_path, qtbot, "last", _offer_copy_from_finder
    )
    main_window_dialogs.save_response = answer

    window.field.deleteObjects()

    assert main_window_dialogs.save_prompts == 1
    if answer == "cancel":
        assert window.series is first
        assert [_counts(first, s).get(NAME, 0) for s in snums] == [0, 0]
        assert NAME not in window.field.section.contours
        return
    assert window.series is not first
    a = Series.openJser(first.jser_fp, progress=NullProgressReporter)
    try:
        assert [_counts(a, s).get(NAME, 0) for s in snums] == [0, 0]
    finally:
        a.close()
