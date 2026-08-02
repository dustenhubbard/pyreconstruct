"""The import must say when it cannot use the history it was asked to use.

"Check history" in the import dialog compares the two series' logs, keeps their
longest matching opening run, and treats everything after it as work done since
the copies diverged. That is what lets an import honor a deletion or a rename
instead of reading the missing object as something the other person has not
drawn yet.

When the logs have no matching opening run, `LogSetPair.last_shared_index` is
-1 and `Section.importTraces` skips its whole history block. The import still
runs, as a plain union of the two series, and nothing anywhere says so: no
dialog, no log line, and the checkbox the user ticked stays ticked. The result
reads exactly like a successful history-aware import.

Measured, and pinned below: a -1 needs only one of the two logs to start
differently from the other, so an empty log on either side is enough, and the
series that ships with this repository has an empty log. Copy it, delete an
object in the copy, import the original back with the history check on, and the
deleted object is present again afterwards.

These tests cover the three claims the notice rests on:

  1. the conditions that produce a -1 (empty log, one-sided trim, logs that
     simply start differently);
  2. what the skipped history block costs, measured against the same merge with
     a usable history;
  3. that `importFromSeries` shows the warning before it changes anything, that
     declining it leaves the series untouched, and that a normal import with a
     shared log prefix is not interrupted.

The third is where an over-eager warning would show up, and it is the reason
tests 4 and 5 exist: a merge whose history *is* usable, and a merge that never
asked for the history check, must both go through in silence.
"""
import types

import pytest

from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.datatypes.log import LogSet, LogSetPair
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.utils import importHistoryWarning


def logLine(obj_name, section, event, date="26-01-01", time="0900", user="u"):
    snum = "-" if section is None else str(section)
    return f"{date}, {time}, {user}, {obj_name}, {snum}, {event}"


def mkPair(self_lines, other_lines):
    return LogSetPair(LogSet.fromList(self_lines), LogSet.fromList(other_lines))


def mk(dx=0.0, dy=0.0, side=10.0, name="square"):
    """A closed square of the given side, offset by (dx, dy)."""
    t = Trace(name, (0, 0, 0), True)
    t.points = [
        (dx, dy), (dx + side, dy), (dx + side, dy + side), (dx, dy + side)
    ]
    return t


class _Series:
    """The slice of Series that Section.importTraces reaches for."""

    def __init__(self):
        self.user = "tester"
        self.logs = []

    def addLog(self, obj_name, snum, event):
        self.logs.append((obj_name, snum, event))

    def getAttr(self, *args, **kwargs):
        return None


def mkSection(contours, snum=2, mag=0.01):
    sec = Section.__new__(Section)
    sec.n = snum
    sec.mag = mag
    sec.contours = dict(contours)
    sec.flags = []
    sec.modified_contours = set()
    sec.series = _Series()
    sec.save = lambda *a, **k: None
    return sec


# --------------------------------------------------------------------------- #
# 1. what produces a divergence point of -1
# --------------------------------------------------------------------------- #
def test_an_empty_log_on_either_side_leaves_no_divergence_point():
    """The case the shipped fixture is in, and every converted series with it."""
    edited = [logLine("square", 1, "Modify trace(s)")]

    assert mkPair([], edited).last_shared_index == -1
    assert mkPair(edited, []).last_shared_index == -1
    assert not mkPair([], edited).complete_match, (
        "premise: an empty log against a non-empty one is a real divergence, "
        "not the 'the two logs are identical' case"
    )


def test_a_one_sided_trim_leaves_no_divergence_point():
    """`LogSet.exportLogHistory` moves old entries out to a CSV. Doing that on
    one copy and not the other drops the shared opening run the comparison is
    built on, so the logs disagree from the first line."""
    full = [
        logLine("square", 1, "Modify trace(s)", date="25-01-01"),
        logLine("square", 1, "Modify trace(s)", date="26-01-01"),
    ]
    trimmed = full[1:]  # the older half exported and removed

    assert mkPair(full, trimmed).last_shared_index == -1


def test_logs_that_start_differently_leave_no_divergence_point():
    """Neither log is empty and neither was trimmed: they simply do not begin
    with the same event, which is enough on its own."""
    a = [logLine("square", 1, "Create trace(s)")]
    b = [logLine("circle", 1, "Create trace(s)")]

    assert mkPair(a, b).last_shared_index == -1


def test_a_shared_opening_run_gives_a_real_divergence_point():
    """The control for all three above."""
    shared = [logLine("seed", 1, "Modify trace(s)")]
    pair = mkPair(
        shared + [logLine("square", 1, "Modify trace(s)")],
        shared + [logLine("circle", 1, "Modify trace(s)")],
    )

    assert pair.last_shared_index == 0
    assert not pair.complete_match


