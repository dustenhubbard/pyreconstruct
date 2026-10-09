"""The `merge-evidence` check: main's copy runs it too, on exact label names.

`.github/workflows/merge-evidence.yml` reports the required `merge-evidence`
check. It runs on `pull_request_target`, so the copy on main also judges a PR
that edits the file, and it must never check out or run the PR head. Until a
later change drops `pull_request`, the head copy reports the check as well.
Only a label named exactly `reviewed` passes it. The one exception is a
dependabot patch or minor bump whose commits are all dependabot's own: authored
by dependabot[bot], committed by GitHub and signed. A major bump needs the
label like any other PR.

The decision steps run here as the workflow's own shell, with `gh` stubbed out
to list a chosen set of PR commits through the real `jq` filter.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from test_pruning_preserves_release_tags import workflow_script


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = "merge-evidence.yml"
DEP = "routine dependency PRs are vouched for by the suite"
LABEL = "require the `reviewed` label"
BOT = "dependabot[bot]"

shell_only = pytest.mark.skipif(
    os.name == "nt" or shutil.which("jq") is None, reason="Linux workflow shell with jq"
)


def source(filename=WORKFLOW):
    return (WORKFLOWS / filename).read_text()


# ---- the workflow file ------------------------------------------------------
def test_runs_from_mains_copy_too_on_every_label_change():
    triggers = source().split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    target = triggers.split("  pull_request_target:\n", 1)[1].split("\n  pull", 1)[0]
    for event in ("opened", "reopened", "synchronize", "labeled", "unlabeled"):
        assert event in target, event


def test_keeps_the_required_check_name():
    jobs = source().split("\njobs:\n", 1)[1]
    assert jobs.startswith("  merge-evidence:\n")
    assert not re.search(r"^    name:", jobs, re.M), "a job name would rename the check"


def test_never_checks_out_or_runs_the_pr_head():
    text = source()
    assert "actions/checkout" not in text
    assert "pull_request.head" not in text
    uses = re.findall(r"uses: (\S+)", text)
    assert uses == [
        "dependabot/fetch-metadata@21025c705c08248db411dc16f3619e6b5f9ea21a"
    ], "a new action here runs with a token for this repository"
    assert uses[0] in source("dependabot-auto.yml"), "pin the same release in both"


def test_token_can_only_read_pull_requests():
    block = source().split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    assert block.strip() == "pull-requests: read"


def test_no_expression_is_spliced_into_a_script():
    for script in re.findall(r"run: \|\n((?:          .*\n|\n)+)", source()):
        assert "${{" not in script, script


# ---- the label step ---------------------------------------------------------
def labels_env(labels):
    """`LABELS` as GitHub renders the step's own `env:` expression for `labels`."""
    step = source().split(f"- name: {LABEL}\n", 1)[1]
    expression = re.search(r"LABELS: \$\{\{ (.*) \}\}", step)[1]
    names = "github.event.pull_request.labels.*.name"
    if expression == f"toJSON({names})":
        return json.dumps(labels)
    if expression == f"join({names}, ',')":
        return ",".join(labels)
    raise AssertionError(f"teach labels_env to render {expression}")


def run_label_step(labels):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c",
         workflow_script(WORKFLOW, LABEL)],
        env=dict(os.environ, LABELS=labels_env(labels)),
        capture_output=True, text=True,
    )


@shell_only
@pytest.mark.parametrize("labels", [["reviewed"], ["bug", "reviewed", "ci"]])
def test_a_label_named_reviewed_passes(labels):
    result = run_label_step(labels)
    assert result.returncode == 0, result.stdout + result.stderr


@shell_only
@pytest.mark.parametrize("labels", [
    [],
    ["x,reviewed,y"],
    ["not reviewed"],
    ["reviewed-later"],
    ["Reviewed"],
])
def test_any_other_label_name_fails(labels):
    result = run_label_step(labels)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "No 'reviewed' label" in result.stdout


# ---- the dependabot step ----------------------------------------------------
FAKE_GH = '''\
import os, subprocess, sys
args = sys.argv[1:]
assert args[0] == "api" and "--paginate" in args, args
jq_filter = args[args.index("--jq") + 1]
sys.exit(subprocess.run(["jq", "-r", jq_filter], input=os.environ["FAKE_COMMITS"],
                        text=True).returncode)
'''


