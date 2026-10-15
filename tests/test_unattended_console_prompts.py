"""The console fallback of `notify` and `notifyConfirm`, with nobody there.

With no user present for a dialog, `notify` and `notifyConfirm(yn=True)` fall
back to the console: print, then `input()`. That is right for a person at a
terminal with no GUI, and wrong under `PYRECON_UNATTENDED=1`, where the caller
has said nobody is there at all. The `input()` then waits forever, or raises
`EOFError` when stdin is closed.

Unattended, a notice prints and returns, and a yes/no question answers no.
An unattended confirmation must never come back as approval. With the variable
unset, the console prompts read stdin as before.

The OK/Cancel form (`notifyConfirm(yn=False)`, `noUndoWarning()`) asks nothing
with no user present. It used to fall off the end and return None, which
`randomizeProject` and `derandomizeProject` do not read as cancel: they test
`response == False`. It now returns False.
"""

import io
import sys

import pytest

from PyReconstruct.modules.gui.utils import utils as gui_utils


def _no_stdin(*args, **kwargs):
    pytest.fail("read stdin with nobody there to answer")


@pytest.fixture
def unattended(monkeypatch):
    monkeypatch.setenv(gui_utils.UNATTENDED_ENV_VAR, "1")
    monkeypatch.setattr("builtins.input", _no_stdin)


@pytest.fixture
def console_user(monkeypatch):
    """No GUI, variable unset: a person at the terminal answers on stdin."""
    monkeypatch.delenv(gui_utils.UNATTENDED_ENV_VAR, raising=False)
    monkeypatch.setattr(gui_utils, "qt_offscreen", True)
    assert gui_utils.user_is_present() is False
    assert gui_utils.is_unattended() is False

    prompts = []

    def answer(response):
        def fake_input(prompt=""):
            prompts.append(prompt)
            return response
        monkeypatch.setattr("builtins.input", fake_input)

    answer.prompts = prompts
    return answer


def test_unattended_notify_prints_and_returns(unattended, capsys):
    assert gui_utils.notify("Traces exported.") is None
    assert "Traces exported." in capsys.readouterr().out


def test_unattended_yes_no_answers_no(unattended, capsys):
    assert gui_utils.notifyConfirm("Save anyway?", yn=True) is False
    assert "Save anyway?" in capsys.readouterr().out


def test_unattended_ok_cancel_answers_cancel(unattended):
    assert gui_utils.notifyConfirm("Continue?") is False
    assert gui_utils.noUndoWarning() is False


def test_unattended_with_stdin_closed_does_not_raise(monkeypatch):
    """The issue as reported: stdin closed, so `input()` raises `EOFError`."""
    monkeypatch.setenv(gui_utils.UNATTENDED_ENV_VAR, "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    gui_utils.notify("notice")
    assert gui_utils.notifyConfirm("question", yn=True) is False


@pytest.mark.parametrize("typed, expected", [("y", True), ("n", False), ("", False)])
def test_console_user_is_still_asked_yes_no(console_user, typed, expected):
    console_user(typed)
    assert gui_utils.notifyConfirm("Save anyway?", yn=True) is expected
    assert console_user.prompts == ["Please enter y/[n]: "]


def test_console_user_still_presses_enter_after_a_notice(console_user):
    console_user("")
    gui_utils.notify("Traces exported.")
    assert console_user.prompts == ["Press Enter to continue..."]


def test_console_ok_cancel_answers_cancel_as_false(console_user):
    console_user("y")
    assert gui_utils.notifyConfirm("Continue?") is False
    assert gui_utils.noUndoWarning() is False
    assert console_user.prompts == []
