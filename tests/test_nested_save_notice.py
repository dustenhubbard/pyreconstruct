"""A save that arrives while another save is running is a notice, not an error.

Saving shows a progress dialog, and each update to it lets Qt run queued events,
so a Save, a Close or a backup can start inside a save that is still writing.
The series refuses the second save. That refusal used to open the error-report
window ("Save failed", with "Report a bug on GitHub") and then raise. From
File > Save the exception reached the exception hook, which opened a second
error-report window. From closing the window it was lost after the save prompt,
and the window closed while the first save was still writing.

A skipped save is expected, not a fault. Now the second one is refused before
it writes, asks or closes anything: a plain message, no error-report window and
no exception. The series stays marked modified until a save has written it,
and the first save still finishes and writes it.

Each test starts a real save and has a zero-delay `QTimer` fire the second
action from inside it, the way a queued shortcut arrives: the timer runs in the
progress dialog's own event processing. Every test checks that it really ran
inside the save, so a change that moves the timer out of the save cannot turn
these into tests of two ordinary saves.
"""

import os

import pytest
from PySide6.QtCore import QTimer

pytestmark = pytest.mark.gui

SKIPPED = "Save skipped: this series is already being saved."


class Screen:
    """What a user at the screen would have seen.

    ``reports`` holds the title of every error-report window. The exception
    hook `MainWindow` installs and the "Save failed" window the series'
    notifier opens both end in `errors.show_error_report`.
    """

    def __init__(self, recorder):
        self.reports = []
        self._recorder = recorder

    def show_error_report(self, summary_html, report, parent=None, title="Error", issue_url=None):
        self.reports.append(title)
        return True

    @property
    def notices(self):
        """The text of every plain message box, in order."""
        return [text for _title, text in self._recorder.message_boxes]


@pytest.fixture
def screen(main_window, main_window_dialogs, tmp_path):
    """Make the series' notifier treat this as a session with a user present.

    Offscreen, the Qt notifier shows nothing at all, so neither the notice nor
    the "Save failed" window would be visible to a test. With `qt_offscreen`
    cleared it takes the on-screen branch: a notice goes through `notify` to
    `QMessageBox.information`, which `main_window_dialogs` records, and an
    error report reaches `show_error_report`, recorded here instead of shown.

    Its own MonkeyPatch, undone before `main_window` closes the window, so the
    window's teardown runs offscreen as usual.
    """
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.gui.utils import errors
    from PyReconstruct.modules.gui.utils import utils as gui_utils

    seen = Screen(main_window_dialogs)
    mp = pytest.MonkeyPatch()
    mp.delenv(gui_utils.UNATTENDED_ENV_VAR, raising=False)
    mp.setattr(gui_utils, "qt_offscreen", False)
    mp.setattr(errors, "show_error_report", seen.show_error_report)
    # a report this session already showed would be skipped by the hook
    mp.setattr(errors, "_reported_signatures", set())
    # the hook writes every report to the log; keep it off the real log file
    mp.setattr(logging_setup, "log_file_path", lambda: tmp_path / "pyreconstruct.log")
    try:
        yield seen
    finally:
        mp.undo()


def _edit(window, name):
    """Add a trace under ``name``, so a written .jser can be told apart."""
    section = window.field.section
    source = section.contours[next(iter(section.contours))][0]
    trace = source.copy()
    trace.name = name
    section.addTrace(trace, log_event=False)
    window.seriesModified(True)


def _save_with(window, action):
    """Save from the File menu's handler while ``action`` runs inside the save."""
    series = window.series
    seen = {}

    def run():
        seen["inside the save"] = series.jserSaveRunning()
        seen["result"] = action()

    QTimer.singleShot(0, run)
    window.saveToJser()
    assert seen.get("inside the save") is True, "the second action did not run inside the save"
    return seen


def test_save_during_a_save_shows_only_a_notice(main_window, screen):
    """File > Save pressed while a save is writing."""
    window = main_window
    series = window.series
    _edit(window, "nested_save_marker")

    def press_save():
        window.save_act.trigger()
        return series.modified

    seen = _save_with(window, press_save)

    assert screen.reports == [], "an error-report window opened"
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(SKIPPED)
    assert series.jser_fp in screen.notices[0]
    # the refused save did not mark the series saved...
    assert seen["result"] is True
    # ...and the first save finished and wrote the edit
    assert series.modified is False
    with open(series.jser_fp, "rb") as f:
        assert b"nested_save_marker" in f.read()


def test_closing_during_a_save_is_refused_and_keeps_the_working_folder(
    main_window, main_window_dialogs, screen
):
    """Closing the window while a save is writing.

    Closing saves first, and the save prompt it raises can answer "No", which
    deletes the working folder the running save is reading from. So the close is
    refused before the prompt, and the window stays open.
    """
    window = main_window
    series = window.series
    _edit(window, "nested_close_marker")
    # what a user would answer, though the prompt must not be reached at all
    main_window_dialogs.save_response = "yes"

    seen = _save_with(window, window.close)

    assert seen["result"] is False, "the window closed during the save"
    assert main_window_dialogs.save_prompts == 0
    assert window.isVisible()
    assert os.path.isdir(series.hidden_dir)
    assert screen.reports == [], "an error-report window opened"
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(SKIPPED)
    with open(series.jser_fp, "rb") as f:
        assert b"nested_close_marker" in f.read()


def test_backup_now_during_a_save_shows_only_a_notice(
    main_window, screen, tmp_path, monkeypatch
):
    """`Backup now...` chosen while a save is writing."""
    from PyReconstruct.modules.gui.main import main_window as mw

    class Comment:
        """The backup comment dialog, answered with a comment and OK."""

        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return ("during", False), True

    monkeypatch.setattr(mw, "BackupCommentDialog", Comment)
    window = main_window
    series = window.series
    backups = tmp_path / "backups"
    backups.mkdir()
    series.setBackupUsesDefaults(False)
    series.setOption("backup_dir", str(backups))
    _edit(window, "nested_backup_marker")

    _save_with(window, window.manualbackup_act.trigger)

    assert list(backups.iterdir()) == [], "the refused backup wrote a file"
    assert screen.reports == [], "an error-report window opened"
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(SKIPPED)
    assert str(backups) in screen.notices[0]
    assert series.modified is False
