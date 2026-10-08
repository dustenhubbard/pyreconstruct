"""The nightly-pruning policy, as pure selection logic.

Two rules: nightlies overtaken by a shipped stable go, and of those still
ahead of stable only the newest seven stay, a week of rollback room. The
retired vX.Y.Z-beta-N shape is recognized for the first rule only, so the
leftovers of that channel disappear as their stables ship. Everything else on
the releases page is untouchable by this script: stables, drafts (filtered by
the caller), and any tag of another shape.
"""

import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prune_nightlies import KEEP_NIGHTLIES, NIGHTLY_RE, select_prunable  # noqa: E402


def lines(*pairs):
    return [f"{tag} {flag}" for tag, flag in pairs]


def nightly(base, day, month=9, year=2026):
    return f"v{base}.dev{year}{month:02d}{day:02d}"


# Ten nights of 1.24.0 previews after 1.23.0 shipped, plus the leftovers of
# the retired channel.
TODAY = lines(
    ("v1.23.0", "false"),
    *((nightly("1.24.0", d), "true") for d in range(1, 11)),
    ("v1.23.0-beta-6", "true"),
    ("v1.23.0-beta-5", "true"),
    ("v1.22.3", "false"),
    ("v1.22.1-beta-1", "true"),
    ("v1.21.3", "true"),           # prerelease-flagged but not a nightly tag
)


def test_the_releases_page_as_it_stands_today():
    """The three oldest nights go (ten minus seven), and every retired-shape
    pre-release of a version that shipped goes with them."""
    assert sorted(select_prunable(TODAY)) == sorted([
        nightly("1.24.0", 1), nightly("1.24.0", 2), nightly("1.24.0", 3),
        "v1.23.0-beta-6", "v1.23.0-beta-5", "v1.22.1-beta-1",
    ])


def test_seven_or_fewer_nightlies_are_never_pruned_within_their_lead():
    rows = lines(("v1.23.0", "false"),
                 *((nightly("1.24.0", d), "true") for d in range(1, KEEP_NIGHTLIES + 1)))
    assert select_prunable(rows) == []


def test_a_shipped_stable_takes_its_whole_nightly_line():
    rows = lines(
        ("v1.24.0", "false"),
        (nightly("1.24.0", 9), "true"),
        (nightly("1.24.0", 10), "true"),
    )
    assert sorted(select_prunable(rows)) == [nightly("1.24.0", 9), nightly("1.24.0", 10)]


def test_a_patch_stable_overtakes_nightlies_of_its_own_and_lower_bases():
    """v1.23.1 ships from a hotfix branch; a 1.23.1 preview is stale, a 1.24.0
    preview is not."""
    rows = lines(
        ("v1.23.1", "false"),
        (nightly("1.23.1", 5), "true"),
        (nightly("1.24.0", 5), "true"),
    )
    assert select_prunable(rows) == [nightly("1.23.1", 5)]


def test_nightlies_sort_by_date_across_months_and_years():
    """20260930 is older than 20261001; a lexical sort of the whole tag would
    agree here, but the date is compared as a number so a two-digit day never
    sorts above a one-digit month."""
    rows = lines(
        ("v1.23.0", "false"),
        *((nightly("1.24.0", d, month=9), "true") for d in range(24, 31)),  # 7
        (nightly("1.24.0", 1, month=10), "true"),
        (nightly("1.24.0", 2, month=1, year=2027), "true"),
    )
    assert select_prunable(rows) == [nightly("1.24.0", 24), nightly("1.24.0", 25)]


def test_the_seven_are_counted_across_base_versions():
    """A planned major line shares the budget with the minor line: it is one
    channel, newest seven by date."""
    rows = lines(
        ("v1.23.0", "false"),
        *((nightly("1.24.0", d), "true") for d in range(1, 6)),   # 5, older
        *((nightly("2.0.0", d), "true") for d in range(6, 11)),   # 5, newer
    )
    assert select_prunable(rows) == [nightly("1.24.0", 1), nightly("1.24.0", 2),
                                     nightly("1.24.0", 3)]


