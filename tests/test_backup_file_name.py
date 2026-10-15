"""The backup file name stays inside the backup folder.

`Series.getBackupPath` joins the series code, the series name, the user, the
prefix and suffix strings, the date and time formats, the delimiter and the
comment into one file name. Any of them can hold a path separator, and an
absolute code made `os.path.join` drop the backup folder entirely, so a code
of `/tmp/outside` wrote the backup to `/tmp/outside.jser`.

Every test injects a `DictSettingsStore`; none reads or writes `QSettings`.
Every adversarial path points under `tmp_path`, so even with the fix reverted
nothing lands outside it. Nothing here writes a backup file.
"""

import ntpath
import os
from datetime import datetime as _datetime
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes import series as series_module


class _FixedDatetime(_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 6, 14, 5, tzinfo=tz)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(series_module, "datetime", _FixedDatetime)


def _series(folder, code="ABC"):
    """A series backing up to its own `folder` with the default name parts."""
    store = DictSettingsStore()
    store.set_value(None, "username", "dusten")
    series = Series.__new__(Series)
    series.options = {}
    series.code = code
    series.name = "ABC_copy"
    series.filepath = "/nonexistent/definitely-not-welcome.ser"
    series.setSettingsStore(store)
    series.setBackupUsesDefaults(False)
    series.setOption("backup_dir", str(folder))
    return series


def _assert_inside(fp, folder):
    assert os.path.dirname(fp) == str(folder)
    name = os.path.basename(fp)
    # what Windows would also read as a folder or a drive
    assert not any(c in name for c in "/\\:")
    assert ntpath.splitdrive(name)[0] == ""


def test_an_ordinary_code_keeps_its_file_name(tmp_path):
    fp = _series(tmp_path).getBackupPath(check_existing=False)
    assert fp == str(tmp_path / "ABC-2026-10-06-14-05-dusten.jser")


def test_an_ordinary_comment_keeps_its_file_name(tmp_path):
    fp = _series(tmp_path).getBackupPath("before merge", check_existing=False)
    assert fp == str(tmp_path / "ABC-2026-10-06-14-05-dusten-before-merge.jser")


def test_an_absolute_code_stays_in_the_folder(tmp_path):
    folder = tmp_path / "backups"
    outside = tmp_path / "outside"
    fp = _series(folder, code=str(outside)).getBackupPath(check_existing=False)
    _assert_inside(fp, folder)
    assert not fp.startswith(str(outside))


@pytest.mark.parametrize(
    "code, safe",
    [
        ("A/../B", "A_.._B"),
        ("..\\..\\up", ".._.._up"),
        ("C:\\Windows\\x", "C__Windows_x"),
        ("C:x", "C_x"),
        ("\\\\server\\share\\x", "__server_share_x"),
    ],
)
def test_a_code_with_separators_or_a_drive_stays_in_the_folder(tmp_path, code, safe):
    fp = _series(tmp_path, code=code).getBackupPath(check_existing=False)
    _assert_inside(fp, tmp_path)
    assert os.path.basename(fp) == f"{safe}-2026-10-06-14-05-dusten.jser"


@pytest.mark.parametrize(
    "options",
    [
        {"backup_prefix": True, "backup_prefix_str": "/abs/prefix"},
        {"backup_filename": True},  # the name below
        {"backup_date_str": "%Y/../../%m"},
        {"backup_time_str": "%H\\..\\%M"},
        {"backup_suffix": True, "backup_suffix_str": "../suffix"},
        {"backup_delimiter": "/../"},
    ],
)
def test_every_other_name_part_stays_in_the_folder(tmp_path, options):
    series = _series(tmp_path)
    series.name = "../../name"
    for key, value in options.items():
        series.setOption(key, value)
    _assert_inside(series.getBackupPath(check_existing=False), tmp_path)


def test_a_comment_with_separators_stays_in_the_folder(tmp_path):
    fp = _series(tmp_path).getBackupPath("../../" + str(tmp_path / "x"), check_existing=False)
    _assert_inside(fp, tmp_path)


def test_a_numbered_name_after_an_existing_backup_stays_in_the_folder(tmp_path):
    series = _series(tmp_path, code="A/B")
    (tmp_path / "A_B-2026-10-06-14-05-dusten.jser").write_bytes(b"")
    fp = series.getBackupPath()
    assert fp == str(tmp_path / "A_B-2026-10-06-14-05-dusten-01.jser")


def test_a_save_with_an_absolute_code_backs_up_into_the_folder(tmp_path, monkeypatch):
    from PyReconstruct.modules.gui.main import main_window

    monkeypatch.setattr(main_window, "notify", lambda *a, **k: pytest.fail("no notice expected"))
    folder = tmp_path / "backups"
    folder.mkdir()
    series = _series(folder, code=str(tmp_path / "outside"))
    series.setOption("autobackup", True)
    saved = []
    series.saveJser = lambda fp=None, **k: saved.append(fp)
    series.jser_fp = ""

    main_window.MainWindow.backup(SimpleNamespace(series=series), check_auto=True)

    assert len(saved) == 1
    _assert_inside(saved[0], folder)
