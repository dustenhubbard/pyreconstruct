"""The `type` job fails a pull request that adds mypy errors, and nothing else.

The core is not at zero errors, so the mypy step in `.github/workflows/test.yml`
counts errors on the pull request and on its merge base and fails only when the
pull request's count is higher. A run that does not complete, on either side,
must fail too rather than read as zero errors. A push to main has no merge base
and passes unless mypy itself did not complete.

These tests run the step's own shell with `uv` and `git` stubbed out: the `uv`
stand-in prints a chosen number of `: error:` lines and exits with a chosen
code, separately for this ref and for the merge base checkout.
"""

import os
import subprocess
import sys

import pytest

from test_pruning_preserves_release_tags import workflow_script


STEP = "mypy (Qt-free core, non-strict, fails on new errors)"
BASE_SHA = "0123456789abcdef0123456789abcdef01234567"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell")

FAKE_UV = '''\
import os, sys
side = "BASE" if os.path.basename(os.getcwd()) == "mypy-base" else "HEAD"
errors = int(os.environ[f"FAKE_{side}_ERRORS"])
code = int(os.environ[f"FAKE_{side}_EXIT"])
for i in range(errors):
    print(f"PyReconstruct/modules/calc/f{i % 2}.py:{i + 1}: error: fake {i}  [misc]")
if code and not errors:
    print("something went wrong before or inside mypy", file=sys.stderr)
sys.exit(code)
'''

FAKE_GIT = '''\
import os, sys
args = sys.argv[1:]
if args[0] == "fetch":
    sys.exit(int(os.environ["FAKE_FETCH_EXIT"]))
if args[:2] == ["worktree", "add"]:
    os.makedirs(args[-2])
    sys.exit(0)
sys.exit(99)
'''


def run_step(tmp_path, *, base_sha, head, base=(0, 0), fetch_exit=0):
    """Run the step; `head` and `base` are (error lines printed, exit code)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in (("uv", FAKE_UV), ("git", FAKE_GIT)):
        shim = bin_dir / name
        shim.write_text(f"#!{sys.executable}\n{source}")
        shim.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    summary = tmp_path / "summary.md"
    env = dict(
        os.environ,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        BASE_SHA=base_sha,
        GITHUB_EVENT_NAME="pull_request" if base_sha else "push",
        GITHUB_STEP_SUMMARY=str(summary),
        RUNNER_TEMP=str(tmp_path),
        FAKE_HEAD_ERRORS=str(head[0]), FAKE_HEAD_EXIT=str(head[1]),
        FAKE_BASE_ERRORS=str(base[0]), FAKE_BASE_EXIT=str(base[1]),
        FAKE_FETCH_EXIT=str(fetch_exit),
    )
    # The shell Actions uses for a `run:` step with no `shell:` key.
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c",
         workflow_script("test.yml", STEP)],
        cwd=work, env=env, capture_output=True, text=True,
    )
    return result, summary.read_text()


@pytest.mark.parametrize("head,base,headline", [
    ((3, 1), (3, 1), "No change in the error count."),
    ((2, 1), (3, 1), "This pull request removes 1 error."),
    ((0, 0), (1, 1), "This pull request removes 1 error."),
])
def test_a_pull_request_that_adds_no_errors_passes(tmp_path, head, base, headline):
    result, summary = run_step(tmp_path, base_sha=BASE_SHA, head=head, base=base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert headline in summary


def test_a_pull_request_that_adds_errors_fails(tmp_path):
    result, summary = run_step(tmp_path, base_sha=BASE_SHA, head=(5, 1), base=(3, 1))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "This pull request adds 2 errors." in summary
    assert "::error title=mypy::This pull request adds 2 errors." in result.stdout


@pytest.mark.parametrize("head,why", [
    ((0, 2), "mypy crashed"),
    ((0, 1), "the uv wrapper failed before mypy ran"),
])
def test_a_run_that_did_not_complete_on_this_ref_fails(tmp_path, head, why):
    result, summary = run_step(tmp_path, base_sha=BASE_SHA, head=head, base=(3, 1))
    assert result.returncode == 1, why
    assert "mypy did not run to completion on this ref" in summary, why


@pytest.mark.parametrize("base,why", [
    ((0, 2), "mypy crashed"),
    ((0, 1), "the uv wrapper failed before mypy ran"),
])
def test_a_run_that_did_not_complete_on_the_merge_base_fails(tmp_path, base, why):
    result, summary = run_step(tmp_path, base_sha=BASE_SHA, head=(3, 1), base=base)
    assert result.returncode == 1, why
    assert "mypy did not run to completion on the merge base 0123456" in summary, why


def test_a_merge_base_that_cannot_be_fetched_fails(tmp_path):
    result, summary = run_step(tmp_path, base_sha=BASE_SHA, head=(3, 1), fetch_exit=128)
    assert result.returncode == 1
    assert "The merge base 0123456 could not be fetched or checked out" in summary


def test_a_push_to_main_reports_the_count_and_passes(tmp_path):
    result, summary = run_step(tmp_path, base_sha="", head=(300, 1))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "300 errors in 2 files." in summary
    assert "has no merge base" in summary


def test_a_push_to_main_fails_when_mypy_did_not_complete(tmp_path):
    result, summary = run_step(tmp_path, base_sha="", head=(0, 2))
    assert result.returncode == 1
    assert "mypy did not run to completion on this ref" in summary