# --------------------------------------------------------------------------- #
# 2. what the skipped history block costs
# --------------------------------------------------------------------------- #
def test_a_deletion_comes_back_when_the_history_cannot_be_used():
    """The measurement the warning exists to describe.

    This series deleted 'square'; the other still has it. With a usable history
    the deletion is honored. With `last_shared_index == -1` the history block
    never runs, the merge is a plain union, and the object is back.
    """
    deleted_here = mkSection({})                       # 'square' deleted
    other = mkSection({"square": Contour("square", [mk(0.0)])})

    unusable = mkPair([], [logLine("circle", 1, "Modify trace(s)")])
    assert unusable.last_shared_index == -1, "premise: no divergence point"

    deleted_here.importTraces(other, threshold=0.95, histories=unusable)

    assert "square" in deleted_here.contours, (
        "premise for the warning: with the history skipped the import is a "
        "plain union, so a deleted object comes back"
    )


def test_the_same_deletion_is_honored_when_the_history_can_be_used():
    """The other half of the measurement: the history check does work when the
    logs share an opening run, which is what makes the silent skip a loss."""
    deleted_here = mkSection({})
    other = mkSection({"square": Contour("square", [mk(0.0)])})

    shared = [logLine("seed", 1, "Modify trace(s)")]
    usable = mkPair(
        shared + [logLine("square", None, "Delete object")],
        shared + [logLine("circle", 1, "Modify trace(s)")],
    )
    assert usable.last_shared_index == 0, "premise: there is a divergence point"

    deleted_here.importTraces(other, threshold=0.95, histories=usable)

    assert "square" not in deleted_here.contours, (
        "with a usable history the recorded deletion is propagated"
    )


# --------------------------------------------------------------------------- #
# 3. the warning text
# --------------------------------------------------------------------------- #
def stubSeries(lines):
    return types.SimpleNamespace(
        getFullHistory=lambda: LogSet.fromList(list(lines))
    )


def test_warning_is_returned_when_the_logs_share_no_opening_run():
    warning = importHistoryWarning(
        stubSeries([]), stubSeries([logLine("square", 1, "Modify trace(s)")])
    )

    assert warning is not None
    assert "history check cannot be used" in warning
    assert "come back" in warning and "both names" in warning, (
        "the warning has to say what the user will actually see: deletions "
        "coming back and renames landing under both names"
    )


def test_no_warning_when_the_logs_share_an_opening_run():
    """The over-eager case. A merge whose history is usable must be silent."""
    shared = [logLine("seed", 1, "Modify trace(s)")]

    assert importHistoryWarning(
        stubSeries(shared + [logLine("square", 1, "Modify trace(s)")]),
        stubSeries(shared + [logLine("circle", 1, "Modify trace(s)")]),
    ) is None


def test_no_warning_when_the_two_logs_are_identical():
    """Identical logs reach `last_shared_index >= 0`, so no warning is returned.

    This pins current behavior rather than endorsing it. Identical logs also set
    `complete_match`, and the gate in `Section.importTraces` is
    `not complete_match and last_shared_index >= 0`, so the history block is
    skipped here too and nothing says so. That is the same silent skip this
    module exists to report, reached by a second path, and it is not covered:
    `importHistoryWarning` tests only `last_shared_index`.

    It is left rather than fixed because warning on every identical-log import
    would be a false alarm on copies that genuinely have not diverged, where a
    plain union is the right answer. The logs alone do not separate that from
    two sides trimmed to the same prefix by `LogSet.exportLogHistory`, which is
    the case where the content diverged after the cut and nothing is said.
    """
    shared = [logLine("seed", 1, "Modify trace(s)")]

    assert importHistoryWarning(stubSeries(shared), stubSeries(shared)) is None


@pytest.mark.parametrize(
    "self_lines, other_lines, phrase",
    [
        ([], [], "Neither series has a log"),
        ([], [logLine("a", 1, "Modify trace(s)")], "current series has no log"),
        ([logLine("a", 1, "Modify trace(s)")], [], "imported from has no log"),
        (
            [logLine("a", 1, "Create trace(s)")],
            [logLine("b", 1, "Create trace(s)")],
            "no shared starting point",
        ),
    ],
)
def test_warning_names_the_reason(self_lines, other_lines, phrase):
    """Four different ways to reach the same skip. A user who is told only
    'the history was skipped' has no way to tell which of their two series is
    the one without a log."""
    warning = importHistoryWarning(
        stubSeries(self_lines), stubSeries(other_lines)
    )

    assert warning is not None and phrase in warning


