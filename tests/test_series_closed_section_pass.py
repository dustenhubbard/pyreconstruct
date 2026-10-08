"""A section pass stops once its series is closed under it.

Every pass that shows a progress dialog runs the event loop on each update,
and another series can open there (a .jser opened from the Finder reaches the
window during any of them). Opening it closes this series and deletes its
working files, and the pass then failed on the next section it read, with a
FileNotFoundError and the app's error window.

What is pinned here:

  * a pass whose series closes at a progress update reads no further section
    and raises SeriesClosedError, which is still a FileNotFoundError
  * the progress dialog is finished on the way out
  * a series closed with leave_open set (its files kept for a series opened
    into the same folder) stops the same way
  * a write pass stopped that way is not quiet: the app's exception hook
    shows and logs it, naming the series (only the read-only clean-up scans
    end without a word; see test_cleanup_lists_series_switch.py)
  * a close that a held working file refuses deletes none of the series'
    files: the series stays open, and a pass over it reads every section
  * a close that cannot clear a file once its files are out of place still
    closes the series, so nothing is left half-deleted under its name
  * the folder moved aside is never the working folder itself, even for a
    series whose folder has the name the move would pick
  * close deletes only the files directly in the working folder: a folder
    in it (a backup folder set there, or any other) keeps all it holds, and
    a held file refuses that close with every file in place too
"""
import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter


@pytest.fixture
def series(series_jser):
    from PyReconstruct.modules.datatypes.series import Series
    opened = Series.openJser(str(series_jser), progress=NullProgressReporter)
    yield opened
    opened.leave_open = False
    opened.close()


def _closes_at(series, update, leave_open=False):
    """Close the series at the given progress update of its next pass.

    Returns the progress values reported and whether the pass finished it.
    """
    seen = {"reported": [], "finished": False}

    class Closes(NullProgressReporter):
        def set_progress(self, percent):
            seen["reported"].append(percent)
            if len(seen["reported"]) == update:
                series.leave_open = leave_open
                series.close()

        def finish(self):
            seen["finished"] = True

    series.setProgressReporter(Closes)
    return seen


@pytest.mark.parametrize("leave_open", [False, True])
def test_a_pass_stops_before_reading_a_closed_series(
    series, monkeypatch, leave_open
):
    from PyReconstruct.modules.datatypes.series import (
        Series,
        SeriesClosedError,
    )
    assert len(series.sections) > 2
    loaded = []
    load = Series.loadSection
    monkeypatch.setattr(
        Series, "loadSection",
        lambda self, n: loaded.append(n) or load(self, n),
    )
    seen = _closes_at(series, update=2, leave_open=leave_open)

    visited = []
    with pytest.raises(SeriesClosedError) as raised:
        for snum, _section in series.enumerateSections(message="Scanning..."):
            visited.append(snum)

    assert isinstance(raised.value, FileNotFoundError)
    assert visited == loaded == sorted(series.sections)[:1]
    assert seen["finished"]


def test_a_write_pass_stopped_part_way_is_reported(
    series, monkeypatch, tmp_path
):
    import sys
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    from PyReconstruct.modules.gui.utils import errors
    shown, printed = [], []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda summary, report, *a, **k: shown.append(report) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    log = tmp_path / "log.txt"
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: str(log))
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: printed.append(a))
    # an object on several sections, so the copy saves some and not others
    name = "d03p14"
    assert len(series.getObjectSections([name])) > 2
    # leave_open keeps the working files, so the saved part of the copy stays
    _closes_at(series, update=2, leave_open=True)

    try:
        series.copyObjects([name])
    except SeriesClosedError:
        errors.customExcepthook(*sys.exc_info())
    else:
        pytest.fail("the copy ran on after its series closed")

    assert len(shown) == 1 and len(printed) == 1
    assert series.name in shown[0] and "part-way" in shown[0]
    assert log.exists() and "SeriesClosedError" in log.read_text()


