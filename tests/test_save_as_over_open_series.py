"""Save As onto a .jser whose working folder is already in use (fork #498).

`Series.move` clears whatever hidden folder sits at the destination before it
moves the current one there. When that folder belongs to a series open in
another window, or holds a crashed session's unsaved work, clearing it deletes
that work. The in-use check only ran on open, so Save As went straight from
the file dialog to the delete.

Each test opens a second, real series ("other") next to the one in the window,
snapshots its working folder byte for byte, points Save As at `other.jser`, and
checks what is left.
"""

import os
import shutil
import time

import pytest

pytestmark = pytest.mark.gui


def _snapshot(folder):
    """{relative path: bytes} for every file under folder."""
    snap = {}
    for root, _dirs, files in os.walk(folder):
        for f in files:
            fp = os.path.join(root, f)
            with open(fp, "rb") as fh:
                snap[os.path.relpath(fp, folder)] = fh.read()
    return snap


@pytest.fixture
def other_series(tmp_path, series_jser):
    """A second series opened from its own .jser, with its working folder."""
    from PyReconstruct.modules.datatypes import Series

    other_dir = tmp_path / "other_folder"
    other_dir.mkdir()
    other_jser = other_dir / "other.jser"
    shutil.copy(series_jser, other_jser)

    series = Series.openJser(str(other_jser))
    # an unsaved edit that exists only in the working folder
    series.modified = True
    series.save()
    yield series
    shutil.rmtree(series.hidden_dir, ignore_errors=True)


def _heartbeat(folder):
    """What FieldWidget.markTime writes while a window has the series."""
    open(os.path.join(folder, str(round(time.time()))), "w").close()


def test_save_as_refuses_a_series_open_elsewhere(
    main_window, main_window_dialogs, other_series
):
    """A fresh heartbeat means another window owns the folder: refuse."""
    window = main_window
    other_hidden = other_series.hidden_dir
    other_jser = other_series.jser_fp
    _heartbeat(other_hidden)

    before = _snapshot(other_hidden)
    with open(other_jser, "rb") as fh:
        jser_before = fh.read()
    own_jser = window.series.jser_fp
    own_hidden = window.series.hidden_dir

    main_window_dialogs.file_responses.append(other_jser)
    result = window.saveAsToJser()

    assert os.path.isdir(other_hidden), "the other series' working folder was deleted"
    assert _snapshot(other_hidden) == before
    with open(other_jser, "rb") as fh:
        assert fh.read() == jser_before
    assert result == "cancel"
    assert window.series.jser_fp == own_jser
    assert os.path.isdir(own_hidden)
    assert any("open in" in text for _title, text in main_window_dialogs.message_boxes)


def test_save_as_keeps_unsaved_work_when_declined(
    main_window, main_window_dialogs, other_series
):
    """No heartbeat but a .ser: that is crash recovery data. Ask; "no" keeps it."""
    window = main_window
    other_hidden = other_series.hidden_dir
    before = _snapshot(other_hidden)
    own_jser = window.series.jser_fp

    main_window_dialogs.confirm_accepted = False
    main_window_dialogs.file_responses.append(other_series.jser_fp)
    result = window.saveAsToJser()

    assert _snapshot(other_hidden) == before
    assert result == "cancel"
    assert window.series.jser_fp == own_jser
    assert any("unsaved" in text for text in main_window_dialogs.notices)


def test_save_as_replaces_unsaved_work_when_confirmed(
    main_window, main_window_dialogs, other_series
):
    """Saying yes to the question saves over it, as Save As always did."""
    window = main_window
    dest = other_series.jser_fp

    main_window_dialogs.confirm_accepted = True
    main_window_dialogs.file_responses.append(dest)
    window.saveAsToJser()

    assert window.series.jser_fp == dest
    assert window.series.modified is False


def _open_window(jser_fp):
    """A second real MainWindow, built the way the main_window fixture builds one."""
    from PyReconstruct.modules.gui.main import MainWindow

    window = MainWindow(str(jser_fp))
    window._captureListLayout = lambda: None
    return window


