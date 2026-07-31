"""The two save prompts, with and without a user to answer them.

`saveNotify` and `unsavedNotify` were the last two dialog helpers with no
offscreen branch: `notify` and `notifyConfirm` fall through to the console, but
these two called `QMessageBox.question` unconditionally. Offscreen that is a
modal with no window manager to dismiss it, so the call never returns. Measured
before the fix by calling each one in a subprocess under
`QT_QPA_PLATFORM=offscreen`: `notify` and `notifyConfirm` returned, both of these
were still inside `QMessageBox.question` when the 25s timeout killed them.

That mattered beyond the two functions, because `MainWindow.closeEvent` calls
`saveToJser(notify=True, close=True)`, which calls `saveNotify()` whenever the
series is dirty. So no test could close a real `MainWindow` that had unsaved
changes, which is to say no test could check that closing does not lose them.
`test_closing_a_dirty_series_writes_it_to_the_jser` is that test.

Both prompts answer the same way with nobody present: take the branch that
cannot destroy data. See the docstrings in
`PyReconstruct/modules/gui/utils/utils.py` for why each of the alternatives can.
The interactive path is asserted here too, because the whole point is that a
real user still sees and still decides both prompts.
"""

import pytest

from PySide6.QtWidgets import QMessageBox

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.utils import utils as gui_utils

pytestmark = pytest.mark.gui


class QuestionRecorder:
    """Stand-in for `QMessageBox.question`, returning a scripted button.

    Records `(args, kwargs)` so the interactive branch can be checked without a
    display: the prompt text, the parent, and the button set are all arguments.
    """

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.answer


def _interactive(monkeypatch, answer):
    """Make `user_is_present()` true and script the next `question()` answer."""
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    recorder = QuestionRecorder(answer)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(recorder)
    )
    return recorder


# --- no user present ---------------------------------------------------------

def test_save_notify_returns_yes_with_nobody_to_ask(qapp, capsys):
    """`saveNotify()` returns instead of blocking, and saving is the answer.

    "no" is discard: `saveToJser` follows it with `Series.close()`, which deletes
    the hidden working directory holding every unsaved edit. "cancel" makes
    `closeEvent` call `event.ignore()`, so the window never closes. Neither is
    acceptable unattended, so "yes" it is.

    The fact that this test finishes at all is the regression guard: before the
    fix the call sat in `QMessageBox.question` forever.
    """
    assert gui_utils.user_is_present() is False

    assert gui_utils.saveNotify() == "yes"

    # the decision is recorded, because it was made on the user's behalf
    assert "saving it before exit" in capsys.readouterr().out


def test_unsaved_notify_keeps_the_recovered_series_with_nobody_to_ask(
    qapp, capsys
):
    """`unsavedNotify()` returns True, which is the branch that deletes nothing.

    `openSeries` answers False by removing every file in the hidden directory and
    then the directory, and that directory is the only copy of whatever the
    previous session did not save.
    """
    assert gui_utils.user_is_present() is False

    assert gui_utils.unsavedNotify() is True

    assert "rather than discarding it" in capsys.readouterr().out


# --- a real user, unchanged --------------------------------------------------

@pytest.mark.parametrize(
    "button, expected",
    [
        (QMessageBox.Yes, "yes"),
        (QMessageBox.No, "no"),
        (QMessageBox.Cancel, "cancel"),
    ],
)
def test_save_notify_still_asks_a_real_user(monkeypatch, button, expected):
    """All three answers still reach the caller from the real dialog.

    Guards the shape of the guard: an early return that swallowed the interactive
    path, or one that reordered the response mapping, fails here. `qt_offscreen`
    is read at call time, which is what makes this checkable without a display.
    """
    recorder = _interactive(monkeypatch, button)

    assert gui_utils.saveNotify() == expected

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args[1] == "Exit"
    assert args[2] == (
        "This series has been modified.\nWould you like save before exiting?"
    )
    assert kwargs["buttons"] == (
        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
    )


