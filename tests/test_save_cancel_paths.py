"""Backing out of a save must never destroy the work it was protecting.

Three paths through `MainWindow` treated "the user canceled" as "the save
succeeded" (found by the review fleet, 2026-08-27). All three end at
`Series.close()`, which deletes the hidden working directory holding every
edit since the last `.jser` write, so all three could throw away an hour of
tracing without a prompt:

1. `saveToJser` on a never-saved series calls `saveAsToJser`, which returned
   None whether it wrote the file or the user dismissed the dialog. Control
   fell through to `seriesModified(False)`, the asterisk went away, and the
   next close deleted the only copy.
2. `openSeries` closes the outgoing series before it has the new one. Cancel
   the Open dialog and the window kept a series whose files were gone: every
   later save raised `FileNotFoundError`.
3. `newSeries` discarded the answer to its save prompt, so Cancel carried on
   through the wizard to `openSeries(query_prev=False)`, which closes the
   series unconditionally.

The tests drive the real `MainWindow`. An empty `file_responses` queue is a
dismissed file dialog, which is exactly the gesture under test.
"""

import os

import pytest

pytestmark = pytest.mark.gui


def _never_saved(window):
    """Put the window's series in the state `Series.new()` leaves it in.

    The hidden working directory exists and holds the work; no `.jser` on
    disk points at it yet. That is the state where a dismissed Save As can
    lose everything.
    """
    window.series.jser_fp = ""
    window.seriesModified(True)
    return window.series.hidden_dir


# --- 1. the dismissed Save As -------------------------------------------------

def test_a_dismissed_save_as_says_it_canceled(main_window, main_window_dialogs):
    """`saveAsToJser` distinguishes "wrote nothing" from "wrote the file"."""
    _never_saved(main_window)

    assert main_window.saveAsToJser() == "cancel"


def test_a_canceled_save_as_leaves_the_series_dirty(
    main_window, main_window_dialogs
):
    """The asterisk stays and the work stays, because nothing was written.

    `seriesModified(False)` here is what made the loss silent: it told the
    rest of the app the series was safe on disk when it was not.
    """
    hidden = _never_saved(main_window)

    assert main_window.saveToJser() == "cancel"

    assert main_window.series.modified is True
    assert os.path.isdir(hidden)


def test_canceling_the_save_as_during_a_close_keeps_the_window_open(
    main_window, main_window_dialogs
):
    """The payoff: answer "yes, save" on exit, then dismiss Save As.

    Before the fix the close ran to completion. `saveToJser` returned None
    rather than "cancel", so `closeEvent` accepted the event and
    `Series.close()` deleted the hidden dir -- the work was gone, with no
    `.jser` anywhere that had it. Now the close is refused and the series is
    still there to save.
    """
    hidden = _never_saved(main_window)
    main_window_dialogs.save_response = "yes"

    assert main_window.close() is False  # closeEvent called event.ignore()

    assert os.path.isdir(hidden)
    assert main_window.series.modified is True


# --- 2. the abandoned open ----------------------------------------------------

def test_canceling_the_open_dialog_leaves_a_series_that_still_saves(
    main_window, main_window_dialogs, series_jser
):
    """Cancel the file picker and the window keeps working.

    `openSeries` closes the outgoing series before asking which series to
    open. Returning on the cancel left `self.series` pointing at deleted
    files, so the next `Section.save()` raised `FileNotFoundError` and no
    edit could be persisted again for the life of the window. The saved copy
    is reopened instead.
    """
    main_window_dialogs.save_response = "yes"

    main_window.openSeries()  # file_responses empty: the picker is dismissed

    assert main_window.series is not None
    assert main_window.series.jser_fp == str(series_jser)
    assert os.path.isdir(main_window.series.hidden_dir)

    # the real proof: the window can still write to disk
    main_window.field.section.save()
    main_window.saveToJser()
    assert main_window.series.modified is False


def test_an_abandoned_open_with_nothing_to_go_back_to_lands_on_welcome(
    main_window, main_window_dialogs
):
    """A never-saved series discarded at the prompt has no `.jser` to reopen.

    The window must still end up on something live rather than on deleted
    files, so it falls back to the welcome series -- the app's own empty
    state, and the one series `Series.close()` refuses to delete.
    """
    _never_saved(main_window)
    main_window_dialogs.save_response = "no"  # discard the unsaved series

    main_window.openSeries()

    assert main_window.series is not None
    assert main_window.series.isWelcomeSeries()


# --- 3. cancel at the New Series prompt ---------------------------------------

def test_cancel_at_the_new_series_prompt_aborts_the_wizard(
    main_window, main_window_dialogs
):
    """Cancel means abort, the way it already did when opening a series.

    The wizard used to continue, and its final `openSeries(query_prev=False)`
    closed the series unconditionally -- destroying the very edits Cancel was
    pressed to protect.
    """
    hidden = main_window.series.hidden_dir
    before = main_window.series
    main_window.seriesModified(True)
    main_window_dialogs.save_response = "cancel"

    main_window.newSeries()

    assert main_window.series is before
    assert main_window.series.modified is True
    assert os.path.isdir(hidden)
    # the wizard never got as far as asking for images
    assert "Select Images" not in main_window_dialogs.dialogs
