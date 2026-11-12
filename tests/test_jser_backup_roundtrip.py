"""Rejected files stay untouched, and backups reopen with the intended edits."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, store_open
from PyReconstruct.modules.datatypes.series import SeriesOpenError, SeriesSaveError
from PyReconstruct.modules.gui.main.main_window import MainWindow

ORIGINAL_POINTS = [(1.25, 3.0), (2.5, 6.0), (4.0, 3.0)]
EDITED_POINTS = [(10.25, 30.0), (20.5, 60.0), (40.0, 30.0)]


def document():
    section = {
        "src": "image.tif",
        "mag": 0.00254,
        "thickness": 0.05,
        "contours": {
            "axon": [[
                [1.25, 2.5, 4.0], [3.0, 6.0, 3.0], [12, 34, 56],
                True, False, False, ["none", "none"], ["original"],
            ]],
        },
    }
    return {
        "series": {"current_section": 1},
        "sections": [None, section, None, None, copy.deepcopy(section)],
        "log": "Date, Time, User, Obj, Sections, Event",
    }


@pytest.fixture
def open_series(monkeypatch):
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    opened = []

    def open_at(path):
        series = Series.openJser(
            str(path), progress=NullProgressReporter, notifier=NullNotifier(),
        )
        opened.append(series)
        series.setProgressReporter(NullProgressReporter)
        series.setNotifier(NullNotifier())
        series.setSettingsStore(DictSettingsStore())
        return series

    yield open_at

    for series in reversed(opened):
        series.leave_open = False
        series.close()


@pytest.fixture
def backed_up_series(tmp_path, open_series):
    path = tmp_path / "source.jser"
    path.write_text(json.dumps(document()), encoding="utf-8")
    series = open_series(path)
    series.code = "IO"
    folder = tmp_path / "backups"
    folder.mkdir()
    series.setBackupUsesDefaults(False)
    series.setOption("backup_dir", str(folder))
    for part in ("prefix", "filename", "date", "time", "user", "suffix"):
        series.setOption("backup_" + part, False)
    series.setOption("backup_series", True)
    series.setOption("backup_delimiter", "-")
    series.saveJser()
    return series


def edit(series):
    section = series.loadSection(1)
    trace = section.contours["axon"][0]
    trace.points = list(EDITED_POINTS)
    trace.tags = {"edited", "café"}
    section.save()
    series.user_columns = {"Stage": ["raw", "reviewed"]}
    series.addLog("axon", 1, "Backup round trip café")
    series.modified = True
    series.unsaved_series_data = True


def assert_edited(series):
    assert sorted(series.sections) == [1, 4]
    trace = series.loadSection(1).contours["axon"][0]
    assert trace.points == EDITED_POINTS
    assert trace.tags == {"edited", "café"}
    assert series.loadSection(4).contours["axon"][0].points == ORIGINAL_POINTS
    assert series.user_columns == {"Stage": ["raw", "reviewed"]}
    assert "Backup round trip café" in str(series.getFullHistory())


def test_a_manual_backup_reopens_with_edits_without_saving_the_source(
    backed_up_series, open_series,
):
    series = backed_up_series
    primary = Path(series.jser_fp)
    original = primary.read_bytes()
    index = series._jser_splice_index
    edit(series)

    backup = MainWindow.backup(SimpleNamespace(series=series), comment="edited")

    assert Path(backup).name == "IO-edited.jser"
    assert primary.read_bytes() == original
    assert series.jser_fp == str(primary)
    assert series._jser_splice_index is index
    assert series.modified is True
    assert series.unsaved_series_data is True
    assert_edited(open_series(backup))

    series.saveJser()
    assert series.unsaved_series_data is False
    series.close()
    assert_edited(open_series(primary))


def test_saved_backups_copy_the_last_save_and_keep_earlier_backups(
    backed_up_series, open_series,
):
    series = backed_up_series
    primary = Path(series.jser_fp)
    saved = primary.read_bytes()
    edit(series)
    window = SimpleNamespace(series=series)

    backups = [
        MainWindow.backup(window, comment="saved", from_saved=True)
        for _ in range(3)
    ]

    assert [Path(path).name for path in backups] == [
        "IO-saved.jser", "IO-saved-01.jser", "IO-saved-02.jser",
    ]
    for path in backups:
        assert Path(path).read_bytes() == saved
    reopened = open_series(backups[-1])
    assert sorted(reopened.sections) == [1, 4]
    assert reopened.loadSection(1).contours["axon"][0].points == ORIGINAL_POINTS
    assert reopened.loadSection(1).contours["axon"][0].tags == {"original"}
    assert "Backup round trip café" not in str(reopened.getFullHistory())
    assert primary.read_bytes() == saved
    assert series.unsaved_series_data is True
    assert series.modified is True


@pytest.mark.parametrize("source_path", ["empty", "missing"])
def test_backup_without_a_saved_file_serializes_the_working_data(
    backed_up_series, open_series, source_path,
):
    series = backed_up_series
    primary = Path(series.jser_fp)
    primary.unlink()
    if source_path == "empty":
        series.jser_fp = ""
    edit(series)

    backup = MainWindow.backup(
        SimpleNamespace(series=series), comment="unsaved", from_saved=True,
    )

    assert not primary.exists()
    assert series.jser_fp == ("" if source_path == "empty" else str(primary))
    assert series.unsaved_series_data is True
    assert_edited(open_series(backup))


def test_a_failed_backup_keeps_the_source_and_can_be_retried(
    backed_up_series, open_series,
):
    series = backed_up_series
    primary = Path(series.jser_fp)
    original = primary.read_bytes()
    index = series._jser_splice_index
    edit(series)
    last = Path(series.hidden_dir) / series.sections[4]
    good_section = last.read_bytes()
    last.write_bytes(b"{broken")
    window = SimpleNamespace(series=series)

    with pytest.raises(SeriesSaveError):
        MainWindow.backup(window, comment="retry")

    assert primary.read_bytes() == original
    assert list(Path(series.backupFolder()).iterdir()) == []
    assert series._jser_splice_index is index
    assert series.jserSaveRunning() is False
    assert series.unsaved_series_data is True

    last.write_bytes(good_section)
    backup = MainWindow.backup(window, comment="retry")

    assert Path(backup).name == "IO-retry.jser"
    assert_edited(open_series(backup))
    assert primary.read_bytes() == original


@pytest.mark.parametrize("invalid", [
    b"{truncated",
    b"[]",
    b"null",
    b"{}",
    b'{"probe.ser": {}}',
    b'{"probe.1": {"contours": {}}}',
    b'{"series": [], "sections": [{"contours": {}}]}',
    b'{"series": {}, "sections": {}}',
    b'{"series": {}, "sections": []}',
    b'{"series": {}, "sections": [null]}',
], ids=[
    "invalid-json", "array-root", "null-root", "empty-object",
    "legacy-no-sections", "legacy-no-series", "non-object-series",
    "non-array-sections", "empty-sections", "only-null-sections",
])
def test_rejected_files_leave_the_input_and_neighboring_work_untouched(
    tmp_path, invalid,
):
    path = tmp_path / "café.jser"
    path.write_bytes(invalid)
    hidden = tmp_path / ".café"
    hidden.mkdir()
    kept = hidden / "unsaved.1"
    kept.write_bytes(b"work from an earlier open")
    before = sorted(tmp_path.iterdir())

    with pytest.raises(SeriesOpenError, match="not a valid series file"):
        Series.openJser(
            str(path), progress=NullProgressReporter, notifier=NullNotifier(),
        )

    assert path.read_bytes() == invalid
    assert kept.read_bytes() == b"work from an earlier open"
    assert list(hidden.iterdir()) == [kept]
    assert sorted(tmp_path.iterdir()) == before


@pytest.mark.parametrize("named_keys", [False, True], ids=["extensions", "filenames"])
def test_legacy_files_save_and_reopen_with_sparse_section_numbers(
    tmp_path, open_series, named_keys,
):
    doc = document()
    prefix = "old." if named_keys else ""
    legacy = {prefix + "ser": doc["series"]}
    legacy.update({
        prefix + str(n): section
        for n, section in enumerate(doc["sections"]) if section is not None
    })
    path = tmp_path / "legacy.jser"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    series = open_series(path)
    edit(series)

    series.saveJser()
    series.close()
    reopened = open_series(path)

    assert_edited(reopened)
    saved = json.loads(path.read_bytes())
    assert list(saved) == ["sections", "series", "log"]
    assert [n for n, section in enumerate(saved["sections"]) if section is not None] == [1, 4]
