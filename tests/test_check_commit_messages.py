"""Behavior of the commit message check that runs on every push to main.

The check lives in ``scripts/check_commit_messages.py`` and runs from
``.github/workflows/main-message-watch.yml``. It only reports, so a mistake costs
nobody a merge, but a check that fires on every ordinary squash subject is
noise, and noise gets ignored. The cases below pin both sides: each rule fires
on the message it is for, and an ordinary squash message passes.

Loaded by file path, like the other CI scripts in ``scripts/``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_commit_messages.py"

_spec = importlib.util.spec_from_file_location("check_commit_messages", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


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
        ("fix: a thing\n\nCo-authored-by: someone <a@b.c>", "has a Co-authored-by trailer"),
        ("fix: a thing\n\nGenerated with [Some Tool](https://example.com)",
         "has a tool attribution line or session link"),
        ("fix: a thing\n\nhttps://example.com/code/session_0123abc",
         "has a tool attribution line or session link"),
        ("fix: a thing \u2014 and more", "has an em dash or a spaced double hyphen"),
        ("fix: a thing -- and more", "has an em dash or a spaced double hyphen"),
        ("fix: a thing\n\n" + "a" * 701, "body is 701 characters; the cap is 700"),
        ("fix: a thing\n\nThis was his call.",
         "names the owner in the third person ('his call')"),
        ("fix: a thing\n\nLet us delve into it.", "has a stock phrase ('delve')"),
    ],
)
def test_each_rule_fires_on_its_message(message, expected):
    assert expected in check.problems_in(message)


def test_the_extra_pattern_is_reported_without_the_matched_text():
    extra = check.extra_pattern({"MESSAGE_SCAN_EXTRA": r"\bsecretword\b"})
    found = check.problems_in("fix: a thing\n\nsecretword here", extra)
    assert found == ["matches the MESSAGE_SCAN_EXTRA pattern"]
    assert "secretword" not in json.dumps(found)


def test_an_unset_extra_pattern_adds_nothing():
    assert check.extra_pattern({}) is None
    assert check.extra_pattern({"MESSAGE_SCAN_EXTRA": "  "}) is None


def test_main_prints_only_the_commits_with_problems(tmp_path, capsys):
    commits = [
        {"sha": "a" * 40, "message": ORDINARY},
        {"sha": "b" * 40, "message": "fix: x \u2014 y"},
    ]
    path = tmp_path / "commits.json"
    path.write_text(json.dumps(commits), encoding="utf-8")
    assert check.main(["check_commit_messages.py", str(path)]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert [h["sha"] for h in hits] == ["b" * 40]
    assert hits[0]["subject"] == "fix: x \u2014 y"
