"""A stable release moves every download link in the README and the User Guide.

The readme-bump job runs three sed expressions over both files after a stable
tag publishes. The User Guide went two releases without a bump because the job
edited only the README, and its version callout wrapped across two lines, which
sed reads one line at a time. This runs the job's own expressions over the real
files and checks that nothing still names the old version.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-installers.yml"
FILES = ("README.md", "docs/USER_GUIDE.md")


def _bump_step() -> str:
    text = WORKFLOW.read_text()
    return text[text.index("\n  readme-bump:\n"):]


def _bumped(path: str, version: str) -> str:
    exprs = re.findall(r'^\s+-e "(.+)" \\$', _bump_step(), re.M)
    assert len(exprs) == 3, exprs
    args = ["sed", "-E"]
    for e in exprs:
        args += ["-e", e.replace("${VERSION}", version)]
    return subprocess.run(args + [str(ROOT / path)], capture_output=True, text=True, check=True).stdout


def test_the_job_edits_and_commits_both_files():
    step = _bump_step()
    for path in FILES:
        assert f"{path}" in step.split("sed -E -i", 1)[1].split("git diff", 1)[0], path
    assert "git add README.md docs/USER_GUIDE.md" in step
    assert "git diff --quiet README.md docs/USER_GUIDE.md" in step


def test_a_new_version_leaves_no_old_download_link_or_callout():
    for path in FILES:
        text = (ROOT / path).read_text()
        old = re.search(r"current stable release, \*\*v(\d+\.\d+\.\d+)\*\*", text)
        assert old, f"{path} has no one-line version callout for the bump to find"
        out = _bumped(path, "9.9.9")
        assert "current stable release, **v9.9.9**" in out, path
        assert f"releases/download/v{old[1]}/" not in out, path
        assert f"PyReconstruct-{old[1]}-" not in out, path