def _locks_a_later_file(series, monkeypatch, holds_folder):
    """Make the working file close removes last refuse to go.

    A file held open on Windows (another program, a sync client) cannot be
    removed, and neither it nor its folder can be renamed while it is held:
    holds_folder. Without it, only the removal fails.
    """
    import os
    hidden_dir = series.hidden_dir
    names = [
        f for f in os.listdir(hidden_dir)
        if os.path.isfile(os.path.join(hidden_dir, f))
    ]
    assert len(names) > 2
    locked = names[-1]
    remove, unlink, rename, replace = (
        os.remove, os.unlink, os.rename, os.replace
    )

    def refused(path):
        raise PermissionError(13, "Permission denied", path)

    def removal(real):
        def call(path, *args, **kwargs):
            if os.path.basename(path) == locked:
                refused(path)
            return real(path, *args, **kwargs)
        return call

    def move(real):
        def call(src, dst, *args, **kwargs):
            if holds_folder and (
                os.path.normpath(src) == hidden_dir
                or os.path.basename(src) == locked
            ):
                refused(src)
            return real(src, dst, *args, **kwargs)
        return call

    monkeypatch.setattr(os, "remove", removal(remove))
    monkeypatch.setattr(os, "unlink", removal(unlink))
    monkeypatch.setattr(os, "rename", move(rename))
    monkeypatch.setattr(os, "replace", move(replace))


def test_a_close_a_held_file_refuses_deletes_nothing(series, monkeypatch):
    import os
    before = sorted(os.listdir(series.hidden_dir))
    _locks_a_later_file(series, monkeypatch, holds_folder=True)

    with pytest.raises(PermissionError):
        series.close()
    monkeypatch.undo()

    assert sorted(os.listdir(series.hidden_dir)) == before
    assert not series.closed
    visited = [
        snum for snum, _section
        in series.enumerateSections(message="Scanning...")
    ]
    assert visited == sorted(series.sections)


def test_a_close_that_cannot_clear_a_file_still_closes(series, monkeypatch):
    import os
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    _locks_a_later_file(series, monkeypatch, holds_folder=False)

    series.close()
    monkeypatch.undo()

    assert series.closed
    assert not os.path.exists(series.hidden_dir)
    with pytest.raises(SeriesClosedError):
        for _snum, _section in series.enumerateSections(message="Scanning..."):
            pass


def test_the_folder_moved_aside_is_never_the_working_folder(
    series_jser, monkeypatch
):
    import os
    import secrets
    from PyReconstruct.modules.datatypes.series import Series
    # a series whose working folder is named as the move would name it
    jser = series_jser.with_name("closing-deadbeef.jser")
    series_jser.rename(jser)
    series = Series.openJser(str(jser), progress=NullProgressReporter)
    assert os.path.basename(series.hidden_dir) == ".closing-deadbeef"
    tokens = iter(["deadbeef", "cafef00d"])
    monkeypatch.setattr(secrets, "token_hex", lambda n: next(tokens))
    _locks_a_later_file(series, monkeypatch, holds_folder=False)

    series.close()
    monkeypatch.undo()

    assert series.closed
    assert not os.path.exists(series.hidden_dir)


def _with_folders(series):
    """Put a backup folder and an unrelated nested folder in the working folder."""
    import os
    backups = os.path.join(series.hidden_dir, "series-backups")
    os.mkdir(backups)
    with open(os.path.join(backups, "series-snapshot.jser"), "w") as f:
        f.write("snapshot")
    nested = os.path.join(series.hidden_dir, "notes", "deeper")
    os.makedirs(nested)
    with open(os.path.join(nested, "note.txt"), "w") as f:
        f.write("note")
    return {
        os.path.join(backups, "series-snapshot.jser"): "snapshot",
        os.path.join(nested, "note.txt"): "note",
    }


def _contents(files):
    contents = {}
    for path in files:
        with open(path) as f:
            contents[path] = f.read()
    return contents


def test_a_close_keeps_the_folders_in_the_working_folder(series):
    import os
    parent = os.path.dirname(series.hidden_dir)
    others = set(os.listdir(parent))
    kept = _with_folders(series)

    series.close()

    assert series.closed
    assert _contents(kept) == kept
    assert sorted(os.listdir(series.hidden_dir)) == ["notes", "series-backups"]
    assert set(os.listdir(parent)) == others


def test_a_close_a_held_file_refuses_keeps_files_beside_folders(
    series, monkeypatch
):
    import os
    kept = _with_folders(series)
    before = sorted(os.listdir(series.hidden_dir))
    parent = os.path.dirname(series.hidden_dir)
    others = set(os.listdir(parent))
    _locks_a_later_file(series, monkeypatch, holds_folder=True)

    with pytest.raises(PermissionError):
        series.close()
    monkeypatch.undo()

    assert sorted(os.listdir(series.hidden_dir)) == before
    assert _contents(kept) == kept
    assert set(os.listdir(parent)) == others
    assert not series.closed
    visited = [
        snum for snum, _section
        in series.enumerateSections(message="Scanning...")
    ]
    assert visited == sorted(series.sections)
