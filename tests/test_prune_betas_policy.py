"""The beta-pruning policy, as pure selection logic.

Two rules (his call, 2026-08-28): betas overtaken by a shipped stable go,
and within a line still ahead of stable only the newest two stay -- the one
the updater offers plus one rollback. Everything else on the releases page
is untouchable by this script: stables, drafts are filtered by the caller,
and any tag not shaped vX.Y.Z-beta-N.
"""

import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prune_betas import select_prunable  # noqa: E402


def lines(*pairs):
    return [f"{tag} {flag}" for tag, flag in pairs]


TODAY = lines(
    ("v1.22.2", "false"),
    ("v1.23.0-beta-4", "true"),
    ("v1.23.0-beta-3", "true"),
    ("v1.23.0-beta-2", "true"),
    ("v1.23.0-beta-1", "true"),
    ("v1.22.1", "false"),
    ("v1.22.0", "false"),
    ("v1.21.3", "true"),           # prerelease-flagged but not a beta tag
)


def test_the_releases_page_as_it_stands_today():
    """Beta-1 and beta-2 go; beta-4 (current) and beta-3 (rollback) stay."""
    assert sorted(select_prunable(TODAY)) == [
        "v1.23.0-beta-1", "v1.23.0-beta-2",
    ]


def test_a_shipped_stable_takes_its_whole_beta_line():
    rows = lines(
        ("v1.23.0", "false"),
        ("v1.23.0-beta-4", "true"),
        ("v1.23.0-beta-3", "true"),
    )
    assert sorted(select_prunable(rows)) == [
        "v1.23.0-beta-3", "v1.23.0-beta-4",
    ]


def test_one_or_two_betas_are_never_pruned_within_their_line():
    rows = lines(("v1.22.2", "false"), ("v1.23.0-beta-1", "true"))
    assert select_prunable(rows) == []

    rows = lines(
        ("v1.22.2", "false"),
        ("v1.23.0-beta-2", "true"),
        ("v1.23.0-beta-1", "true"),
    )
    assert select_prunable(rows) == []


def test_beta_numbers_sort_numerically_not_lexically():
    """beta-10 is newer than beta-9: a lexical sort would prune the wrong one."""
    rows = lines(
        ("v1.22.2", "false"),
        ("v1.23.0-beta-10", "true"),
        ("v1.23.0-beta-9", "true"),
        ("v1.23.0-beta-8", "true"),
    )
    assert select_prunable(rows) == ["v1.23.0-beta-8"]


def test_separate_lines_keep_their_own_newest_two():
    rows = lines(
        ("v1.22.2", "false"),
        ("v1.23.0-beta-2", "true"),
        ("v1.23.0-beta-1", "true"),
        ("v1.24.0-beta-3", "true"),
        ("v1.24.0-beta-2", "true"),
        ("v1.24.0-beta-1", "true"),
    )
    assert select_prunable(rows) == ["v1.24.0-beta-1"]


def test_no_stable_release_means_no_pruning_at_all():
    rows = lines(
        ("v1.23.0-beta-4", "true"),
        ("v1.23.0-beta-1", "true"),
    )
    assert select_prunable(rows) == []


def test_odd_tags_are_never_selected():
    rows = TODAY + lines(
        ("prerelease", "true"),            # the retired rolling tag
        ("v1.23.0-rc.1", "true"),          # not a -beta-N tag
        ("v1.23.0b9", "true"),             # PEP 440 form: not this script's shape
    )
    selected = select_prunable(rows)
    assert "prerelease" not in selected
    assert "v1.23.0-rc.1" not in selected
    assert "v1.23.0b9" not in selected


def test_the_script_runs_as_the_workflow_runs_it():
    """stdin in, tags out, stdlib only."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "prune_betas.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        input="\n".join(TODAY), capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert sorted(result.stdout.split()) == [
        "v1.23.0-beta-1", "v1.23.0-beta-2",
    ]
