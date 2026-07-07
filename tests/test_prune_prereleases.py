"""Tests for scripts/prune_prereleases.py.

The helper feeds `gh release delete` in the release workflow, so the tests
pin its selection contract hard: for a stable vX.Y.Z it selects exactly the
same-line pre-releases -- never the stable itself, never any other version
line (including the v1.21.10-vs-v1.21.0 prefix trap).
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "prune_prereleases.py"

_spec = importlib.util.spec_from_file_location("prune_prereleases", SCRIPT)
prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune)

# Every same-line pre-release form the repo has used or planned:
# PEP 440 compact (rcN / aN / bN) and dashed semver (-rc.N / -alpha.N / -beta.N),
# including the hyphen-number spelling -beta-N (the fork's chosen beta scheme).
SUPERSEDED = [
    "v1.21.0rc1",
    "v1.21.0rc2",
    "v1.21.0-rc.1",
    "v1.21.0-alpha.1",
    "v1.21.0-beta.2",
    "v1.21.0-beta-1",
    "v1.21.0-beta-3",
    "v1.21.0a1",
    "v1.21.0b2",
]

# Must survive: the stable itself, other version lines (stable or pre-release),
# and v1.21.10rc1 -- a prefix-matching bug would lump it into the v1.21.0 line.
SURVIVORS = [
    "v1.21.0",
    "v1.20.5rc1",
    "v1.20.4",
    "v1.20.4rc2",
    "v1.22.0rc1",
    "v1.22.0-beta-1",
    "v1.21.10rc1",
]


def test_selects_only_same_line_prereleases():
    tags = SURVIVORS + SUPERSEDED
    assert sorted(prune.select_superseded("v1.21.0", tags)) == sorted(SUPERSEDED)


@pytest.mark.parametrize("tag", SUPERSEDED)
def test_each_superseded_form_is_selected(tag):
    assert prune.select_superseded("v1.21.0", [tag]) == [tag]


@pytest.mark.parametrize("tag", SURVIVORS)
def test_each_survivor_is_not_selected(tag):
    assert prune.select_superseded("v1.21.0", [tag]) == []


def test_never_selects_the_stable_itself():
    assert prune.select_superseded("v1.21.0", ["v1.21.0"]) == []


@pytest.mark.parametrize("bad", ["v1.21.0rc1", "1.21.0", "prerelease", "v1.21"])
def test_rejects_non_stable_trigger(bad):
    with pytest.raises(ValueError):
        prune.select_superseded(bad, ["v1.21.0rc1"])


def test_cli_contract_matches_workflow_invocation():
    """stdin tag list + argv[1] stable -> stdout tags to delete, one per line."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "v1.21.0"],
        input="\n".join(SURVIVORS + SUPERSEDED) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert sorted(result.stdout.split()) == sorted(SUPERSEDED)


def test_cli_exits_nonzero_on_non_stable_argument():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "v1.21.0rc1"],
        input="v1.21.0rc1\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert result.stdout == ""