@pytest.mark.parametrize(
    "button, expected", [(QMessageBox.Yes, True), (QMessageBox.No, False)]
)
def test_unsaved_notify_still_asks_a_real_user(monkeypatch, button, expected):
    """The recovery prompt still runs, and No still means discard.

    Deliberately asserts that a real user answering No gets False. The offscreen
    default is the opposite, and it has to be, but it must not leak into the path
    where somebody actually answered.
    """
    recorder = _interactive(monkeypatch, button)

    assert gui_utils.unsavedNotify() is expected

    assert len(recorder.calls) == 1
    args, _ = recorder.calls[0]
    assert args[1] == "Unsaved Series"
    assert args[2] == (
        "An unsaved version of this series has been found.\n"
        "Would you like to open it?"
    )
    assert args[3:] == (QMessageBox.Yes, QMessageBox.No)


def test_no_prompt_helper_is_left_without_an_offscreen_branch(qapp):
    """Every prompt in `gui.utils.utils` returns with nobody present.

    A list rather than a loop over the module, because these four are the ones
    `MainWindow` can reach from teardown and they are the ones that have to hold.
    `notify` and `notifyConfirm` end in `input()` offscreen, which raises under
    pytest's output capture rather than hanging, so they are exercised through
    their console branch here only to pin that they do not sit on a modal.
    """
    assert gui_utils.saveNotify() == "yes"
    assert gui_utils.unsavedNotify() is True

    with pytest.raises(OSError):  # stdin is captured, so the console branch
        gui_utils.notify("no display")  # cannot read -- it does not hang

    with pytest.raises(OSError):
        gui_utils.notifyConfirm("no display", yn=True)


# --- the payoff: a real MainWindow, closed with unsaved work -----------------

def _add_a_trace(section, name):
    """Copy the first trace on `section` under a new name. Returns the copy."""
    source = section.contours[next(iter(section.contours))][0]
    trace = source.copy()
    trace.name = name
    section.addTrace(trace, log_event=False)
    return trace


def test_closing_a_dirty_series_writes_it_to_the_jser(
    main_window, monkeypatch, series_jser
):
    """Closing a modified series saves it rather than dropping the changes.

    The test that could not be written before. It needs a real `MainWindow`
    (`closeEvent` is the only caller of `saveToJser(notify=True)`) and it needs
    the real `saveNotify`, so it undoes the `main_window_dialogs` patch of that
    one name. Every other dialog stays neutralized.

    The edit lives only in the series' hidden working directory until something
    writes the `.jser`, which is what makes the assertion meaningful.

    The "before" check reads the `.jser` bytes rather than reopening it, because
    `Series.openJser` reuses an existing hidden directory when it finds one: with
    the window still up, a second `openJser` on the same path returns the live
    working copy and would see the trace whether or not anything had been saved.
    A `.jser` is plain JSON, so the name is greppable in it.
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    monkeypatch.setattr(mw, "saveNotify", gui_utils.saveNotify)

    window = main_window
    section = window.field.section
    snum = section.n
    trace_name = "closeevent_unsaved_work"

    _add_a_trace(section, trace_name)
    section.save()
    window.seriesModified(True)
    assert window.series.modified is True

    # the .jser on disk does not have it yet
    assert trace_name not in series_jser.read_text()

    window.close()

    assert window.series.modified is False
    assert trace_name in series_jser.read_text()

    # and it comes back as a real trace, not just as matching bytes
    reopened = Series.openJser(str(series_jser))
    try:
        assert trace_name in reopened.loadSection(snum).contours
    finally:
        reopened.close()


def test_closing_an_unmodified_series_writes_nothing(
    main_window, monkeypatch, series_jser
):
    """A clean series is not saved on close, so the prompt is not reached.

    The other half of the pair. `saveToJser` only consults `saveNotify` when
    `series.modified` is true, so an unattended close of a clean series must not
    reach the decision and must not rewrite the file. Without this, "always
    answer yes" would be indistinguishable from "always save on exit".
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    calls = []

    def counting_save_notify():
        calls.append(1)
        return gui_utils.saveNotify()

    monkeypatch.setattr(mw, "saveNotify", counting_save_notify)

    window = main_window
    assert window.field is not None  # a real window, not a stub
    window.series.modified = False
    before = series_jser.read_bytes()

    assert window.close() is True  # closeEvent accepted, not ignored

    assert calls == []
    assert series_jser.read_bytes() == before
