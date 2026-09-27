"""Run the release-pruning shell steps against disposable releases and Git tags."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")


def workflow_script(filename, step):
    source = (ROOT / ".github" / "workflows" / filename).read_text()
    body = source.split(f"- name: {step}\n", 1)[1].split("        run: |\n", 1)[1]
    lines = []
    for line in body.splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


NIGHTLIES = [f"v1.23.0.dev202609{d:02d}" for d in range(1, 10)]   # nine nights


@pytest.mark.parametrize("workflow,step,stable,deleted", [
    # Ten nightlies ahead of v1.22.2 (nine of 1.23.0, one of 1.24.0): the three
    # oldest go, and so does the retired-shape leftover of a shipped version.
    ("prune-nightlies.yml", "Delete overtaken and superseded nightlies", "v1.22.2",
     set(NIGHTLIES[:3]) | {"v1.22.1-beta-1"}),
    # v1.23.0 ships: every pre-release of exactly 1.23.0 goes, in either shape.
    ("build-installers.yml", "Prune superseded pre-releases", "v1.23.0",
     set(NIGHTLIES) | {"v1.23.0-beta-1"}),
])
def test_pruning_removes_downloads_but_keeps_historical_tags(
    tmp_path, workflow, step, stable, deleted,
):
    releases = {"v1.22.2": False, "v1.24.0.dev20261001": True,
                "v1.22.1-beta-1": True, "v1.23.0-beta-1": True}
    releases.update({t: True for t in NIGHTLIES})
    releases[stable] = False
    state = tmp_path / "releases.json"
    state.write_text(json.dumps(releases))
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    subprocess.run([
        "git", "-C", str(repository), "-c", "user.name=Pruning test",
        "-c", "user.email=test@example.invalid", "-c", "core.hooksPath=/dev/null",
        "-c", "commit.gpgsign=false", "commit", "--quiet", "--allow-empty",
        "-m", "Release fixture",
    ], check=True)
    for tag in releases:
        subprocess.run(["git", "-C", str(repository), "tag", tag], check=True)

    # Execute the actual workflow commands. Only the GitHub CLI is replaced:
    # --cleanup-tag has its real destructive effect on the disposable repo.
    gh = tmp_path / "gh"
    gh.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys

        state = Path(os.environ["TEST_RELEASES"])
        releases = json.loads(state.read_text())
        args = sys.argv[1:]
        if args[0] == "api":
            for tag, prerelease in releases.items():
                print(tag, str(prerelease).lower())
        elif args[:2] == ["release", "list"]:
            print("\\n".join(releases))
        elif args[:2] == ["release", "delete"]:
            tag = args[2]
            del releases[tag]
            state.write_text(json.dumps(releases))
            if "--cleanup-tag" in args:
                subprocess.run(["git", "-C", os.environ["TEST_TAG_REPO"],
                                "tag", "-d", tag], check=True)
        else:
            raise SystemExit(f"Unexpected gh arguments: {args}")
    '''))
    gh.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
               TEST_RELEASES=str(state), TEST_TAG_REPO=str(repository),
               GITHUB_REPOSITORY="fixture/repository", GITHUB_REF_NAME=stable,
               GH_TOKEN="unused-by-fake-gh")
    subprocess.run(["bash", "-eo", "pipefail", "-c", workflow_script(workflow, step)],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True,
                   timeout=30)

    assert set(json.loads(state.read_text())) == set(releases) - deleted
    tags = subprocess.check_output(
        ["git", "-C", str(repository), "tag", "--list"], text=True,
    ).splitlines()
    assert set(tags) == set(releases), "Pruning erased release-history evidence"
