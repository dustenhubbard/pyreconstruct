"""promote-stable.yml: a Stable release is a nightly plus its release notes.

Run by hand from main once the notes PR is merged, the workflow resolves the
nightly and the version, checks that both notes files have the version's
section and that nothing but the notes changed on main since the nightly, then
tags main's HEAD and dispatches build-installers.yml on the tag. These pin the
workflow's shape and run each step's shell against disposable repositories.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest
import yaml

from test_nightly_workflow import NIGHTLY_RE_SHELL
from test_pruning_preserves_release_tags import workflow_script


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "promote-stable.yml"
PROMOTE = "promote-stable.yml"
STEPS = ["Refuse any ref but main", None, "Resolve the nightly", "Resolve the version",
         "Notes gate", "Drift check", "Tag and build"]

linux_only = pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")


class GitHubLoader(yaml.SafeLoader):
    """YAML as GitHub reads it: only true and false are booleans, so the
    top-level ``on:`` stays the string "on" (YAML 1.1 would make it True)."""


GitHubLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
GitHubLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))


def source():
    return WORKFLOW.read_text()


def workflow(text=None):
    return yaml.load(source() if text is None else text, Loader=GitHubLoader)


def all_uses(node):
    """Every ``uses:`` value anywhere in the parsed workflow."""
    if isinstance(node, dict):
        return [v for k, v in node.items() if k == "uses"] + [
            u for v in node.values() for u in all_uses(v)]
    if isinstance(node, list):
        return [u for v in node for u in all_uses(v)]
    return []


# ---- the workflow file ------------------------------------------------------
def test_runs_only_by_hand_with_a_nightly_and_a_version_input():
    triggers = workflow()["on"]
    assert list(triggers) == ["workflow_dispatch"]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["nightly", "version"]
    for name, spec in inputs.items():
        assert sorted(spec) == ["default", "description", "required"], name
        assert (spec["required"], spec["default"]) == (False, ""), name


def test_a_trigger_after_a_blank_line_is_still_seen():
    """A blank line does not end a YAML mapping, so a schedule added below the
    inputs is a second trigger, one that would run the release unattended."""
    schedule = '\n  schedule:\n    - cron: "17 2 * * *"\n'
    text = source().replace("\n\npermissions:", schedule + "\npermissions:", 1)
    assert list(workflow(text)["on"]) == ["workflow_dispatch", "schedule"]


def test_permissions_are_the_tag_push_and_the_dispatch_only():
    doc = workflow()
    assert doc["permissions"] == {"contents": "write", "actions": "write"}
    assert all("permissions" not in job for job in doc["jobs"].values()), "no job widens them"
    assert doc["concurrency"] == {"group": "stable", "cancel-in-progress": False}


def test_the_first_step_refuses_any_ref_but_main():
    first = workflow()["jobs"]["promote"]["steps"][0]
    assert first["name"] == "Refuse any ref but main"
    assert "if" not in first, "a skipped refusal is no refusal"
    assert '[ "$GITHUB_REF" != "refs/heads/main" ]' in first["run"]
    assert "exit 1" in first["run"]


def test_one_job_runs_the_steps_in_order_and_checks_out_main_with_tags():
    jobs = workflow()["jobs"]
    assert list(jobs) == ["promote"]
    steps = jobs["promote"]["steps"]
    assert [step.get("name") for step in steps] == STEPS
    checkout = steps[1]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {"ref": "main", "fetch-depth": 0, "fetch-tags": True}
    assert not any("if" in step for step in steps), "every step runs on every run"


def test_actions_are_pinned_to_a_sha_with_a_version_comment():
    uses = all_uses(workflow())
    assert uses
    # The comment is not in the parsed document, so it is read from the line.
    lines = dict(re.findall(r"^\s*-?\s*uses: (\S+)(.*)$", source(), re.MULTILINE))
    assert sorted(lines) == sorted(uses)
    for action in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), action
        assert re.match(r"\s*#\s*v\d", lines[action]), (action, "no version comment")


def test_writes_go_only_to_this_repository():
    text = WORKFLOW.read_text()
    assert re.findall(r"git push \S+", text) == ["git push origin"]
    gh_calls = re.findall(r"^\s*gh .*$", text, re.MULTILINE)
    assert gh_calls == [
        '          gh workflow run build-installers.yml --repo "$GITHUB_REPOSITORY" --ref "$STABLE"'
    ]


def test_the_nightly_shape_matches_the_nightly_workflow():
    assert NIGHTLY_RE_SHELL in workflow_script(PROMOTE, "Resolve the nightly")


def test_the_drift_check_allows_only_the_notes():
    step = workflow_script(PROMOTE, "Drift check")
    assert ("git diff --name-only \"$NIGHTLY_COMMIT..HEAD\" -- . "
            "':!CHANGELOG.md' ':!WHATS_NEW.md' ':!changelog.d'") in step


# ---- the steps, run for real -------------------------------------------------
def run_step(step, cwd, tmp_path, **env):
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", workflow_script(PROMOTE, step)],
        cwd=cwd, env=dict(os.environ, GITHUB_OUTPUT=str(out_file), **env),
        capture_output=True, text=True, timeout=30,
    )
    outputs = dict(line.split("=", 1) for line in out_file.read_text().splitlines() if "=" in line)
    return result, outputs


@pytest.mark.parametrize("ref,ok", [
    ("refs/heads/main", True),
    ("refs/heads/release/1.25.1", False),
    ("refs/tags/v1.25.0.dev202610151111", False),
])
@linux_only
def test_any_ref_but_main_is_refused(tmp_path, ref, ok):
    result, _outputs = run_step("Refuse any ref but main", tmp_path, tmp_path, GITHUB_REF=ref)
    assert (result.returncode == 0) is ok, result.stdout


def make_repo(tmp_path):
    """v1.24.0, two nightlies of 1.25.0 (an 8-digit one, then a timed one),
    then the notes PR for 1.25.0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=Promote test",
           "-c", "user.email=test@example.invalid", "-c", "core.hooksPath=/dev/null",
           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(repo)], check=True)
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "fix.fixed.md").write_text("- **A fix.**\n")
    (repo / "app.py").write_text("print('1.24.0')\n")
    for notes in ("CHANGELOG.md", "WHATS_NEW.md"):
        (repo / notes).write_text("## [Unreleased]\n\n## [1.24.0] - 2026-10-08\n")
    subprocess.run(git + ["add", "."], check=True)
    commit(git, "release 1.24.0")
    subprocess.run(git + ["tag", "-a", "v1.24.0", "-m", "Stable v1.24.0"], check=True)
    edit(repo, git, "app.py", "print('work')\n")
    subprocess.run(git + ["tag", "-a", "v1.25.0.dev20261014", "-m", "nightly"], check=True)
    edit(repo, git, "app.py", "print('more work')\n")
    subprocess.run(git + ["tag", "-a", "v1.25.0.dev202610151111", "-m", "nightly"], check=True)
    add_notes(repo, git, "1.25.0")
    return repo, git


