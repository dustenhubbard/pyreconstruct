"""Behavior of the missing-docs-change check.

The check lives in ``scripts/check_docs_entry.py`` and runs from
``.github/workflows/notes-checks.yml``. It is report-only for now, and a
report-only check that is quietly wrong produces noise, which is how a check
gets ignored. Loaded by file path, the same way ``test_check_changelog_entry.py``
loads its script.

What is pinned: it fires on a user-facing change with no docs, it stays quiet
when ``docs/`` or ``README.md`` changes or the body opts out, it ignores files
off the list, the stale-shot list works with and without its map, and the exit
code follows ``BLOCKING``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_docs_entry.py"

_spec = importlib.util.spec_from_file_location("check_docs_entry", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


DIALOG = "PyReconstruct/modules/gui/dialog/shortcuts.py"
UI_CHANGE = [DIALOG, "PyReconstruct/modules/datatypes/series.py"]


def test_user_facing_change_without_docs_is_the_finding():
    status, _ = check.evaluate(UI_CHANGE, "Adds a row.")
    assert status == "missing"


@pytest.mark.parametrize(
    "path",
    [
        "PyReconstruct/modules/gui/main/menubar.py",
        "PyReconstruct/modules/gui/main/mac_menubar.py",
        "PyReconstruct/modules/gui/main/context_menu_list.py",
        "PyReconstruct/modules/gui/dialog/knife.py",
        "PyReconstruct/modules/gui/palette/mouse_palette.py",
        "PyReconstruct/modules/gui/popup/about.py",
        "PyReconstruct/modules/datatypes/default_settings.py",
        "PyReconstruct/modules/backend/updater/apply.py",
        "packaging/linux/install.sh",
        "packaging/windows/PyReconstruct.iss",
        "packaging/macos/first-launch.html",
    ],
)
def test_each_kind_of_user_facing_path_is_in_scope(path):
    status, _ = check.evaluate([path], "")
    assert status == "missing"


@pytest.mark.parametrize(
    "path",
    [
        "PyReconstruct/modules/gui/main/field_widget_5_mouse.py",
        "PyReconstruct/modules/datatypes/series.py",
        # A file entry is one file, not a prefix.
        "PyReconstruct/modules/gui/main/menubar_helpers.py",
        "packaging/linux/make_appimage.sh",
        "packaging/PyReconstruct.spec",
        "scripts/check_docs_entry.py",
        "tests/test_check_docs_entry.py",
        ".github/workflows/notes-checks.yml",
    ],
)
def test_files_off_the_list_are_out_of_scope(path):
    """The list is narrow on purpose; a refactor elsewhere asks nothing."""
    status, _ = check.evaluate([path], "")
    assert status == "no-ui-change"


def test_every_listed_path_exists():
    """A renamed or deleted file would drop out of the check without a sound."""
    missing = [p for p in check.USER_FACING if not (ROOT / p).exists()]
    assert missing == []


@pytest.mark.parametrize(
    "docs", ["docs/USER_GUIDE.md", "docs/index.md", "README.md"]
)
def test_a_docs_or_readme_change_is_enough(docs):
    status, detail = check.evaluate(UI_CHANGE + [docs], "")
    assert (status, detail) == ("recorded", docs)


def test_a_nested_readme_is_not_the_readme():
    status, _ = check.evaluate(UI_CHANGE + ["packaging/linux/README.md"], "")
    assert status == "missing"


@pytest.mark.parametrize(
    "body",
    [
        "No docs change: internal refactor, nothing a user sees moved",
        "Prose first.\n\nNo docs change: tooltip typo\n\nMore prose.",
        "- No docs change: reverts an unreleased change",
        "no docs change: lowercase is accepted",
        "NO DOCS CHANGE: so is shouting",
        "Line one\r\nNo docs change: Windows line endings\r\n",
    ],
)
def test_the_opt_out_line_is_accepted_and_the_reason_is_captured(body):
    status, reason = check.evaluate(UI_CHANGE, body)
    assert status == "opted-out"
    assert reason and "\r" not in reason


@pytest.mark.parametrize(
    "body",
    [
        "No docs change:",
        "No docs change",
        "No docs change:   ",
        "There is no docs change needed here.",
        "This needs no docs change: I think",
        "No changelog entry: the other check's line does not count here",
    ],
)
def test_a_marker_with_no_reason_or_no_marker_does_not_opt_out(body):
    """The line must be a whole line with a reason, so prose cannot switch it off."""
    status, _ = check.evaluate(UI_CHANGE, body)
    assert status == "missing"


def test_the_message_names_the_files_and_the_opt_out():
    message = check._message(UI_CHANGE)
    assert DIALOG in message
    # Only the user-facing file is listed as the reason for the finding.
    assert "series.py" not in message
    assert check.OPT_OUT_EXAMPLE in message
    assert "docs/USER_GUIDE.md" in message


# Stale-shot list.

SHOTS = {
    "docs/assets/images/user-guide/06-knife-options.png": [
        "PyReconstruct/modules/gui/dialog/knife.py"
    ],
    "docs/assets/images/user-guide/06-tool-palette.png": [
        "PyReconstruct/modules/gui/palette/"
    ],
}


def test_a_shot_that_shows_a_changed_file_is_listed():
    found = check.stale_shots(
        ["PyReconstruct/modules/gui/palette/mouse_palette.py"], SHOTS
    )
    assert found == [
        (
            "docs/assets/images/user-guide/06-tool-palette.png",
            ["PyReconstruct/modules/gui/palette/mouse_palette.py"],
        )
    ]


def test_a_reshot_image_is_not_listed():
    changed = [
        "PyReconstruct/modules/gui/dialog/knife.py",
        "docs/assets/images/user-guide/06-knife-options.png",
    ]
    assert check.stale_shots(changed, SHOTS) == []


def test_no_shot_is_listed_for_an_unrelated_change():
    assert check.stale_shots(["PyReconstruct/modules/datatypes/series.py"], SHOTS) == []


def test_a_missing_map_is_skipped(tmp_path):
    assert check.load_shot_sources(tmp_path / "sources.json") is None
    assert check.load_shot_sources(None) is None


def test_a_broken_map_is_an_error(tmp_path):
    bad = tmp_path / "sources.json"
    bad.write_text(json.dumps({"a.png": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        check.load_shot_sources(bad)


# The command line, end to end.


def _run(tmp_path, changed, body, shots=None):
    files = tmp_path / "changed.txt"
    files.write_text("\n".join(changed) + "\n", encoding="utf-8")
    body_file = tmp_path / "body.txt"
    body_file.write_text(body, encoding="utf-8")
    argv = ["--changed-files", str(files), "--body", str(body_file)]
    if shots is not None:
        argv += ["--shot-sources", str(shots)]
    return check.main(argv)


def test_report_only_passes_on_a_finding_and_warns(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert _run(tmp_path, UI_CHANGE, "") == 0
    out = capsys.readouterr().out
    assert "::warning title=Missing docs change (report-only, not blocking)::" in out


def test_blocking_fails_on_a_finding(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(check, "BLOCKING", True)
    assert _run(tmp_path, UI_CHANGE, "") == 1
    assert "::error title=Missing docs change::" in capsys.readouterr().out


def test_blocking_still_passes_an_opt_out(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "BLOCKING", True)
    assert _run(tmp_path, UI_CHANGE, "No docs change: copy fix") == 0


def test_the_stale_shot_list_never_fails(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(check, "BLOCKING", True)
    shots = tmp_path / "sources.json"
    shots.write_text(json.dumps(SHOTS), encoding="utf-8")
    changed = ["PyReconstruct/modules/gui/dialog/knife.py", "docs/USER_GUIDE.md"]
    assert _run(tmp_path, changed, "", shots) == 0
    out = capsys.readouterr().out
    assert "::notice title=Guide images that may be stale::" in out
    assert "06-knife-options.png" in out


def test_a_missing_map_says_so(tmp_path, capsys):
    assert _run(tmp_path, UI_CHANGE, "", tmp_path / "absent.json") == 0
    assert "stale-shot list: skipped" in capsys.readouterr().out


def test_the_body_is_data_and_cannot_forge_an_annotation(tmp_path, capsys, monkeypatch):
    """The body is untrusted. A reason that tries to start a workflow command
    stays inside the ok line, which does not start with ``::``."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    body = "No docs change: x\n::error::forged\n$(touch /tmp/pwned)"
    assert _run(tmp_path, UI_CHANGE, body) == 0
    lines = capsys.readouterr().out.splitlines()
    assert not any(line.startswith("::") for line in lines)


def test_an_annotation_stays_one_command():
    """A newline or percent sign in the text cannot end the command early."""
    escaped = check._escape("a%0Ab\nc\rd")
    assert "\n" not in escaped and "\r" not in escaped
    assert escaped == "a%250Ab%0Ac%0Dd"


def test_the_check_is_report_only():
    """Pinned so that flipping it to blocking is a deliberate, visible edit."""
    assert check.BLOCKING is False


def test_the_workflow_passes_the_body_through_env_and_a_file():
    """The body reaches the job only as an environment variable, never as text
    spliced into a script, and the job points at the real image map path."""
    workflow = (ROOT / ".github/workflows/notes-checks.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  docs-entry:\n", 1)[1]
    uses = [line.strip() for line in job.splitlines() if "pull_request.body" in line]
    assert uses == ["PR_BODY: ${{ github.event.pull_request.body }}"]
    assert "scripts/check_docs_entry.py" in job
    assert check.SHOT_SOURCES in job
