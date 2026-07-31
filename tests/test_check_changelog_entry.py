"""Behavior of the missing-changelog-entry check.

The check itself lives in ``scripts/check_changelog_entry.py`` and runs from
``.github/workflows/notes-checks.yml``. It is report-only, so a mistake in it
costs nobody a merge, which is also why it needs tests: a report-only check that
is quietly wrong produces noise, and noise is how a check gets ignored and then
deleted.

Loaded by file path, the same way ``test_prune_prereleases.py`` loads the other
CI script. Both are stdlib-only tools that ship in ``scripts/`` rather than in
the package, so neither is on an import path.

The five cases pinned here are the five the check has to get right: it fires on
an application change that records nothing, and it stays quiet when a fragment
is there, when ``CHANGELOG.md`` is there, when the author opted out in the body,
and when only tests and workflows change.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_changelog_entry.py"

_spec = importlib.util.spec_from_file_location("check_changelog_entry", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


APP_CHANGE = [
    "PyReconstruct/modules/gui/main/field_widget.py",
    "PyReconstruct/modules/datatypes/series.py",
]

FRAGMENT = "changelog.d/stale-color-render-9c1f04.fixed.md"


def test_application_change_without_an_entry_is_the_finding():
    status, _ = check.evaluate(APP_CHANGE, "Fixes a crash.")
    assert status == "missing"


def test_a_fragment_is_enough():
    """The normal way to record a change, and the reason this directory exists."""
    status, detail = check.evaluate(APP_CHANGE + [FRAGMENT], "Fixes a crash.")
    assert status == "recorded"
    assert detail == FRAGMENT


@pytest.mark.parametrize(
    "fragment",
    [
        "changelog.d/a-000000.added.md",
        "changelog.d/b-111111.changed.md",
        "changelog.d/c-222222.fixed.md",
        "changelog.d/d-333333.removed.md",
        # The category is the last dotted field, so a slug may contain dots.
        "changelog.d/fix.for.v1.21-abc123.fixed.md",
    ],
)
def test_any_fragment_in_the_directory_counts(fragment):
    """The check does not validate the category; the assembler does.

    Splitting it the other way would put the same list of categories in two
    files and let them drift, and a check that rejected a category the
    assembler accepts would be wrong in the direction that costs an author
    time.
    """
    status, _ = check.evaluate(APP_CHANGE + [fragment], "")
    assert status == "recorded"


def test_the_fragment_readme_is_documentation_and_does_not_count():
    """Otherwise editing the instructions would silence the check."""
    status, _ = check.evaluate(APP_CHANGE + ["changelog.d/README.md"], "")
    assert status == "missing"


def test_changelog_in_the_change_is_still_enough():
    """The direct edit keeps working. It is how an assembled release lands."""
    status, detail = check.evaluate(APP_CHANGE + ["CHANGELOG.md"], "Fixes a crash.")
    assert status == "recorded"
    assert detail == "CHANGELOG.md"


def test_a_fragment_is_named_ahead_of_the_changelog_when_both_are_present():
    status, detail = check.evaluate(APP_CHANGE + ["CHANGELOG.md", FRAGMENT], "")
    assert (status, detail) == ("recorded", FRAGMENT)


def test_tests_and_workflows_only_is_exempt_without_asking():
    status, _ = check.evaluate(
        [
            "tests/test_geometry.py",
            "tests/conftest.py",
            ".github/workflows/test.yml",
        ],
        "",
    )
    assert status == "exempt"


def test_a_change_touching_neither_is_out_of_scope():
    status, _ = check.evaluate(["docs/USER_GUIDE.md", "README.md"], "")
    assert status == "no-app-change"


@pytest.mark.parametrize(
    "body",
    [
        "No changelog entry: internal refactor, no behavior change",
        "Some prose first.\n\nNo changelog entry: pure comment fix\n\nMore prose.",
        "- No changelog entry: reverts an unreleased change",
        "no changelog entry: lowercase is accepted",
        "NO CHANGELOG ENTRY: so is shouting",
    ],
)
def test_the_opt_out_line_is_accepted_and_the_reason_is_captured(body):
    status, reason = check.evaluate(APP_CHANGE, body)
    assert status == "opted-out"
    assert reason


@pytest.mark.parametrize(
    "body",
    [
        "No changelog entry:",
        "No changelog entry",
        "No changelog entry:   ",
        "There is no changelog entry needed here.",
        "This needs no changelog entry: I think",
    ],
)
def test_a_marker_with_no_reason_or_no_marker_does_not_opt_out(body):
    """A bare marker is a checkbox. The point of the line is the reason.

    The last two cases matter more than they look: the line must be the whole
    line, so ordinary prose that happens to contain the words does not silently
    turn the check off.
    """
    status, _ = check.evaluate(APP_CHANGE, body)
    assert status == "missing"


def test_exemption_wins_over_scope_even_if_scope_widens():
    """A tests-only change reports as exempt, not as out of scope.

    Today no path can be both under `tests/` and under `PyReconstruct/`, so the
    two rules cannot disagree. The order is pinned anyway: widening the scope
    prefix later must not start failing test-only pull requests.
    """
    status, _ = check.evaluate(["tests/test_geometry.py"], "")
    assert status == "exempt"


def test_the_message_names_the_command_the_categories_and_the_opt_out():
    """The message has to make the fix obvious without reading a convention.

    It names the command rather than a file and a heading, which is the whole
    difference: an author who never has to decide which release section an entry
    belongs under cannot file it under the wrong one.
    """
    message = check._message(APP_CHANGE)

    assert check.NEW_FRAGMENT_COMMAND in message
    assert check.FRAGMENT_DIR in message
    for category in check.CATEGORIES:
        assert category in message
    assert check.ENTRY_SHAPE in message
    assert check.OPT_OUT_EXAMPLE in message
    # The fallback is named, so nobody concludes the direct edit stopped working.
    assert check.CHANGELOG in message
    for path in APP_CHANGE:
        assert path in message


def test_the_message_does_not_send_anyone_to_a_release_heading():
    """The old message named the topmost section. That is now the wrong advice.

    Naming a heading is what produced eight entries filed under a build that
    does not contain them, so no heading appears here at all.
    """
    message = check._message(APP_CHANGE)
    assert "[Unreleased]" not in message
    assert "###" not in message


def test_the_check_is_report_only():
    """Pinned so that flipping it to blocking is a deliberate, visible edit."""
    assert check.BLOCKING is False
