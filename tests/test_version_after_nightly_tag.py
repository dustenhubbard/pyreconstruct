"""The version resolves on any commit, including one past a nightly tag.

A nightly tag ends in a date, v1.24.0.dev20260927. setuptools_scm's default
scheme guesses the next version by bumping the tag's last number, and it
refuses to bump a .dev number it did not choose, so every checkout one commit
past a nightly failed to build. `uv sync` failed on every dev machine the day
after the first nightly (2026-09-27). pyproject.toml now pins
`version_scheme = "only-version"`: on a tag the version is the tag, between
tags it is the newest tag plus a commit hash.

The first test pins the setting and always runs. The second builds a tiny git
repository with a nightly-shaped tag and a commit after it and asks
setuptools_scm for the version, so it proves the scheme rather than the
spelling. It needs setuptools_scm, which is a build dependency and not in the
test environment, so it skips where that is missing.
"""
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _scm_config():
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["tool"]["setuptools_scm"]


def test_pyproject_pins_a_scheme_that_never_guesses():
    assert _scm_config().get("version_scheme") == "only-version"


def _git(cwd, *args):
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null",
    )
    subprocess.run(["git", *args], cwd=cwd, check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _repo(tmp_path, tag):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "one")
    _git(tmp_path, "tag", tag)
    (tmp_path / "a.txt").write_text("2")
    _git(tmp_path, "commit", "-q", "-am", "two")
    return tmp_path


@pytest.mark.parametrize("tag, public", [
    ("v1.24.0.dev20260927", "1.24.0.dev20260927"),   # one past a nightly
    ("v1.23.0", "1.23.0"),                            # one past a stable
])
def test_one_commit_past_a_tag_resolves(tmp_path, tag, public):
    scm = pytest.importorskip("setuptools_scm")
    from packaging.version import Version

    repo = _repo(tmp_path, tag)
    cfg = _scm_config()
    v = scm.get_version(
        root=str(repo),
        version_scheme=cfg["version_scheme"],
        local_scheme="node-and-date",
    )
    parsed = Version(v)               # a valid PEP 440 version, not an error
    assert parsed.public == public    # the newest tag, no guessed next number
    assert parsed.local and parsed.local.startswith("g")   # plus the commit


def test_on_the_tag_itself_the_version_is_the_tag(tmp_path):
    scm = pytest.importorskip("setuptools_scm")
    repo = _repo(tmp_path, "v9.9.9")
    _git(repo, "tag", "v1.24.0.dev20260928")
    cfg = _scm_config()
    assert scm.get_version(root=str(repo), version_scheme=cfg["version_scheme"]) \
        == "1.24.0.dev20260928"


def test_the_default_scheme_is_the_one_that_fails(tmp_path):
    """The premise, pinned: guess-next-dev raises one commit past a nightly."""
    scm = pytest.importorskip("setuptools_scm")
    repo = _repo(tmp_path, "v1.24.0.dev20260927")
    with pytest.raises(Exception, match="devX"):
        scm.get_version(root=str(repo), version_scheme="guess-next-dev")
