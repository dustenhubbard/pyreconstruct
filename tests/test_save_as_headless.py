"""Headless save-as for a never-saved series.

`saveAsToJser` calls `FileDialog.get` with no offscreen branch: on the
offscreen platform the native dialog has no window manager to dismiss it, so
the call never returns. The `main_window_dialogs` fixture neutralizes this by
replacing `FileDialog.get` with `DialogRecorder.fileDialogGet`, which ordinarily
returns `""` -- the same as a cancelled dialog. That keeps the suite from
hanging, but it also means every call to `saveAsToJser` exits early at the
`if not new_jser_fp: return` guard, and the save never completes.

`fileDialogGet` now pops from `recorder.file_responses` when the queue is
non-empty, which lets a test supply the destination path without showing any
UI. The test below uses that queue to exercise the full save path:

1. The `main_window` fixture opens a real MainWindow on a copied fixture series.
   Resetting `series.jser_fp` to `""` puts it in the same state as a series
   created with `Series.new()` and never saved: the hidden directory exists,
   but there is no `.jser` on disk yet.

2. A destination path is pushed onto `file_responses`.

3. `saveAsToJser()` is called.  Without the queue fix it would return
   immediately; with it, `series.move()` relocates the hidden directory,
   `series.saveJser()` writes the file, and the series reports clean.

4. The assertion on the new path confirms the full write path ran, not just
   that the method returned.
"""

import pytest

pytestmark = pytest.mark.gui


def test_save_as_headless_writes_jser(
    tmp_path, main_window, main_window_dialogs
):
    """save-as on a never-saved series writes the .jser to the given path.

    The fact that this test finishes is the primary guard: before the
    `file_responses` queue existed, `saveAsToJser` silently returned without
    writing anything (the dialog stub returned `""`), so the assertion on the
    destination path would always fail.
    """
    dest = tmp_path / "saved_as" / "newseries.jser"
    dest.parent.mkdir(parents=True, exist_ok=True)

    window = main_window

    # Simulate a never-saved series: jser_fp is empty, but the hidden
    # working directory already exists (exactly the state Series.new() leaves).
    window.series.jser_fp = ""

    # Script the file dialog to return the destination path.
    main_window_dialogs.file_responses.append(str(dest))

    window.saveAsToJser()

    assert dest.exists(), (
        "saveAsToJser did not write the .jser file; the dialog stub returned "
        "an empty path instead of the queued destination."
    )
    assert window.series.jser_fp == str(dest)
    assert window.series.modified is False
