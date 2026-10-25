"""Behavior of the fragment voice check.

The check lives in ``scripts/check_fragment_voice.py`` and runs from
``.github/workflows/notes-checks.yml`` on the fragments a pull request adds or
edits. It is report-only, so a mistake in it costs nobody a merge, which is why
it needs tests: a report-only check that is quietly wrong is noise, and noise is
how a check gets ignored. Loaded by file path, the same way
``test_check_changelog_entry.py`` loads its script.

Pinned here: for each of the four rules it checks (1, 3, 5 and 6 of
``changelog.d/README.md``), one bullet that breaks the rule is a finding and one
that follows it is not; the shapes that look like a break and are not (a path
with dots in backticks, St. Patrick's Day, a second bullet in one file); the
README's own example passes; the changed-files mode reads only fragments that
exist; and the exit code follows ``BLOCKING``.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_fragment_voice.py"

_spec = importlib.util.spec_from_file_location("check_fragment_voice", SCRIPT)
voice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(voice)


def rules(bullet):
    """The rule numbers the check reports for one flattened bullet."""
    return sorted({rule for rule, _ in voice.check_bullet(bullet)})


GOOD = (
    "**When a Save at close fails, the window and the series stay open.** Free "
    "space or fix the file, then save or close again."
)


def test_the_readme_example_passes():
    assert rules(GOOD) == []


# Rule 1: one bold claim, at most one sentence after it.


def test_rule_1_three_sentences_is_a_finding():
    bullet = (
        "**The scale bar is thinner.** Its tick labels are below the bar. "
        "They are legible on light and dark images."
    )
    assert 1 in rules(bullet)


def test_rule_1_two_sentences_pass():
    assert 1 not in rules("**The scale bar is thinner.** Its tick labels are below the bar.")


def test_rule_1_a_bullet_that_does_not_open_bold_is_a_finding():
    assert 1 in rules("The scale bar is thinner. Its tick labels are below the bar.")


def test_rule_1_a_two_sentence_bold_claim_is_a_finding():
    assert 1 in rules("**The scale bar is thinner. Its labels moved.** They are legible now.")


def test_rule_1_a_semicolon_is_not_a_sentence_break():
    bullet = (
        "**Help ▸ What's new in PyReconstruct Dev shows the latest stable notes.** A "
        "nightly has no notes of its own; the dialog shows the newest stable section."
    )
    assert rules(bullet) == []


# Rule 3: no "Before," sentence.


def test_rule_3_before_sentence_is_a_finding():
    bullet = "**Undo now reverses an alignment rename.** Before, undo left the new name on every section."
    assert 3 in rules(bullet)


def test_rule_3_no_longer_in_the_claim_passes():
    bullet = "**Renaming an object keeps its alignment.** It no longer resets to the series alignment."
    assert 3 not in rules(bullet)


def test_rule_3_before_inside_a_sentence_is_not_the_form():
    bullet = "**Old flags keep the same ID on every open.** Each open gave them a new one before."
    assert 3 not in rules(bullet)


# Rule 5: "the app".


def test_rule_5_the_app_is_a_finding():
    assert 5 in rules("**The app icon changes for the holidays.** PyReconstruct Dev keeps its badge.")


def test_rule_5_pyreconstruct_passes():
    assert 5 not in rules("**PyReconstruct has a new icon.** PyReconstruct Dev keeps its badge.")


def test_rule_5_does_not_match_a_longer_word():
    assert 5 not in rules("**The application menu lists the series.** Pick one to open it.")


# Rule 6: one menu-path form.


@pytest.mark.parametrize(
    "bullet",
    [
        # ">" between the items
        "**The scale bar is thinner.** Series > Options > View sets its thickness.",
        # backticked items joined by ">"
        "**Help > What's new shows the stable notes.** Open `Help` > `What's new`.",
        # the whole path in backticks
        "**Backup Settings has a checkbox.** Check it under `File ▸ Backup ▸ Settings`.",
        # backticked items joined by the separator
        "**Save as follows the folder's case rule.** Use `File` ▸ `Save as`.",
        # "..." after an item
        "**Choose how a selected trace looks.** It is in Series ▸ Options... ▸ View.",
        # a lone backticked item written the old way
        "**Edit image source saves the name.** `Edit image source...` keeps it.",
    ],
)
def test_rule_6_each_old_form_is_a_finding(bullet):
    assert 6 in rules(bullet)


def test_rule_6_the_house_form_passes():
    bullet = "**The scale bar is thinner.** Series ▸ Options ▸ View sets its thickness."
    assert rules(bullet) == []


def test_rule_6_code_in_backticks_is_not_a_menu_path():
    bullet = (
        "**A zarr image whose name has a backslash now shows on macOS and Linux.** "
        "An image such as `a\\b.png` showed as missing, and `crop_log.txt` names it."
    )
    assert rules(bullet) == []


# Shapes that look like a break and are not.


def test_dots_in_code_and_an_abbreviation_are_not_sentences():
    bullet = (
        "**Images named like `a.b.c.png` open on St. Patrick's Day.** "
        "Nothing else changes."
    )
    assert rules(bullet) == []


def test_each_bullet_in_a_file_is_checked_on_its_own_line(tmp_path):
    fragment = tmp_path / "two-abc123.changed.md"
    fragment.write_text(
        "- **The scale bar is 15 pixels thick by default.** A thickness you saved\n"
        "  is kept.\n"
        "- **The Scale Bar group is easier to read.** It is in `Series > Options`.\n",
        encoding="utf-8",
    )
    assert [(line, rule) for line, rule, _ in voice.check_file(fragment)] == [(3, 6), (3, 6)]


def test_a_hard_wrapped_bullet_is_read_as_one(tmp_path):
    fragment = tmp_path / "wrap-abc123.fixed.md"
    fragment.write_text(
        "- **When a Save at close fails, the window and the series stay open.** Free\n"
        "  space or fix the file, then save or close again.\n",
        encoding="utf-8",
    )
    assert voice.check_file(fragment) == []


def test_every_fragment_waiting_on_main_passes():
    """The rules apply to new fragments; the ones waiting today already follow them."""
    waiting = ROOT / voice.FRAGMENT_DIR
    findings = [
        f"{path.name}:{line}: rule {rule}: {message}"
        for path in sorted(waiting.glob("*.md"))
        if path.name not in voice.NOT_FRAGMENTS
        for line, rule, message in voice.check_file(path)
    ]
    assert not findings, "\n".join(findings)


# The command line.


def test_changed_files_mode_reads_only_fragments_that_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "changelog.d").mkdir()
    bad = tmp_path / "changelog.d" / "bad-abc123.fixed.md"
    bad.write_text("- **Undo works.** Before, it did not.\n", encoding="utf-8")
    listed = tmp_path / "changed.txt"
    listed.write_text(
        "changelog.d/bad-abc123.fixed.md\n"
        "changelog.d/gone-abc123.fixed.md\n"  # deleted in this change
        "changelog.d/README.md\n"
        "PyReconstruct/modules/datatypes/series.py\n",
        encoding="utf-8",
    )
    status = voice.main(["--changed-files", str(listed)])
    out = capsys.readouterr().out
    assert "changelog.d/bad-abc123.fixed.md:1: rule 3:" in out
    assert "gone-abc123" not in out
    assert status == 0  # report-only


def test_exit_code_follows_blocking(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad-abc123.fixed.md"
    bad.write_text("- **Undo works.** Before, it did not.\n", encoding="utf-8")
    assert voice.main([str(bad)]) == 0
    assert "::warning " in capsys.readouterr().out
    monkeypatch.setattr(voice, "BLOCKING", True)
    assert voice.main([str(bad)]) == 1
    assert "::error " in capsys.readouterr().out


def test_a_clean_fragment_exits_zero(tmp_path, capsys):
    good = tmp_path / "good-abc123.fixed.md"
    good.write_text(f"- {GOOD}\n", encoding="utf-8")
    assert voice.main([str(good)]) == 0
    assert "fragment voice: ok" in capsys.readouterr().out
