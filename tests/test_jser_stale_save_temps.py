"""Opening a real .jser cleans only abandoned atomic-save temp files."""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes import series as series_mod
from PyReconstruct.modules.datatypes.series import SeriesOpenError


def make_temp(folder, name=".save-abcdef.tmp", age=20 * 60):
    temp = folder / name
    temp.write_bytes(b"unfinished save")
    mtime = time.time() - age
    os.utime(temp, (mtime, mtime))
    return temp


def test_jser_open_removes_stale_save_temp(series_jser):
    stale = make_temp(series_jser.parent)
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert series.sections
        assert not stale.exists()
    finally:
        series.close()


@pytest.mark.parametrize("age", [0, 9 * 60, -60], ids=["fresh", "recent", "future"])
def test_jser_open_keeps_recent_save_temp(series_jser, age):
    recent = make_temp(series_jser.parent, age=age)
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert recent.read_bytes() == b"unfinished save"
    finally:
        series.close()


@pytest.mark.parametrize("name", [
    ".save-abc.tmp", "save-abcdef.tmp", ".save-ABCDEF.tmp",
    ".save-abcdeg.tmp", ".save-abcdef0.tmp", ".save-abcdef.tmp.bak",
    ".save-abcdef.tmp\n", "series.jser.tmp",
])
def test_jser_open_keeps_other_temp_names(series_jser, name):
    other = make_temp(series_jser.parent, name)
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert other.read_bytes() == b"unfinished save"
    finally:
        series.close()


def test_jser_open_ignores_save_temp_removal_error(series_jser, monkeypatch):
    stale = make_temp(series_jser.parent)
    removed = []

    def locked_file(fp):
        removed.append(fp)
        raise OSError("file is locked")

    with monkeypatch.context() as patch:
        patch.setattr(series_mod.os, "remove", locked_file)
        series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert series.sections
        assert removed == [str(stale)]
        assert stale.exists()
    finally:
        series.close()


def test_jser_open_ignores_save_temp_scan_error(series_jser, monkeypatch):
    scans = []

    def inaccessible_folder(folder):
        scans.append(folder)
        raise OSError("folder is inaccessible")

    with monkeypatch.context() as patch:
        patch.setattr(series_mod.os, "scandir", inaccessible_folder)
        series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert series.sections
        assert str(series_jser.parent) in scans
    finally:
        series.close()


@pytest.mark.parametrize("locked_first", [True, False], ids=["locked-first", "locked-last"])
def test_jser_open_removes_other_save_temp_after_removal_error(
    series_jser, monkeypatch, locked_first
):
    locked = make_temp(series_jser.parent, ".save-aaaaaa.tmp")
    removable = make_temp(series_jser.parent, ".save-bbbbbb.tmp")
    real_remove = series_mod.os.remove
    real_scandir = series_mod.os.scandir

    def remove_unlocked(fp):
        if Path(fp).name == locked.name:
            raise OSError("file is locked")
        real_remove(fp)

    @contextmanager
    def ordered_scandir(folder):
        # Exercise both orders explicitly: the outer scan handler alone would
        # abort this folder when the locked file comes first.
        with real_scandir(folder) as entries:
            yield iter(sorted(
                entries, key=lambda entry: entry.name == locked.name,
                reverse=locked_first,
            ))

    with monkeypatch.context() as patch:
        patch.setattr(series_mod.os, "remove", remove_unlocked)
        patch.setattr(series_mod.os, "scandir", ordered_scandir)
        series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert series.sections
        assert locked.exists()
        assert not removable.exists()
    finally:
        series.close()


def test_jser_open_removes_eleven_minute_old_save_temp(series_jser):
    stale = make_temp(series_jser.parent, age=11 * 60)
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert series.sections
        assert not stale.exists()
    finally:
        series.close()


def test_jser_open_sweeps_hidden_working_folder(series_jser, monkeypatch):
    # The completion reporter can process events, including a save into the
    # freshly loaded working folder. Both folders are swept after it finishes.
    temps = []

    class FinishingReporter(NullProgressReporter):
        def finish(self):
            hidden_dir = series_jser.parent / f".{series_jser.stem}"
            temps.append(make_temp(hidden_dir))
            temps.append(make_temp(hidden_dir, ".save-123456.tmp", age=0))

    calls = []
    original = series_mod._sweepStaleSaveTemps

    def record_sweep(*folders):
        calls.append(folders)
        original(*folders)

    monkeypatch.setattr(series_mod, "_sweepStaleSaveTemps", record_sweep)
    series = Series.openJser(str(series_jser), progress=FinishingReporter)
    try:
        assert len(calls) == 1
        assert not temps[0].exists()
        assert temps[1].exists()
    finally:
        series.close()


def test_jser_open_keeps_matching_directories_and_symlinks(series_jser):
    folder = series_jser.parent / ".save-abcdef.tmp"
    folder.mkdir()
    target = make_temp(series_jser.parent, "unrelated.txt")
    link = series_jser.parent / ".save-123456.tmp"
    link.symlink_to(target)
    old = time.time() - 20 * 60
    os.utime(folder, (old, old))
    os.utime(link, (old, old), follow_symlinks=False)
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert folder.is_dir()
        assert link.is_symlink()
        assert target.read_bytes() == b"unfinished save"
    finally:
        series.close()


def test_jser_open_failure_keeps_stale_save_temp(series_jser):
    stale = make_temp(series_jser.parent)
    series_jser.write_bytes(b"invalid JSON")
    with pytest.raises(SeriesOpenError):
        Series.openJser(str(series_jser), progress=NullProgressReporter)
    assert stale.exists()


def test_jser_open_cancellation_keeps_stale_save_temp(series_jser):
    stale = make_temp(series_jser.parent)

    class CancelingReporter(NullProgressReporter):
        def was_canceled(self):
            return True

    assert Series.openJser(str(series_jser), progress=CancelingReporter) is None
    assert stale.exists()


def test_jser_open_declined_merge_keeps_stale_save_temp(shapes1_jser):
    data = json.loads(shapes1_jser.read_text())
    for section in data["sections"]:
        if section is None:
            continue
        contours = section["contours"]
        for old, new in (("star", "my trace"), ("square", "my,trace")):
            if old in contours:
                contours[new] = contours.pop(old)
    assert series_mod.contourNameCollisions(data) == {
        "my_trace": ["my trace", "my,trace"],
    }
    shapes1_jser.write_text(json.dumps(data))
    before = shapes1_jser.read_bytes()
    stale = make_temp(shapes1_jser.parent)

    class DecliningNotifier(NullNotifier):
        def __init__(self):
            self.questions = []

        def confirm(self, message, title="Confirm"):
            self.questions.append(message)
            return False

    notifier = DecliningNotifier()
    result = Series.openJser(
        str(shapes1_jser), progress=NullProgressReporter, notifier=notifier
    )
    assert result is None
    assert len(notifier.questions) == 1
    assert "my_trace" in notifier.questions[0]
    assert stale.exists()
    assert shapes1_jser.read_bytes() == before
    assert not (shapes1_jser.parent / f".{shapes1_jser.stem}").exists()


def test_jser_recovery_without_reading_jser_keeps_save_temps(series_jser):
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    stale = make_temp(series_jser.parent)
    hidden_stale = make_temp(Path(series.hidden_dir))
    # Recovery deliberately does not read the .jser; a damaged master must not
    # block access to the recoverable working data or trigger this sweep.
    series_jser.write_bytes(b"invalid JSON")
    recovered = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert recovered.leave_open
        assert stale.exists()
        assert hidden_stale.exists()
    finally:
        series.close()
