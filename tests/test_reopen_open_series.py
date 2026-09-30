"""Opening the series that is already open (fork #527).

The save prompt closes the outgoing series, which deletes its hidden working
folder. `Series.openJser` then unpacks the same .jser into that same folder,
and `openSeries` used to close the outgoing object a second time, deleting the
folder the new copy had just been given. Building the field then raised
`FileNotFoundError`, and every save after that failed.

Reopening is now a plain reload from the .jser: whatever the save prompt
decided is what comes back, and the window keeps a working folder.
"""

import os

import pytest

pytestmark = pytest.mark.gui


def _add_a_trace(window, name):
    """Copy the first trace on the current section under a new name."""
    section = window.field.section
    source = section.contours[next(iter(section.contours))][0]
    trace = source.copy()
    trace.name = name
    section.addTrace(trace, log_event=False)
    window.seriesModified(True)


def _assert_series_works(window):
    """The open series still has its files and can be saved."""
    assert os.path.isdir(window.series.hidden_dir), "the working folder is gone"
    assert os.path.isfile(window.series.filepath)
    assert os.path.isfile(window.field.section.filepath)
    window.saveAllData()
    window.series.saveJser()


def test_open_series_on_itself_discarding_changes(main_window, main_window_dialogs):
    """File > Open on the open .jser, answering "no" to the save prompt."""
    window = main_window
    jser = window.series.jser_fp
    old = window.series
    _add_a_trace(window, "reopen_discarded")

    main_window_dialogs.file_responses.append(jser)
    main_window_dialogs.save_response = "no"
    window.openSeries()

    assert window.series is not old
    assert window.series.jser_fp == jser
    _assert_series_works(window)
    assert "reopen_discarded" not in window.field.section.contours


def test_open_recent_on_itself_saving_changes(main_window, main_window_dialogs):
    """File > Open Recent on the open .jser, answering "yes" to the save prompt."""
    window = main_window
    jser = window.series.jser_fp
    _add_a_trace(window, "reopen_saved")

    main_window_dialogs.save_response = "yes"
    window.openSeries(jser_fp=jser)  # what an Open Recent entry calls

    _assert_series_works(window)
    assert "reopen_saved" in window.field.section.contours
    assert not window.series.modified


def test_open_series_on_itself_unmodified(main_window, main_window_dialogs):
    """No save prompt at all when nothing changed; the reload still works."""
    window = main_window
    jser = window.series.jser_fp
    window.seriesModified(False)

    window.openSeries(jser_fp=jser)

    assert main_window_dialogs.save_prompts == 0
    _assert_series_works(window)
