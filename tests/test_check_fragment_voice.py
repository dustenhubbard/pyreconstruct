"""Behavior of the fragment voice check.

The check lives in ``scripts/check_fragment_voice.py`` and runs from
``.github/workflows/notes-checks.yml`` on the fragments a pull request adds or
edits. It is report-only, so a mistake in it costs nobody a merge, which is why
it needs tests: a report-only check that is quietly wrong is noise, and noise is
how a check gets ignored. Loaded by file path, the same way
``test_check_changelog_entry.py`` loads its script.

Pinned here: for each of the four rules it checks (1, 3, 5 and 6 of
``changelog.d/README.md``), one bullet that breaks the rule is a finding and one
that follows it is not; the shapes that look like a break and are not (code and
file names in backticks, a comparison, St. Patrick's Day, a second bullet in one
file); the README's own example passes; the changed-files mode reads only
fragments that exist; a fragment that is not UTF-8 is reported, not a crash; and
the exit code follows ``BLOCKING``. Every case is literal text written here: no
test reads the repository's own ``changelog.d``, since the check is report-only
and a test over the live directory would make its findings fail the suite.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_fragment_voice.py"

_spec = importlib.util.spec_from_file_location("check_fragment_voice", SCRIPT)
voice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(voice)


# The menus every rule test runs against: a fixed set written here, so no test
# result depends on how menubar.py or context_menu_list.py is written. The
# reader itself is tested on inline source further down.
PINNED_ROOTS = frozenset({
    "File", "Edit", "Series", "Section", "Lists", "Alignments", "Autosegment",
    "View", "Help", "Trace", "Object", "Ztrace", "3D",
})
PINNED_LABELS = PINNED_ROOTS | {
    "New series", "Options", "Brightness/contrast", "Images", "Export meshes",
}


@pytest.fixture(autouse=True)
def pinned_menus(monkeypatch):
    """Rule tests see PINNED_ROOTS and PINNED_LABELS, never the live menu files."""
    monkeypatch.setattr(
        voice, "_MENUS", (PINNED_ROOTS, frozenset(label.lower() for label in PINNED_LABELS))
    )


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


def test_rule_1_a_second_bold_run_is_a_finding():
    bullet = "**The scale bar is thinner.** **Its tick labels are below the bar.**"
    assert voice.check_bullet(bullet) == [
        (1, "a second bold run follows the claim; one bold claim, then plain text")
    ]


def test_rule_1_bold_inside_code_is_not_a_second_claim():
    assert rules("**The field redraws faster.** A name such as `**x**` still opens.") == []


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
        # the whole path in backticks, with ">" and "..."
        "**The scale bar is thinner.** `Series > Options... > View` sets its thickness.",
        # backticked items joined by the separator
        "**Save as follows the folder's case rule.** Use `File` ▸ `Save as`.",
        # "..." after an item, before the next separator
        "**Choose how a selected trace looks.** It is in Series ▸ Options... ▸ View.",
        # "..." on the last item
        "**Close is the right size in dark dialogs.** Help ▸ View log file... shows it.",
        # a lone backticked item written the old way
        "**Edit image source saves the name.** `Edit image source...` keeps it.",
    ],
)
def test_rule_6_each_old_form_is_a_finding(bullet):
    assert 6 in rules(bullet)


def test_rule_6_backticked_items_joined_by_gt_are_two_findings():
    bullet = "**Help > What's new shows the stable notes.** Open `Help` > `What's new`."
    assert [rule for rule, _ in voice.check_bullet(bullet)] == [6, 6]
    assert [m.split(";")[0] for _, m in voice.check_bullet(bullet)] == [
        'menu path uses ">"',
        "menu path in backticks",
    ]


def test_rule_6_the_house_form_passes():
    bullet = "**The scale bar is thinner.** Series ▸ Options ▸ View sets its thickness."
    assert rules(bullet) == []


@pytest.mark.parametrize(
    "bullet",
    [
        # a comparison is not a menu path
        "**The scale bar is thinner.** A value such as `15 > 10` is accepted.",
        "**Zoom steps are larger.** A step where new > old is kept.",
        # dots in a file name are not a menu item's "..."
        "**Image names are preserved.** A file named `a...b.png` opens normally.",
        # code and file names in backticks
        (
            "**A zarr image whose name has a backslash now shows on macOS and Linux.** "
            "An image such as `a\\b.png` showed as missing, and `crop_log.txt` names it."
        ),
        # a backticked option or setting name, with no separator and no "..."
        "**The scale bar follows the zoom.** It is limited to `Scale bar size`.",
        # a key and an environment variable
        "**The 3D scene opens on Wayland.** It works without `QT_QPA_PLATFORM=xcb` or `B`.",
        # alphabetic comparisons: no item is a menu
        "**The view is clearer.** A value such as `A > B` is accepted.",
        "**The view is clearer.** A step where new > Old is kept.",
        # comparisons that happen to hold a menu word
        "**The view is clearer.** It follows the View > 3 rule.",
        "**The view is clearer.** Edit > 5 traces in one pass.",
        "**The view is clearer.** A filter accepts `trace > 5`.",
        # ">" with a menu word that is not the whole first item
        "**The scale bar is thinner.** The Series > Options page sets it.",
    ],
)
def test_rule_6_ordinary_code_and_comparisons_pass(bullet):
    assert rules(bullet) == []


@pytest.mark.parametrize(
    "bullet, expected",
    [
        # items with a slash, a hyphen, a leading digit; the field context menu
        ("**The view is clearer.** Open `Edit ▸ Brightness/contrast`.", ["in backticks"]),
        ("**The view is clearer.** Open `View ▸ Show z-traces`.", ["in backticks"]),
        ("**The view is clearer.** Open `Series ▸ 3D ▸ Load 3D scene`.", ["in backticks"]),
        ("**The view is clearer.** Open Series ▸ Brightness/contrast profiles...", ['"..."']),
        ("**Traces keep their hosts.** Right-click and choose `Trace` > `Set hosts`.", ['">"', "in backticks"]),
        # with ▸ a submenu name is enough; with ">" the lone item still shows
        ("**A 4D zarr opens.** `New series` ▸ `From neuroglancer zarr...` reads it.", ["in backticks", '"..."']),
        ("**A 4D zarr opens.** `New series` > `From neuroglancer zarr...` reads it.", ["in backticks", '"..."']),
        # a ">" path whose items start with a digit then a letter
        ("**Meshes export.** Series > 3D > Export meshes writes them.", ['">"']),
    ],
)
def test_rule_6_real_menu_labels_are_recognized(bullet, expected):
    findings = [m for r, m in voice.check_bullet(bullet) if r == 6]
    assert len(findings) == len(expected), findings
    for message, marker in zip(findings, expected):
        assert marker in message, (message, marker)


# The menu reader. Checked on small inline sources, not on the live menubar, so
# an equivalent rewrite of the menu files cannot fail this suite.

MENU_SOURCE = '''
def return_file_menu(self):
    return {
        "text": "File",
        "opts": [("open_act", "Open..."), {"text": "New series", "opts": []}],
    }

context_menu_list = [{"text": "Trace", "opts": []}, {"text": "View", "opts": []}]
'''


def test_menu_reader_tells_roots_from_submenus(tmp_path):
    source = tmp_path / "menubar.py"
    source.write_text(MENU_SOURCE, encoding="utf-8")
    roots, labels = voice.menu_labels(files=(source,))
    assert roots == {"File", "Trace", "View"}
    assert labels == {"File", "New series", "Trace", "View"}


def test_menu_reader_falls_back_without_files_or_labels(tmp_path):
    assert voice.menu_labels(files=()) == (voice.FALLBACK_ROOTS, voice.FALLBACK_LABELS)
    plain = tmp_path / "plain.py"
    plain.write_text("x = 1\n", encoding="utf-8")
    assert voice.menu_labels(files=(plain,)) == (voice.FALLBACK_ROOTS, voice.FALLBACK_LABELS)


@pytest.mark.parametrize(
    "content",
    [
        b"def broken(:\n",  # a syntax error
        b'# coding: latin-1\nmenu = {"text": "File", "tip": "caf\xe9"}\n',  # not UTF-8
    ],
)
def test_menu_reader_falls_back_when_a_menu_file_cannot_be_read(tmp_path, content):
    bad = tmp_path / "menubar.py"
    bad.write_bytes(content)
    assert voice.menu_labels(files=(bad,)) == (voice.FALLBACK_ROOTS, voice.FALLBACK_LABELS)


def test_an_unreadable_menu_file_keeps_the_step_report_only(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "menubar.py"
    bad.write_bytes(b"def broken(:\n")
    monkeypatch.setattr(voice, "MENU_FILES", (bad,))
    monkeypatch.setattr(voice, "_MENUS", None)
    good = tmp_path / "good-abc123.fixed.md"
    good.write_text(f"- {GOOD}\n", encoding="utf-8")
    assert voice.main([str(good)]) == 0
    assert "fragment voice: ok" in capsys.readouterr().out
    monkeypatch.setattr(voice, "_MENUS", None)
    assert rules("**Help > What's new shows the notes.** Open it.") == [6]  # the fallback still knows Help


def test_the_live_menu_files_yield_some_labels():
    roots, labels = voice.menu_labels()
    assert roots and labels  # a soft check: the fixed lists satisfy it too


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


def test_a_fragment_that_is_not_utf8_is_a_finding_not_a_crash(tmp_path):
    fragment = tmp_path / "cp1252-abc123.fixed.md"
    fragment.write_bytes(b"- **Undo works.** It keeps the user\x92s choice.\n")
    findings = voice.check_file(fragment)
    assert [(line, rule) for line, rule, _ in findings] == [(1, "read")]
    assert "UTF-8" in findings[0][2]


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


def test_an_unreadable_fragment_follows_blocking_too(tmp_path, monkeypatch, capsys):
    fragment = tmp_path / "cp1252-abc123.fixed.md"
    fragment.write_bytes(b"- **Undo works.** It keeps the user\x92s choice.\n")
    assert voice.main([str(fragment)]) == 0
    out = capsys.readouterr().out
    assert f"{fragment}:1: not read:" in out and "::warning " in out
    monkeypatch.setattr(voice, "BLOCKING", True)
    assert voice.main([str(fragment)]) == 1


def test_a_clean_fragment_exits_zero(tmp_path, capsys):
    good = tmp_path / "good-abc123.fixed.md"
    good.write_text(f"- {GOOD}\n", encoding="utf-8")
    assert voice.main([str(good)]) == 0
    assert "fragment voice: ok" in capsys.readouterr().out
