"""Behavior of the missing-changelog-entry check.

The check itself lives in ``scripts/check_changelog_entry.py`` and runs from
``.github/workflows/notes-checks.yml``. It is report-only, so a mistake in it
costs nobody a merge, which is also why it needs tests: a report-only check that
is quietly wrong produces noise, and noise is how a check gets ignored and then
deleted.

Loaded by file path, the same way ``test_prune_prereleases.py`` loads the other
CI script. Both are stdlib-only tools that ship in ``scripts/`` rather than in
the package, so neither is on an import path.

The four cases pinned here are the four the check has to get right: it fires on
an application change with no entry, and it stays quiet when the entry is there,
when the author opted out in the body, and when only tests and workflows change.
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


def test_application_change_without_an_entry_is_the_finding():
    status, _ = check.evaluate(APP_CHANGE, "Fixes a crash.")
    assert status == "missing"


def test_changelog_in_the_change_is_enough():
    status, _ = check.evaluate(APP_CHANGE + ["CHANGELOG.md"], "Fixes a crash.")
    assert status == "recorded"


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


def test_the_message_names_the_file_the_sections_and_the_opt_out():
    """The message has to make the fix obvious without reading a convention."""

    changelog = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- **A thing.** It does something.\n\n"
        "### Fixed\n"
        "- **Another thing.** It stopped doing something.\n\n"
        "## [1.0.0] - 2026-01-01\n\n"
        "### Removed\n"
        "- **An old thing.**\n"
    )
    message = check._message(APP_CHANGE, changelog)

    assert "CHANGELOG.md" in message
    # The section an entry goes under, named, not left to be looked up.
    assert "## [Unreleased]" in message
    assert "Added" in message and "Fixed" in message
    # Only the topmost section's buckets: `Removed` belongs to 1.0.0.
    assert "Removed" not in message
    assert check.ENTRY_SHAPE in message
    assert check.OPT_OUT_EXAMPLE in message
    for path in APP_CHANGE:
        assert path in message


def test_the_message_survives_an_unreadable_changelog():
    message = check._message(APP_CHANGE, "")
    for section in check.KEEP_A_CHANGELOG_SECTIONS:
        assert section in message
    assert "## [Unreleased]" in message


def test_the_check_is_report_only():
    """Pinned so that flipping it to blocking is a deliberate, visible edit."""
    assert check.BLOCKING is False
