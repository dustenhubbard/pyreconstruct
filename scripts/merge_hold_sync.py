#!/usr/bin/env python3
"""Make every open PR's `merge-evidence` result agree with the merge hold.

    MERGE_HOLD=1 REPO=owner/name python3 scripts/merge_hold_sync.py

Run by ``merge-hold-sync.yml``. While the repository variable MERGE_HOLD is
``1``, merge-evidence.yml fails on every new run, but a variable change is not
an event: a PR whose check passed before the hold keeps its green check. A
re-run does not help, because it runs the workflow file as it was for the
original event, which may predate the hold.

So this does not lean on the workflow at all. While the hold is set, it puts a
failed check run named ``merge-evidence`` on each open PR's head commit. Branch
protection counts every check of that name, and a red one blocks the merge
whatever the others say. When the hold is cleared, it marks those check runs
as passed, which leaves the PR to its own merge-evidence run, and re-runs any
merge-evidence run that failed at its ``merge hold`` step.

Each pass only changes what disagrees with the hold, so running it again
changes nothing. Nothing here approves, labels or merges anything.

Stdlib and the ``gh`` command, like the other scripts the workflows run.
"""

import json
import os
import subprocess
import sys

CHECK = "merge-evidence"
# Marks the check runs this script makes, so it never touches any other.
HOLD_ID = "merge-hold"
HOLD_STEP = "merge hold"
HELD = {
    "title": "Merge hold",
    "summary": "Merge hold in force (repository variable MERGE_HOLD is 1). "
               "Nothing merges until it is cleared.",
}
CLEARED = {"title": "Merge hold cleared", "summary": "The merge hold is cleared."}


def gh_api(method, path, body=None):
    """Call the GitHub API through ``gh`` and return the parsed reply."""
    argv = ["gh", "api", "-X", method, path]
    if body is not None:
        argv += ["--input", "-"]
    out = subprocess.run(
        argv, input=json.dumps(body) if body is not None else None,
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out) if out.strip() else None


def every_page(api, path, key=None):
    """All items from a paged list endpoint, 100 at a time."""
    items, page = [], 1
    while True:
        reply = api("GET", f"{path}&per_page=100&page={page}")
        batch = reply[key] if key else reply
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def hold_checks(api, repo, sha):
    runs = every_page(
        api, f"repos/{repo}/commits/{sha}/check-runs?check_name={CHECK}&filter=all",
        key="check_runs",
    )
    return [r for r in runs if r.get("external_id") == HOLD_ID]


def set_check(api, repo, check_id, conclusion, output):
    api("PATCH", f"repos/{repo}/check-runs/{check_id}",
        {"status": "completed", "conclusion": conclusion, "output": output})


def failed_at_hold(api, repo, sha):
    """IDs of the PR's latest merge-evidence run, if it failed at the hold step."""
    reply = api("GET", f"repos/{repo}/actions/workflows/{CHECK}.yml/runs"
                       f"?head_sha={sha}&event=pull_request_target&per_page=1")
    runs = reply["workflow_runs"]
    if not runs or runs[0]["status"] != "completed" or runs[0]["conclusion"] != "failure":
        return []
    jobs = api("GET", f"repos/{repo}/actions/runs/{runs[0]['id']}/jobs")["jobs"]
    held = any(s["name"] == HOLD_STEP and s["conclusion"] == "failure"
               for job in jobs for s in job.get("steps") or [])
    return [runs[0]["id"]] if held else []


def sync(api, repo, hold):
    """Bring each open PR in line with ``hold``; return a line per change."""
    done = []
    for pr in every_page(api, f"repos/{repo}/pulls?state=open"):
        number, sha = pr["number"], pr["head"]["sha"]
        mine = hold_checks(api, repo, sha)
        if hold:
            if any(r["conclusion"] == "failure" for r in mine):
                continue
            if mine:
                set_check(api, repo, mine[0]["id"], "failure", HELD)
            else:
                api("POST", f"repos/{repo}/check-runs", {
                    "name": CHECK, "head_sha": sha, "external_id": HOLD_ID,
                    "status": "completed", "conclusion": "failure", "output": HELD,
                })
            done.append(f"#{number}: held")
            continue
        for r in mine:
            if r["conclusion"] == "failure":
                set_check(api, repo, r["id"], "success", CLEARED)
                done.append(f"#{number}: hold cleared")
        for run_id in failed_at_hold(api, repo, sha):
            api("POST", f"repos/{repo}/actions/runs/{run_id}/rerun")
            done.append(f"#{number}: re-ran merge-evidence run {run_id}")
    return done


def main():
    hold = os.environ.get("MERGE_HOLD", "").strip() == "1"
    print("merge hold in force" if hold else "no merge hold")
    for line in sync(gh_api, os.environ["REPO"], hold):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