# --------------------------------------------------------------------------- #
# 4. the wiring in importFromSeries
# --------------------------------------------------------------------------- #
TRACE_RESPONSE = [
    None,   # srange
    [],     # regex_filters
    [],     # group_filters
    0.95,   # threshold
    True,   # flag_conflicts
    True,   # check_history
    True,   # import_obj_attrs
    "self", # keep_above
    "",     # keep_below
]


def importWindow(monkeypatch, self_lines, other_lines, check_history=True):
    """A stub MainWindow wired for one trip through importFromSeries.

    Returns (window, calls). `calls["imported"]` records the importTraces call
    and `calls["closed"]` the other series being closed.
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    calls = {"imported": [], "closed": 0}

    o_series = types.SimpleNamespace(
        avg_mag=0.01,
        getFullHistory=lambda: LogSet.fromList(list(other_lines)),
    )
    o_series.close = lambda: calls.__setitem__("closed", calls["closed"] + 1)

    monkeypatch.setattr(
        mw, "FileDialog",
        types.SimpleNamespace(get=lambda *a, **k: "/some/series.jser"),
    )
    monkeypatch.setattr(
        mw.Series, "openJser", staticmethod(lambda *a, **k: o_series)
    )
    monkeypatch.setattr(mw, "checkMag", lambda s, o: True)

    traces = list(TRACE_RESPONSE)
    traces[5] = check_history
    monkeypatch.setattr(
        mw, "ImportSeriesDialog",
        lambda *a, **k: types.SimpleNamespace(
            exec=lambda: ({"traces": traces}, True)
        ),
    )

    series = types.SimpleNamespace(
        getFullHistory=lambda: LogSet.fromList(list(self_lines)),
        importTraces=lambda *a, **k: calls["imported"].append((a, k)),
    )
    window = types.SimpleNamespace(
        series=series,
        saveAllData=lambda: None,
        field=types.SimpleNamespace(
            series_states={},
            reload=lambda: None,
            table_manager=types.SimpleNamespace(refresh=lambda: None),
        ),
    )
    return window, calls


def test_the_user_is_warned_before_a_degraded_import(
    monkeypatch, main_window_dialogs
):
    """The whole point: an import that cannot use the history says so, and it
    says so before it has changed anything."""
    from PyReconstruct.modules.gui.main import main_window as mw

    window, calls = importWindow(
        monkeypatch, [], [logLine("square", 1, "Modify trace(s)")]
    )

    mw.MainWindow.importFromSeries(window)

    warnings = [
        n for n in main_window_dialogs.notices
        if "history check cannot be used" in n
    ]
    assert len(warnings) == 1, (
        f"expected one history warning, saw {main_window_dialogs.notices!r}"
    )
    assert calls["imported"], "accepting the warning still runs the import"


def test_declining_the_warning_leaves_the_series_untouched(
    monkeypatch, main_window_dialogs
):
    """The warning is worth nothing if the only answer is 'yes'."""
    from PyReconstruct.modules.gui.main import main_window as mw

    main_window_dialogs.confirm_accepted = False
    window, calls = importWindow(
        monkeypatch, [], [logLine("square", 1, "Modify trace(s)")]
    )

    mw.MainWindow.importFromSeries(window)

    assert not calls["imported"], "declining must abort before any import runs"
    assert calls["closed"] == 1, "the other series is closed on the way out"


def test_a_usable_history_is_not_interrupted(monkeypatch, main_window_dialogs):
    """The over-eager case, at the level the user meets it."""
    from PyReconstruct.modules.gui.main import main_window as mw

    shared = [logLine("seed", 1, "Modify trace(s)")]
    window, calls = importWindow(
        monkeypatch,
        shared + [logLine("square", 1, "Modify trace(s)")],
        shared + [logLine("circle", 1, "Modify trace(s)")],
    )

    mw.MainWindow.importFromSeries(window)

    assert not [
        n for n in main_window_dialogs.notices
        if "history check cannot be used" in n
    ], "a merge whose history is usable must not be interrupted"
    assert calls["imported"], "and it must still import"


def test_no_warning_when_the_history_check_was_not_requested(
    monkeypatch, main_window_dialogs
):
    """Nothing was promised, so nothing was skipped: an unchecked box gets a
    plain union by request and must not be warned about."""
    from PyReconstruct.modules.gui.main import main_window as mw

    window, calls = importWindow(
        monkeypatch,
        [],
        [logLine("square", 1, "Modify trace(s)")],
        check_history=False,
    )

    mw.MainWindow.importFromSeries(window)

    assert not [
        n for n in main_window_dialogs.notices
        if "history check cannot be used" in n
    ]
    assert calls["imported"]
