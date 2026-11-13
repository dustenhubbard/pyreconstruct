"""The error window, for a session with nobody in front of it.

`show_error_report` runs a modal `exec`. Under `PYRECON_UNATTENDED=1` nobody
can close it, so a failed save in a scripted run waited forever on
"Save failed". Unattended, no window opens: the hook has already printed and
logged its report, and a failed save prints its message.
"""

import pytest

from PyReconstruct.modules.gui.utils import errors
from PyReconstruct.modules.gui.utils import utils as gui_utils

pytestmark = pytest.mark.gui


@pytest.fixture
def windows(qapp, monkeypatch):
    """Record each error window instead of opening it."""
    opened = []

    class Dialog:
        def __init__(self, summary, report, parent=None, issue_url=None):
            opened.append(report)

        def setWindowTitle(self, title):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr(errors, "ErrorReportDialog", Dialog)
    monkeypatch.setattr(errors, "_showing_report", False)
    monkeypatch.setattr(
        errors.QMessageBox, "critical", staticmethod(lambda *a, **k: opened.append(a))
    )
    return opened


def test_an_unattended_run_opens_no_error_window(windows, monkeypatch):
    monkeypatch.setenv(gui_utils.UNATTENDED_ENV_VAR, "1")
    assert errors.show_error_report("<b>x</b>", "the report") is False
    assert windows == []


def test_with_someone_there_the_window_still_opens(windows, monkeypatch):
    monkeypatch.delenv(gui_utils.UNATTENDED_ENV_VAR, raising=False)
    assert errors.show_error_report("<b>x</b>", "the report") is True
    assert windows == ["the report"]


def test_an_unattended_save_failure_prints_its_message(
    windows, monkeypatch, capsys
):
    """On a real platform the notifier would show the window; unattended it
    says nothing was shown, so the series prints the message."""
    from types import SimpleNamespace

    from PyReconstruct.modules.backend.notifier import QtNotifier
    from PyReconstruct.modules.datatypes.series import Series

    series = SimpleNamespace(_notifier=QtNotifier)
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    monkeypatch.setenv(gui_utils.UNATTENDED_ENV_VAR, "1")
    Series._surfaceSaveError(series, "/x/S.jser", OSError("disk full"))
    assert windows == []
    assert "Save failed: disk full" in capsys.readouterr().out

    monkeypatch.delenv(gui_utils.UNATTENDED_ENV_VAR)
    Series._surfaceSaveError(series, "/x/S.jser", OSError("disk full"))
    assert len(windows) == 1
    assert "Save failed" not in capsys.readouterr().out
