"""Independent series backing up into one folder keep both copies."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.main.main_window import MainWindow


@pytest.fixture
def copies(tmp_path):
    source = Path(__file__).resolve().parents[1] / "dev/assets/checker/files/shapes1.jser"
    backups = tmp_path / "backups"
    backups.mkdir()
    opened = []
    try:
        for marker in ("first", "second"):
            folder = tmp_path / marker
            folder.mkdir()
            fp = folder / "copy.jser"
            shutil.copyfile(source, fp)
            series = Series.openJser(str(fp), progress=NullProgressReporter)
            opened.append(series)
            series.setSettingsStore(DictSettingsStore())
            series.setProgressReporter(NullProgressReporter)
            series.setNotifier(NullNotifier())
            series.code = "ABC"
            series.options["concurrent_backup_marker"] = marker
            series.setBackupUsesDefaults(False)
            series.setOption("backup_dir", str(backups))
            for part in ("date", "time", "user"):
                series.setOption(f"backup_{part}", False)
            series.saveJser()
        yield opened, backups
    finally:
        for series in opened:
            series.leave_open = False
            series.close()


@pytest.mark.parametrize("from_saved", [True, False])
def test_concurrent_backups_keep_both_series(copies, monkeypatch, from_saved):
    series_copies, backups = copies
    selected = Barrier(2, timeout=10)
    get_path = Series.getBackupPath

    # Both windows have selected the same available name before either writes.
    # A retry must not wait for a window that has already finished its backup.
    for series in series_copies:
        def paused_path(comment="", *, _series=series, **kwargs):
            fp = get_path(_series, comment, **kwargs)
            if not getattr(_series, "_backup_name_selected", False):
                _series._backup_name_selected = True
                selected.wait()
            return fp
        monkeypatch.setattr(series, "getBackupPath", paused_path)

    def backup(series):
        return MainWindow.backup(SimpleNamespace(series=series), from_saved=from_saved)

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(backup, series_copies))

    assert len(set(paths)) == 2
    assert {p.name for p in backups.iterdir()} == {"ABC.jser", "ABC-01.jser"}
    markers = [
        json.loads(Path(fp).read_bytes())["series"]["options"]["concurrent_backup_marker"]
        for fp in paths
    ]
    assert markers == ["first", "second"]
    if from_saved:
        for fp, series in zip(paths, series_copies):
            assert Path(fp).read_bytes() == Path(series.jser_fp).read_bytes()


@pytest.mark.parametrize("from_saved", [True, False])
@pytest.mark.parametrize("occupied", ["files", "directory_and_symlink"])
def test_backup_skips_occupied_names(copies, from_saved, occupied):
    series_copies, backups = copies
    first = backups / "ABC.jser"
    second = backups / "ABC-01.jser"
    if occupied == "files":
        first.write_bytes(b"existing first backup")
        second.write_bytes(b"existing second backup")
    else:
        first.mkdir()
        try:
            second.symlink_to(backups / "missing.jser")
        except OSError as error:
            pytest.skip(f"Symlink creation is unavailable: {error}")

    fp = MainWindow.backup(SimpleNamespace(series=series_copies[0]), from_saved=from_saved)

    assert fp == str(backups / "ABC-02.jser")
    assert json.loads(Path(fp).read_bytes())["series"]["options"]["concurrent_backup_marker"] == "first"
    if occupied == "files":
        assert first.read_bytes() == b"existing first backup"
        assert second.read_bytes() == b"existing second backup"
    else:
        assert first.is_dir()
        assert second.is_symlink()
        assert not (backups / "missing.jser").exists()


@pytest.mark.parametrize("from_saved", [True, False])
def test_failed_backup_removes_its_reservation(copies, monkeypatch, from_saved):
    series_copies, backups = copies
    series = series_copies[0]
    saved = Path(series.jser_fp).read_bytes()
    existing = backups / "ABC.jser"
    existing.write_bytes(b"existing backup")

    def failed_write(fp):
        Path(fp).write_bytes(b"partial backup")
        raise OSError("backup write failed")

    with monkeypatch.context() as patch:
        if from_saved:
            patch.setattr(shutil, "copyfile", lambda src, dst: failed_write(dst))
        else:
            patch.setattr(series, "saveJser", failed_write)
        with pytest.raises(OSError, match="backup write failed"):
            MainWindow.backup(SimpleNamespace(series=series), from_saved=from_saved)

    assert list(backups.iterdir()) == [existing]
    assert existing.read_bytes() == b"existing backup"
    assert Path(series.jser_fp).read_bytes() == saved
    fp = MainWindow.backup(SimpleNamespace(series=series), from_saved=from_saved)
    assert fp == str(backups / "ABC-01.jser")
    assert json.loads(Path(fp).read_bytes())["series"]["options"]["concurrent_backup_marker"] == "first"


@pytest.mark.parametrize("from_saved", [True, False])
def test_empty_backup_name_keeps_jser_extension(copies, from_saved):
    series_copies, backups = copies
    for series in series_copies:
        for part in ("prefix", "series", "filename", "date", "time", "user", "suffix"):
            series.setOption(f"backup_{part}", False)

    first = MainWindow.backup(SimpleNamespace(series=series_copies[0]), from_saved=from_saved)
    first_bytes = Path(first).read_bytes()
    second = MainWindow.backup(SimpleNamespace(series=series_copies[1]), from_saved=from_saved)

    assert Path(first).name == ".jser"
    assert Path(second).name == "-01.jser"
    assert {p.name for p in backups.iterdir()} == {".jser", "-01.jser"}
    assert Path(first).read_bytes() == first_bytes
    assert json.loads(Path(second).read_bytes())["series"]["options"]["concurrent_backup_marker"] == "second"
