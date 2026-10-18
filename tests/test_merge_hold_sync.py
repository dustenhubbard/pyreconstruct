"""The merge hold reaches every open PR, and a second pass changes nothing.

``scripts/merge_hold_sync.py`` runs from ``.github/workflows/merge-hold-sync.yml``.
A re-run of a passed `merge-evidence` run keeps the workflow file of its first
event, which may have no hold step, so re-running cannot apply a hold. The
script adds a failed check run of the same name instead. These tests run it
against a small stand-in for the GitHub API that keeps the check runs, workflow
runs and re-runs it is asked for.

Loaded by file path, like the other CI scripts in ``scripts/``.
"""

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "merge_hold_sync.py"

_spec = importlib.util.spec_from_file_location("merge_hold_sync", SCRIPT)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)

REPO = "owner/repo"


class FakeGitHub:
    """The endpoints the script calls, over in-memory state."""

    def __init__(self, prs=1):
        self.prs = [{"number": n, "head": {"sha": f"{n:040d}"}} for n in range(1, prs + 1)]
        self.check_runs = []      # every check run on any commit
        self.runs = {}            # head sha -> latest merge-evidence workflow run
        self.steps = {}           # run id -> [(step name, conclusion)]
        self.reruns = []
        self.next_id = 1000

    def latest_run(self, sha, conclusion, steps):
        run_id = self.next_id
        self.next_id += 1
        self.runs[sha] = {"id": run_id, "status": "completed", "conclusion": conclusion}
        self.steps[run_id] = steps
        return run_id

    def __call__(self, method, path, body=None):
        parts = urlsplit(path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        segs = parts.path.split("/")[3:]
        page = int(query.get("page", 1))
        per = int(query.get("per_page", 30))

        def paged(items):
            return items[(page - 1) * per: page * per]

        if method == "GET" and segs == ["pulls"]:
            assert query["state"] == "open"
            return paged(self.prs)
        if method == "GET" and segs[0] == "commits" and segs[2] == "check-runs":
            assert query["filter"] == "all"
            found = [c for c in self.check_runs
                     if c["head_sha"] == segs[1] and c["name"] == query["check_name"]]
            return {"total_count": len(found), "check_runs": paged(found)}
        if method == "POST" and segs == ["check-runs"]:
            run = dict(body, id=self.next_id)
            self.next_id += 1
            self.check_runs.append(run)
            return run
        if method == "PATCH" and segs[0] == "check-runs":
            run = next(c for c in self.check_runs if c["id"] == int(segs[1]))
            run.update(body)
            return run
        if method == "GET" and segs[:2] == ["actions", "workflows"]:
            assert segs[2] == "merge-evidence.yml"
            assert query["event"] == "pull_request_target"
            run = self.runs.get(query["head_sha"])
            return {"workflow_runs": [run] if run else []}
        if method == "GET" and segs[:2] == ["actions", "runs"] and segs[3] == "jobs":
            steps = self.steps[int(segs[2])]
            return {"jobs": [{"steps": [{"name": n, "conclusion": c} for n, c in steps]}]}
        if method == "POST" and segs[:2] == ["actions", "runs"] and segs[3] == "rerun":
            self.reruns.append(int(segs[2]))
            self.runs_by_id(int(segs[2]))["status"] = "queued"
            return None
        raise AssertionError(f"unexpected call {method} {path}")

    def runs_by_id(self, run_id):
        return next(r for r in self.runs.values() if r["id"] == run_id)

    def hold_checks(self, sha):
        return [c for c in self.check_runs if c["head_sha"] == sha
                and c.get("external_id") == "merge-hold"]


OLD_GATE = [("require the `reviewed` label", "success")]
HELD_GATE = [("merge hold", "failure"), ("require the `reviewed` label", "skipped")]


def test_a_hold_blocks_a_pr_whose_green_check_predates_the_hold_step():
    gh = FakeGitHub()
    sha = gh.prs[0]["head"]["sha"]
    gh.latest_run(sha, "success", OLD_GATE)
    for _ in range(3):
        sync.sync(gh, REPO, hold=True)
    held = gh.hold_checks(sha)
    assert [(c["name"], c["conclusion"]) for c in held] == [("merge-evidence", "failure")]
    assert gh.reruns == []


def test_a_hold_reaches_every_open_pr_across_pages():
    gh = FakeGitHub(prs=205)
    assert len(sync.sync(gh, REPO, hold=True)) == 205
    assert all(len(gh.hold_checks(pr["head"]["sha"])) == 1 for pr in gh.prs)
    assert sync.sync(gh, REPO, hold=True) == []


def test_clearing_passes_the_hold_check_and_reruns_a_run_the_hold_failed():
    gh = FakeGitHub()
    sha = gh.prs[0]["head"]["sha"]
    run_id = gh.latest_run(sha, "failure", HELD_GATE)
    sync.sync(gh, REPO, hold=True)
    sync.sync(gh, REPO, hold=False)
    assert [c["conclusion"] for c in gh.hold_checks(sha)] == ["success"]
    assert gh.reruns == [run_id]
    # The re-run finishes on the cleared hold; nothing is left to change.
    gh.latest_run(sha, "failure", [("merge hold", "success"),
                                   ("require the `reviewed` label", "failure")])
    assert sync.sync(gh, REPO, hold=False) == []
    assert gh.reruns == [run_id]


def test_clearing_leaves_a_run_that_failed_for_another_reason():
    gh = FakeGitHub()
    gh.latest_run(gh.prs[0]["head"]["sha"], "failure",
                  [("merge hold", "success"), ("require the `reviewed` label", "failure")])
    assert sync.sync(gh, REPO, hold=False) == []
    assert gh.reruns == []


def test_a_new_hold_reuses_the_cleared_check():
    gh = FakeGitHub()
    sha = gh.prs[0]["head"]["sha"]
    sync.sync(gh, REPO, hold=True)
    sync.sync(gh, REPO, hold=False)
    sync.sync(gh, REPO, hold=True)
    assert [c["conclusion"] for c in gh.hold_checks(sha)] == ["failure"]


def test_other_merge_evidence_check_runs_are_left_alone():
    gh = FakeGitHub()
    sha = gh.prs[0]["head"]["sha"]
    gh.check_runs.append({"id": 1, "name": "merge-evidence", "head_sha": sha,
                          "conclusion": "failure"})
    sync.sync(gh, REPO, hold=True)
    sync.sync(gh, REPO, hold=False)
    assert gh.check_runs[0]["conclusion"] == "failure"


def test_the_sync_runs_on_the_fork_only_with_the_permissions_it_needs():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "merge-hold-sync.yml").read_text()
    )
    assert workflow["permissions"] == {
        "actions": "write", "checks": "write", "contents": "read", "pull-requests": "read",
    }
    for job in workflow["jobs"].values():
        assert job.get("if") == "github.repository == 'dustenhubbard/pyreconstruct'"