def commit(git, message):
    subprocess.run(git + ["commit", "--quiet", "--allow-empty", "-m", message], check=True)


def edit(repo, git, path, text):
    (repo / path).write_text(text)
    subprocess.run(git + ["add", path], check=True)
    commit(git, f"edit {path}")


def add_notes(repo, git, version, files=("CHANGELOG.md", "WHATS_NEW.md")):
    for notes in files:
        text = (repo / notes).read_text()
        (repo / notes).write_text(
            text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{version}] - 2026-10-16\n"))
    subprocess.run(git + ["rm", "--quiet", "-r", "--ignore-unmatch", "changelog.d"], check=True)
    subprocess.run(git + ["add", *files], check=True)
    commit(git, f"docs: release notes for {version}")


def sha(git, rev):
    return subprocess.check_output(git + ["rev-parse", f"{rev}^{{commit}}"], text=True).strip()


def resolve(tmp_path, repo, nightly="", version=""):
    """The two resolve steps, chained as the workflow chains them."""
    result, nightly_out = run_step("Resolve the nightly", repo, tmp_path, NIGHTLY_INPUT=nightly)
    if result.returncode:
        return result, {}
    result, version_out = run_step("Resolve the version", repo, tmp_path,
                                   NIGHTLY=nightly_out["tag"], VERSION_INPUT=version)
    return result, {**{f"nightly_{k}": v for k, v in nightly_out.items()}, **version_out}


