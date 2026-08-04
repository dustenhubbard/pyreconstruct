"""One unreadable log row costs only itself, not the whole editors set.

``Series.getEditorsFromHistory`` folds the log's rows into a set of usernames.
``Series.__init__`` calls it exactly when the stored ``editors`` list is empty,
and stores whatever comes back, so what it returns is what the series then
claims about who has worked on it.

It used to wrap the whole read in a bare ``except:``, print "ERROR: corrupt
history" and return an empty set. The parse, though, is row-at-a-time
(``LogSet.fromList`` loops over the rows and calls ``Log.fromStr`` on each), so
one row that will not read says nothing about the rows around it -- and a union
is precisely the shape where dropping the file to save one row is the wrong
trade. The reproduction is one line long: a legacy object name holding ``", "``,
the same pair ``Log.fromStr`` splits on (see
``tests/test_contour_name_collision.py`` for why such names exist and why the
log is not repointed away from them), shifts every field after it and raises on
the section range. Every OTHER user's well-formed row in the same file went with
it.

Now ``fromList`` takes ``skip_corrupt``, ``getFullHistory`` passes it through,
and ``getEditorsFromHistory`` asks for it. What is pinned here:

* the regression itself -- a good row for one user survives a bad row for
  another (``test_one_bad_row_no_longer_costs_another_user_their_entry``);
* the loss is reported rather than swallowed: the dropped rows are on the
  returned set as ``skipped_rows`` and a count is printed;
* the narrowing is real -- an error that is *not* a parse failure still
  propagates, where the bare ``except:`` would have eaten it;
* blast radius: ``fromList``/``getFullHistory`` still raise by default, so the
  history table, the import comparison and the curation restore -- every other
  caller -- behave exactly as before, and only the two callers of
  ``getEditorsFromHistory`` (``Series.__init__``, ``MainWindow.displayAbout``,
  both of which only ever add names) see the recovered rows.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.log import Log, LogSet
from PyReconstruct.modules.datatypes.series import Series

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)

HEADER = "Date, Time, User, Obj, Sections, Event\n"

# A row that reads, and a row that does not. The bad one is the documented
# real-world shape: the object name holds ", ", so the split yields seven fields
# and the section range is read off the name's own tail.
GOOD = "26-06-29, 1200, alice, obj_a, 5, Modify trace(s)"
BAD = "26-06-30, 1300, bob, weird, name, 7, Modify trace(s)"


@pytest.fixture
def series(tmp_path):
    """A real series, opened from the fixture, with its own hidden dir."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    s = Series.openJser(fp, progress=NullProgressReporter, notifier=NullNotifier())
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.leave_open = False
    s.close()


def write_log(series, *rows):
    """Replace the series' existing_log.csv with the given rows."""
    fp = os.path.join(series.hidden_dir, "existing_log.csv")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(HEADER)
        for row in rows:
            f.write(row + "\n")
    return fp


# --------------------------------------------------------------------------- #
# the shape of the bad row, asserted rather than assumed
# --------------------------------------------------------------------------- #
def test_the_bad_row_really_is_a_parse_failure():
    """The premise the rest of the module rests on.

    ``BAD`` is not arbitrary garbage: it is what ``Log.__str__`` writes for an
    object literally named ``weird, name``, which is why a legacy file can hold
    it. Recorded here so a later change to ``fromStr`` that happens to make this
    row readable turns into a visible failure rather than a silently vacuous
    test.
    """
    assert BAD == str(Log("26-06-30", "1300", "bob", "weird, name", 7,
                          "Modify trace(s)"))
    with pytest.raises(ValueError):
        Log.fromStr(BAD)
    # ... while the good row reads, and reads as alice's
    assert Log.fromStr(GOOD).user == "alice"


# --------------------------------------------------------------------------- #
# the regression
# --------------------------------------------------------------------------- #
def test_one_bad_row_no_longer_costs_another_user_their_entry(series):
    """alice's row is well formed and hers. bob's failing to parse is not her
    problem, and used to be: the whole set came back empty."""
    write_log(series, GOOD, BAD)

    editors = series.getEditorsFromHistory()

    assert "alice" in editors, "a well-formed row was discarded with the bad one"
    assert editors == {"alice"}, "the unreadable row must not invent an editor"


def test_the_bad_row_can_be_anywhere_in_the_file(series):
    """Order must not decide who survives.

    Before the fix the parse aborted where it stood, so a row's fate depended
    on whether it sat above or below the bad one -- which is not a property
    anyone would choose. Now neither position loses anything but the bad row.
    """
    late = "26-07-01, 1400, carol, obj_c, 9, Modify trace(s)"
    for rows in ([BAD, GOOD, late], [GOOD, BAD, late], [GOOD, late, BAD]):
        write_log(series, *rows)
        assert series.getEditorsFromHistory() == {"alice", "carol"}


