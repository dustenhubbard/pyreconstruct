"""A stable release moves every download link in the README, User Guide, and website.

The readme-bump job runs three sed expressions over those files after a stable
tag publishes. The User Guide and the website's front page went two releases
without a bump because the job edited only the README, and the guide's version
callout wrapped across two lines, which sed reads one line at a time. This runs
the job's own expressions over the real files and checks that nothing still
names the old version.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-installers.yml"
FILES = ("README.md", "docs/USER_GUIDE.md", "docs/index.md")


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
