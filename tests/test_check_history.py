"""`PyReconstruct --check-history` lists unreadable history rows and changes nothing.

Older versions wrote some history rows that PyReconstruct cannot read back: a
row split across lines by a line break in a name, or a row with a comma in a
user or object name. Those rows stay in the .jser. Opening the series only
printed a count to the console when it read the editors list, so nothing told a
user which files held one. The check reads each file and reports the file, the
line and the raw row. It never writes.
"""

import hashlib
import io
import json
import os
import shutil

import pytest

from PyReconstruct import cli
from PyReconstruct.modules.backend.func.check_history import (
    checkHistory,
    checkJser,
    unreadableRows,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

HEADER = "Date, Time, User, Obj, Sections, Event"
GOOD = "26-06-29, 12:00, alice, obj_a, 5, Modify trace(s)"
COMMA_NAME = "26-09-29, 22:07, Smith, John, axon, -, Modify object"
SPLIT_HEAD = "26-07-03, 16:00, bob"
SPLIT_TAIL = "and more of a pasted name"
LATE = "26-07-01, 14:00, carol, obj_c, 9, Modify trace(s)"


def _log(*rows):
    return "\n".join((HEADER,) + rows)


def _jser(tmp_path, log_text, name="series.jser"):
    with open(FIXTURE, "rb") as f:
        data = json.loads(f.read())
    data["log"] = log_text
    fp = tmp_path / name
    fp.write_text(json.dumps(data))
    return fp


def _digest(fp):
    return hashlib.sha256(open(fp, "rb").read()).hexdigest()


def test_a_clean_history_has_no_unreadable_rows():
    assert unreadableRows(_log(GOOD, LATE)) == []
    assert unreadableRows(HEADER) == []
    assert unreadableRows("") == []


def test_each_unreadable_row_comes_with_its_line_number():
    text = _log(GOOD, COMMA_NAME, LATE, SPLIT_HEAD, SPLIT_TAIL, GOOD)
    assert unreadableRows(text) == [
        (3, COMMA_NAME),
        (5, SPLIT_HEAD),
        (6, SPLIT_TAIL),
    ]


def test_windows_line_endings_count_lines_the_same_way():
    text = _log(GOOD, COMMA_NAME).replace("\n", "\r\n")
    assert unreadableRows(text) == [(3, COMMA_NAME)]


def test_the_check_agrees_with_what_opening_the_series_drops(tmp_path):
    """Same rows as Series.getFullHistory(skip_corrupt=True) on the open series."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PyReconstruct.modules.backend.notifier import NullNotifier
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    from PyReconstruct.modules.datatypes.series import Series

    fp = _jser(tmp_path, _log(GOOD, COMMA_NAME, SPLIT_HEAD, SPLIT_TAIL, LATE))
    found = [raw for _, raw in checkJser(fp)]

    series = Series.openJser(
        str(fp), progress=NullProgressReporter, notifier=NullNotifier()
    )
    series.setSettingsStore(DictSettingsStore())
    try:
        skipped = series.getFullHistory(skip_corrupt=True).skipped_rows
    finally:
        series.leave_open = False
        series.close()

    assert found == [row.rstrip("\n") for row in skipped]
    assert found == [COMMA_NAME, SPLIT_HEAD, SPLIT_TAIL]


def test_a_folder_is_checked_and_no_file_changes(tmp_path):
    bad = _jser(tmp_path, _log(GOOD, COMMA_NAME), "bad.jser")
    sub = tmp_path / "sub"
    sub.mkdir()
    clean = _jser(sub, _log(GOOD), "clean.jser")
    hidden = tmp_path / ".bad"
    hidden.mkdir()
    _jser(hidden, _log(COMMA_NAME), "inside-hidden.jser")
    before = {fp: _digest(fp) for fp in (bad, clean)}
    mtimes = {fp: os.stat(fp).st_mtime_ns for fp in (bad, clean)}

    out = io.StringIO()
    code = checkHistory([str(tmp_path)], out)

    assert code == 1
    assert out.getvalue().splitlines() == [
        f"{bad}: 1 unreadable history row",
        f"  line 3: {COMMA_NAME}",
        "Checked 2 of 2 files. 1 file had unreadable history rows. No file was changed.",
    ]
    assert {fp: _digest(fp) for fp in (bad, clean)} == before
    assert {fp: os.stat(fp).st_mtime_ns for fp in (bad, clean)} == mtimes
    assert sorted(p.name for p in tmp_path.iterdir()) == [".bad", "bad.jser", "sub"]


def test_clean_files_exit_zero(tmp_path):
    clean = _jser(tmp_path, _log(GOOD, LATE))
    out = io.StringIO()
    assert checkHistory([str(clean)], out) == 0
    assert out.getvalue() == (
        "Checked 1 of 1 file. 0 files had unreadable history rows. "
        "No file was changed.\n"
    )


def test_a_file_that_is_not_a_series_is_named_and_skipped(tmp_path):
    broken = tmp_path / "broken.jser"
    broken.write_text("{not json")
    missing = tmp_path / "missing.jser"
    clean = _jser(tmp_path, _log(GOOD))

    out = io.StringIO()
    code = checkHistory([str(broken), str(missing), str(clean)], out)

    assert code == 1
    lines = out.getvalue().splitlines()
    assert lines[0] == f"{broken}: not checked. It is not a series file."
    assert lines[1].startswith(f"{missing}: not checked. It could not be opened")
    assert lines[2] == (
        "Checked 1 of 3 files. 0 files had unreadable history rows. No file was changed."
    )


def test_a_folder_with_no_series_says_so(tmp_path):
    out = io.StringIO()
    assert checkHistory([str(tmp_path)], out) == 1
    assert out.getvalue() == "No .jser files found.\n"


def test_the_command_line_flag_runs_the_check(tmp_path, monkeypatch, capsys):
    bad = _jser(tmp_path, _log(COMMA_NAME))
    monkeypatch.setattr("sys.argv", ["PyReconstruct", "--check-history", str(bad)])
    monkeypatch.setattr(cli, "open_file", lambda *_: pytest.fail("opened a series"))

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 1
    assert f"  line 2: {COMMA_NAME}" in capsys.readouterr().out