def test_several_bad_rows_cost_only_themselves(series):
    """The recovery is per row, not "tolerate one and give up"."""
    other_bad = "26-07-02, 1500, dave, another, bad, 3, Modify trace(s)"
    write_log(series, BAD, GOOD, other_bad)

    assert series.getEditorsFromHistory() == {"alice"}


def test_a_clean_log_is_unchanged(series):
    """The ordinary case still reads every row, and this is what makes the
    test above discriminating rather than a tautology."""
    write_log(series, GOOD, "26-07-01, 1400, carol, obj_c, 9, Modify trace(s)")

    assert series.getEditorsFromHistory() == {"alice", "carol"}


# --------------------------------------------------------------------------- #
# the loss is reported, not swallowed
# --------------------------------------------------------------------------- #
def test_the_dropped_rows_are_recorded_and_counted(series, capsys):
    """Keeping the good rows must not make the bad ones invisible.

    The dropped rows come back on the log set, and the count is printed, so a
    partial history is still something a user can be told about.
    """
    write_log(series, GOOD, BAD)

    ls = series.getFullHistory(skip_corrupt=True)
    assert len(ls.skipped_rows) == 1
    assert "weird, name" in ls.skipped_rows[0]
    assert [l.user for l in ls.all_logs] == ["alice"]

    capsys.readouterr()
    series.getEditorsFromHistory()
    assert "1 unreadable history row" in capsys.readouterr().out


def test_nothing_is_reported_when_nothing_is_dropped(series, capsys):
    write_log(series, GOOD)

    assert series.getFullHistory(skip_corrupt=True).skipped_rows == []
    capsys.readouterr()
    series.getEditorsFromHistory()
    assert "unreadable" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# the narrowing is real
# --------------------------------------------------------------------------- #
def test_a_non_parse_error_still_propagates(series, monkeypatch):
    """The bare ``except:`` caught everything, including bugs.

    ``skip_corrupt`` is deliberately not a second bare except: only the two
    exception types a row's parse can raise are skipped. Anything else -- here
    an error standing in for a defect in the parser itself -- still reaches the
    caller instead of being turned into a silently empty editors set.
    """
    write_log(series, GOOD)

    def boom(s):
        raise RuntimeError("not a parse failure")

    monkeypatch.setattr(Log, "fromStr", boom)
    with pytest.raises(RuntimeError):
        series.getEditorsFromHistory()


def test_a_read_failure_still_yields_an_empty_set(series, capsys):
    """A missing log file is the one case with nothing to salvage.

    Series.__init__ calls this on every open of a series with no stored
    editors, including one whose hidden directory has no log yet, so this path
    must not raise.
    """
    os.remove(os.path.join(series.hidden_dir, "existing_log.csv"))

    assert series.getEditorsFromHistory() == set()
    assert "cannot read history" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# blast radius: every other caller is untouched
# --------------------------------------------------------------------------- #
def test_from_list_still_raises_by_default():
    """The history table, the import comparison and the curation restore all
    read the log through the default and would rather fail loudly than show a
    history they know is incomplete. That default is unchanged."""
    with pytest.raises(ValueError):
        LogSet.fromList([GOOD, BAD])

    kept = LogSet.fromList([GOOD, BAD], skip_corrupt=True)
    assert [l.user for l in kept.all_logs] == ["alice"]


def test_get_full_history_still_raises_by_default(series):
    write_log(series, GOOD, BAD)

    with pytest.raises(ValueError):
        series.getFullHistory()


def test_session_logs_are_still_appended_to_the_recovered_history(series):
    """``getFullHistory`` is the on-disk log plus the current session's. The
    skip must not cost the session half."""
    write_log(series, GOOD, BAD)
    series.log_set.addLog("erin", "obj_e", 2, "Modify trace(s)")

    users = [l.user for l in series.getFullHistory(skip_corrupt=True).all_logs]
    assert users == ["alice", "erin"]
    assert "erin" in series.getEditorsFromHistory()


# --------------------------------------------------------------------------- #
# end to end: the series open that this function exists for
# --------------------------------------------------------------------------- #
def test_reopening_the_series_keeps_the_surviving_editor(series):
    """The whole point: ``Series.__init__`` stores what this returns.

    The fixture carries an empty ``editors`` list, which is the condition under
    which __init__ consults the history at all -- asserted, not assumed, so the
    test cannot pass by never reaching the code it is about.
    """
    assert series.editors == set()
    write_log(series, GOOD, BAD)

    reopened = Series(series.filepath, dict(series.sections))
    try:
        assert reopened.editors == {"alice"}
    finally:
        reopened.leave_open = True  # the fixture owns the hidden dir
        reopened.close()
