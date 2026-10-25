"""A Save that fails while the series is being let go keeps the window and the series.

Answer Yes at the save prompt on a close, Quit, opening another series or
New series, and the .jser write fails (a full disk, a file that cannot be
written). The Save failed notice shows once, the existing .jser is left as it
was, and the series stays open and modified so the user can free space and
save again. The write used to raise out of `saveToJser`, and `closeEvent`
ignores a close only when that returns "cancel", so the window closed.
"""
import os
import shutil
import sys

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes import store_open
from PyReconstruct.modules.datatypes.series import Series

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _jser_mode(monkeypatch):
    """The plain .jser save, with no local store in the way."""
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)


def _move_a_trace(window):
    for snum in sorted(window.series.sections):
        window.changeSection(snum)
        section = window.field.section
        traces = section.tracesAsList()
        if traces:
            section.selected_traces = [traces[0]]
            section.translateTraces(4.0, 2.0)
            window.seriesModified(True)
            return snum, section.getDict()
    raise AssertionError("no traces")


def _disk_full(window, monkeypatch):
    """Make every write of the series' .jser fail as a full disk does.

    Returns the errors the user is shown, and the errors that reached the
    exception hook (each of those would open a second error window).
    """
    shown = []
    window.series._surfaceSaveError = lambda fp, err, message=None: shown.append(err)
    hooked = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: hooked.append(exc))

    write = series_module._atomicWrite

    def full(fp, data):
        if str(fp) == window.series.jser_fp:
            raise OSError(28, "No space left on device")
        return write(fp, data)

    monkeypatch.setattr(series_module, "_atomicWrite", full)
    return shown, hooked


def _kept(window, outgoing, shown, hooked):
    assert len(shown) == 1 and isinstance(shown[0], OSError)
    assert hooked == []
    assert window.series is outgoing
    assert not outgoing.closed
    assert os.path.isdir(outgoing.hidden_dir)
    assert outgoing.modified is True


def _saved(fp, snum, edited):
    reopened = Series.openJser(str(fp), progress=NullProgressReporter)
    try:
        assert reopened.loadSection(snum).getDict() == edited
    finally:
        reopened.close()


@pytest.mark.parametrize("how", ["close", "quit"])
def test_a_yes_close_that_cannot_write_the_jser_leaves_the_window_open(
    how, main_window, main_window_dialogs, series_jser, monkeypatch,
):
    before = series_jser.read_bytes()
    snum, edited = _move_a_trace(main_window)
    outgoing = main_window.series
    main_window_dialogs.save_response = "yes"

    with monkeypatch.context() as m:
        shown, hooked = _disk_full(main_window, m)
        if how == "close":
            assert main_window.close() is False
        else:
            main_window.quit_act.trigger()

    _kept(main_window, outgoing, shown, hooked)
    assert main_window.isVisible()
    assert series_jser.read_bytes() == before

    # the space is back: the same close now saves the edit and goes
    assert main_window.close() is True
    _saved(series_jser, snum, edited)


@pytest.mark.parametrize("leave", ["open another", "new series"])
def test_leaving_for_another_series_keeps_this_one_when_the_jser_cannot_be_written(
    leave, main_window, main_window_dialogs, series_jser, tmp_path, monkeypatch,
):
    before = series_jser.read_bytes()
    _move_a_trace(main_window)
    outgoing = main_window.series
    main_window_dialogs.save_response = "yes"
    other = tmp_path / "other" / "other.jser"
    other.parent.mkdir()
    shutil.copyfile(series_jser, other)

    with monkeypatch.context() as m:
        shown, hooked = _disk_full(main_window, m)
        if leave == "open another":
            main_window.openSeries(jser_fp=str(other))
        else:
            image = tmp_path / "img0.png"
            image.write_bytes(b"")
            main_window.newSeries(
                image_locations=[str(image)], series_name="new", mag=0.00254, thickness=0.05
            )

    _kept(main_window, outgoing, shown, hooked)
    assert series_jser.read_bytes() == before
    assert not (tmp_path / "new.jser").exists()


def test_a_save_as_at_close_that_cannot_write_leaves_the_window_open(
    main_window, main_window_dialogs, tmp_path, monkeypatch,
):
    """A series never saved asks where to save first; that write failing keeps it too."""
    snum, edited = _move_a_trace(main_window)
    main_window.series.jser_fp = ""
    outgoing = main_window.series
    target = tmp_path / "elsewhere" / "saved.jser"
    target.parent.mkdir()
    main_window_dialogs.save_response = "yes"
    main_window_dialogs.file_responses = [str(target)]

    with monkeypatch.context() as m:
        shown, hooked = _disk_full(main_window, m)
        assert main_window.close() is False

    _kept(main_window, outgoing, shown, hooked)
    assert main_window.isVisible()
    assert not target.exists()

    assert main_window.close() is True
    _saved(target, snum, edited)


# --- the close itself raises --------------------------------------------------

def _held_close(window, monkeypatch):
    """Make the series' close raise, as a working file another program holds open does.

    Returns the errors the user is shown, and the errors that reached the
    exception hook (each of those would open a second error window).
    """
    shown = []
    monkeypatch.setattr(
        window.series, "_surfaceSaveError",
        lambda fp, err, message=None: shown.append(err),
    )
    hooked = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: hooked.append(exc))

    held = window.series.filepath

    def refused():
        raise PermissionError(13, "Permission denied", held)

    monkeypatch.setattr(window.series, "close", refused)
    return shown, hooked


@pytest.mark.parametrize("how", ["close", "quit"])
def test_a_close_that_raises_leaves_the_window_open(
    how, main_window, main_window_dialogs, series_jser, monkeypatch,
):
    snum, edited = _move_a_trace(main_window)
    outgoing = main_window.series
    main_window_dialogs.save_response = "yes"

    with monkeypatch.context() as m:
        shown, hooked = _held_close(main_window, m)
        if how == "close":
            assert main_window.close() is False
        else:
            main_window.quit_act.trigger()

    assert len(shown) == 1 and isinstance(shown[0], PermissionError)
    assert hooked == []
    assert main_window.series is outgoing
    assert not outgoing.closed
    assert os.path.isdir(outgoing.hidden_dir)
    assert main_window.isVisible()

    # the series is still the one in the window, and it still saves
    main_window.field.section.save()
    assert main_window.saveToJser() is None
    assert outgoing.modified is False

    # the file is free again: the same close now goes
    assert main_window.close() is True
    assert outgoing.closed
    _saved(series_jser, snum, edited)


def test_a_close_that_raises_drops_a_pending_restart(
    main_window, main_window_dialogs, monkeypatch,
):
    """A refused close resets the restart flag, as a canceled one does."""
    _move_a_trace(main_window)
    main_window_dialogs.save_response = "yes"
    main_window.restart_mainwindow = True

    with monkeypatch.context() as m:
        _held_close(main_window, m)
        assert main_window.close() is False

    assert main_window.restart_mainwindow is False
