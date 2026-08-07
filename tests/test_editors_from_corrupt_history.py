"""One unreadable log row costs only itself, not the whole editors set.

``Series.getEditorsFromHistory`` folds the log's rows into a set of usernames.
``Series.__init__`` calls it exactly when the stored ``editors`` list is empty,
and stores whatever comes back, so what it returns is what the series then
claims about who has worked on it.

It used to wrap the whole read in a bare ``except:``, print "ERROR: corrupt
history" and return an empty set. The parse, though, is row-at-a-time
(``LogSet.fromList`` loops over the rows and calls ``Log.fromStr`` on each), so
a row that arrives whole and will not read says nothing about the rows around
it -- and a union is precisely the shape where dropping the file to save one
row is the wrong trade. The reproduction is one line long: a legacy object name holding ``", "``,
the same pair ``Log.fromStr`` splits on (see
``tests/test_contour_name_collision.py`` for why such names exist and why the
log is not repointed away from them), shifts every field after it and raises on
the section range. Every OTHER user's well-formed row in the same file went with
it.

Now ``fromList`` takes ``skip_corrupt``, ``getFullHistory`` passes it through,
and ``getEditorsFromHistory`` asks for it. What is pinned here:

* the regression itself -- a good row for one user survives a bad row for
  another (``test_one_bad_row_no_longer_costs_another_user_their_entry``);
* both halves of the handler, not just one. The rows above fail in
  ``Log.fromStr`` (``ValueError``); a row that stops partway through with
  nothing after it fails in ``fromList``'s continuation join instead
  (``IndexError``), and is recovered the same way
  (``test_a_truncated_final_row_costs_only_itself``);
* the loss is reported rather than swallowed: the dropped rows are on the
  returned set as ``skipped_rows`` and a count is printed;
* the narrowing is real -- an error that is *not* a parse failure still
  propagates, where the bare ``except:`` would have eaten it;
* blast radius: ``fromList``/``getFullHistory`` still raise by default, so the
  history table, the import comparison and the curation restore -- every other
  caller -- behave exactly as before, and only the two callers of
  ``getEditorsFromHistory`` (``Series.__init__``, ``MainWindow.displayAbout``,
  both of which only ever add names) see the recovered rows;
* and -- now -- "a bad row costs only itself" without the qualification that
  used to follow it. A row SHORT of six comma fields is glued to the line after
  it first, because a name or event carrying a literal newline arrives split
  across the physical lines it was written to. That join used to be unguarded,
  so it took whatever followed, and when the concatenation happened to parse it
  produced a fabricated ``Log`` standing in for two real rows: nothing in
  ``skipped_rows``, no warning, and on the default path as well. This module
  used to pin that as a known limitation. It is now closed, by two changes that
  meet in the middle, and the last three sections of this module are about
  them:

  - **write side.** ``Log.__str__`` replaces ``\\n``, ``\\r\\n`` and ``\\r``
    with ``_``. It is the only place a ``Log`` becomes text, so no ``Log``
    written from here on can occupy more than one physical line, and the
    reader never sees a fragment at all.
  - **read side.** ``fromList`` anchors a row on the ``"YY-MM-DD, HH:MM, "``
    stamp ``Log.__str__`` writes unconditionally: a line carrying it is a row
    and will not be eaten as a continuation, and a line lacking it is not a row
    and will not be read as one. That is a structural fact about this
    program's writer, not a guess about content. It is needed *in addition* to
    the write-side fix because the historical log is copied through byte for
    byte on open and save and is never re-emitted, so a file corrupted by an
    older build stays corrupted for good.

  What is left is one genuinely irreducible case, pinned below: a pasted name
  whose own text contains a line shaped like a whole row is byte-identical to
  two real rows, and nothing in the file can tell them apart. The anchor fails
  *safe* there -- it reads both lines as rows, which truncates the name --
  where the unguarded join failed unsafe, inventing an editor out of another
  row's timestamp.

  "Safe" here is not "nothing gets through", and
  ``test_the_irreducible_case_fails_safe_rather_than_inventing_an_editor``
  pins the part that does. The embedded line is still read as a row, so
  whatever it names in the user field -- text the paster chose -- is kept as
  that row's ``user``, which is exactly what ``getEditorsFromHistory`` unions
  into the series' editors. The test asserts it on purpose: ``carol`` in its
  hazard string is text ``bob`` pasted, and it is still there in
  ``all_logs``. What is prevented is the other failure -- reading a TIMESTAMP
  as if it were a person -- not the admission of a plausible name somebody
  typed into a dialog.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.log import ROW_START, Log, LogSet
from PyReconstruct.modules.datatypes.series import Series

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

HEADER = "Date, Time, User, Obj, Sections, Event\n"

# A row that reads, and a row that does not. The bad one is the documented
# real-world shape: the object name holds ", ", so the split yields seven fields
# and the section range is read off the name's own tail.
GOOD = "26-06-29, 12:00, alice, obj_a, 5, Modify trace(s)"
BAD = "26-06-30, 13:00, bob, weird, name, 7, Modify trace(s)"

# The other failing shape, and the only one that reaches the IndexError half of
# the handler: a final row that stops partway through. fromList's continuation
# join (which exists so a row holding a literal newline can be reassembled from
# the physical lines it was split across) keeps pulling log_list[i+1] while the
# row is short of six comma fields, so a short row with nothing after it runs
# the index off the end. Position is what picks the arm: the same text with a
# row after it gets joined to that row and fails in fromStr instead.
TRUNCATED = "26-07-03, 16:00, bob"


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
    assert BAD == str(Log("26-06-30", "13:00", "bob", "weird, name", 7,
                          "Modify trace(s)"))
    with pytest.raises(ValueError):
        Log.fromStr(BAD)
    # ... while the good row reads, and reads as alice's
    assert Log.fromStr(GOOD).user == "alice"


def test_a_truncated_final_row_is_the_index_error_case():
    """The handler names two exception types; this is the second one.

    ``BAD`` above exercises ``ValueError``. Nothing exercised ``IndexError``,
    which is not a hypothetical branch: it is the continuation join in
    ``fromList`` running ``log_list[i+1]`` off the end of the list, which is
    what a row that stops partway through and has no row after it does.

    Asserted rather than assumed, because the two arms are reached by
    *different* code and could not be swapped for one another:
    """
    # through fromStr alone the short row is an unpack failure -- ValueError.
    # The IndexError is not fromStr's at all; it belongs to fromList's join.
    with pytest.raises(ValueError):
        Log.fromStr(TRUNCATED)

    with pytest.raises(IndexError):
        LogSet.fromList([GOOD, TRUNCATED])

    # and it really is *lastness* that selects the arm: give the same text a
    # row to join to and the join stops on that row's date stamp rather than
    # running off the end, so the short head fails in fromStr instead. (It
    # used to reach fromStr by a different route -- the join swallowed the
    # following row and the concatenation failed to parse. Same exception,
    # and now the following row is never touched at all.)
    with pytest.raises(ValueError):
        LogSet.fromList([GOOD, TRUNCATED, GOOD])


def test_the_log_writer_can_no_longer_leave_a_short_last_line(series):
    """The shape the writer used to produce, and no longer can.

    This test used to assert the opposite. An object name carrying both
    hazards -- the ``", "`` ``fromStr`` splits on (see ``BAD``, and
    ``tests/test_contour_name_collision.py`` for why such names exist) and a
    literal newline, the "return key in name" the continuation join exists for
    -- was emitted verbatim, so one ``Log`` became two physical lines: a head
    with six comma fields already, and an orphaned tail after it.

    ``Log.__str__`` now replaces the newline, so the row is one line. The
    comma in the name still breaks it -- that is a different, older defect and
    is deliberately untouched here -- so bob's row is still skipped and alice
    is still kept. What changed is the *count*: one lost row instead of two
    lost file lines, because there is only one line now.
    """
    row = str(Log("26-06-30", "13:00", "bob", "a, b, c\nd", 7, "Modify trace(s)"))
    assert "\n" not in row, "the writer must not emit a row spanning two lines"
    assert "\r" not in row
    assert row == "26-06-30, 13:00, bob, a, b, c_d, 7, Modify trace(s)"

    write_log(series, GOOD, row)

    assert series.getEditorsFromHistory() == {"alice"}
    assert len(series.getFullHistory(skip_corrupt=True).skipped_rows) == 1


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
    late = "26-07-01, 14:00, carol, obj_c, 9, Modify trace(s)"
    for rows in ([BAD, GOOD, late], [GOOD, BAD, late], [GOOD, late, BAD]):
        write_log(series, *rows)
        assert series.getEditorsFromHistory() == {"alice", "carol"}


def test_several_bad_rows_cost_only_themselves(series):
    """The recovery is per row, not "tolerate one and give up"."""
    other_bad = "26-07-02, 15:00, dave, another, bad, 3, Modify trace(s)"
    write_log(series, BAD, GOOD, other_bad)

    assert series.getEditorsFromHistory() == {"alice"}


def test_a_truncated_final_row_costs_only_itself(series):
    """The IndexError arm, through the real recovery path.

    A history whose last row stops partway through is the shape that reaches
    ``IndexError`` rather than ``ValueError`` (see
    ``test_a_truncated_final_row_is_the_index_error_case``). It must behave the
    same as any other unreadable row: alice keeps her entry, the truncated row
    is recorded rather than swallowed, and -- the part that matters most --
    ``getEditorsFromHistory`` returns instead of raising. Narrow the handler to
    ``ValueError`` alone and this call raises ``IndexError`` out of
    ``Series.__init__``, which is worse than the pre-fix behavior it replaced:
    that at least opened the series with an empty set.
    """
    write_log(series, GOOD, TRUNCATED)

    assert series.getEditorsFromHistory() == {"alice"}

    ls = series.getFullHistory(skip_corrupt=True)
    assert [l.user for l in ls.all_logs] == ["alice"]
    assert len(ls.skipped_rows) == 1
    assert ls.skipped_rows[0].strip() == TRUNCATED


def test_a_truncated_final_row_does_not_break_opening_the_series(series):
    """The blast radius of the arm, end to end.

    ``Series.__init__`` calls ``getEditorsFromHistory`` whenever the stored
    editors list is empty, and it does not guard the call. So an escaping
    ``IndexError`` is not a wrong answer, it is a series that will not open at
    all. The fixture's empty ``editors`` is asserted so this cannot pass by
    never reaching the code it is about.
    """
    assert series.editors == set()
    write_log(series, GOOD, TRUNCATED)

    reopened = Series(series.filepath, dict(series.sections))
    try:
        assert reopened.editors == {"alice"}
    finally:
        reopened.leave_open = True  # the fixture owns the hidden dir
        reopened.close()


def test_a_clean_log_is_unchanged(series):
    """The ordinary case still reads every row, and this is what makes the
    test above discriminating rather than a tautology."""
    write_log(series, GOOD, "26-07-01, 14:00, carol, obj_c, 9, Modify trace(s)")

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


# --------------------------------------------------------------------------- #
# the continuation join, and both halves of what it used to cost
#
# Everything above is about a row that arrives whole. A row SHORT of six comma
# fields is glued to the line after it first, because a name or event holding a
# literal newline arrives split across the physical lines it was written to.
#
# That join used to be unguarded -- it could not tell a real continuation from
# an unrelated next row, so it took whatever followed. Two outcomes, and they
# needed different fixes:
#
# * the join FAILS to parse. Fixed by the handler: it records only the first
#   physical line and resumes at the line after it, so every line the join
#   swept up is re-read on its own. Reached only on an attempt that already
#   raised, so it cannot change any log that parses today -- a recovery, not a
#   parsing rule.
# * the join SUCCEEDS. Used to be a silent fabricated ``Log`` standing in for
#   two real rows, on the default path as well. Fixed by anchoring the join on
#   the date stamp every row carries. This section pins that it stays fixed.
#
# The three sections below are, in order: the recovery half (unchanged), the
# fabrication half (now closed, where the pins used to be), and the write-side
# sanitizer that stops the fragments being produced in the first place.
# --------------------------------------------------------------------------- #
LATE = "26-07-01, 14:00, carol, obj_c, 9, Modify trace(s)"

# A series-level row: every ``addLog(None, ...)`` call site writes one, and
# there are on the order of forty of them -- alignment and profile events,
# "Reorder sections", "Modify transform", "Create series", every import. Both
# the object and the section slot come back as the ``"-"`` ``Log.__str__``
# writes for an empty field, which is what makes them the second half of the
# live fabrication below.
SERIES_LEVEL = "26-07-01, 14:00, carol, -, -, Create series"


def test_the_writer_uses_a_colon_in_the_time_field():
    """The premise the shapes below rest on, asserted rather than assumed.

    Which of the next row's fields lands in the section-range slot -- the only
    slot that has to read as an integer -- is what decides whether a join
    parses, and for one alignment that field is the next row's *time*. So a
    test written against an ``HHMM`` timestamp can pin a fabrication this app
    cannot produce. ``getDateTime`` has written ``"%H:%M"`` since the commit
    that created the log (``c46d5204``, Aug 2023); ``git log --all -S '"%H%M"'``
    finds nothing. Recorded here so the constants in this module cannot drift
    back to a shape no version of the product has ever written.
    """
    from PyReconstruct.modules.constants import getDateTime

    assert ":" in getDateTime()[1]
    assert ":" in str(Log(*getDateTime(), "alice", "obj_a", 5, "Modify")).split(", ")[1]


def test_a_row_swallowed_by_a_FAILED_join_is_given_back():
    """The half that is fixed, and the regression guard for it.

    ``TRUNCATED`` is short, so the join runs and takes ``LATE`` -- a perfectly
    well-formed row belonging to somebody else. The concatenation does not
    parse. It used to cost carol her row: both lines went into ``skipped_rows``
    as ONE entry, so the count callers print undercounted the file lines too.

    Now the failure records only the line that was actually short and the scan
    resumes at the next line, so carol's row is read on its own and survives,
    and the recorded entry is one file line rather than two rows' worth.
    """
    ls = LogSet.fromList([GOOD, TRUNCATED, LATE], skip_corrupt=True)

    assert [l.user for l in ls.all_logs] == ["alice", "carol"], (
        "the well-formed row the join swallowed must be given a second read"
    )
    assert len(ls.skipped_rows) == 1
    assert ls.skipped_rows[0].strip() == TRUNCATED
    assert "carol" not in ls.skipped_rows[0], (
        "the recorded entry must be the short line alone, not the concatenation"
    )


def test_position_no_longer_decides_whether_the_next_row_survives():
    """The control, and the point of the fix stated as an invariant.

    The same three rows with the short one last always worked. The same three
    rows with the short one in the middle used to lose carol -- so a row's fate
    turned on where the damage sat relative to it, which is not a property
    anyone would choose. Both orders now agree, and both record the short line
    and nothing else.
    """
    middle = LogSet.fromList([GOOD, TRUNCATED, LATE], skip_corrupt=True)
    last = LogSet.fromList([GOOD, LATE, TRUNCATED], skip_corrupt=True)

    assert [l.user for l in middle.all_logs] == [l.user for l in last.all_logs]
    assert [s.strip() for s in middle.skipped_rows] == [TRUNCATED]
    assert [s.strip() for s in last.skipped_rows] == [TRUNCATED]


def test_the_recovery_cannot_reach_a_log_that_parses():
    """Why the fix above needed no judgement call about the format.

    The recovery lives entirely in the handler for a join that has ALREADY
    raised. There is no way for it to make a currently-succeeding parse succeed
    differently, so no caller whose log reads sees any change -- which is what
    made this half a commit rather than a design decision, and is worth pinning
    so a later "improvement" that moves logic out of the handler and into the
    join is a visible change rather than a quiet one.
    """
    clean = [GOOD, LATE, SERIES_LEVEL]
    for skip in (False, True):
        ls = LogSet.fromList(list(clean), skip_corrupt=skip)
        assert [str(l) for l in ls.all_logs] == clean
        assert ls.skipped_rows == []

    # and a row that fails on its own still costs exactly itself
    ls = LogSet.fromList([GOOD, BAD, LATE], skip_corrupt=True)
    assert [l.user for l in ls.all_logs] == ["alice", "carol"]
    assert len(ls.skipped_rows) == 1


# --------------------------------------------------------------------------- #
# the half that used to fabricate: a join that succeeded, and invented an editor
#
# These tests replace the pins that used to sit here. They asserted the
# fabrication -- that a two-field orphan before a series-level row produced an
# editor named after the next row's timestamp -- and recorded it as a known
# limitation whose cure was a maintainer's call, because refusing the join
# makes an uncompletable short head RAISE where it used to fabricate.
#
# That call has been made, and these tests now assert the opposite of what they
# used to. Measured before deciding, on this machine's own data: across 872
# real ``.jser`` files (675 with a log, 1,987,237 real log rows) the anchored
# parser changes ZERO files and raises on ZERO previously-clean paths, so the
# "every default caller sees a change" cost is empirically nil on real logs;
# and across 200,000 generated files built from the writer's own output it
# fabricates in 0, against 43,698 and 44,005 for the unguarded join.
#
# The exception is a raise, which a caller can see and report. A fabrication is
# not, which is the whole reason to prefer it.
# --------------------------------------------------------------------------- #
def test_a_two_field_orphan_before_a_series_level_row_no_longer_invents_one():
    """The fabrication this module used to pin, asserted gone.

    Let ``k`` be the number of ``", "`` fields on the orphan line. The old
    join put the next row's field ``k-1`` into the section-range slot -- the
    only slot that must read as an integer -- so ``k`` alone decided whether
    the concatenation parsed. ``k=2`` put the next row's *obj_name* there, and
    every series-level row writes ``"-"`` in that field, so ``k=2`` parsed
    whenever the next row was series-level, which is an ordinary thing for a
    row to be. carol's row vanished and her row's own timestamp was reported
    as an editor, with ``skipped_rows`` empty so no caller could report it.

    The join now stops on the date stamp the follower carries. The orphan
    fails alone, carol's row is read as the row it is, and the loss is
    recorded where a caller can see it.
    """
    orphan = "d, e"
    assert len(orphan.split(", ")) == 2, "k=2 is the alignment that used to fabricate"

    ls = LogSet.fromList([GOOD, orphan, SERIES_LEVEL], skip_corrupt=True)

    users = [l.user for l in ls.all_logs]
    assert users == ["alice", "carol"], "the follower must survive intact"
    assert "14:00" not in users, "no timestamp may stand in for a person"
    assert [s.strip() for s in ls.skipped_rows] == [orphan], (
        "and the orphan is recorded rather than silently absorbed"
    )


def test_the_default_path_now_raises_where_it_used_to_fabricate():
    """The price of the fix, pinned as deliberately as the fabrication was.

    ``skip_corrupt`` was never what admitted the fabrication: the join
    succeeded, so the flag never came into it and every default caller -- the
    history table, the import comparison, the curation restore -- read the
    invented row too. The cure changes that path, which is exactly why it was
    a decision rather than a cleanup.

    What the default caller sees now is a ``ValueError``. That is the trade,
    and it is the right way round: a raise is visible and a fabricated editor
    is not.
    """
    with pytest.raises(ValueError):
        LogSet.fromList([GOOD, "d, e", SERIES_LEVEL])


def test_a_one_field_orphan_no_longer_pollutes_the_next_row():
    """The other silent shape, and the cheapest one to reach.

    ``k=1`` put the next row's own section range in the section slot, so the
    join ALWAYS parsed: the next row survived and kept its user, but the
    orphan was glued onto its date, so the entry the app displayed was not the
    one that was written. Nothing was recorded then either.
    """
    clean_head = "26-06-30, 13:00, bob, zt_old, -, Rename ztrace to new"
    orphan = "name"

    ls = LogSet.fromList([clean_head, orphan, LATE], skip_corrupt=True)

    assert [l.user for l in ls.all_logs] == ["bob", "carol"]
    assert ls.all_logs[1].date == "26-07-01", "the follower's date is its own"
    assert [s.strip() for s in ls.skipped_rows] == [orphan]


def test_a_fragment_that_is_itself_six_fields_is_not_read_as_a_row():
    """The route no round of review before this one named.

    A name holding SEVERAL newlines splits its row into three or more physical
    lines. The head fails, the recovery hands the remaining fragments back one
    at a time, and a middle fragment can carry six comma fields all by itself
    -- at which point ``Log.fromStr`` reads it as a whole row and takes its
    first three fields for a date, a time and a USER. No join is involved, so
    guarding the join alone does not reach it. Only requiring a row to BEGIN
    with a date stamp does.

    The shape below is the writer's own output for a pasted ztrace name of
    ``"x\\ny, z, w, v"``, and the invented editor was ``w``.
    """
    hazard = "21-04-17, 00:05, carol, x\ny, z, w, v, -, Offloaded log to x\ny, z, w, v"
    lines = hazard.split("\n")
    assert len(lines[1].split(",")) == 6, "the middle fragment is six-field-shaped"
    assert Log.fromStr(lines[1]).user == "w", (
        "read on its own it really does yield an editor named after a name fragment"
    )

    ls = LogSet.fromList([GOOD] + lines + [LATE], skip_corrupt=True)

    users = [l.user for l in ls.all_logs]
    assert "w" not in users, "a name fragment must not become an editor"
    assert users == ["alice", "carol"], "and the untouched rows either side survive"


def test_the_writer_produced_hazard_no_longer_reaches_the_series(series, capsys):
    """End to end, through a real series, on the shape that used to fabricate.

    Every physical line here is one an older build's ``Log.__str__`` emitted,
    written the way the app writes ``existing_log.csv`` and read back the way
    ``getFullHistory`` reads it. ``Series.modifyAlignments`` writes
    ``f"Rename alignment {old_a} to {new_a}"`` from a ``QLineEdit`` that keeps
    a pasted newline, so this file is what a paste into the alignment rename
    box used to leave on disk.

    It is still on disk for anyone it already happened to -- the historical log
    is copied through byte for byte on open and save -- which is why the
    read-side anchor is not made redundant by the writer no longer producing
    it. What changed is what the series then claims. bob's head carries six
    comma fields of its own and always parsed (with his pasted name cut at the
    newline); it is the orphaned TAIL that used to swallow the row after it.
    carol now keeps that row, no timestamp is reported as an editor, and the
    loss is printed instead of passing in silence.
    """
    head = "26-08-04, 19:14, bob, -, -, Rename alignment old to x"
    tail = "y, z"
    assert len(tail.split(", ")) == 2, "the k=2 orphan an older writer produced"

    write_log(series, GOOD, head, tail, SERIES_LEVEL)

    capsys.readouterr()
    editors = series.getEditorsFromHistory()
    out = capsys.readouterr().out

    assert editors == {"alice", "bob", "carol"}, (
        "the row the orphan used to swallow is read as the row it is"
    )
    assert "19:14" not in editors and "14:00" not in editors
    assert "unreadable" in out, "and the loss is reported rather than hidden"
    assert [
        s.strip() for s in series.getFullHistory(skip_corrupt=True).skipped_rows
    ] == [tail], "the orphaned tail alone, not the row after it"


def test_an_anchored_short_head_does_not_swallow_the_row_after_it():
    """The join guard specifically, told apart from the row-start anchor.

    These are two applications of the same stamp and it is easy to think one
    subsumes the other. It does not. A head that DOES carry the stamp is a
    real row -- the row-start check passes it -- and it can still be short of
    six comma fields, at which point the join runs and, unguarded, takes the
    next row.

    ``k=3`` is the reachable alignment for such a head: the concatenation puts
    the follower's USER into the section-range slot, so it parses whenever
    that username is numeric, and ``series.user`` is free text from a dialog.
    What came out was an editor named ``bob26-07-01`` -- bob's name welded to
    the next row's date -- while the real user of the row that was eaten
    disappeared.
    """
    head = "26-07-03, 16:00, bob"
    follower = "26-07-01, 14:00, 5, obj_c, 9, Modify trace(s)"
    assert len(head.split(", ")) == 3, "k=3 puts the follower's user in the section slot"
    assert ROW_START.match(head), "the head is itself a row; the start anchor passes it"

    ls = LogSet.fromList([head, follower], skip_corrupt=True)

    assert [l.user for l in ls.all_logs] == ["5"], (
        "the follower must be read as itself, not welded onto the short head"
    )
    assert [x.strip() for x in ls.skipped_rows] == [head]


def test_a_line_that_merely_contains_a_stamp_is_not_a_row():
    """The anchor is anchored, and that is load-bearing.

    Matching anywhere in the line rather than at its start would admit a
    fragment that happens to carry a stamp part-way through -- and such a
    fragment parses, reading its own leading text as a date and the embedded
    stamp's date as a USER.
    """
    frag = "zz, 26-07-01, 14:00, carol, 9, Modify trace(s)"
    assert ROW_START.search(frag), "the stamp is in there"
    assert not ROW_START.match(frag), "but not where a row starts"
    assert Log.fromStr(frag).user == "14:00", (
        "and admitting it would name a date as an editor"
    )

    ls = LogSet.fromList([GOOD, frag, LATE], skip_corrupt=True)

    assert [l.user for l in ls.all_logs] == ["alice", "carol"]
    assert [x.strip() for x in ls.skipped_rows] == [frag]


def test_the_stamp_must_be_a_whole_date_and_time_and_not_just_a_date():
    """Why ``ROW_START`` spells out the time and the separator after it.

    A date alone is too weak: a fragment whose first field merely looks like a
    date would anchor a row and yield an editor off its third field. And the
    trailing ``", "`` is what requires a user field to actually begin, so a
    row truncated before it is not mistaken for one.
    """
    looks_like_a_date = "12-34-56, notatime, x, y, 1, z"
    assert not ROW_START.match(looks_like_a_date)
    assert Log.fromStr(looks_like_a_date).user == "x", "it would parse if admitted"

    assert not ROW_START.match("26-07-03, 16:00"), "no user field begins here"
    assert ROW_START.match("26-07-03, 16:00, bob"), "here one does"

    ls = LogSet.fromList([GOOD, looks_like_a_date, LATE], skip_corrupt=True)

    assert [l.user for l in ls.all_logs] == ["alice", "carol"]
    assert "x" not in [l.user for l in ls.all_logs]


def test_the_irreducible_case_fails_safe_rather_than_inventing_an_editor():
    """What is left, and why nothing can be done about it.

    A pasted name whose own text contains a line shaped like a whole row
    produces bytes indistinguishable from two real rows. No parser can tell
    them apart, because there is nothing in the file to tell them apart with.

    What a parser CAN choose is which way to be wrong. The anchor treats the
    embedded line as a row, which truncates the pasted name -- a visible,
    bounded loss of text. The unguarded join treated it as a continuation and
    then read somebody's timestamp as a username, which is an assertion about
    a person that was never true. This test pins the choice, not the ambiguity.
    """
    hazard = ("26-08-04, 19:14, bob, -, -, Rename ztrace to x\n"
              "26-07-01, 14:00, carol, obj_c, 9, Modify trace(s)")
    ls = LogSet.fromList(hazard.split("\n"))

    assert [l.user for l in ls.all_logs] == ["bob", "carol"]
    assert ls.all_logs[0].event == "Rename ztrace to x", "the name is truncated"
    assert ls.skipped_rows == [], "and nothing is lost beyond the pasted text"


def test_a_genuine_continuation_is_still_joined():
    """The control, and what stops the two tests above from being vacuous.

    The join exists for a reason and the anchor must not disable it. A
    fragment that does NOT open with a date stamp is still a continuation and
    is still glued back on, which is how a row written by an older build with
    an ordinary multi-line name is read correctly today. This is the shape the
    one real corrupted file on this machine holds.
    """
    ls = LogSet.fromList([
        "23-05-11, 09:30, lab, d001sp003",
        ", 12, Modify trace(s)",
        LATE,
    ])

    assert [l.user for l in ls.all_logs] == ["lab", "carol"]
    assert ls.all_logs[0].obj_name == "d001sp003"
    assert ls.all_logs[0].section_ranges == [(12, 12)]
    assert ls.skipped_rows == []


# --------------------------------------------------------------------------- #
# the write side: the fragments are not produced any more
#
# The anchor above is a reader's defence against files that already exist.
# This is the other half: ``Log.__str__`` is the single point at which a
# ``Log`` becomes text -- ``getList``, ``getLogList(as_str=True)``,
# ``LogSet.__str__`` and ``__eq__`` all route through it, and it holds the only
# row-formatting f-string in the package -- so normalizing there makes "one
# Log, one physical line" a property of the format rather than of whichever
# call sites remembered to sanitize their free text.
# --------------------------------------------------------------------------- #
def test_a_log_never_renders_as_more_than_one_line():
    """Every terminator, not just ``\\n``.

    ``\\r`` matters as much as ``\\n``: a file written with a lone ``\\r``
    comes back as ``\\n`` through the universal-newline text mode
    ``getFullHistory`` reads with, so leaving it would only defer the split to
    the next read. ``\\r\\n`` must cost one character, not two.
    """
    for text in ("x\ny", "x\r\ny", "x\ry", "\n", "\r", "\r\n", "a\nb\nc"):
        for field in ("user", "obj_name", "event"):
            log = Log("26-06-30", "13:00", "u", "obj", 7, "Modify")
            setattr(log, field, text)
            row = str(log)
            assert "\n" not in row and "\r" not in row, (
                f"{field}={text!r} still renders across lines"
            )

    assert str(Log("26-06-30", "13:00", "u", "obj", 7, "a\r\nb")).endswith("a_b")
    assert str(Log("26-06-30", "13:00", "u", "obj", 7, "a\n\nb")).endswith("a__b")


def test_the_replacement_is_not_a_space():
    """``_`` and not ``" "``, for a reason worth pinning.

    A space next to an existing comma manufactures the ``", "`` ``fromStr``
    splits on, so sanitizing with one would trade a newline hazard for a
    field-shift hazard -- the ``BAD`` shape at the top of this module -- rather
    than removing anything.
    """
    row = str(Log("26-06-30", "13:00", "u", "obj", 7, "a,\nb"))

    assert row.count(", ") == 5, "the five separators the format has, and no more"
    assert Log.fromStr(row).event == "a,_b"


def test_sanitizing_changes_nothing_that_was_not_already_broken():
    """The cost, asserted to be zero.

    A row with no terminator in any field must render byte for byte as it did
    before. Measured over 300,000 generated renders (0 differences); this pins
    the property on the shapes that carry the format's own punctuation.
    """
    for name, event in (
        ("obj_a", "Modify trace(s)"), ("weird, name", "Modify trace(s)"),
        ("d001sp003", "Rename alignment old to new"), ("-", "Create series"),
        ("5", "Add to group 'x'"), ("é ü", "Set user column c as tab\there"),
    ):
        log = Log("26-06-30", "13:00", "bob", name, [(1, 3), (7, 7)], event)
        expected = (f"26-06-30, 13:00, bob, {name}, 1-3 7, {event}")
        assert str(log) == expected


def test_the_writer_and_the_reader_agree_end_to_end(series):
    """The two halves composed, which is the point of doing both.

    A pasted name that used to split its row now cannot, so the file has one
    line per row; and every row still round-trips through the anchored parser.
    Neither half is asserted in isolation here -- this is the claim a user
    cares about.
    """
    rows = [
        str(Log("26-06-30", "13:00", "bob", None, None,
                "Rename alignment old to x\ny, z")),
        str(Log("26-06-30", "13:01", "dave", "zt\nold", 7, "Rename ztrace to a\nb")),
        LATE,
    ]
    for row in rows:
        assert "\n" not in row

    write_log(series, *rows)

    ls = series.getFullHistory(skip_corrupt=True)
    assert [l.user for l in ls.all_logs] == ["bob", "dave", "carol"]
    assert ls.skipped_rows == []
    assert series.getEditorsFromHistory() == {"bob", "dave", "carol"}


def test_the_writer_uses_a_padded_two_digit_time(series):
    """The premise the anchor rests on, asserted rather than assumed.

    ``ROW_START`` recognises a row by ``getDateTime``'s own output, so what
    that output looks like is load-bearing. ``strftime``'s ``%y-%m-%d`` and
    ``%H:%M`` zero-pad every component, which is what makes "a line opening
    with this stamp is a row" a structural claim and not a guess. Recorded
    here so a change to the timestamp format turns into a visible failure
    rather than a parser that silently stops recognising its own rows.
    """
    from PyReconstruct.modules.constants import getDateTime
    from PyReconstruct.modules.datatypes.log import ROW_START

    d, t = getDateTime()
    assert len(d) == 8 and d.count("-") == 2
    assert len(t) == 5 and ":" in t
    assert ROW_START.match(str(Log(d, t, "alice", "obj_a", 5, "Modify")))


# --------------------------------------------------------------------------- #
# exportLogHistory: the same on-disk corruption, a second consumer
#
# Series > Export Log History reads existing_log.csv line by line and calls
# strptime on each line's first field. A row split across two lines by an older
# build has no date in the second one, so the call raised an uncaught
# ValueError out of the menu action -- on real data, reproduced before being
# fixed. Same file, same root cause, same anchor.
# --------------------------------------------------------------------------- #
def _today_row(user):
    """A row dated today, so "newer than 30 days" holds whenever this runs."""
    from PyReconstruct.modules.constants import getDateTime

    d, t = getDateTime()
    return f"{d}, {t}, {user}, obj_c, 9, Modify trace(s)"


def test_export_log_history_survives_a_row_split_across_two_lines(tmp_path):
    """The crash, and that the split row's halves stay together.

    Before the anchor, ``", 12, Modify trace(s)"`` reached ``strptime`` as a
    date and raised ``ValueError`` straight out of the menu action.
    """
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    recent = _today_row("carol")
    (hidden / "existing_log.csv").write_text(
        HEADER
        + "23-05-11, 09:30, lab, d001sp003\n"
        + ", 12, Modify trace(s)\n"
        + recent + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "archive.csv"

    LogSet.exportLogHistory(str(hidden), str(out), 30)

    archived = out.read_text(encoding="utf-8")
    kept = (hidden / "existing_log.csv").read_text(encoding="utf-8")

    # the 2023 row is older than 30 days, so it moves -- and its continuation
    # line must move with it, or the row is torn in half across two files.
    assert "d001sp003" in archived and ", 12, Modify trace(s)" in archived
    assert "d001sp003" not in kept and ", 12, Modify trace(s)" not in kept
    # today's row stays
    assert "carol" in kept and "carol" not in archived


def test_export_log_history_still_splits_an_ordinary_log_by_date(tmp_path):
    """The control: the anchor must not change the ordinary case."""
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    recent = _today_row("carol")
    (hidden / "existing_log.csv").write_text(
        HEADER + recent + "\n" + "20-01-01, 08:00, old, obj, 1, Modify\n",
        encoding="utf-8",
    )
    out = tmp_path / "archive.csv"

    LogSet.exportLogHistory(str(hidden), str(out), 30)

    archived = out.read_text(encoding="utf-8")
    kept = (hidden / "existing_log.csv").read_text(encoding="utf-8")

    assert archived.startswith(HEADER) and kept.startswith(HEADER)
    assert "20-01-01" in archived and "20-01-01" not in kept
    assert "carol" in kept and "carol" not in archived


def test_export_log_history_does_not_mistake_a_continuation_for_the_header(tmp_path):
    """A continuation whose text says "Date" is still a continuation.

    The header branch used to test ``"Date" in line`` -- a substring, not the
    header. A continuation line is free-form event text (a field of its row
    held a literal newline), so any of them mentioning a date field matched
    first, before the row/continuation branches ever ran, and was written to
    BOTH output files: duplicated into the file its row did not go to, and
    severed from the row it belongs to. ``test_export_log_history_survives_a_
    row_split_across_two_lines`` above does not catch it -- its continuation
    reads ``", 12, Modify trace(s)"``, which has no "Date" in it.

    The header is one exact literal (``LOG_HEADER``, matching all three writers
    in the tree), so matching it exactly is both sufficient and correct.
    """
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    recent = _today_row("carol")
    continuation = "Changed the Date field on this trace\n"
    (hidden / "existing_log.csv").write_text(
        HEADER
        + "20-01-01, 08:00, lab, d001sp003, 12, Modify trace(s)\n"
        + continuation
        + recent + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "archive.csv"

    LogSet.exportLogHistory(str(hidden), str(out), 30)

    archived = out.read_text(encoding="utf-8")
    kept = (hidden / "existing_log.csv").read_text(encoding="utf-8")

    # its row is older than the cutoff, so the continuation follows it out --
    # and appears there once, not in both files.
    assert continuation in archived
    assert continuation not in kept
    assert archived.count(continuation) == 1
    # the header itself is still recognised and still lands in both files
    assert archived.startswith(HEADER) and kept.startswith(HEADER)
    # and the ordinary split is unaffected
    assert "d001sp003" in archived and "d001sp003" not in kept
    assert "carol" in kept and "carol" not in archived
