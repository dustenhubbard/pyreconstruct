"""Behavior of the commit message check that runs on every push to main.

The check lives in ``scripts/check_commit_messages.py`` and runs from
``.github/workflows/main-message-watch.yml``. It only reports, so a mistake costs
nobody a merge, but a check that fires on every ordinary squash subject is
noise, and noise gets ignored. The cases below pin both sides: each rule fires
on the message it is for, and an ordinary squash message passes.

The rules are a copy of the pre-commit check's. Set MESSAGE_RULES_SOURCE to the
path of that check's script to compare the two; without it, that test skips.
The names the rules look for come from the script, so this file does not carry
them either.

Loaded by file path, like the other CI scripts in ``scripts/``.
"""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_commit_messages.py"

_spec = importlib.util.spec_from_file_location("check_commit_messages", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


TOOL = check.TOOL.capitalize()
MODEL = check.NAME_WORDS[2]
VENDOR = check.VENDOR

ATTRIBUTION = "has an attribution trailer, a session line or a generated-with line"
NAME = "names a tool or process"

ORDINARY = (
    "fix(undo): keep a traceless imported host on a section redo (#914)\n\n"
    "A redo on one section dropped an imported host with no traces. It is kept now,\n"
    "and `--no-verify` style flags in a body are not dashes.\n"
)


def test_an_ordinary_squash_message_passes():
    assert check.problems_in(ORDINARY) == []


def test_the_pr_number_github_adds_is_not_counted_in_the_subject():
    title = "x" * 70
    assert check.problems_in(f"{title} (#914)") == []
    assert check.problems_in(f"{title}y (#914)") == [
        "subject is 71 characters; the cap is 70"
    ]


@pytest.mark.parametrize(
    "message, expected",
    [
        ("fix: a thing\n\nCo-authored-by: someone <a@b.c>", ATTRIBUTION),
        ("fix: a thing, co-authored-by: someone", ATTRIBUTION),
        (f"fix: a thing\n\n{TOOL}-Session: abc", ATTRIBUTION),
        (f"fix: a thing\n\nGenerated with {TOOL}", ATTRIBUTION),
        (f"fix: a thing\n\nGenerated with [{TOOL}](https://example.com)", ATTRIBUTION),
        (f"fix: a thing\n\nhttps://{TOOL.lower()}.ai/code/abc", ATTRIBUTION),
        (f"fix: a thing\n\nnoreply@{VENDOR}.com", ATTRIBUTION),
        (f"fix: {TOOL} integration", NAME),
        (f"fix: {MODEL} integration", NAME),
        ("fix: a thing \u2014 and more", "has an em dash or a spaced double hyphen"),
        ("fix: a thing -- and more", "has an em dash or a spaced double hyphen"),
        ("fix: a thing\n\n" + "a" * 701, "message is 715 characters; the cap is 700"),
        ("fix: a thing\n\nThis was his call.",
         "names the owner in the third person ('his call')"),
        ("fix: a thing\n\nLet us delve into it.", "has a stock phrase ('delve')"),
    ],
)
def test_each_rule_fires_on_its_message(message, expected):
    assert expected in check.problems_in(message)


# The 700 cap counts the whole message, subject and body, as the pre-commit
# check does.
CAP_CASES = [
    ("fix: short\n\n" + "a" * 688, None),
    ("fix: short\n\n" + "a" * 689, "message is 701 characters; the cap is 700"),
    ("fix: short\n\n" + "a" * 690, "message is 702 characters; the cap is 700"),
    ("fix: " + "s" * 65 + "\n\n" + "a" * 628, None),
    ("fix: " + "s" * 65 + "\n\n" + "a" * 630, "message is 702 characters; the cap is 700"),
]


@pytest.mark.parametrize("message, expected", CAP_CASES)
def test_the_cap_counts_the_subject_and_the_body(message, expected):
    assert check.problems_in(message) == ([expected] if expected else [])


def test_the_pr_number_github_adds_is_not_counted_in_the_whole_message():
    message = "fix: short (#914)\n\n" + "a" * 688
    assert check.problems_in(message) == []
    assert check.problems_in(message + "a") == [
        "message is 701 characters; the cap is 700"
    ]


def test_a_name_inside_a_longer_word_passes():
    assert check.problems_in(f"fix: {MODEL}cule {TOOL}x wording") == []


def test_names_and_attribution_lines_are_not_repeated_in_the_report():
    found = check.problems_in(f"fix: {TOOL} integration\n\nGenerated with {TOOL}")
    assert found == [ATTRIBUTION, NAME]
    assert TOOL.lower() not in json.dumps(found).lower()


def test_the_extra_pattern_is_reported_without_the_matched_text():
    extra = check.extra_pattern({"MESSAGE_SCAN_EXTRA": r"\bsecretword\b"})
    found = check.problems_in("fix: a thing\n\nsecretword here", extra)
    assert found == ["matches the MESSAGE_SCAN_EXTRA pattern"]
    assert "secretword" not in json.dumps(found)


def test_an_unset_extra_pattern_adds_nothing():
    assert check.extra_pattern({}) is None
    assert check.extra_pattern({"MESSAGE_SCAN_EXTRA": "  "}) is None


# ---- the copy matches the pre-commit check ----------------------------------
PROBES = [
    ORDINARY,
    "fix: a thing\n\nCo-authored-by: someone <a@b.c>",
    "fix: a thing, co-authored-by: someone",
    f"fix: a thing\n\n{TOOL}-Session: abc",
    f"fix: a thing\n\nGenerated with {TOOL}",
    f"fix: a thing\n\nhttps://{TOOL.lower()}.ai/code/abc",
    f"fix: a thing\n\nnoreply@{VENDOR}.com",
    f"fix: {TOOL} integration",
    f"fix: {MODEL} integration",
    f"fix: {MODEL}cule {TOOL}x wording",
    "fix: a thing \u2014 and more",
    "fix: a thing -- and more",
    "fix: a thing\n\nThis was his call.",
    "fix: a thing\n\nLet us delve into it.",
    "fix: plain wording\n\nNothing to see here.",
    *(message for message, _ in CAP_CASES),
]


@pytest.fixture
def source_check():
    path = os.environ.get("MESSAGE_RULES_SOURCE")
    if not path:
        pytest.skip("MESSAGE_RULES_SOURCE is not set")
    spec = importlib.util.spec_from_file_location("message_rules_source", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_copy_has_the_same_patterns_and_caps(source_check):
    theirs = {(v.pattern, v.flags) for v in vars(source_check).values()
              if isinstance(v, re.Pattern)}
    for mine in (check.ATTRIBUTION, check.NAMES, check.EM_DASH,
                 check.THIRD_PERSON, check.STOCK_PHRASES):
        assert (mine.pattern, mine.flags) in theirs, mine.pattern
    assert check.SUBJECT_MAX == source_check.SUBJECT_MAX
    assert check.TEXT_MAX == source_check.PUBLIC_TEXT_MAX


@pytest.mark.parametrize("message", PROBES)
def test_the_copy_refuses_what_the_source_refuses(source_check, message):
    try:
        source_check.scan_message(message, True, subject=True)
        refused = False
    except SystemExit:
        refused = True
    assert bool(check.problems_in(message)) == refused


# ---- every commit the push adds ---------------------------------------------
def make_history(repo, messages):
    """A repository whose main branch has one commit per message, oldest first."""
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(repo)], check=True)
    stream = []
    for i, message in enumerate(messages):
        data = message.encode()
        stream.append(b"commit refs/heads/main\n")
        stream.append(f"committer T <t@example.invalid> {1700000000 + i} +0000\n".encode())
        stream.append(f"data {len(data)}\n".encode() + data + b"\n")
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"],
                   input=b"".join(stream), check=True)
    out = subprocess.run(["git", "-C", str(repo), "rev-list", "--reverse", "main"],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def test_a_push_of_more_than_250_commits_is_checked_in_full(tmp_path, monkeypatch):
    messages = [f"fix: change {i}" for i in range(262)]
    messages[3] = "fix: change 3 \u2014 with a dash"
    shas = make_history(tmp_path, messages)
    monkeypatch.chdir(tmp_path)
    commits = check.commits_between(shas[0], shas[-1])
    assert len(commits) == 261
    hits = check.scan(commits)
    assert [h["sha"] for h in hits] == [shas[3]]
    assert hits[0]["subject"] == messages[3]


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_a_first_push_checks_every_commit_on_the_branch(tmp_path, monkeypatch):
    messages = ["fix: first \u2014 with a dash", "fix: clean middle", "fix: clean tip"]
    shas = make_history(tmp_path, messages)
    monkeypatch.chdir(tmp_path)
    commits = check.commits_between("0" * 40, shas[-1])
    assert [c["sha"] for c in commits] == shas[::-1]
    assert [h["sha"] for h in check.scan(commits)] == [shas[0]]


def test_a_first_push_skips_commits_another_branch_or_tag_has(tmp_path, monkeypatch):
    shas = make_history(tmp_path, [f"fix: change {i}" for i in range(5)])
    git(tmp_path, "branch", "other", shas[1])
    git(tmp_path, "tag", "v1", shas[2])
    git(tmp_path, "update-ref", "refs/remotes/origin/main", shas[-1])
    git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    monkeypatch.chdir(tmp_path)
    commits = check.commits_between("0" * 40, shas[-1])
    assert [c["sha"] for c in commits] == [shas[4], shas[3]]


def test_a_base_the_clone_does_not_have_is_an_error(tmp_path, monkeypatch):
    shas = make_history(tmp_path, ["fix: one", "fix: two"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="not in this clone"):
        check.commits_between("1" * 40, shas[-1])


def test_main_prints_only_the_commits_with_problems(tmp_path, monkeypatch, capsys):
    shas = make_history(tmp_path, ["fix: base", ORDINARY, "fix: x \u2014 y"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MESSAGE_SCAN_EXTRA", raising=False)
    assert check.main(["check_commit_messages.py", shas[0], shas[-1]]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert [h["sha"] for h in hits] == [shas[2]]
    assert hits[0]["subject"] == "fix: x \u2014 y"


# ---- the workflow -----------------------------------------------------------
def test_the_watch_opens_issues_on_the_fork_only():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "main-message-watch.yml").read_text()
    )
    for job in workflow["jobs"].values():
        assert job.get("if") == "github.repository == 'dustenhubbard/pyreconstruct'"


def test_the_watch_checks_out_the_full_history():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "main-message-watch.yml").read_text()
    )
    checkout = workflow["jobs"]["scan"]["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["fetch-depth"] == 0
