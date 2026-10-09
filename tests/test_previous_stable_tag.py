"""Tests for scripts/previous_stable_tag.py and the stable notes step that uses it.

A stable release's notes end with a compare link from the previous stable. A
plain version sort over every tag puts v1.23.0-beta-6 between v1.24.0 and
v1.23.0, so the link for v1.24.0 started at the last beta. These tests pin the
pick to stable tags only, on the repository's real tag list and on a synthetic
one full of betas, release candidates and nightlies.
"""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_pruning_preserves_release_tags import workflow_script


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "previous_stable_tag.py"

_spec = importlib.util.spec_from_file_location("previous_stable_tag", SCRIPT)
previous = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(previous)

# `git ls-remote --tags origin` on dustenhubbard/pyreconstruct, 2026-10-09,
# the day after 1.24.0 shipped.
REAL_TAGS = """
v1.0.0 v1.1.0 v1.2.0 v1.3.0 v1.4.0 v1.5.0 v1.6.0 v1.7.0 v1.8.0
v1.9.0 v1.9.1 v1.9.2 v1.9.3 v1.9.4 v1.10.0 v1.11.0 v1.12.0 v1.13.0
v1.14.0 v1.15.0 v1.15.1 v1.16.0 v1.16.1 v1.17.0 v1.18.0 v1.19.0
v1.20.0 v1.20.1 v1.20.2 v1.20.3 v1.20.4 v1.21.0 v1.21.0-beta-1
v1.21.0-beta-2 v1.21.0-beta-3 v1.21.0-beta-4 v1.21.0-beta-5
v1.21.0-beta-6 v1.21.0-beta-7 v1.21.1 v1.21.2 v1.21.2-beta-1 v1.21.3
v1.22.0 v1.22.1 v1.22.2 v1.22.3 v1.23.0 v1.23.0-beta-2 v1.23.0-beta-3
v1.23.0-beta-4 v1.23.0-beta-5 v1.23.0-beta-6 v1.24.0
v1.24.0.dev20260927 v1.24.0.dev20260928 v1.24.0.dev20260929
v1.24.0.dev20260930 v1.24.0.dev20261001 v1.24.0.dev20261002
v1.24.0.dev20261003 v1.24.0.dev20261004 v1.24.0.dev20261005
v1.24.0.dev20261006 v1.24.0.dev20261007 v1.24.0.dev20261008
v1.24.0.dev202610081408 v1.24.0.dev202610082242 v1.25.0.dev202610090706
""".split()

# Every pre-release form the repo has tagged or planned, on the line being
# released and the lines either side of it, plus non-version tags.
SYNTHETIC_TAGS = [
    "v1.29.0", "v1.29.1", "v1.29.10",
    "v1.29.11-beta-1", "v1.29.11rc1", "v1.29.11.dev20270101",
    "v1.30.0-beta-1", "v1.30.0-beta.2", "v1.30.0-rc.1", "v1.30.0-alpha.1",
    "v1.30.0rc1", "v1.30.0a1", "v1.30.0b2", "v1.30.0.dev20270201",
    "v1.30.0.dev202702011200",
    "v1.30.0",
    "v1.30.1-beta-1", "v1.30.1.dev20270301", "v1.31.0.dev20270401",
    "prerelease", "recovery/main-43-merges",
]


@pytest.mark.parametrize("current,expected", [
    ("v1.24.0", "v1.23.0"),        # the 1.24.0 release: not v1.23.0-beta-6
    ("v1.23.0", "v1.22.3"),
    ("v1.22.0", "v1.21.3"),        # not v1.21.2-beta-1
    ("v1.21.1", "v1.21.0"),        # not v1.21.0-beta-7
    ("v1.10.0", "v1.9.4"),         # by number, not by text
    ("v1.25.0", "v1.24.0"),        # the next stable, tagged after the list
    ("v1.24.1", "v1.24.0"),        # not a v1.24.0 nightly
    ("v1.25.0-beta-1", "v1.24.0"),
    ("v1.0.0", None),
])
def test_picks_previous_stable_on_the_real_tags(current, expected):
    assert previous.previous_stable(current, REAL_TAGS) == expected


@pytest.mark.parametrize("current,expected", [
    ("v1.30.0", "v1.29.10"),
    ("v1.30.1", "v1.30.0"),
    ("v1.31.0", "v1.30.0"),
    ("v1.30.0-beta-1", "v1.29.10"),
    ("v1.30.0rc1", "v1.29.10"),
    ("v1.30.1.dev20270301", "v1.30.0"),
    ("v1.29.0", None),
])
def test_picks_previous_stable_among_betas_and_nightlies(current, expected):
    assert previous.previous_stable(current, SYNTHETIC_TAGS) == expected


@pytest.mark.parametrize("current", ["main", "prerelease", "v1.30", "1.30.0"])
def test_no_pick_for_a_ref_that_is_not_a_release_tag(current):
    assert previous.previous_stable(current, SYNTHETIC_TAGS) is None


def test_cli_contract_matches_workflow_invocation():
    """stdin tag list + argv[1] released tag -> stdout previous stable or nothing."""
    def run(current):
        return subprocess.run(
            [sys.executable, str(SCRIPT), current],
            input="\n".join(REAL_TAGS) + "\n",
            capture_output=True, text=True, check=True,
        ).stdout

    assert run("v1.24.0") == "v1.23.0\n"
    assert run("v1.0.0") == ""


def _local_tags():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v*"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return out.split()


def test_picks_previous_stable_on_the_checkout_tags():
    """The live tag list, when the checkout has the tags (CI clones are shallow)."""
    tags = _local_tags()
    if not {"v1.23.0", "v1.24.0"} <= set(tags):
        pytest.skip("checkout has no release tags")
    assert previous.previous_stable("v1.24.0", tags) == "v1.23.0"


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("current,expected", [
    ("v1.24.0", "v1.23.0"),
    ("v1.21.1", "v1.21.0"),
])
def test_stable_notes_step_links_from_the_previous_stable(tmp_path, current, expected):
    """Run the workflow's own notes step in a repository tagged like origin."""
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    subprocess.run([
        "git", "-C", str(repository), "-c", "user.name=Notes test",
        "-c", "user.email=test@example.invalid", "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "--allow-empty",
        "-m", "Release fixture",
    ], check=True)
    for tag in REAL_TAGS:
        subprocess.run(["git", "-C", str(repository), "tag", tag], check=True)
    (repository / "scripts").mkdir()
    shutil.copy(SCRIPT, repository / "scripts" / SCRIPT.name)
    (repository / "WHATS_NEW.md").write_text(f"## [{current[1:]}]\n\n- Something new.\n")

    env = dict(os.environ, GITHUB_REPOSITORY="fixture/repository",
               GITHUB_REF_NAME=current)
    subprocess.run(
        ["bash", "-eo", "pipefail", "-c",
         workflow_script("build-installers.yml", "Build friendly release notes")],
        cwd=repository, env=env, check=True, capture_output=True, text=True,
        timeout=30,
    )

    body = (repository / "release_body.md").read_text()
    assert f"compare/{expected}...{current}" in body, body
