"""The nightly release train: nightly.yml cuts the tag, build-installers.yml ships it.

Once a day, and on any manual run, nightly.yml tags main's HEAD as
vX.Y.Z.devYYYYMMDDHHMM (UTC) when main has moved since the last release on
either channel, then dispatches
build-installers.yml on that tag (a tag pushed with GITHUB_TOKEN never fires a
`push: tags:` trigger). The release job publishes a nightly as a pre-release
that is never "latest", with GitHub's generated notes against the previous
nightly. These pin the pieces that would break silently, and run the shell of
the decision steps against disposable repositories.
"""

import os
from pathlib import Path
import re
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
# nightly must use exactly this string. The dev number is the UTC date and
# time, YYYYMMDDHHMM; the 8-digit YYYYMMDD of the tags cut before 2026-10-08
# stays valid.
NIGHTLY_RE_SHELL = r"^v[0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]{8}([0-9]{4})?$"
NIGHTLY_RE = re.compile(NIGHTLY_RE_SHELL)

linux_only = pytest.mark.skipif(os.name == "nt", reason="Linux workflow shell integration")


def source(filename):
    return (WORKFLOWS / filename).read_text()


# The clock every run of the pick step reads, through a fake `date`.
NOW = "2026-10-08T13:15"


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
    assert (r"^v[0-9]+\.[0-9]+\.[0-9]+(\.dev[0-9]{8}([0-9]{4})?)?$"
            in workflow_script(BUILD, "Compute version"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from prune_nightlies import NIGHTLY_RE as policy_re
    for tag, ok in [("v1.24.0.dev20260928", True), ("v2.0.0.dev20270101", True),
                    ("v1.24.0.dev202610081315", True), ("v2.0.0.dev202701010000", True),
                    ("v1.24.0.dev2026100813", False), ("v1.24.0.dev2026100813150", False),
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


def fake_date(tmp_path, now):
    """A `date` that prints the UTC time `now` ("YYYY-MM-DDTHH:MM") in the
    format it is asked for, so the tag a run picks is known in advance."""
    bindir = tmp_path / "fake-date"
    bindir.mkdir(exist_ok=True)
    shim = bindir / "date"
    shim.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f'''\
        import sys
        from datetime import datetime
        assert "-u" in sys.argv[1:], sys.argv
        fmt = next(a[1:] for a in sys.argv[1:] if a.startswith("+"))
        print(datetime.strptime({now!r}, "%Y-%m-%dT%H:%M").strftime(fmt))
    '''))
    shim.chmod(0o755)
    return bindir


def run_pick(tmp_path, repo, version_input="", now=NOW):
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    env = dict(os.environ, GITHUB_OUTPUT=str(out_file), VERSION_INPUT=version_input,
               PATH=f"{fake_date(tmp_path, now)}{os.pathsep}{os.environ['PATH']}")
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
    assert outputs == {"tag": "v1.24.0.dev202610081315"}, "the newest stable's minor, bumped"


@linux_only
def test_a_second_run_in_the_same_minute_cuts_nothing(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    subprocess.run(git + ["tag", "v1.24.0.dev202610081315"], check=True)
    commit(git, "later the same minute")
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": ""}
    assert "already exists" in result.stdout


@linux_only
@pytest.mark.parametrize("morning", [
    "v1.24.0.dev20261008",       # the 8-digit shape the scheduled run cut before 2026-10-08
    "v1.24.0.dev202610080709",   # a timed tag from earlier the same day
])
def test_a_second_nightly_the_same_day_gets_its_own_tag(tmp_path, morning):
    repo, git = make_repo(tmp_path)
    commit(git)
    subprocess.run(git + ["tag", morning], check=True)
    commit(git, "merged after the morning nightly")
    result, outputs = run_pick(tmp_path, repo, now="2026-10-08T13:15")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": "v1.24.0.dev202610081315"}
    assert f"newest nightly: {morning}" in result.stdout


@linux_only
def test_two_runs_the_same_day_pick_different_tags(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    _result, first = run_pick(tmp_path, repo, now="2026-10-08T06:00")
    subprocess.run(git + ["tag", first["tag"]], check=True)
    commit(git, "afternoon work")
    _result, second = run_pick(tmp_path, repo, now="2026-10-08T13:15")
    assert (first["tag"], second["tag"]) == ("v1.24.0.dev202610080600", "v1.24.0.dev202610081315")


@linux_only
def test_a_quiet_main_since_a_timed_nightly_cuts_nothing(tmp_path):
    """The 12-digit tag on HEAD is the newest nightly, above the 8-digit one
    from the same morning, so an unchanged main makes no new nightly."""
    repo, git = make_repo(tmp_path)
    commit(git)
    subprocess.run(git + ["tag", "v1.24.0.dev20261008"], check=True)
    commit(git)
    subprocess.run(git + ["tag", "v1.24.0.dev202610080709"], check=True)
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": ""}
    assert "no commits since v1.24.0.dev202610080709" in result.stdout


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
    assert outputs == {"tag": "v1.24.0.dev202610081315"}


@linux_only
def test_the_version_input_overrides_the_base(tmp_path):
    repo, git = make_repo(tmp_path)
    commit(git)
    result, outputs = run_pick(tmp_path, repo, version_input="v2.0.0")
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": "v2.0.0.dev202610081315"}
    result, outputs = run_pick(tmp_path, repo, version_input="2.0")
    assert result.returncode != 0
    assert "version must be X.Y.Z" in result.stdout


@linux_only
def test_the_bump_is_numeric_and_from_the_newest_stable(tmp_path):
    repo, git = make_repo(tmp_path, tags=("v1.9.0", "v1.10.2", "v1.10.3-rc.1", "v0.99.0"))
    commit(git)
    result, outputs = run_pick(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tag": "v1.11.0.dev202610081315"}


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
    ("v1.24.0.dev202610081315", {"prerelease": "true", "nightly": "true",
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
    # a timed nightly follows the 8-digit one from the same morning
    (("v1.23.0", "v1.24.0.dev20261007", "v1.24.0.dev20261008"),
     "v1.24.0.dev202610081315", "v1.24.0.dev20261008"),
    # and a later one the same day follows it
    (("v1.23.0", "v1.24.0.dev20261008", "v1.24.0.dev202610081315"),
     "v1.24.0.dev202610081840", "v1.24.0.dev202610081315"),
    # a build that finishes, or reruns, after a later nightly is tagged
    # compares against the one before it, never the later one
    (("v1.23.0", "v1.24.0.dev20261008", "v1.24.0.dev202610081840"),
     "v1.24.0.dev202610081315", "v1.24.0.dev20261008"),
    (("v1.23.0", "v1.24.0.dev20261007", "v1.24.0.dev202610081315"),
     "v1.24.0.dev20261008", "v1.24.0.dev20261007"),
    # with only later nightlies, the newest stable
    (("v1.23.0", "v1.24.0.dev202610081840"), "v1.24.0.dev202610081315", "v1.23.0"),
])
def test_nightly_notes_compare_against_the_previous_release_on_the_channel(
    tmp_path, tags, ref, previous,
):
    repo, git = make_repo(tmp_path, tags=tags)
    subprocess.run(git + ["tag", ref], check=True)
    sha = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    bindir = fake_gh(tmp_path)
    result = run_step(repo, NIGHTLY_NOTES, {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REF_NAME": ref, "GITHUB_SHA": sha, "GITHUB_REPOSITORY": "fixture/repository",
        "GH_TOKEN": "unused-by-fake-gh",
    })
    assert result.returncode == 0, result.stderr
    body = (repo / "release_body.md").read_text()
    assert body.startswith("Nightly build of PyReconstruct Dev from main at ")
    assert f"tag_name={ref}" in body
    assert f"target_commitish={sha}" in body
    # whole words: dev20261008 is a prefix of dev202610081840
    assert f"previous_tag_name={previous}" in body.split()
