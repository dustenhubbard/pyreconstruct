"""The startup prompts, for a GUI session with nobody sitting in front of it.

`user_is_present()` answers "can a real user see and answer a blocking dialog".
It was answering that question with `QApplication.instance() and not
qt_offscreen`, which is a test for *how Qt is drawing*, not for whether anyone
is watching. The two come apart for a scripted GUI session: a click-test
harness, a `codex exec` computer-use run, a screenshot script. Those launch on a
real platform, so `qt_offscreen` is False and the predicate says True, and then
`MainWindow.openSeries` raises a modal that no unattended script can dismiss.

Reproduced before the fix, with the fixture series (whose `src_dir` does not
resolve) and `qt_offscreen` flipped to False to stand in for an on-screen
launch: `_ensureImagesAvailable` reached `changeSrcDir(notify=True)` and the
"Images Not Found" `QMessageBox.question` fired. In a real unattended run that
is a permanent stall, exactly the way an offscreen one was before
`user_is_present()` existed.

`PYRECON_UNATTENDED=1` is the missing half of the predicate: the caller
asserting that nobody is at the keyboard. It is checked inside
`user_is_present()` rather than at the one call site the bug was found at,
because the images prompt is only the *first* of the three startup blockers --
`setSeriesCode(cancelable=False)` and the unscaled-zarr question sit right
behind it, guarded by the same predicate. Fixing the call site alone would move
the hang down two lines.

Both halves are pinned here, and the second one is the one that matters for
review: with the variable unset, an on-screen user still gets the prompt, byte
for byte the behavior they had before.
"""

import pytest

from PyReconstruct.modules.gui.utils import utils as gui_utils

pytestmark = pytest.mark.gui


UNATTENDED_ENV = gui_utils.UNATTENDED_ENV_VAR


# --- the predicate itself ----------------------------------------------------

def test_the_variable_is_named_what_the_documentation_says():
    """The name is the public contract, so spell it out once here.

    Everything else in this file addresses it through the constant, which would
    keep passing if the constant were renamed. `docs/DEV_UV.md`, the changelog
    fragment and every script anyone writes against this hold the literal
    string, and they cannot be renamed by an IDE.
    """
    assert gui_utils.UNATTENDED_ENV_VAR == "PYRECON_UNATTENDED"


def test_unattended_makes_the_predicate_false_on_a_real_platform(
    qapp, monkeypatch
):
    """The new half. A real platform, a real QApplication, and still no user.

    This is the case the old predicate got wrong: everything Qt can observe
    says "on screen", and the only thing that knows better is the caller.

    The `delenv` is not decoration. Measured: with `PYRECON_UNATTENDED=1`
    exported into the whole run, this was the only test in 5769 that failed,
    and it failed on its own first line rather than on anything it was written
    to check. Every test in this file that depends on the variable's value now
    sets it, in both directions.
    """
    monkeypatch.delenv(UNATTENDED_ENV, raising=False)
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    assert gui_utils.user_is_present() is True

    monkeypatch.setenv(UNATTENDED_ENV, "1")
    assert gui_utils.user_is_present() is False


def test_the_variable_is_read_at_call_time(qapp, monkeypatch):
    """Set, unset and set again within one process, like `qt_offscreen`.

    Read at call time rather than captured at import, so a test can flip it and
    so a caller can set it after the module is loaded.
    """
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)

    monkeypatch.setenv(UNATTENDED_ENV, "1")
    assert gui_utils.user_is_present() is False
    monkeypatch.delenv(UNATTENDED_ENV)
    assert gui_utils.user_is_present() is True
    monkeypatch.setenv(UNATTENDED_ENV, "1")
    assert gui_utils.user_is_present() is False


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "2"])
def test_only_an_explicit_1_opts_out(qapp, monkeypatch, value):
    """Anything other than `1` leaves the prompts alone.

    Same spelling as `PYRECON_FORCE_FROZEN` and `PYRECON_JSER_PRETTY`, the two
    environment switches this codebase already has: an exact `== "1"`, so a
    stale `PYRECON_UNATTENDED=0` in a shell profile cannot silently disable a
    real user's dialogs.
    """
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    monkeypatch.setenv(UNATTENDED_ENV, value)
    assert gui_utils.user_is_present() is True


def test_unattended_does_not_resurrect_a_user_offscreen(qapp, monkeypatch):
    """Offscreen stays False whatever the variable says. Belt and braces."""
    assert gui_utils.qt_offscreen is True
    monkeypatch.delenv(UNATTENDED_ENV, raising=False)
    assert gui_utils.user_is_present() is False
    monkeypatch.setenv(UNATTENDED_ENV, "1")
    assert gui_utils.user_is_present() is False


# --- the window, opened on a series whose images are missing -----------------

