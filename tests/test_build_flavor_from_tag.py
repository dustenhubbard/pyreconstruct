"""A stable build is cut from main by removing packaging/FLAVOR in the workflow.

main carries packaging/FLAVOR = dev, so every installer is the Dev app unless
build-installers.yml takes the file away first. It does that for a clean vX.Y.Z
tag and for a manual run with flavor=stable. These pin the step's placement in
every job that reads the file, and run its shell against a disposable repo.
"""

import os
from pathlib import Path
import re
import subprocess

import pytest

from test_pruning_preserves_release_tags import workflow_script


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "build-installers.yml"
STEP = "Pick the build flavor"
STABLE_TAG = r"^v[0-9]+\.[0-9]+\.[0-9]+$"

# Anything that reads packaging/FLAVOR, directly or through a script or spec.
READERS = ("packaging/FLAVOR", "packaging\\FLAVOR", "make_icns.sh", "make_dmg.sh",
           "PyReconstruct.spec", "PyReconstruct.iss")


def job_steps(job):
    """The steps of one job in build-installers.yml, as raw text blocks."""
    source = (ROOT / ".github" / "workflows" / WORKFLOW).read_text()
    body = source.split(f"\n  {job}:\n", 1)[1]
    body = re.split(r"\n  [a-z][a-z-]*:\n", body, maxsplit=1)[0]
    steps = body.split("\n    steps:\n", 1)[1]
    return re.split(r"\n(?=      - )", steps)


@pytest.mark.parametrize("job", ["build", "release"])
def test_flavor_step_runs_before_the_first_flavor_read(job):
    steps = job_steps(job)
    names = [s.split("- name: ", 1)[1].split("\n", 1)[0] if "- name: " in s else s
             for s in steps]
    assert names.count(STEP) == 1, f"{job} has no single '{STEP}' step"
    strip = names.index(STEP)
    readers = [i for i, s in enumerate(steps) if i != strip and any(r in s for r in READERS)]
    assert readers, f"{job} reads packaging/FLAVOR nowhere; is this test stale?"
    assert strip < min(readers), f"{job} reads packaging/FLAVOR before '{STEP}'"
    text = steps[strip]
    assert STABLE_TAG in text
    assert "FLAVOR_INPUT: ${{ inputs.flavor }}" in text


def test_readme_bump_never_reads_the_flavor():
    """readme-bump checks out main and edits the README only, so it needs no step."""
    assert not any(r in s for s in job_steps("readme-bump") for r in READERS)


def test_both_jobs_run_the_same_snippet():
    blocks = [s for job in ("build", "release") for s in job_steps(job)
              if f"- name: {STEP}\n" in s]
    assert len(blocks) == 2 and blocks[0].strip() == blocks[1].strip()


def test_dispatch_offers_the_flavor_choice():
    source = (ROOT / ".github" / "workflows" / WORKFLOW).read_text()
    dispatch = source.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "flavor:" in dispatch
    assert "type: choice" in dispatch
    assert "options: [dev, stable]" in dispatch
    assert "default: dev" in dispatch


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("ref,flavor_input,stable", [
    ("v1.23.0", "", True),                 # a stable tag push
    ("v1.23.0-beta-7", "", False),         # a pre-release tag push
    ("v1.24.0.dev3", "", False),           # a nightly tag push
    ("v1.23.0rc1", "", False),
    ("ci/stable-dry-run", "stable", True),  # the dispatch dry run
    ("main", "dev", False),
    ("v1.23.0", "dev", True),              # a stable tag is stable whatever the input
])
def test_flavor_step_strips_the_file_and_keeps_the_tree_clean(
    tmp_path, ref, flavor_input, stable,
):
    repo = tmp_path / "repo"
    (repo / "packaging").mkdir(parents=True)
    (repo / "packaging" / "FLAVOR").write_text("dev\n")
    git = ["git", "-C", str(repo), "-c", "user.name=Flavor test",
           "-c", "user.email=test@example.invalid", "-c", "core.hooksPath=/dev/null",
           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "--quiet", "-m", "fixture"], check=True)
    subprocess.run(git + ["tag", "v1.23.0"], check=True)

    env = dict(os.environ, GITHUB_REF_NAME=ref, FLAVOR_INPUT=flavor_input)
    out = subprocess.run(["bash", "-eo", "pipefail", "-c", workflow_script(WORKFLOW, STEP)],
                         cwd=repo, env=env, check=True, capture_output=True, text=True,
                         timeout=30).stdout

    assert (repo / "packaging" / "FLAVOR").exists() is not stable
    assert out.strip() == ("flavor: stable" if stable else "flavor: dev")
    # setuptools-scm marks a dirty tree in the version (a date suffix under
    # the only-version scheme), so a stable tag would not build as 1.23.0
    status = subprocess.check_output(git + ["status", "--porcelain"], text=True)
    assert status == ""
    described = subprocess.check_output(git + ["describe", "--tags", "--dirty"], text=True)
    assert described.strip() == "v1.23.0"
