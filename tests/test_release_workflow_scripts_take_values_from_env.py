"""The release and nightly workflows hand values to their shell through env.

A `${{ }}` expression inside a `run:` script is pasted into the script text
before bash reads it, so the value becomes code. The same goes for a shell
variable pasted into a program another tool parses, like `python3 -c "...$X..."`
or a sed script. These workflows publish releases and hold the signing key, so
their scripts read every such value from the environment. The Linux installer
step, which turns the tag name into an asset name and an install pin, runs here
against a normal tag and a tag that tries to run code.
"""

import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest

from test_pruning_preserves_release_tags import workflow_script


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_WORKFLOWS = ("build-installers.yml", "nightly.yml", "prune-nightlies.yml",
                     "publish-pypi.yml")
LINUX_INSTALLER = "Package the Linux .sh installer"

linux_only = pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell")


def run_scripts(filename):
    """Every `run:` script in a workflow, block or one-line, as text."""
    lines = (WORKFLOWS / filename).read_text().splitlines()
    scripts = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2)
        if not rest.startswith(("|", ">")):
            scripts.append(rest)
            continue
        body = []
        for later in lines[i + 1:]:
            if later.strip() and len(later) - len(later.lstrip()) <= indent:
                break
            body.append(later)
        scripts.append("\n".join(body))
    return scripts


@pytest.mark.parametrize("filename", RELEASE_WORKFLOWS)
def test_no_expression_is_pasted_into_a_run_script(filename):
    scripts = run_scripts(filename)
    assert scripts, f"{filename} has no run: script; is this test stale?"
    pasted = [s for s in scripts if "${{" in s]
    assert not pasted, pasted


@pytest.mark.parametrize("filename", RELEASE_WORKFLOWS)
def test_no_shell_value_is_pasted_into_a_python_program(filename):
    programs = [p for s in run_scripts(filename)
                for p in re.findall(r'python3? -c "([^"]*)"', s)]
    assert not [p for p in programs if "$" in p], programs


def run_linux_installer_step(tmp_path, tag):
    """The step's shell, in a stand-in checkout, with pip stubbed out."""
    work = tmp_path / "work"
    (work / "packaging" / "linux").mkdir(parents=True)
    (work / "dist").mkdir()
    for name in ("install.sh", "uninstall.sh", "pyreconstruct.desktop.in", "README.md"):
        (work / "packaging" / "linux" / name).write_bytes(
            (ROOT / "packaging" / "linux" / name).read_bytes())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        '[ "$1" = -m ] && [ "$2" = pip ] && exit 0\n'
        f'exec "{sys.executable}" "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, GITHUB_REF_NAME=tag, RUNNER_TEMP=str(tmp_path),
               PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    result = subprocess.run(["bash", "-e", "-c", workflow_script("build-installers.yml",
                                                                 LINUX_INSTALLER)],
                            cwd=work, env=env, capture_output=True, text=True)
    return work, result


@linux_only
def test_linux_installer_names_the_asset_by_version_and_pins_the_tag(tmp_path):
    work, result = run_linux_installer_step(tmp_path, "v1.21.0-rc.1")
    assert result.returncode == 0, result.stderr
    assets = sorted(p.name for p in (work / "dist").iterdir())
    assert assets == ["PyReconstruct-1.21.0rc1-Linux-installer.tar.gz"], assets
    pinned = (work / "PyReconstruct-linux-installer" / "install.sh").read_text()
    assert 'DEFAULT_SOURCE="git+https://github.com/dustenhubbard/PyReconstruct.git@v1.21.0-rc.1"' \
        in pinned


@linux_only
def test_linux_installer_never_runs_a_tag_name_as_code(tmp_path):
    marker = tmp_path / "ran"
    tag = f"v1'+__import__('os').system('touch {marker}')+'"
    work, result = run_linux_installer_step(tmp_path, tag)
    assert not marker.exists(), "the tag name ran as Python"
    assert result.returncode != 0, "a tag that is not a version must fail the step"
    assert not list((work / "dist").iterdir())
