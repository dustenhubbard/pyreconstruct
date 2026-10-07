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
from pathlib import Path

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


# --- backups ------------------------------------------------------------------
#
# A backup during a save has more to get wrong than a save does. `manualBackup`
# writes the working files first, through `saveAllData`, and the running save
# is reading exactly those files, one section at a time. Then it opens the
# comment dialog, and `backup` makes the backup folder and either copies the
# .jser (`from_saved`, the save paths' own autobackup) or writes one. Every one
# of those used to happen before the running save was noticed. So these tests
# record each of them from inside the save, and expect none.


class Touches:
    """What a backup did to disk while ``active`` was set.

    The running save calls `Series.save` itself and reads the working files, so
    only calls made while the recorded action runs are counted.
    """

    def __init__(self):
        self.active = False
        self.working_file_writes = 0  # Section.save and Series.save
        self.copies = 0  # shutil.copyfile, the from_saved backup


@pytest.fixture
def touches(monkeypatch):
    """Count the working-file writers and the backup copy, while ``active``."""
    from PyReconstruct.modules.datatypes import Section, Series
    from PyReconstruct.modules.gui.main import main_window as mw

    touches = Touches()

    def counted(name, original):
        def call(*args, **kwargs):
            if touches.active:
                setattr(touches, name, getattr(touches, name) + 1)
            return original(*args, **kwargs)

        return call

    monkeypatch.setattr(Section, "save", counted("working_file_writes", Section.save))
    monkeypatch.setattr(Series, "save", counted("working_file_writes", Series.save))
    monkeypatch.setattr(mw.shutil, "copyfile", counted("copies", mw.shutil.copyfile))
    return touches


@pytest.fixture
def backup_dialogs(monkeypatch):
    """Replace the two backup dialogs with stand-ins that record each one opened.

    The comment dialog answers with a comment and OK, so a build that reaches it
    goes on to the folder setup and the copy, where the assertions catch those
    too. The settings dialog is dismissed.
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    opened = []

    class Comment:
        def __init__(self, *args, **kwargs):
            opened.append("Backup With Comment")

        def exec(self):
            return ("during", False), True

    class Settings:
        def __init__(self, *args, **kwargs):
            opened.append("Backup Settings")

        def exec(self):
            return False

    monkeypatch.setattr(mw, "BackupCommentDialog", Comment)
    monkeypatch.setattr(mw, "BackupDialog", Settings)
    return opened


def _default_backup_folder(series, tmp_path):
    """Point the series at the default backup folder, one it has yet to make.

    The default folder names the series with ``{series}``, and `backup` makes
    that folder on the way to writing, so whether it exists afterwards tells
    whether the backup got that far.
    """
    backups = tmp_path / "backups"
    backups.mkdir()
    series.setBackupUsesDefaults(True)
    series.setOption("default_backup_dir", str(backups / "{series}"))
    folder = Path(series.backupFolder())
    assert folder.parent == backups and not folder.exists()
    return folder


def _recording(touches, backup_dialogs, folder, screen, action):
    """Run ``action`` and return everything a backup could have done by then."""

    def run():
        touches.active = True
        try:
            action()
        finally:
            touches.active = False
        return {
            "working-file writes": touches.working_file_writes,
            "backup copies": touches.copies,
            "dialogs": list(backup_dialogs),
            "folder made": folder.exists(),
            "backup files": sorted(p.name for p in folder.parent.rglob("*") if p.is_file()),
            "error reports": list(screen.reports),
        }

    return run


NOTHING = {
    "working-file writes": 0,
    "backup copies": 0,
    "dialogs": [],
    "folder made": False,
    "backup files": [],
    "error reports": [],
}


def test_backup_now_during_a_save_shows_only_a_notice(
    main_window, local_series_settings, screen, backup_dialogs, touches, tmp_path
):
    """`Backup now...` chosen while a save is writing.

    Refused before it does anything: `manualBackup` used to rewrite the working
    files under the save that was reading them, open the comment dialog and make
    the backup folder, and only then notice the running save.
    """
    window = main_window
    series = local_series_settings(window)
    folder = _default_backup_folder(series, tmp_path)
    _edit(window, "nested_backup_marker")

    seen = _save_with(
        window,
        _recording(touches, backup_dialogs, folder, screen, window.manualbackup_act.trigger),
    )

    assert seen["result"] == NOTHING
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(SKIPPED)
    assert str(folder) in screen.notices[0]
    # the first save finished and wrote the edit, and nothing came after it:
    # this series does not back up on save
    assert series.modified is False
    with open(series.jser_fp, "rb") as f:
        assert b"nested_backup_marker" in f.read()
    assert not folder.exists()


def test_an_autobackup_from_the_saved_file_during_a_save_copies_nothing(
    main_window, local_series_settings, screen, backup_dialogs, touches, tmp_path
):
    """The save paths' own `backup(check_auto=True, from_saved=True)`, inside a save.

    ``from_saved`` copies the .jser instead of writing one, trusting that it was
    just saved. Inside a save that file is the one being replaced, so the copy is
    refused like any other backup, with the same notice. The save's own
    autobackup, which runs after it, still makes the one copy.
    """
    window = main_window
    series = local_series_settings(window)
    folder = _default_backup_folder(series, tmp_path)
    series.setOption("default_autobackup", True)
    _edit(window, "nested_autobackup_marker")

    seen = _save_with(
        window,
        _recording(
            touches, backup_dialogs, folder, screen,
            lambda: window.backup(check_auto=True, from_saved=True),
        ),
    )

    assert seen["result"] == NOTHING
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(SKIPPED)
    assert str(folder) in screen.notices[0]
    # the first save finished and wrote the edit...
    assert series.modified is False
    with open(series.jser_fp, "rb") as f:
        saved = f.read()
    assert b"nested_autobackup_marker" in saved
    # ...and its own autobackup, after it, copied that file once
    copies = list(folder.iterdir())
    assert len(copies) == 1
    assert copies[0].read_bytes() == saved
