"""The version resolves on any commit, including one past a nightly tag.

A nightly tag ends in a date, v1.24.0.dev20260927. setuptools_scm's default
scheme guesses the next version by bumping the tag's last number, and it
refuses to bump a .dev number it did not choose, so every checkout one commit
past a nightly failed to build. `uv sync` failed on every dev machine the day
after the first nightly (2026-09-27). pyproject.toml now pins
`version_scheme = "only-version"`: on a tag the version is the tag, between
tags it is the newest tag plus a commit hash.

The first test pins the setting. The rest build tiny git repositories with
nightly-shaped tags and ask setuptools_scm for the version, so they prove the
scheme rather than the spelling. setuptools_scm is a build dependency, so the
test extra lists it too; before that these tests skipped in CI.

The last group runs the "Compute version" step of build-installers.yml against
such a repository. Tag builds keep taking their version from setuptools_scm,
and that step fails the build unless the version equals the tag, so a nightly
or stable installer carries exactly the tag's version. Those repositories
carry annotated tags, as nightly.yml and the stable recipe in
docs/RELEASE_CHANNELS.md make them. git describe prefers an annotated tag on
the same commit, so a lightweight stable tag on a nightly's commit builds as
the nightly; the last tests pin that and the recipe's `git tag -a`.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import tomllib

import pytest
import setuptools_scm
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "build-installers.yml"
RELEASE_DOC = ROOT / "docs" / "RELEASE_CHANNELS.md"
STEP = "Compute version"
BUILD_JOBS = ("build", "build-linux")

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_NOSYSTEM="1",
)
# An override in the developer's shell would mask the scheme under test.
for _k in [k for k in GIT_ENV if k.startswith("SETUPTOOLS_SCM_PRETEND_VERSION")]:
    del GIT_ENV[_k]


def _scm_config():
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["tool"]["setuptools_scm"]


def test_pyproject_pins_a_scheme_that_never_guesses():
    assert _scm_config().get("version_scheme") == "only-version"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, env=GIT_ENV,
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


def _annotated_tag(cwd, tag):
    _git(cwd, "tag", "-a", tag, "-m", tag)


def _full_clone(tmp_path, past_nightly=True):
    """A stable tag, a later nightly tag, and optionally a commit past it.

    Both tags are annotated, as the real ones are.

    The repository carries the real [tool.setuptools_scm] table, so the
    version comes from the same settings a clone of main builds with.
    """
    scm_table = re.search(r"^\[tool\.setuptools_scm\]\n.*?(?=^\[|\Z)",
                          PYPROJECT.read_text(), re.MULTILINE | re.DOTALL).group(0)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pyreconstruct"\ndynamic = ["version"]\n\n' + scm_table)
    (tmp_path / ".gitignore").write_text("PyReconstruct/_version.py\n")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one")
    _annotated_tag(tmp_path, "v1.23.0")
    (tmp_path / "a.txt").write_text("2")
    _git(tmp_path, "commit", "-q", "-am", "two")
    _annotated_tag(tmp_path, "v1.24.0.dev20260929")
    if past_nightly:
        (tmp_path / "a.txt").write_text("3")
        _git(tmp_path, "commit", "-q", "-am", "three")
    return tmp_path


@pytest.mark.parametrize("tag, public", [
    ("v1.24.0.dev20260927", "1.24.0.dev20260927"),   # one past a nightly
    ("v1.23.0", "1.23.0"),                            # one past a stable
])
def test_one_commit_past_a_tag_resolves(tmp_path, tag, public):
    repo = _repo(tmp_path, tag)
    cfg = _scm_config()
    v = setuptools_scm.get_version(
        root=str(repo),
        version_scheme=cfg["version_scheme"],
        local_scheme="node-and-date",
    )
    parsed = Version(v)               # a valid PEP 440 version, not an error
    assert parsed.public == public    # the newest tag, no guessed next number
    assert parsed.local and parsed.local.startswith("g")   # plus the commit


def test_on_the_tag_itself_the_version_is_the_tag(tmp_path):
    repo = _repo(tmp_path, "v9.9.9")
    _git(repo, "tag", "v1.24.0.dev20260928")
    cfg = _scm_config()
    assert setuptools_scm.get_version(
        root=str(repo), version_scheme=cfg["version_scheme"]) == "1.24.0.dev20260928"


def test_the_default_scheme_is_the_one_that_fails(tmp_path):
    """The premise, pinned: guess-next-dev raises one commit past a nightly."""
    repo = _repo(tmp_path, "v1.24.0.dev20260927")
    with pytest.raises(Exception, match="devX"):
        setuptools_scm.get_version(root=str(repo), version_scheme="guess-next-dev")


def _cli_version(repo):
    """What `python -m setuptools_scm` prints, the command the workflow runs."""
    return subprocess.run(
        [sys.executable, "-m", "setuptools_scm"], cwd=repo, env=GIT_ENV,
        check=True, capture_output=True, text=True, timeout=60,
    ).stdout.strip()


def test_a_full_clone_past_a_nightly_resolves_with_the_real_settings(tmp_path):
    v = Version(_cli_version(_full_clone(tmp_path)))
    assert v.public == "1.24.0.dev20260929"
    assert v.local and v.local.startswith("g")


def _compute_version_script(job):
    source = WORKFLOW.read_text()
    body = source.split(f"\n  {job}:\n", 1)[1]
    body = re.split(r"\n  [a-z][a-z-]*:\n", body, maxsplit=1)[0]
    step = body.split(f"- name: {STEP}\n", 1)[1]
    step = re.split(r"\n      - ", step, maxsplit=1)[0]
    lines = []
    for line in step.split("        run: |\n", 1)[1].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


@pytest.mark.parametrize("job", BUILD_JOBS)
def test_the_build_refuses_a_fallback_and_a_version_that_is_not_the_tag(job):
    script = _compute_version_script(job)
    assert 'V="$(python -m setuptools_scm)"' in script
    assert "0.0.0*|*unknown*)" in script
    assert r"(\.dev[0-9]{8}([0-9]{4})?)?$" in script   # nightly tags are checked too
    assert '"$V" != "${GITHUB_REF_NAME#v}"' in script
    assert 'echo "PYR_VERSION=$V" >> "$GITHUB_ENV"' in script
    assert 'echo "PYR_PUBLIC=${V%%+*}" >> "$GITHUB_ENV"' in script


def _run_step(tmp_path, repo, job, ref):
    """Run the step's shell in `repo`, with `python` being this interpreter."""
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (shim / "python").chmod(0o755)
    github_env = tmp_path / "github_env"
    github_env.write_text("")
    env = dict(GIT_ENV, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}",
               GITHUB_REF_NAME=ref, GITHUB_ENV=str(github_env))
    result = subprocess.run(["bash", "-eo", "pipefail", "-c", _compute_version_script(job)],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    exported = dict(line.split("=", 1) for line in github_env.read_text().splitlines())
    return result, exported


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
@pytest.mark.parametrize("ref,past_nightly,version", [
    ("v1.24.0.dev20260929", False, "1.24.0.dev20260929"),   # a nightly tag build
    ("main", True, None),                                    # a manual run on main
])
def test_a_tag_build_carries_exactly_the_tag_version(
    tmp_path, job, ref, past_nightly, version,
):
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo", past_nightly=past_nightly)
    result, exported = _run_step(tmp_path, repo, job, ref)
    assert result.returncode == 0, result.stdout + result.stderr
    if version:
        assert exported == {"PYR_VERSION": version, "PYR_PUBLIC": version}
    else:
        assert Version(exported["PYR_VERSION"]).public == "1.24.0.dev20260929"
        assert exported["PYR_PUBLIC"] == "1.24.0.dev20260929"


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
def test_a_stable_tag_build_carries_exactly_the_stable_version(tmp_path, job):
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo", past_nightly=False)
    _annotated_tag(repo, "v1.24.0")              # the stable cut on the same commit
    result, exported = _run_step(tmp_path, repo, job, "v1.24.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert exported == {"PYR_VERSION": "1.24.0", "PYR_PUBLIC": "1.24.0"}


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
def test_a_tag_build_past_its_tag_is_refused(tmp_path, job):
    """HEAD is not the tag the run names, so its version cannot be the tag."""
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo", past_nightly=True)
    result, exported = _run_step(tmp_path, repo, job, "v1.24.0.dev20260929")
    assert result.returncode != 0
    assert "for the tag v1.24.0.dev20260929" in result.stdout
    assert exported == {}


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
def test_a_clone_without_tags_is_refused_not_built_as_the_fallback(tmp_path, job):
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo")
    for tag in ("v1.23.0", "v1.24.0.dev20260929"):
        _git(repo, "tag", "-d", tag)
    result, exported = _run_step(tmp_path, repo, job, "v1.24.0.dev20260929")
    assert result.returncode != 0
    assert "fallback version (0.0.0+unknown" in result.stdout
    assert exported == {}


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
def test_a_timed_nightly_tag_build_carries_exactly_the_tag_version(tmp_path, job):
    """A 12-digit vX.Y.Z.devYYYYMMDDHHMM tag, cut since 2026-10-08, builds as
    exactly that version."""
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo", past_nightly=True)
    _git(repo, "tag", "v1.24.0.dev202610081315")
    result, exported = _run_step(tmp_path, repo, job, "v1.24.0.dev202610081315")
    assert result.returncode == 0, result.stdout + result.stderr
    assert exported == {"PYR_VERSION": "1.24.0.dev202610081315",
                        "PYR_PUBLIC": "1.24.0.dev202610081315"}


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
def test_a_timed_nightly_build_past_its_tag_is_refused(tmp_path, job):
    """The timed tag is real and HEAD is one commit past it, so the version is
    the tag plus a commit hash, and its public part alone matches the tag."""
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo", past_nightly=True)
    _git(repo, "tag", "v1.24.0.dev202610081315")
    (repo / "a.txt").write_text("4")
    _git(repo, "commit", "-q", "-am", "four")
    assert Version(_cli_version(repo)).public == "1.24.0.dev202610081315"
    result, exported = _run_step(tmp_path, repo, job, "v1.24.0.dev202610081315")
    assert result.returncode != 0
    assert "for the tag v1.24.0.dev202610081315" in result.stdout
    assert exported == {}


@pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")
@pytest.mark.parametrize("job", BUILD_JOBS)
def test_a_lightweight_stable_tag_on_a_nightly_commit_is_refused(tmp_path, job):
    """git describe picks the annotated nightly over the lightweight stable tag,
    so the version is the nightly's and the step refuses the stable build."""
    (tmp_path / "repo").mkdir()
    repo = _full_clone(tmp_path / "repo", past_nightly=False)
    _git(repo, "tag", "v1.24.0")
    assert _cli_version(repo) == "1.24.0.dev20260929"
    result, exported = _run_step(tmp_path, repo, job, "v1.24.0")
    assert result.returncode != 0
    assert "produced 1.24.0.dev20260929 for the tag v1.24.0" in result.stdout
    assert exported == {}


def test_the_stable_recipe_makes_an_annotated_tag():
    recipe = RELEASE_DOC.read_text().split("## Stable releases", 1)[1]
    tags = re.findall(r"^git tag .*$", recipe, re.MULTILINE)
    assert tags and all(re.match(r"git tag -a v\d+\.\d+\.\d+ -m ", t) for t in tags), tags