@pytest.fixture
def on_screen_window(
    request, qapp, series_jser, qsettings_snapshot, main_window_dialogs,
    monkeypatch,
):
    """Build a `MainWindow` as if the platform were a real one.

    Same recipe as the `main_window` fixture in `conftest.py` -- see its
    docstring for why the What's-new key is written first and why teardown is
    shaped the way it is -- with one difference: `qt_offscreen` is flipped
    *before* construction, so every `user_is_present()` call on the startup path
    takes the interactive branch. That is what makes this a stand-in for a
    scripted on-screen launch rather than the headless one the rest of the suite
    runs.

    Nothing real is drawn. The platform plugin is still `offscreen`; only the
    module-level flag the predicate consults is patched, and every modal is
    already replaced by `main_window_dialogs`' recorder, so no dialog can spin
    an event loop here. That replacement is what makes this test safe to run at
    all: an unreplaced modal offscreen is a permanent stall, which is the whole
    defect under test.

    Parametrized indirectly with the value of `PYRECON_UNATTENDED`: True sets it
    to "1" before the window is built, and the default (no param) clears it, so
    a test that says nothing gets the interactive case. It has to be set before
    construction, not inside the test body, because the prompts fire during
    `MainWindow.__init__`.

    Yields the recorder alongside the window: what the test asserts on is what
    *would* have been shown.
    """
    import sys as _sys

    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP, ORG, current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    if getattr(request, "param", False):
        monkeypatch.setenv(UNATTENDED_ENV, "1")
    else:
        monkeypatch.delenv(UNATTENDED_ENV, raising=False)

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)

    previous_excepthook = _sys.excepthook
    window = MainWindow(str(series_jser))
    try:
        yield window, main_window_dialogs
    finally:
        _sys.excepthook = previous_excepthook
        window.series.modified = False
        window.close()
        window.deleteLater()


def _images_prompts(recorder):
    """The recorded ("Images Not Found", ...) message boxes, if any."""
    return [box for box in recorder.message_boxes if box[0] == "Images Not Found"]


def test_the_fixture_series_really_has_no_images(main_window):
    """The premise, asserted rather than assumed.

    Every test below is vacuous if the images happen to resolve, and they would
    resolve if someone dropped an image directory beside the asset. Both halves
    of the guard's condition are checked: the layer found nothing, and the
    fallback that looks beside the `.jser` finds nothing either.
    """
    assert main_window.field.section_layer.image_found is False
    assert main_window.findImagesBesideJser() is False


def test_an_on_screen_user_still_gets_the_images_prompt(on_screen_window):
    """Half (a): the real user's behavior is unchanged.

    This is the reproduction of the bug *and* the regression guard for the fix,
    which is the same assertion read two ways. Before the fix it passed for the
    wrong reason -- the prompt fired for everyone on a real platform, scripted
    or not. After it, it passes because the caller did not claim to be
    unattended, which is the only case where the prompt is correct.

    A fix that suppressed the modal outright, or that keyed off "is a
    QApplication running", fails here.
    """
    _window, recorder = on_screen_window

    assert _images_prompts(recorder), (
        "an interactive user opening a series with no images must still be "
        "offered the chance to locate them"
    )


@pytest.mark.parametrize("on_screen_window", [True], indirect=True)
def test_an_unattended_launch_is_not_asked_to_locate_the_images(
    on_screen_window
):
    """Half (b): the scripted launch comes up instead of stalling.

    `_ensureImagesAvailable` is still reached and `findImagesBesideJser` still
    runs -- the cheap non-blocking recovery is not skipped, only the question
    is.
    """
    _window, recorder = on_screen_window

    assert _images_prompts(recorder) == []


@pytest.mark.parametrize("on_screen_window", [True], indirect=True)
def test_an_unattended_launch_raises_no_startup_prompt_at_all(on_screen_window):
    """The other two startup blockers, which the same guard covers.

    The images question is the first one `openSeries` reaches, so it is the only
    one a manual click-test ever gets far enough to see. `setSeriesCode`'s
    non-cancelable `QuickDialog` and the unscaled-zarr question are behind it
    and would stall a scripted launch just as completely. Pinning all three here
    is the reason the fix belongs in the predicate rather than at one call site.
    """
    window, recorder = on_screen_window

    assert recorder.message_boxes == []
    assert recorder.dialogs == []
    assert recorder.notices == []
    # and the window still came up whole
    assert window.field is not None
    assert window.menubar is not None
    assert window.actions_initialized is True


def test_change_src_dir_still_prompts_when_asked_to(
    main_window, main_window_dialogs, monkeypatch
):
    """`changeSrcDir(notify=True)` is unchanged; only its caller's guard moved.

    Called directly with `notify=True` it raises the question regardless of the
    predicate, the same as before, and under `PYRECON_UNATTENDED` too. The fix
    deliberately does not push the guard inside the function: `notify` is
    already that function's own "should I ask" parameter, its other caller
    ("Change image directory" on the Series menu) passes False, and a caller
    that has explicitly decided to ask should get to ask. Moving the decision
    inside would make the parameter a lie.
    """
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    monkeypatch.setenv(UNATTENDED_ENV, "1")
    main_window_dialogs.message_boxes.clear()
    main_window_dialogs.message_box_response = None  # falls through to the No branch

    main_window.changeSrcDir(notify=True)

    assert _images_prompts(main_window_dialogs)
