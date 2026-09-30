"""A comma in a username or a z-trace name no longer breaks the log.

Log rows are written as ``date, time, user, obj, sections, event`` and read
back by splitting on ``", "``. A username such as ``Smith, John`` or a z-trace
named ``dendrite 1, spine a`` shifted every field after it, so the section
field held part of a name and ``int()`` raised. That stopped a crash-recovery
open, ``getFullHistory`` after a reopen, and a history-aware ``importTraces``.

The writer now quotes a user or object name that needs it, CSV style (wrapped
in double quotes, inner quotes doubled). Everything else is written exactly as
before, so older logs read the same way they always did. That last claim is
pinned against a copy of the old reader below.

The username is never assigned through ``series.user``: its setter writes the
real ``username`` setting. The end-to-end tests patch the property on the
class instead, and ``monkeypatch`` puts it back.
"""
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.log import Log, LogSet
from PyReconstruct.modules.datatypes.series import Series


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "dev" / "assets" / "checker" / "files" / "shapes1.jser"
)


def old_from_str(s):
    """The field split Log.fromStr used before names could be quoted."""
    l = s.split(", ")
    if len(l) > 6:
        l[5] = ", ".join(l[5:])
        l = l[:6]
    date, time, user, obj_name, sections, event = tuple(l)
    if obj_name == "-":
        obj_name = None
    return date, time, user, obj_name, sections, event.strip()


def fields(log):
    return (log.date, log.time, log.user, log.obj_name,
            log.section_ranges, log.event)


# --------------------------------------------------------------------------- #
# the row format
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("user, obj_name", [
    ("Smith, John", "axon"),
    ("alice", "dendrite 1, spine a"),
    ("Smith, John", "dendrite 1, spine a"),
    ('say "hi", bob', 'a "quoted", name'),
    ('"quoted"', '"x'),
    ("trailing, ", ", leading"),
    ("alice", "-"),
    ("", "obj"),
])
def test_any_name_round_trips(user, obj_name):
    log = Log("26-09-30", "12:00", user, obj_name, [(1, 3), (7, 7)],
              "Modify trace(s), then more")
    back = Log.fromStr(str(log))
    assert fields(back) == fields(log)
    assert str(back) == str(log)


def test_no_object_still_reads_as_none():
    log = Log("26-09-30", "12:00", "Smith, John", None, None, "Create series")
    assert str(log) == '26-09-30, 12:00, "Smith, John", -, -, Create series'
    back = Log.fromStr(str(log))
    assert back.obj_name is None
    assert back.section_ranges is None
    assert back.user == "Smith, John"


def test_the_quoted_row_shape():
    log = Log("26-09-30", "12:00", "Smith, John", 'dendrite 1, "a"', 4, "x")
    assert str(log) == (
        '26-09-30, 12:00, "Smith, John", "dendrite 1, ""a""", 4, x'
    )


@pytest.mark.parametrize("row", [
    "26-06-29, 12:00, alice, obj_a, 5, Modify trace(s)",
    "26-06-29, 12:00, alice, -, -, Create series",
    "26-06-29, 12:00, alice, d001, 1-4 9 12-13, Create trace(s)",
    "26-06-29, 12:00, alice, obj_a, -, Rename object to b, with a comma",
    "26-06-29, 12:00, alice, obj_a, -, Set user column c as \"v, w\"",
    "26-06-29, 12:00, al\"ice, ob\"j, 3, Modify trace(s)",
    "26-06-29, 12:00, alice, obj_a, 3, ",
    "26-06-29, 12:00, a,b, c,d, 3, Modify trace(s)",
])
def test_older_rows_read_as_they_always_did(row):
    """Rows an older version wrote parse to the same fields and write back
    byte for byte."""
    log = Log.fromStr(row)
    date, time, user, obj_name, sections, event = old_from_str(row)
    assert (log.date, log.time, log.user, log.obj_name, log.event) == (
        date, time, user, obj_name, event
    )
    assert str(log) == row


def test_an_older_name_opening_with_a_quote_still_reads():
    """A name that opens with a quote but is not a quoted field reads the
    old way. It is the one shape the writer now spells differently."""
    row = '26-06-29, 12:00, "alice, obj_a, 3, Modify trace(s)'
    log = Log.fromStr(row)
    assert fields(log) == ('26-06-29', '12:00', '"alice', 'obj_a', [(3, 3)],
                           'Modify trace(s)')
    assert fields(Log.fromStr(str(log))) == fields(log)


@pytest.mark.parametrize("row", [
    '26-06-29, 12:00, "alice", axon, 3, Modify trace(s)',
    '26-06-29, 12:00, alice, "axon", 3, Modify trace(s)',
    '26-06-29, 12:00, "alice, axon", 3, Modify trace(s)',
])
def test_quotes_an_older_version_wrote_stay_literal(row):
    """Older versions wrote names as they were, quotes included. Those
    quotes are read as part of the name, and a row that only parses the old
    way is read the old way."""
    log = Log.fromStr(row)
    date, time, user, obj_name, sections, event = old_from_str(row)
    assert (log.date, log.time, log.user, log.obj_name, log.event) == (
        date, time, user, obj_name, event
    )
    assert fields(Log.fromStr(str(log))) == fields(log)


