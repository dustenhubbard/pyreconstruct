"""A stable release moves every download link in the README, User Guide, and website.

download-links-bump.yml runs three sed expressions over those files once a
stable release publishes. The User Guide and the website's front page went two
releases without a bump because the job edited only the README, and the
guide's version callout wrapped across two lines, which sed reads one line at a
time. This runs the job's own expressions over the real files and checks that
nothing still names the old version.

The bump used to run at the end of the release build, which stages a stable as
a hidden draft, so its PR opened while the release had no public downloads and
merging it first broke every link. The last tests here run the gate step
against a stand-in `gh` and check that only a published stable goes on to the
bump, and that the build hands a stable it publishes itself over to the bump.
"""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from test_pruning_preserves_release_tags import workflow_script

ROOT = Path(__file__).resolve().parents[1]
BUMP = "download-links-bump.yml"
WORKFLOW = ROOT / ".github" / "workflows" / BUMP
BUILD = ROOT / ".github" / "workflows" / "build-installers.yml"
FILES = ("README.md", "docs/USER_GUIDE.md", "docs/index.md")
GATE = "Check the release is public"
KICK = "Kick the publish-time workflows"


def _bump_step() -> str:
    text = WORKFLOW.read_text()
    return text[text.index("\n      - name: Open the bump PR\n"):]


def _bumped(path: str, version: str) -> str:
    exprs = re.findall(r'^\s+-e "(.+)" \\$', _bump_step(), re.M)
    assert len(exprs) == 3, exprs
    args = ["sed", "-E"]
    for e in exprs:
        args += ["-e", e.replace("${VERSION}", version)]
    return subprocess.run(args + [str(ROOT / path)], capture_output=True, text=True, check=True).stdout


def test_the_job_edits_and_commits_every_file():
    step = _bump_step()
    assert f"FILES=({' '.join(FILES)})" in step
    sed_block = step[step.index("sed -E -i"):step.index("git diff --quiet")]
    assert '"${FILES[@]}"' in sed_block
    for use in ('git diff --quiet "${FILES[@]}"', 'git add "${FILES[@]}"'):
        assert use in step, use


def test_a_new_version_leaves_no_old_download_link_or_callout():
    for path in FILES:
        text = (ROOT / path).read_text()
        old = re.search(r"current stable release, \*\*v(\d+\.\d+\.\d+)\*\*", text)
        assert old, f"{path} has no one-line version callout for the bump to find"
        out = _bumped(path, "9.9.9")
        assert "current stable release, **v9.9.9**" in out, path
        assert f"releases/download/v{old[1]}/" not in out, path
        assert f"PyReconstruct-{old[1]}-" not in out, path


def _fake_gh(tmp_path, answer):
    """A `gh` that logs its arguments and prints `answer`, or fails when it is None."""
    log = tmp_path / "gh.log"
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    body = 'echo "$*" >> "%s"\n' % log
    body += "exit 1\n" if answer is None else "echo '%s'\n" % answer
    gh.write_text("#!/bin/bash\n" + body)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return gh.parent, log


def _run(tmp_path, script, answer, **env):
    bindir, log = _fake_gh(tmp_path, answer)
    out = tmp_path / "output"
    out.touch()
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
           "GITHUB_OUTPUT": str(out), "GITHUB_REPOSITORY": "owner/repo", **env}
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    calls = log.read_text() if log.exists() else ""
    return result, out.read_text(), calls


def test_the_bump_runs_when_a_release_publishes_not_when_a_tag_is_pushed():
    text = WORKFLOW.read_text()
    on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "release:\n    types: [published]" in on
    assert "workflow_dispatch:" in on and "tag:" in on
    assert "push:" not in on
    assert "gh pr create" not in BUILD.read_text()


def test_every_step_after_the_gate_waits_for_it():
    steps = re.split(r"\n(?=      - )", WORKFLOW.read_text().split("\n    steps:\n", 1)[1])
    assert f"- name: {GATE}\n" in steps[0]
    assert "id: public" in steps[0]
    assert len(steps) == 3
    for step in steps[1:]:
        assert "if: steps.public.outputs.bump == 'true'" in step, step


@pytest.mark.parametrize("answer", [None, "true false", "true true"])
def test_a_draft_release_opens_no_bump(tmp_path, answer):
    """The by-tag lookup 404s for a draft; a draft flag that shows up anyway stops it too."""
    result, output, calls = _run(tmp_path, workflow_script(BUMP, GATE), answer, TAG="v9.9.9")
    assert "bump=true" not in output, result.stdout
    assert "repos/owner/repo/releases/tags/v9.9.9" in calls
    if answer is None:
        assert result.returncode != 0
        assert "has no published release" in result.stdout


def test_a_published_prerelease_opens_no_bump(tmp_path):
    result, output, _ = _run(tmp_path, workflow_script(BUMP, GATE), "false true", TAG="v9.9.9")
    assert result.returncode == 0, result.stderr
    assert "bump=true" not in output


def test_a_nightly_tag_opens_no_bump_and_asks_nothing(tmp_path):
    result, output, calls = _run(tmp_path, workflow_script(BUMP, GATE), "false false",
                                 TAG="v9.9.9.dev20260929")
    assert result.returncode == 0, result.stderr
    assert "bump=true" not in output
    assert calls == ""


def test_a_published_stable_goes_on_to_the_bump(tmp_path):
    result, output, _ = _run(tmp_path, workflow_script(BUMP, GATE), "false false", TAG="v9.9.9")
    assert result.returncode == 0, result.stderr
    assert output.splitlines() == ["bump=true", "version=9.9.9"]


@pytest.mark.parametrize("prerelease,bumps", [("false", True), ("true", False)])
def test_the_build_hands_a_stable_it_publishes_to_the_bump(tmp_path, prerelease, bumps):
    """A publish with the workflow token fires no release trigger, so the build dispatches it."""
    kick = BUILD.read_text().split(f"- name: {KICK}\n", 1)[1].split("\n      - name:", 1)[0]
    assert "if: steps.rel.outputs.draft != 'true'" in kick
    assert "PRERELEASE: ${{ steps.rel.outputs.prerelease }}" in kick
    _, _, calls = _run(tmp_path, workflow_script("build-installers.yml", KICK), "",
                       PRERELEASE=prerelease, GITHUB_REF_NAME="v9.9.9")
    dispatch = f"workflow run {BUMP} --repo owner/repo -f tag=v9.9.9"
    assert (dispatch in calls) is bumps, calls
