"""Run the download-link workflow against disposable Git remotes and a fake API."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest

from test_pruning_preserves_release_tags import workflow_script


pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("jq") is None,
    reason="Linux workflow shell with GNU tools and jq",
)
FILES = ("README.md", "docs/USER_GUIDE.md", "docs/index.md")
WORKFLOW = "download-links-bump.yml"
PR_URL = "https://github.com/owner/repo/pull/1"
FOREIGN_PR_URL = "https://github.com/owner/repo/pull/99"


def download_table(version):
    return (
        f"The current stable release, **v{version}**\n"
        f"[Windows](releases/download/v{version}/PyReconstruct-{version}-Windows-x86_64-Setup.exe)\n"
        f"[Linux](releases/download/v{version}/PyReconstruct-{version}-linux-x86_64.AppImage)\n"
    )


class BumpWorkflow:
    def __init__(self, root):
        self.root = root
        self.work = root / "work"
        self.remote = root / "remote.git"
        self.bindir = root / "bin"
        self.bindir.mkdir()
        self.state = root / "github.json"
        self.state.write_text(json.dumps({
            "pr": "", "foreign_prs": [], "create_error": False, "list_error": False,
            "created": 0,
        }))
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_OUTPUT": str(root / "output"),
            "TEST_GITHUB_STATE": str(self.state),
            "PATH": f"{self.bindir}{os.pathsep}{os.environ['PATH']}",
        }
        self.git("init", "--bare", "--initial-branch=main", str(self.remote), cwd=root)
        self.git("clone", str(self.remote), str(self.work), cwd=root)
        self.git("config", "user.name", "Download test")
        self.git("config", "user.email", "test@example.invalid")
        for name in FILES:
            path = self.work / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(download_table("1.25.0"))
        self.commit("Initial download tables")
        self.git("push", "origin", "main")
        gh = self.bindir / "gh"
        gh.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
            import json
            import os
            from pathlib import Path
            import subprocess
            import sys

            path = Path(os.environ["TEST_GITHUB_STATE"])
            state = json.loads(path.read_text())
            args = sys.argv[1:]
            if args[0] == "api":
                print("false false")
            elif args[:2] == ["pr", "list"]:
                if state["list_error"]:
                    sys.exit("HTTP 403: cannot list pull requests")
                prs = [{"url": url, "isCrossRepository": True}
                       for url in state["foreign_prs"]]
                if state["pr"]:
                    prs.append({"url": state["pr"], "isCrossRepository": False})
                fields = args[args.index("--json") + 1].split(",")
                response = [{field: pr[field] for field in fields} for pr in prs]
                sys.exit(subprocess.run(
                    ["jq", "-r", args[args.index("--jq") + 1]],
                    input=json.dumps(response), text=True,
                ).returncode)
            elif args[:2] == ["pr", "create"]:
                if state["create_error"]:
                    sys.exit("HTTP 403: cannot create pull request")
                if state["pr"]:
                    sys.exit("A pull request already exists")
                state["pr"] = "https://github.com/owner/repo/pull/1"
                state["created"] += 1
                path.write_text(json.dumps(state))
                print(state["pr"])
            else:
                sys.exit("Unexpected gh invocation: " + repr(args))
        '''))
        gh.chmod(0o755)

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args], cwd=cwd or self.work, env=self.env,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def commit(self, message):
        self.git("add", *FILES)
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def github(self, **updates):
        state = json.loads(self.state.read_text())
        state.update(updates)
        self.state.write_text(json.dumps(state))
        return state

    def run(self, version="1.26.0"):
        # Each workflow run starts from a fresh checkout of main.
        self.git("checkout", "main")
        branch = f"docs/downloads-v{version}"
        if self.git("branch", "--list", branch):
            self.git("branch", "-D", branch)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        script = workflow_script(WORKFLOW, "Check the release is public")
        script += '\nif grep -q "^bump=true$" "$GITHUB_OUTPUT"; then\n'
        script += workflow_script(WORKFLOW, "Open the bump PR") + "\nfi\n"
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", script],
            cwd=self.work, env={**self.env, "TAG": f"v{version}", "VERSION": version},
            capture_output=True, text=True,
        )

    def existing_branch(self):
        self.git("checkout", "-b", "docs/downloads-v1.26.0")
        with (self.work / "README.md").open("a") as readme:
            readme.write("\nKeep this manual PR edit.\n")
        head = self.commit("Manual PR edit")
        self.git("push", "origin", "HEAD")
        self.git("checkout", "main")
        self.git("branch", "-D", "docs/downloads-v1.26.0")
        return head


@pytest.fixture
def bump(tmp_path):
    return BumpWorkflow(tmp_path)


def test_an_older_published_stable_does_not_lower_any_download_table(bump):
    result = bump.run("1.24.0")
    assert result.returncode == 0, result.stderr
    assert {name: (bump.work / name).read_text() for name in FILES} == {
        name: download_table("1.25.0") for name in FILES
    }
    assert bump.git("ls-remote", "--heads", "origin", "docs/downloads-v1.24.0") == ""


def test_a_rerun_preserves_commits_on_the_existing_pr_branch(bump):
    manual = bump.existing_branch()
    bump.github(pr=PR_URL)
    result = bump.run()
    assert result.returncode == 0, result.stderr
    bump.git("merge-base", "--is-ancestor", manual, "HEAD")
    assert (bump.work / "README.md").read_text() == (
        download_table("1.26.0") + "\nKeep this manual PR edit.\n"
    )


@pytest.mark.parametrize("foreign_prs", [[], [FOREIGN_PR_URL]])
def test_a_pr_creation_error_fails_the_workflow(bump, foreign_prs):
    bump.github(create_error=True, foreign_prs=foreign_prs)
    result = bump.run()
    assert result.returncode != 0, result.stdout
    assert "HTTP 403: cannot create pull request" in result.stderr
    assert bump.github()["pr"] == ""


def test_a_newer_stable_updates_every_table_and_opens_a_pr(bump):
    result = bump.run()
    assert result.returncode == 0, result.stderr
    assert {name: (bump.work / name).read_text() for name in FILES} == {
        name: download_table("1.26.0") for name in FILES
    }
    assert bump.github()["pr"] == PR_URL
    assert bump.git("ls-remote", "--heads", "origin", "docs/downloads-v1.26.0").split()[0] == (
        bump.git("rev-parse", "HEAD")
    )


@pytest.mark.parametrize("current,target", [
    ("1.9.0", "1.10.0"), ("1.25.9", "1.25.10"), ("1.99.0", "2.0.0"),
])
def test_version_order_is_numeric(bump, current, target):
    for name in FILES:
        (bump.work / name).write_text(download_table(current))
    bump.commit("Set the current release")
    bump.git("push", "origin", "main")
    result = bump.run(target)
    assert result.returncode == 0, result.stderr
    assert {name: (bump.work / name).read_text() for name in FILES} == {
        name: download_table(target) for name in FILES
    }
    assert bump.github()["pr"] == PR_URL


def test_a_newer_version_in_any_table_prevents_a_downgrade(bump):
    (bump.work / "docs/index.md").write_text(download_table("1.27.0"))
    bump.commit("Website already recommends a newer stable")
    bump.git("push", "origin", "main")
    result = bump.run()
    assert result.returncode == 0, result.stderr
    assert (bump.work / "docs/index.md").read_text() == download_table("1.27.0")
    assert bump.git("ls-remote", "--heads", "origin", "docs/downloads-v1.26.0") == ""


def test_a_rerun_recovers_after_pr_creation_failed_without_another_commit(bump):
    bump.github(create_error=True)
    first = bump.run()
    assert first.returncode != 0, first.stdout
    head = bump.git("rev-parse", "HEAD")
    bump.github(create_error=False)
    second = bump.run()
    assert second.returncode == 0, second.stderr
    assert bump.git("rev-parse", "HEAD") == head
    assert bump.github()["pr"] == PR_URL
    assert bump.github()["created"] == 1


def test_a_rerun_with_a_confirmed_pr_succeeds_without_recreating_it(bump):
    first = bump.run()
    assert first.returncode == 0, first.stderr
    bump.github(create_error=True)
    second = bump.run()
    assert second.returncode == 0, second.stderr
    assert PR_URL in second.stdout
    assert bump.github()["created"] == 1


@pytest.mark.parametrize("existing_pr", [False, True])
def test_a_foreign_pr_does_not_replace_the_same_repository_pr(bump, existing_pr):
    bump.github(foreign_prs=[FOREIGN_PR_URL], pr=PR_URL if existing_pr else "")
    result = bump.run()
    assert result.returncode == 0, result.stderr
    assert PR_URL in result.stdout.splitlines()
    assert FOREIGN_PR_URL not in result.stdout.splitlines()
    assert bump.github()["pr"] == PR_URL
    assert bump.github()["created"] == (0 if existing_pr else 1)
    assert bump.git("ls-remote", "--heads", "origin", "docs/downloads-v1.26.0").split()[0] == (
        bump.git("rev-parse", "HEAD")
    )


def test_an_already_current_main_needs_no_bump_branch(bump):
    result = bump.run("1.25.0")
    assert result.returncode == 0, result.stderr
    assert {name: (bump.work / name).read_text() for name in FILES} == {
        name: download_table("1.25.0") for name in FILES
    }
    assert bump.git("ls-remote", "--heads", "origin", "docs/downloads-v1.25.0") == ""


def test_a_failed_pr_lookup_fails_the_run(bump):
    bump.github(list_error=True)
    result = bump.run()
    assert result.returncode != 0, result.stdout
    assert "HTTP 403: cannot list pull requests" in result.stderr
    assert (bump.work / "README.md").read_text() == download_table("1.26.0")


def test_a_concurrent_pr_branch_update_is_rejected_and_preserved(bump):
    bump.existing_branch()
    other = bump.root / "other"
    bump.git("clone", "--branch", "docs/downloads-v1.26.0", str(bump.remote), str(other))
    bump.git("config", "user.name", "Concurrent editor", cwd=other)
    bump.git("config", "user.email", "editor@example.invalid", cwd=other)
    with (other / "README.md").open("a") as readme:
        readme.write("\nKeep the concurrent edit too.\n")
    bump.git("add", "README.md", cwd=other)
    bump.git("commit", "-m", "Concurrent PR edit", cwd=other)
    concurrent = bump.git("rev-parse", "HEAD", cwd=other)

    # Publish the competing commit after the workflow fetched, just before its push.
    git = bump.bindir / "git"
    real_git = shutil.which("git")
    git.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f'''\
        import os
        import subprocess
        import sys

        if sys.argv[1] == "push":
            subprocess.run([{real_git!r}, "-C", {str(other)!r}, "push", "origin", "HEAD"],
                           check=True)
        os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])
    '''))
    git.chmod(0o755)
    result = bump.run()
    assert result.returncode != 0, result.stdout
    assert "rejected" in result.stderr
    assert bump.git("ls-remote", "--heads", "origin", "docs/downloads-v1.26.0").split()[0] == concurrent
    assert (other / "README.md").read_text() == (
        download_table("1.25.0") + "\nKeep this manual PR edit.\n\nKeep the concurrent edit too.\n"
    )
