"""The nightly release train: nightly.yml cuts the tag, build-installers.yml ships it.

Once a day, nightly.yml tags main's HEAD as vX.Y.Z.devYYYYMMDD when main has
moved since the last release on either channel, then dispatches
build-installers.yml on that tag (a tag pushed with GITHUB_TOKEN never fires a
`push: tags:` trigger). The release job publishes a nightly as a pre-release
that is never "latest", with GitHub's generated notes against the previous
nightly. These pin the pieces that would break silently, and run the shell of
the decision steps against disposable repositories.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

from test_pruning_preserves_release_tags import workflow_script


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
NIGHTLY = "nightly.yml"
BUILD = "build-installers.yml"
PICK = "Pick tonight's tag"
TAG_AND_BUILD = "Tag main and dispatch the build"
CLASSIFY = "Classify release"
NIGHTLY_NOTES = "Build nightly release notes"

# The one tag shape, as the shell spells it. Every workflow step that names a
# nightly must use exactly this string.
NIGHTLY_RE_SHELL = r"^v[0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]{8}$"
NIGHTLY_RE = re.compile(NIGHTLY_RE_SHELL)

linux_only = pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")


def source(filename):
    return (WORKFLOWS / filename).read_text()


def today():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


# ---- the workflow file ------------------------------------------------------
def test_runs_once_a_day_and_by_hand_with_a_version_override():
    text = source(NIGHTLY)
    assert '- cron: "0 6 * * *"' in text
    assert text.count("- cron:") == 1, "one nightly a day means one schedule"
    dispatch = text.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "version:" in dispatch
    assert "required: false" in dispatch


def test_actions_are_pinned_to_a_sha_with_a_version_comment():
    for filename in (NIGHTLY, "prune-nightlies.yml"):
        uses = re.findall(r"uses: (\S+)(.*)", source(filename))
        assert uses, f"{filename} uses no action; is this test stale?"
        for action, rest in uses:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), (filename, action)
            assert re.search(r"#\s*v\d", rest), (filename, action, "no version comment")


def test_permissions_cover_the_tag_push_and_the_dispatch():
    text = source(NIGHTLY)
    perms = text.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    assert "contents: write" in perms
    assert "actions: write" in perms


def test_the_tag_push_is_followed_by_a_dispatch_of_the_build():
    """GitHub does not run workflows for events the GITHUB_TOKEN caused, other
    than workflow_dispatch and repository_dispatch, so the tag push alone would
    build nothing."""
    step = workflow_script(NIGHTLY, TAG_AND_BUILD)
    assert 'git push origin "refs/tags/$TAG"' in step
    assert 'gh workflow run build-installers.yml --repo "$GITHUB_REPOSITORY" --ref "$TAG"' in step
    assert "git tag -a" in step, "an annotated tag, like the stables"
    # and the build workflow can be dispatched, on a tag ref, into the release job
    build = source(BUILD)
    assert "workflow_dispatch:" in build
    assert 'tags: ["v*.*.*"]' in build   # still fires for a hand-pushed tag
    assert "startsWith(github.ref, 'refs/tags/v')" in build


def test_the_tag_step_is_gated_on_the_pick():
    text = source(NIGHTLY)
    step = text.split(f"- name: {TAG_AND_BUILD}\n", 1)[1]
    assert step.lstrip().startswith("if: steps.pick.outputs.tag != ''")
    pick = workflow_script(NIGHTLY, PICK)
    assert pick.count('echo "tag=" >> "$GITHUB_OUTPUT"') == 2, "two skips, both neutral"
    assert "already exists" in pick
    assert 'git rev-list --count "$prev..HEAD"' in pick
    assert "exit 1" in pick   # the only failures: no stable tag, a bad override


def test_every_step_spells_the_nightly_shape_the_same_way():
    assert NIGHTLY_RE_SHELL in workflow_script(NIGHTLY, PICK)
    assert NIGHTLY_RE_SHELL in workflow_script(BUILD, CLASSIFY)
    assert NIGHTLY_RE_SHELL in workflow_script(BUILD, NIGHTLY_NOTES)
    # the version guard accepts a stable or a nightly, nothing else
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+(\.dev[0-9]{8})?$" in workflow_script(BUILD, "Compute version")
    sys.path.insert(0, str(ROOT / "scripts"))
    from prune_nightlies import NIGHTLY_RE as policy_re
    for tag, ok in [("v1.24.0.dev20260928", True), ("v2.0.0.dev20270101", True),
                    ("v1.24.0.dev3", False), ("v1.24.0", False),
                    ("v1.23.0-beta-6", False), ("v1.24.0.dev20260928+dirty", False)]:
        assert bool(NIGHTLY_RE.match(tag)) is ok, tag
        assert bool(policy_re.match(tag)) is ok, tag


def test_the_release_job_keeps_a_nightly_off_latest():
    text = source(BUILD)
    release = text.split("\n  release:\n", 1)[1]
    publish = release.split("- uses: softprops/action-gh-release", 1)[1].split("\n      - name:", 1)[0]
    assert "prerelease: ${{ steps.rel.outputs.prerelease }}" in publish
    assert "make_latest: ${{ steps.rel.outputs.make_latest }}" in publish
    assert "body_path: release_body.md" in publish
    classify = workflow_script(BUILD, CLASSIFY)
    assert 'echo "nightly=$IS_NIGHTLY"' in classify
    assert 'echo "make_latest=$IS_STABLE"' in classify
    # the two notes steps are mutually exclusive on the same condition
    assert "if: contains(github.ref_name, '.dev')" in release
    assert "if: ${{ !contains(github.ref_name, '.dev') }}" in release
    assert "generate-notes" in workflow_script(BUILD, NIGHTLY_NOTES)


def test_the_publish_path_kicks_the_renamed_prune_workflow():
    kick = workflow_script(BUILD, "Kick the publish-time workflows")
    assert 'gh workflow run prune-nightlies.yml' in kick
    assert (WORKFLOWS / "prune-nightlies.yml").is_file()
    assert (ROOT / "scripts" / "prune_nightlies.py").is_file()
    for path in list(WORKFLOWS.glob("*.yml")) + list((ROOT / "scripts").glob("*.py")):
        text = path.read_text()
        assert "prune-betas" not in text and "prune_betas" not in text, path.name
        assert "Beta channel" not in text, path.name


# ---- the decision step, run for real ---------------------------------------
def make_repo(tmp_path, tags=("v1.23.0",)):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=Nightly test",
           "-c", "user.email=test@example.invalid", "-c", "core.hooksPath=/dev/null",
           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(git + ["commit", "--quiet", "--allow-empty", "-m", "release"], check=True)
    for tag in tags:
        subprocess.run(git + ["tag", tag], check=True)
    return repo, git


def commit(git, message="work"):
    subprocess.run(git + ["commit", "--quiet", "--allow-empty", "-m", message], check=True)


def run_pick(tmp_path, repo, version_input=""):
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    env = dict(os.environ, GITHUB_OUTPUT=str(out_file), VERSION_INPUT=version_input)
    result = subprocess.run(["bash", "-eo", "pipefail", "-c", workflow_script(NIGHTLY, PICK)],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=30)
    outputs = dict(line.split("=", 1) for line in out_file.read_text().splitlines() if "=" in line)
    return result, outputs


@linux_only
def test_a_quiet_main_since_the_stable_cuts_nothing(tmp_path):
    repo, _git = make_repo(tmp_path)
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": ""}
    assert "no commits since v1.23.0" in result.stdout


@linux_only
def test_new_commits_since_the_stable_cut_tonights_tag(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": f"v1.24.0.dev{today()}"}, "the newest stable's minor, bumped"


@linux_only
def test_a_second_run_on_the_same_day_cuts_nothing(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    subprocess.run(git + ["tag", f"v1.24.0.dev{today()}"], check=True)
    commit(git, "later the same day")
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": ""}
    assert "already exists" in result.stdout


@linux_only
def test_a_quiet_main_since_the_last_nightly_cuts_nothing(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    subprocess.run(git + ["tag", "v1.24.0.dev20200101"], check=True)
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": ""}
    assert "no commits since v1.24.0.dev20200101" in result.stdout


@linux_only
def test_a_stable_from_a_hotfix_branch_does_not_hide_new_main_commits(tmp_path):
    """The stable is newer by version but not an ancestor of main; only the
    nightly can say whether main moved, and it did."""
    repo, git = make_repo(tmp_path)
    commit(git)
    subprocess.run(git + ["tag", "v1.24.0.dev20200101"], check=True)
    subprocess.run(git + ["checkout", "--quiet", "-b", "hotfix", "v1.23.0"], check=True)
    commit(git, "hotfix")
    subprocess.run(git + ["tag", "v1.23.1"], check=True)
    subprocess.run(git + ["checkout", "--quiet", "-"], check=True)
    commit(git, "main moves on")
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": f"v1.24.0.dev{today()}"}


@linux_only
def test_the_version_input_overrides_the_base(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    result, outputs = run_pick(tmp_path, repo, version_input="v2.0.0")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": f"v2.0.0.dev{today()}"}
    result, outputs = run_pick(tmp_path, repo, version_input="2.0")
    assert result.returncode != 0
    assert "version must be X.Y.Z" in result.stdout


@linux_only
def test_the_bump_is_numeric_and_from_the_newest_stable(tmp_path):
    repo, git = make_repo(tmp_path, tags=("v1.9.0", "v1.10.2", "v1.10.3-rc.1", "v0.99.0"))
    commit(git)
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": f"v1.11.0.dev{today()}"}


@linux_only
def test_no_stable_tag_is_a_loud_failure_not_a_guess(tmp_path):
    repo, git = make_repo(tmp_path, tags=())
    commit(git)
    result, _outputs = run_pick(tmp_path, repo)
    assert result.returncode != 0
    assert "no stable vX.Y.Z tag" in result.stdout


# ---- the release job's steps, run for real ----------------------------------
def run_step(repo, step, env):
    return subprocess.run(["bash", "-eo", "pipefail", "-c", workflow_script(BUILD, step)],
                          cwd=repo, env=dict(os.environ, **env), capture_output=True,
                          text=True, timeout=30)


@linux_only
@pytest.mark.parametrize("ref,expected", [
    ("v1.24.0.dev20260928", {"prerelease": "true", "nightly": "true",
                             "make_latest": "false", "draft": "false"}),
    ("v1.24.0", {"prerelease": "false", "nightly": "false",
                 "make_latest": "true", "draft": "true"}),
    ("v1.24.0rc1", {"prerelease": "true", "nightly": "false",
                    "make_latest": "false", "draft": "false"}),
])
def test_classify_flags_a_nightly_as_a_prerelease_that_is_never_latest(tmp_path, ref, expected):
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    result = run_step(tmp_path, CLASSIFY, {"GITHUB_REF_NAME": ref, "GITHUB_OUTPUT": str(out_file),
                                           "STAGE": ""})
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in out_file.read_text().splitlines())
    assert outputs == expected


def fake_gh(tmp_path):
    """A `gh` that echoes the request it was given, as the notes body."""
    gh = tmp_path / "gh"
    gh.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
        import sys
        args = sys.argv[1:]
        assert args[:3] == ["api", "--method", "POST"], args
        assert args[3].endswith("/releases/generate-notes"), args
        fields = [a for a in args if "=" in a]
        print("GENERATED " + " ".join(fields))
    '''))
    gh.chmod(0o755)
    return tmp_path


CHANGELOG = (
    "# Changelog\n\n## [Unreleased]\n\n"
    "## [1.23.0] - 2026-09-27\n\n### Added\n- **Shipped in the stable.**\n"
)
FRAGMENT = (
    "- **A fragment waiting on main.** Hard-wrapped at eighty columns, with\n"
    "  the continuation indented by two spaces.\n"
)
FRAGMENT_ON_ONE_LINE = (
    "- **A fragment waiting on main.** Hard-wrapped at eighty columns, with "
    "the continuation indented by two spaces."
)
SINCE_STABLE = (
    "## Changes since [v1.23.0](https://github.com/fixture/repository/releases/tag/v1.23.0)"
)


def nightly_repo(tmp_path, tags=("v1.23.0",), changelog=CHANGELOG, fragments=(FRAGMENT,)):
    """A disposable repository with what the notes step reads: the collating
    script and the assembler it imports under scripts/, CHANGELOG.md, and
    changelog.d/, committed under ``tags``."""
    repo, git = make_repo(tmp_path, tags=())
    (repo / "scripts").mkdir()
    for name in ("changelog_fragments.py", "changes_since_stable.py"):
        shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "CHANGELOG.md").write_text(changelog)
    (repo / "changelog.d").mkdir()
    for index, text in enumerate(fragments):
        (repo / "changelog.d" / f"entry-{index}.fixed.md").write_text(text)
    subprocess.run(git + ["add", "scripts", "CHANGELOG.md", "changelog.d"], check=True)
    commit(git, "the notes and the tools")
    for tag in tags:
        subprocess.run(git + ["tag", tag], check=True)
    return repo, git


def run_nightly_notes(tmp_path, repo, git, ref):
    """The notes step on the checked-out commit, as ``ref``; the result and the body."""
    sha = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    bindir = fake_gh(tmp_path)
    result = run_step(repo, NIGHTLY_NOTES, {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REF_NAME": ref, "GITHUB_SHA": sha, "GITHUB_REPOSITORY": "fixture/repository",
        "GH_TOKEN": "unused-by-fake-gh",
    })
    body = (repo / "release_body.md").read_text() if result.returncode == 0 else ""
    return result, body, sha


@linux_only
@pytest.mark.parametrize("tags,ref,previous", [
    # the previous nightly is the newest by date
    (("v1.23.0", "v1.24.0.dev20260927", "v1.24.0.dev20260926"),
     "v1.24.0.dev20260928", "v1.24.0.dev20260927"),
    # by date, not by version: a planned-major nightly from earlier in the
    # month is older than last night's minor-line nightly
    (("v1.23.0", "v1.24.0.dev20260930", "v2.0.0.dev20260901"),
     "v1.24.0.dev20261001", "v1.24.0.dev20260930"),
    # the first nightly ever: the newest stable
    (("v1.22.3", "v1.23.0", "v1.23.0-beta-6"), "v1.24.0.dev20260928", "v1.23.0"),
    # the tag being built is never its own previous
    (("v1.23.0",), "v1.24.0.dev20260928", "v1.23.0"),
])
def test_nightly_notes_compare_against_the_previous_release_on_the_channel(
    tmp_path, tags, ref, previous,
):
    repo, git = nightly_repo(tmp_path, tags=tags)
    subprocess.run(git + ["tag", ref], check=True)
    result, body, sha = run_nightly_notes(tmp_path, repo, git, ref)
    assert result.returncode == 0, result.stderr
    assert "::warning::" not in result.stdout, result.stdout   # the real path, not the fallback
    assert body.startswith("Nightly build of PyReconstruct Dev from main at ")
    # the since-stable section, one line per bullet, then a rule, then the generated notes
    assert SINCE_STABLE in body
    assert FRAGMENT_ON_ONE_LINE in body
    assert "Shipped in the stable." not in body
    assert body.index(SINCE_STABLE) < body.index("\n---\n") < body.index("GENERATED ")
    assert f"tag_name={ref}" in body
    assert f"target_commitish={sha}" in body
    assert f"previous_tag_name={previous}" in body


@linux_only
def test_a_rebuilt_nightly_measures_against_the_releases_in_its_own_history(tmp_path):
    """Rebuilding v1.24.0.dev20261007 after v1.25.0 and a later nightly exist:
    neither is in the rebuilt commit's history, so neither is its baseline, for
    the since-stable heading or for the generated notes."""
    repo, git = nightly_repo(tmp_path, tags=("v1.23.0", "v1.24.0.dev20261006"))
    commit(git, "the night's work")
    subprocess.run(git + ["tag", "v1.24.0.dev20261007"], check=True)
    commit(git, "the next stable")
    subprocess.run(git + ["tag", "v1.25.0"], check=True)
    commit(git, "and a nightly after it")
    subprocess.run(git + ["tag", "v1.26.0.dev20261101"], check=True)
    subprocess.run(git + ["checkout", "--quiet", "v1.24.0.dev20261007"], check=True)
    result, body, _sha = run_nightly_notes(tmp_path, repo, git, "v1.24.0.dev20261007")
    assert result.returncode == 0, result.stderr
    assert SINCE_STABLE in body
    assert "previous_tag_name=v1.24.0.dev20261006" in body
    assert "1.25.0" not in body and "1.26.0" not in body


@linux_only
def test_a_release_section_written_ahead_of_its_tag_is_in_the_nightly_body(tmp_path):
    """Release prep assembles the fragments into ``## [1.24.0]`` on main before
    v1.24.0 is tagged; a nightly built in that window has no fragments and
    nothing under Unreleased, and still owes the Dev reader those changes."""
    changelog = CHANGELOG.replace(
        "## [1.23.0]",
        "## [1.24.0] - 2026-10-08\n\n### Fixed\n- **Prepared for the next stable.** Written\n"
        "  before its tag.\n\n## [1.23.0]",
    )
    repo, git = nightly_repo(tmp_path, changelog=changelog, fragments=())
    subprocess.run(git + ["tag", "v1.24.0.dev20261007"], check=True)
    result, body, _sha = run_nightly_notes(tmp_path, repo, git, "v1.24.0.dev20261007")
    assert result.returncode == 0, result.stderr
    assert "::warning::" not in result.stdout, result.stdout
    assert SINCE_STABLE in body
    assert "- **Prepared for the next stable.** Written before its tag." in body
    assert "Shipped in the stable." not in body


@linux_only
def test_a_quiet_main_and_a_refused_fragment_both_leave_the_generated_notes(tmp_path):
    """Nothing since the stable: no section and no warning. A fragment the
    assembler refuses: a warning, and the nightly still publishes with the
    generated notes alone rather than failing or dropping the fragment quietly."""
    repo, git = nightly_repo(tmp_path, fragments=())
    subprocess.run(git + ["tag", "v1.24.0.dev20261007"], check=True)
    result, body, _sha = run_nightly_notes(tmp_path, repo, git, "v1.24.0.dev20261007")
    assert result.returncode == 0, result.stderr
    assert "::warning::" not in result.stdout
    assert "Changes since" not in body
    assert body.startswith("Nightly build of PyReconstruct Dev from main at ")
    assert "GENERATED tag_name=v1.24.0.dev20261007" in body

    (repo / "changelog.d" / "no-category.md").write_text("- **Named wrong.**\n")
    result, body, _sha = run_nightly_notes(tmp_path, repo, git, "v1.24.0.dev20261007")
    assert result.returncode == 0, result.stderr
    assert "::warning::changelog.d did not assemble" in result.stdout
    assert "Changes since" not in body
    assert "GENERATED tag_name=v1.24.0.dev20261007" in body