def test_save_as_onto_a_series_open_in_another_window(
    tmp_path, series_jser, main_window, main_window_dialogs
):
    """Two real windows: A saves as onto B.jser while B has unsaved work.

    B's working folder, B's .jser, and A's own working folder must all come
    through untouched, and B must still save its own edits afterwards.
    """
    import json
    import sys

    wa = main_window
    b_dir = tmp_path / "B"
    b_dir.mkdir()
    b_jser = b_dir / "B.jser"
    shutil.copy(series_jser, b_jser)

    hook = sys.excepthook
    wb = _open_window(b_jser)
    try:
        b_hidden = wb.series.hidden_dir
        a_hidden = wa.series.hidden_dir
        assert b_hidden != a_hidden

        # B: an unsaved edit on a section it is not showing, and one on the
        # section it is showing, both flushed to its working folder
        cur = wb.series.current_section
        other = next(s for s in wb.series.sections if s != cur)
        sec = wb.series.loadSection(other)
        sec.src = "B_UNSAVED_EDIT.tif"
        sec.save()
        wb.field.section.src = "B_CURRENT_EDIT.tif"
        wb.saveAllData()
        wb.seriesModified(True)

        # A: edits of its own, so a mixed result would show
        a_sec = wa.series.loadSection(other)
        a_sec.src = "A_IMAGE.tif"
        a_sec.save()
        wa.field.section.src = "A_CURRENT.tif"
        wa.saveAllData()  # Save As flushes this first anyway
        wa.seriesModified(True)

        # B's heartbeat, fresh, the way its timer keeps it; then hold the
        # timer so the byte-for-byte comparison below cannot race it
        wb.field.timer.stop()
        wb.field.markTime()

        b_before = _snapshot(b_hidden)
        with open(b_jser, "rb") as fh:
            b_jser_before = fh.read()
        a_before = _snapshot(a_hidden)
        a_jser = wa.series.jser_fp

        # yes to any "save anyway?" question: only the owner check may stop it
        main_window_dialogs.confirm_accepted = True
        main_window_dialogs.file_responses.append(str(b_jser))
        result = wa.saveAsToJser()

        assert result == "cancel"
        assert _snapshot(b_hidden) == b_before, "B's working folder changed"
        with open(b_jser, "rb") as fh:
            assert fh.read() == b_jser_before
        assert wa.series.hidden_dir == a_hidden
        assert wa.series.jser_fp == a_jser
        assert wa.series.modified is True
        # A's own folder is as it was, apart from its own heartbeat ticking
        def _without_heartbeat(snap):
            return {k: v for k, v in snap.items() if not k.isdigit()}
        assert _without_heartbeat(_snapshot(a_hidden)) == _without_heartbeat(a_before)
        assert any(
            "B.jser is open in" in text
            for _title, text in main_window_dialogs.message_boxes
        )

        # B saves, and gets its own work, not a mix with A's
        wb.saveToJser()
        with open(b_jser) as fh:
            data = json.load(fh)
        assert data["sections"][other]["src"] == "B_UNSAVED_EDIT.tif"
        assert data["sections"][cur]["src"] == "B_CURRENT_EDIT.tif"
    finally:
        sys.excepthook = hook
        # if the guard ever regresses, A and B share one folder; do not let
        # both windows try to delete it
        shared = wa.series.hidden_dir == wb.series.hidden_dir
        wb.series.modified = False
        if shared:
            wa.series.leave_open = True
            wb.series.leave_open = True
        wb.close()
        wb.deleteLater()


def test_open_still_refuses_a_series_open_elsewhere(
    main_window, main_window_dialogs, other_series
):
    """The open path shares the heartbeat check; it still aborts on a fresh one."""
    from PyReconstruct.modules.gui.main.main_window import _OPEN_ABORTED

    folder = other_series.hidden_dir
    old = str(round(time.time()) - 60)
    open(os.path.join(folder, old), "w").close()
    new_series_fp, _sections = main_window._scanHiddenSeriesDir(folder)
    assert new_series_fp.endswith(".ser")
    assert main_window_dialogs.message_boxes == []

    os.remove(os.path.join(folder, old))
    _heartbeat(folder)
    assert main_window._scanHiddenSeriesDir(folder) is _OPEN_ABORTED
    assert any(
        "already open in" in text
        for _title, text in main_window_dialogs.message_boxes
    )