def commit(sha, login, committer="web-flow", verified=True):
    """One entry of the PR commits API, shaped as GitHub returns it."""
    return {
        "sha": sha * 40,
        "author": {"login": login} if login else None,
        "committer": {"login": committer} if committer else None,
        "commit": {"verification": {"verified": verified}},
    }


def run_dep_step(tmp_path, *, author, update_type="", commits=()):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "gh"
    shim.write_text(f"#!{sys.executable}\n{FAKE_GH}")
    shim.chmod(0o755)
    output = tmp_path / "output"
    output.touch()
    env = dict(
        os.environ,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        GITHUB_OUTPUT=str(output),
        REPO="owner/repo", PR="7",
        AUTHOR=author, UPDATE_TYPE=update_type,
        FAKE_COMMITS=json.dumps(list(commits)),
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c",
         workflow_script(WORKFLOW, DEP)],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output.read_text().strip(), result.stdout


@shell_only
@pytest.mark.parametrize("update_type", [
    "version-update:semver-patch", "version-update:semver-minor",
])
def test_a_dependabot_patch_or_minor_bump_needs_no_label(tmp_path, update_type):
    skip, _ = run_dep_step(tmp_path, author=BOT, update_type=update_type,
                           commits=[commit("a", BOT), commit("b", BOT)])
    assert skip == "skip=true"


@shell_only
@pytest.mark.parametrize("update_type", ["version-update:semver-major", ""])
def test_a_dependabot_major_or_unknown_bump_needs_the_label(tmp_path, update_type):
    skip, _ = run_dep_step(tmp_path, author=BOT, update_type=update_type,
                           commits=[commit("a", BOT)])
    assert skip == "skip=false"


@shell_only
@pytest.mark.parametrize("other", ["someone", None])
def test_a_commit_from_anyone_else_on_a_dependabot_branch_needs_the_label(tmp_path, other):
    skip, stdout = run_dep_step(tmp_path, author=BOT,
                                update_type="version-update:semver-patch",
                                commits=[commit("a", BOT), commit("c", other)])
    assert skip == "skip=false"
    assert "cccccccc" in stdout


@shell_only
def test_anyone_else_needs_the_label(tmp_path):
    skip, _ = run_dep_step(tmp_path, author="someone",
                           update_type="version-update:semver-patch",
                           commits=[commit("a", "someone")])
    assert skip == "skip=false"


PATCH = "version-update:semver-patch"


@shell_only
def test_a_dependabot_rebase_stays_eligible(tmp_path):
    # A rebase replaces the commits with new ones of the same authentic shape.
    skip, _ = run_dep_step(tmp_path, author=BOT, update_type=PATCH,
                           commits=[commit("d", BOT)])
    assert skip == "skip=true"


@shell_only
@pytest.mark.parametrize("later", [
    commit("e", BOT, committer="someone", verified=False),
    commit("e", BOT, committer="someone", verified=True),
    commit("e", BOT, committer="web-flow", verified=False),
    commit("e", BOT, committer=None, verified=True),
], ids=["unsigned-human-committer", "signed-human-committer",
        "unsigned-web-flow", "unknown-committer"])
def test_a_commit_only_attributed_to_dependabot_needs_the_label(tmp_path, later):
    # The author is only the commit's email: anyone who can push to the branch
    # can set it. Dependabot's own commits are committed and signed by GitHub.
    skip, stdout = run_dep_step(tmp_path, author=BOT, update_type=PATCH,
                                commits=[commit("a", BOT), later])
    assert skip == "skip=false"
    assert "eeeeeeee" in stdout


@shell_only
def test_a_merge_from_main_by_a_person_needs_the_label(tmp_path):
    # The `Update branch` button: authored by a person, committed and signed by GitHub.
    skip, stdout = run_dep_step(tmp_path, author=BOT, update_type=PATCH,
                                commits=[commit("a", BOT), commit("f", "someone")])
    assert skip == "skip=false"
    assert "ffffffff" in stdout