def test_no_stable_release_means_no_pruning_at_all():
    rows = lines(*((nightly("1.24.0", d), "true") for d in range(1, 11)))
    assert select_prunable(rows) == []


def test_a_retired_shape_ahead_of_stable_is_left_alone():
    """Rule 2 is for nightlies only: a leftover beta of an unshipped version is
    not counted against the seven and not pruned by age."""
    rows = lines(
        ("v1.23.0", "false"),
        ("v1.24.0-beta-1", "true"),
        *((nightly("1.24.0", d), "true") for d in range(1, 9)),
    )
    assert select_prunable(rows) == [nightly("1.24.0", 1)]


def test_odd_tags_are_never_selected():
    rows = TODAY + lines(
        ("prerelease", "true"),            # the retired rolling tag
        ("v1.23.0-rc.1", "true"),          # neither shape
        ("v1.23.0b9", "true"),             # PEP 440 beta: not this script's shape
        ("v1.23.0.dev3", "true"),          # a dev tag without the eight-digit date
        ("v1.23.0.dev2026092", "true"),    # seven digits
        ("v1.23.0.dev202609281", "true"),  # nine digits
    )
    selected = select_prunable(rows)
    for tag in ("prerelease", "v1.23.0-rc.1", "v1.23.0b9", "v1.23.0.dev3",
                "v1.23.0.dev2026092", "v1.23.0.dev202609281"):
        assert tag not in selected


def test_a_stable_flagged_as_prerelease_is_not_a_stable():
    """Only a non-prerelease vX.Y.Z sets the bar. A vX.Y.Z accidentally
    published as a pre-release would otherwise prune every nightly."""
    rows = lines(
        ("v1.24.0", "true"),
        (nightly("1.24.0", 1), "true"),
    )
    assert select_prunable(rows) == []


def test_the_nightly_shape_is_exactly_the_workflow_tag_shape():
    assert NIGHTLY_RE.pattern == r"^v(\d+)\.(\d+)\.(\d+)\.dev(\d{8}(?:\d{4})?)$"
    assert NIGHTLY_RE.match("v1.24.0.dev20260928")
    assert NIGHTLY_RE.match("v1.24.0.dev202610081315")
    assert not NIGHTLY_RE.match("v1.24.0.dev2026100813")
    assert NIGHTLY_RE.match("v10.0.12.dev20261231")
    assert not NIGHTLY_RE.match("v1.24.0.dev2026092")
    assert not NIGHTLY_RE.match("v1.24.0dev20260928")
    assert not NIGHTLY_RE.match("1.24.0.dev20260928")
    assert not NIGHTLY_RE.match("v1.24.0.dev20260928+dirty")


def test_the_script_runs_as_the_workflow_runs_it():
    """stdin in, tags out, stdlib only."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "prune_nightlies.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        input="\n".join(TODAY), capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert sorted(result.stdout.split()) == sorted([
        nightly("1.24.0", 1), nightly("1.24.0", 2), nightly("1.24.0", 3),
        "v1.23.0-beta-6", "v1.23.0-beta-5", "v1.22.1-beta-1",
    ])


def test_timed_nightlies_count_with_the_dated_ones_in_time_order():
    """Since 2026-10-08 a nightly's dev number is YYYYMMDDHHMM. Every one sorts
    above every 8-digit YYYYMMDD tag, and the seven kept are the newest seven."""
    dated = [nightly("1.24.0", d, month=10) for d in range(3, 9)]   # 10-03 .. 10-08
    timed = ["v1.24.0.dev202610081315", "v1.24.0.dev202610081840",
             "v1.24.0.dev202610090600"]
    rows = lines(("v1.23.0", "false"), *((tag, "true") for tag in timed + dated))
    assert sorted(select_prunable(rows)) == sorted(dated[:2])   # 10-03 and 10-04 go
