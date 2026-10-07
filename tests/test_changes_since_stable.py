"""The since-stable section a nightly's release body opens with.

``scripts/changes_since_stable.py`` collates three sources into one section:
the ``changelog.d`` fragments, the entries under ``## [Unreleased]``, and any
release section already written into ``CHANGELOG.md`` above the last stable
(the notes for a stable land on ``main`` before its tag, and a nightly built in
that window carries them). The Dev app's ``Help > What's new`` links the
nightly's release page as the live changelog, so a change missing here is a
change the Dev reader never hears about.

Loaded by file path like the other stdlib-only tools in ``scripts/``.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "changes_since_stable.py"

_spec = importlib.util.spec_from_file_location("changes_since_stable", SCRIPT)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


CHANGELOG = """# Changelog

Preamble.

## [Unreleased]

### Fixed
- **Parked under Unreleased.** Written before
  the fragments existed.

## [1.23.0] - 2026-09-27

### Added
- **Shipped in the stable.**

## [1.22.3] - 2026-09-14

### Fixed
- **Shipped before that.**
"""

ADDED = (
    "- **A fragment waiting on main.** Hard-wrapped at eighty columns, with the\n"
    "  continuation indented by two spaces.\n"
)
FIXED = "- **A fix waiting on main.**\n"


def repo(tmp_path, changelog=CHANGELOG, fragments=None):
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "changelog.d").mkdir()
    for name, text in (fragments or {}).items():
        (tmp_path / "changelog.d" / name).write_text(text)
    return tmp_path


def section(root, stable="v1.23.0", repository="owner/repo"):
    return cs.changes_since_stable(
        (root / "CHANGELOG.md").read_text(), root / "changelog.d", stable, repository
    )


# ---- what goes in, and in what order -----------------------------------------
def test_fragments_and_unreleased_entries_make_one_section_in_the_files_order(tmp_path):
    root = repo(tmp_path, fragments={"a.added.md": ADDED, "b.fixed.md": FIXED})
    out = section(root)
    assert out == (
        "## Changes since [v1.23.0](https://github.com/owner/repo/releases/tag/v1.23.0)\n"
        "\n"
        "### Added\n"
        "- **A fragment waiting on main.** Hard-wrapped at eighty columns, with the "
        "continuation indented by two spaces.\n"
        "\n"
        "### Fixed\n"
        "- **Parked under Unreleased.** Written before the fragments existed.\n"
        "- **A fix waiting on main.**\n"
    )
    # nothing the stable already shipped
    assert "Shipped" not in out


def test_a_release_section_written_ahead_of_its_tag_is_since_the_stable(tmp_path):
    """Release prep assembles the fragments into ``## [1.24.0]`` before the tag
    exists. The last stable tag is still v1.23.0, so those entries are since
    it, and so is a beta's section above the stable; the stable's own section
    and the ones below it are not."""
    changelog = CHANGELOG.replace(
        "## [1.23.0] - 2026-09-27",
        "## [1.24.0] - 2026-10-08\n"
        "\n"
        "### Added\n"
        "- **Prepared for the next stable.** Written\n"
        "  before its tag.\n"
        "\n"
        "### Fixed\n"
        "- **A fix prepared for the next stable.**\n"
        "\n"
        "## [1.24.0-beta-1] - 2026-10-01\n"
        "\n"
        "### Added\n"
        "- **Shipped in a beta.**\n"
        "\n"
        "## [1.23.0] - 2026-09-27",
    )
    root = repo(tmp_path, changelog=changelog, fragments={"a.added.md": ADDED})
    out = section(root)
    assert out == (
        "## Changes since [v1.23.0](https://github.com/owner/repo/releases/tag/v1.23.0)\n"
        "\n"
        "### Added\n"
        "- **Shipped in a beta.**\n"
        "- **Prepared for the next stable.** Written before its tag.\n"
        "- **A fragment waiting on main.** Hard-wrapped at eighty columns, with the "
        "continuation indented by two spaces.\n"
        "\n"
        "### Fixed\n"
        "- **A fix prepared for the next stable.**\n"
        "- **Parked under Unreleased.** Written before the fragments existed.\n"
    )


def test_a_prepared_section_alone_is_still_a_section(tmp_path):
    """No fragments and nothing under Unreleased, which is exactly the state
    of main after release prep: the prepared section is the whole body."""
    changelog = CHANGELOG.replace(
        "### Fixed\n- **Parked under Unreleased.** Written before\n  the fragments existed.\n", ""
    ).replace(
        "## [1.23.0] - 2026-09-27",
        "## [1.24.0] - 2026-10-08\n\n### Fixed\n- **Prepared.**\n\n## [1.23.0] - 2026-09-27",
    )
    out = section(repo(tmp_path, changelog=changelog))
    assert "### Fixed\n- **Prepared.**\n" in out
    assert "Shipped" not in out


def test_nothing_since_the_stable_prints_nothing(tmp_path):
    changelog = CHANGELOG.replace(
        "### Fixed\n- **Parked under Unreleased.** Written before\n  the fragments existed.\n", ""
    )
    assert section(repo(tmp_path, changelog=changelog)) == ""


def test_without_a_stable_only_the_waiting_entries_are_printed(tmp_path):
    root = repo(tmp_path, fragments={"a.added.md": ADDED})
    out = section(root, stable="")
    assert out.startswith("## Changes since the last stable release\n\n### Added\n")
    assert "Shipped" not in out   # no stable to be above: no section counts as prepared
    assert section(root, stable="v1.23.0", repository="").startswith("## Changes since v1.23.0\n")


@pytest.mark.parametrize("below,above", [
    ("1.23.0", "1.24.0"),
    ("1.23.0", "1.23.1"),
    ("1.24.0-beta-1", "1.24.0"),   # a suffix sorts below its own release
    ("1.24.0rc1", "1.24.0"),
    ("v1.9.9", "v1.10.0"),         # numeric, not lexical
])
def test_version_key_orders_releases(below, above):
    assert cs.version_key(below) < cs.version_key(above)
    assert cs.version_key("Unreleased") is None


# ---- one line per item, structure kept ---------------------------------------
def test_nested_lists_code_blocks_and_tables_keep_their_lines(tmp_path):
    fragment = (
        "- **Import changes.**\n"
        "  Supported types:\n"
        "  - XML, which the old importer\n"
        "    also read\n"
        "  - JSON\n"
        "- **A command.** Run it as\n"
        "  ```sh\n"
        "  pyreconstruct --check-history\n"
        "    series.jser\n"
        "  ```\n"
        "  and read the\n"
        "  output.\n"
        "- **Shortcuts.**\n"
        "  | Key | Action |\n"
        "  | --- | --- |\n"
        "  | K | Knife |\n"
        "  > A quoted\n"
        "  line.\n"
    )
    root = repo(tmp_path, fragments={"a.changed.md": fragment})
    out = section(root)
    assert out.split("### Changed\n", 1)[1].split("\n### Fixed", 1)[0] == (
        "- **Import changes.** Supported types:\n"
        "  - XML, which the old importer also read\n"
        "  - JSON\n"
        "- **A command.** Run it as\n"
        "  ```sh\n"
        "  pyreconstruct --check-history\n"
        "    series.jser\n"
        "  ```\n"
        "  and read the output.\n"
        "- **Shortcuts.**\n"
        "  | Key | Action |\n"
        "  | --- | --- |\n"
        "  | K | Knife |\n"
        "  > A quoted line.\n"
    )


def test_a_fence_closes_only_on_its_own_kind_and_length(tmp_path):
    """A shorter fence, or one of the other character, inside a fenced block
    is content; closing on it would join the code lines that follow."""
    fragment = (
        "- **Fences.** Shown as\n"
        "  ~~~~\n"
        "  ```\n"
        "  one\n"
        "  two\n"
        "  ~~~\n"
        "  three\n"
        "  ~~~~\n"
        "  and after\n"
        "  it.\n"
    )
    out = section(repo(tmp_path, fragments={"a.added.md": fragment}))
    assert out.split("### Added\n", 1)[1].split("\n### Fixed", 1)[0] == (
        "- **Fences.** Shown as\n"
        "  ~~~~\n"
        "  ```\n"
        "  one\n"
        "  two\n"
        "  ~~~\n"
        "  three\n"
        "  ~~~~\n"
        "  and after it.\n"
    )


def test_a_second_paragraph_inside_a_bullet_stays_a_paragraph(tmp_path):
    fragment = (
        "- **Two paragraphs.** The first\n"
        "  one.\n"
        "\n"
        "  The second\n"
        "  one.\n"
    )
    out = section(repo(tmp_path, fragments={"a.added.md": fragment}))
    assert "- **Two paragraphs.** The first one.\n\n  The second one.\n" in out


# ---- the command ----------------------------------------------------------------
def test_main_prints_the_section_and_refuses_a_fragment_it_cannot_name(tmp_path, capsys):
    root = repo(tmp_path, fragments={"a.added.md": ADDED})
    args = ["--stable", "v1.23.0", "--repository", "owner/repo",
            "--changelog", str(root / "CHANGELOG.md"), "--dir", str(root / "changelog.d")]
    assert cs.main(args) == 0
    out = capsys.readouterr().out
    assert out.startswith("## Changes since [v1.23.0]")
    assert "A fragment waiting on main." in out

    (root / "changelog.d" / "no-category.md").write_text("- **Named wrong.**\n")
    assert cs.main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Not a fragment name" in captured.err