@linux_only
def test_blank_inputs_promote_the_newest_nightly_as_its_base_version(tmp_path):
    repo, git = make_repo(tmp_path)
    result, out = resolve(tmp_path, repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert out == {"nightly_tag": "v1.25.0.dev202610151111",
                   "nightly_commit": sha(git, "v1.25.0.dev202610151111"),
                   "tag": "v1.25.0", "version": "1.25.0"}


@linux_only
def test_a_named_nightly_and_version_are_taken_as_given(tmp_path):
    repo, git = make_repo(tmp_path)
    result, out = resolve(tmp_path, repo, nightly="v1.25.0.dev20261014", version="v2.0.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert out["nightly_commit"] == sha(git, "v1.25.0.dev20261014")
    assert (out["tag"], out["version"]) == ("v2.0.0", "2.0.0")


@linux_only
@pytest.mark.parametrize("nightly,message", [
    ("v1.25.0", "is not a nightly tag"),
    ("v1.25.0.dev2026101511", "is not a nightly tag"),
    ("v1.25.0.dev20261231", "no tag v1.25.0.dev20261231"),
    ("v1.25.0.dev20261013", "is not on main"),
])
def test_a_nightly_that_is_not_a_nightly_on_main_fails(tmp_path, nightly, message):
    repo, git = make_repo(tmp_path)
    subprocess.run(git + ["checkout", "--quiet", "-b", "side", "v1.24.0"], check=True)
    commit(git, "off main")
    subprocess.run(git + ["tag", "v1.25.0.dev20261013"], check=True)
    subprocess.run(git + ["checkout", "--quiet", "main"], check=True)
    result, out = resolve(tmp_path, repo, nightly=nightly)
    assert result.returncode != 0 and out == {}
    assert message in result.stdout


@linux_only
@pytest.mark.parametrize("version,message", [
    ("1.25", "version must be X.Y.Z"),
    ("1.24.0", "v1.24.0 already exists"),
    ("1.23.9", "not above the newest stable, v1.24.0"),
])
def test_a_version_that_is_not_new_fails(tmp_path, version, message):
    repo, _git = make_repo(tmp_path)
    result, _out = resolve(tmp_path, repo, version=version)
    assert result.returncode != 0
    assert message in result.stdout


@linux_only
def test_the_notes_gate_needs_the_section_in_both_files(tmp_path):
    repo, git = make_repo(tmp_path)
    result, _out = run_step("Notes gate", repo, tmp_path, VERSION="1.25.0")
    assert result.returncode == 0, result.stdout
    result, _out = run_step("Notes gate", repo, tmp_path, VERSION="1.25.1")
    assert result.returncode != 0
    assert "CHANGELOG.md has no ## [1.25.1] section" in result.stdout
    assert "WHATS_NEW.md has no ## [1.25.1] section" in result.stdout

    add_notes(repo, git, "1.25.1", files=("CHANGELOG.md",))
    result, _out = run_step("Notes gate", repo, tmp_path, VERSION="1.25.1")
    assert result.returncode != 0
    assert "CHANGELOG.md" not in result.stdout
    assert "WHATS_NEW.md has no ## [1.25.1] section" in result.stdout


@linux_only
def test_the_drift_check_passes_the_notes_and_fails_anything_else(tmp_path):
    repo, git = make_repo(tmp_path)
    env = dict(NIGHTLY="v1.25.0.dev202610151111",
               NIGHTLY_COMMIT=sha(git, "v1.25.0.dev202610151111"))
    result, _out = run_step("Drift check", repo, tmp_path, **env)
    assert result.returncode == 0, result.stdout + result.stderr

    edit(repo, git, "app.py", "print('merged after the nightly')\n")
    result, _out = run_step("Drift check", repo, tmp_path, **env)
    assert result.returncode != 0
    assert "app.py" in result.stdout
    assert "CHANGELOG.md" not in result.stdout


@linux_only
def test_tag_and_build_tags_head_pushes_it_and_dispatches_the_build(tmp_path):
    repo, git = make_repo(tmp_path)
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    subprocess.run(git + ["remote", "add", "origin", str(remote)], check=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "gh-calls"
    gh = bindir / "gh"
    gh.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f'''\
        import sys
        with open({str(calls)!r}, "a") as f:
            f.write(" ".join(sys.argv[1:]) + "\\n")
    '''))
    gh.chmod(0o755)
    nightly_commit = sha(git, "v1.25.0.dev202610151111")
    head = sha(git, "HEAD")

    result, _out = run_step(
        "Tag and build", repo, tmp_path,
        PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", GIT_CONFIG_GLOBAL="/dev/null",
        NIGHTLY="v1.25.0.dev202610151111", NIGHTLY_COMMIT=nightly_commit, STABLE="v1.25.0",
        GITHUB_REPOSITORY="fixture/repository", GH_TOKEN="unused-by-fake-gh",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    pushed = subprocess.check_output(
        ["git", "-C", str(remote), "cat-file", "-p", "refs/tags/v1.25.0"], text=True)
    assert f"object {head}" in pushed and "type commit" in pushed   # annotated, on HEAD
    assert (f"Stable v1.25.0: nightly v1.25.0.dev202610151111 ({nightly_commit}) "
            f"plus notes {head}") in pushed
    assert calls.read_text() == (
        "workflow run build-installers.yml --repo fixture/repository --ref v1.25.0\n")
    assert (f"::notice::v1.25.0 promotes nightly v1.25.0.dev202610151111 ({nightly_commit}) "
            f"plus notes {head}") in result.stdout