def test_an_older_row_with_a_comma_name_is_still_a_parse_failure():
    """Rows older versions already wrote with a comma in a name cannot be
    split reliably, so they still fail and skip_corrupt still drops only
    them."""
    bad = "26-09-29, 22:07, Smith, John, axon, -, Modify object"
    good = "26-09-29, 22:08, alice, axon, -, Modify object"
    with pytest.raises(ValueError):
        Log.fromStr(bad)
    ls = LogSet.fromList([bad, good], skip_corrupt=True)
    assert ls.skipped_rows == [bad]
    assert [l.user for l in ls.all_logs] == ["alice"]


# --------------------------------------------------------------------------- #
# the paths that used to raise
# --------------------------------------------------------------------------- #
def open_series(fp):
    s = Series.openJser(str(fp), progress=NullProgressReporter,
                        notifier=NullNotifier())
    s.setSettingsStore(DictSettingsStore())
    return s


@pytest.fixture
def series_fp(tmp_path):
    if not FIXTURE.exists():
        pytest.skip("fixture shapes1.jser not found")
    fp = tmp_path / "a" / "shapes1.jser"
    fp.parent.mkdir()
    shutil.copyfile(FIXTURE, fp)
    return fp


@pytest.fixture
def other_fp(tmp_path):
    if not FIXTURE.exists():
        pytest.skip("fixture shapes1.jser not found")
    fp = tmp_path / "b" / "shapes1.jser"
    fp.parent.mkdir()
    shutil.copyfile(FIXTURE, fp)
    return fp


@pytest.fixture
def as_user(monkeypatch):
    """Set the username the series logs under without touching settings."""
    def set_user(name):
        monkeypatch.setattr(Series, "user", property(lambda self: name))
    return set_user


def first_object(series):
    return sorted(series.data["objects"])[0]


def close(*series):
    for s in series:
        s.leave_open = False
        s.close()


def test_comma_username_survives_crash_recovery_and_reopen(
    series_fp, other_fp, as_user
):
    as_user("Smith, John")
    s = open_series(series_fp)
    name = first_object(s)
    s.editObjectAttributes([name], color=(1, 2, 3))
    s.save()  # what a crash leaves behind in the hidden folder

    recovered = open_series(series_fp)  # crash-recovery open
    assert any(l.user == "Smith, John" for l in recovered.log_set.all_logs)
    recovered.saveJser(close=True)
    s.leave_open = True  # the hidden folder is gone now

    reopened = open_series(series_fp)
    hist = reopened.getFullHistory()
    assert any(
        l.user == "Smith, John" and l.obj_name == name for l in hist.all_logs
    )
    assert "Smith, John" in reopened.getEditorsFromHistory()

    other = open_series(other_fp)
    reopened.importTraces(other)
    other.importTraces(reopened)
    close(reopened, other)


def test_comma_ztrace_name_survives_crash_recovery_and_reopen(
    series_fp, other_fp, as_user
):
    as_user("alice")
    s = open_series(series_fp)
    s.createZtrace(first_object(s))
    zname = next(iter(s.ztraces))
    s.editZtraceAttributes(zname, "dendrite 1, spine a", None)
    s.save()

    recovered = open_series(series_fp)
    assert "dendrite 1, spine a" in {
        l.obj_name for l in recovered.log_set.all_logs
    }
    recovered.saveJser(close=True)
    s.leave_open = True

    reopened = open_series(series_fp)
    hist = reopened.getFullHistory()
    assert "dendrite 1, spine a" in {l.obj_name for l in hist.all_logs}

    other = open_series(other_fp)
    reopened.importTraces(other)
    close(reopened, other)


def test_history_view_keeps_a_comma_name_in_one_cell(qapp):
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.gui.table import HistoryTableWidget

    parent = QWidget()
    log_set = LogSet()
    log_set.all_logs.append(
        Log("26-09-30", "12:00", "Smith, John", "dendrite 1, spine a",
            [(2, 4)], "Modify ztrace")
    )
    widget = HistoryTableWidget(log_set, parent)
    cells = [widget.table.item(0, c).text() for c in range(6)]
    assert cells == ["26-09-30", "12:00", "Smith, John",
                     "dendrite 1, spine a", "2-4", "Modify ztrace"]
    widget.close()
    parent.deleteLater()


def test_history_view_opens_with_an_empty_event(qapp):
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.gui.table import HistoryTableWidget

    parent = QWidget()
    log_set = LogSet()
    log_set.all_logs.append(Log("26-09-30", "12:00", "alice", "axon", 3, ""))
    widget = HistoryTableWidget(log_set, parent)
    cells = [widget.table.item(0, c).text() for c in range(6)]
    assert cells == ["26-09-30", "12:00", "alice", "axon", "3", ""]
    widget.close()
    parent.deleteLater()
