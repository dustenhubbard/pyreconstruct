"""A series whose log names an object with a lone surrogate reopens.

A lone surrogate is half of a UTF-16 pair with no other half. An old or
damaged file can hold one in an object name. The sections and the series keep
it, since JSON escapes it as ``\\ud800``. The log is different: an edit to such
an object writes a log row that names it, Save writes that row into the .jser,
and the next open wrote the log out to ``existing_log.csv`` as strict UTF-8.
Strict UTF-8 has no encoding for a lone surrogate, so the open raised.

The username is never assigned through ``series.user``: its setter writes the
real ``username`` setting. The tests patch the property on the class instead.
"""
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.log import LogSet
from PyReconstruct.modules.datatypes.series import Series


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "dev" / "assets" / "checker" / "files" / "shapes1.jser"
)

NAME = "axon_\ud800_1"


def open_series(fp):
    s = Series.openJser(str(fp), progress=NullProgressReporter,
                        notifier=NullNotifier())
    s.setSettingsStore(DictSettingsStore())
    return s


def close(series):
    series.leave_open = False
    series.close()


@pytest.fixture
def series_fp(tmp_path, monkeypatch):
    if not FIXTURE.exists():
        pytest.skip("fixture shapes1.jser not found")
    monkeypatch.setattr(Series, "user", property(lambda self: "alice"))
    fp = tmp_path / "a" / "shapes1.jser"
    fp.parent.mkdir()
    shutil.copyfile(FIXTURE, fp)
    return fp


@pytest.fixture
def saved_with_surrogate(series_fp):
    """The .jser after a rename to NAME and a Save, then an edit and a Save."""
    s = open_series(series_fp)
    old = sorted(s.data["objects"])[0]
    s.editObjectAttributes([old], name=NAME)
    s.saveJser(close=True)

    s = open_series(series_fp)
    s.editObjectAttributes([NAME], color=(1, 2, 3))
    s.saveJser(close=True)
    return series_fp


def test_a_saved_series_reopens_with_the_name_in_its_history(saved_with_surrogate):
    s = open_series(saved_with_surrogate)
    assert NAME in s.data["objects"]
    names = {l.obj_name for l in s.getFullHistory().all_logs}
    assert NAME in names
    close(s)


def test_the_name_survives_more_save_and_reopen_rounds(saved_with_surrogate):
    for _ in range(2):
        s = open_series(saved_with_surrogate)
        s.saveJser(close=True)
    s = open_series(saved_with_surrogate)
    rows = [l for l in s.getFullHistory().all_logs if l.obj_name == NAME]
    assert len(rows) >= 2  # the rename and the color edit, both kept
    assert not any("\ufffd" in (l.obj_name or "") for l in s.getFullHistory().all_logs)
    close(s)


def test_a_crash_recovery_open_keeps_the_name(series_fp):
    s = open_series(series_fp)
    old = sorted(s.data["objects"])[0]
    s.editObjectAttributes([old], name=NAME)
    s.save()  # what a crash leaves behind in the hidden folder

    recovered = open_series(series_fp)
    assert NAME in {l.obj_name for l in recovered.log_set.all_logs}
    recovered.saveJser(close=True)
    s.leave_open = True  # the hidden folder is gone now

    reopened = open_series(series_fp)
    assert NAME in {l.obj_name for l in reopened.getFullHistory().all_logs}
    close(reopened)


def test_export_log_history_writes_the_name_as_valid_utf8(saved_with_surrogate, tmp_path):
    """The exported file is for other programs: the surrogate goes as text."""
    s = open_series(saved_with_surrogate)
    out = tmp_path / "old_log.csv"
    LogSet.exportLogHistory(s.hidden_dir, str(out), 0)
    exported = out.read_bytes().decode("utf-8")  # strict: valid UTF-8
    assert "axon_\\ud800_1" in exported
    s.saveJser(close=True)

    s = open_series(saved_with_surrogate)
    assert NAME in s.data["objects"]
    close(s)


def test_export_log_history_keeps_the_rows_it_does_not_export(saved_with_surrogate, tmp_path):
    s = open_series(saved_with_surrogate)
    LogSet.exportLogHistory(s.hidden_dir, str(tmp_path / "old_log.csv"), 10000)
    assert NAME in {l.obj_name for l in s.getFullHistory().all_logs}
    s.saveJser(close=True)

    s = open_series(saved_with_surrogate)
    assert NAME in {l.obj_name for l in s.getFullHistory().all_logs}
    close(s)


def test_other_bad_bytes_in_the_log_are_still_replaced(series_fp):
    """A damaged byte that is not a surrogate reads as U+FFFD, as before."""
    s = open_series(series_fp)
    fp = Path(s.hidden_dir) / "existing_log.csv"
    good = "26-10-19, 12:00, alice, axon_\ud800_1, 1, Modify object\n"
    with fp.open("ab") as f:
        f.write(b"\n26-10-19, 12:00, alice, bad\xff\xfe, 1, Modify object\n")
        f.write(good.encode("utf-8", "surrogatepass"))
    names = {l.obj_name for l in s.getFullHistory().all_logs}
    assert "bad\ufffd\ufffd" in names
    assert NAME in names
    s.saveJser(close=True)

    s = open_series(series_fp)
    names = {l.obj_name for l in s.getFullHistory().all_logs}
    assert {"bad\ufffd\ufffd", NAME} <= names
    close(s)
