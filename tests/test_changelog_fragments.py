"""Behavior of the changelog fragment tool.

The tool lives in ``scripts/changelog_fragments.py``. It runs by hand at release
time and nothing gates on it, so the cost of a mistake in it is not a red check:
it is a released ``CHANGELOG.md`` with an entry missing or with a section that
does not look like the ones above it. Both are silent, which is why the shape of
the assembled section is pinned here as hard as the collation is.

Loaded by file path, the same way ``test_prune_prereleases.py`` and
``test_check_changelog_entry.py`` load the other two stdlib-only tools in
``scripts/``. None of the three is on an import path.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "changelog_fragments.py"

_spec = importlib.util.spec_from_file_location("changelog_fragments", SCRIPT)
frag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(frag)


HEADER = (
    "# Changelog\n\nPreamble that no version heading is part of.\n\n## [Unreleased]\n"
)

# A real section from CHANGELOG.md, trimmed to two entries. The assembled output
# is compared against this shape rather than against a description of it.
BETA_6 = (
    "## [1.21.0-beta-6] - 2026-07-30\n"
    "\n"
    "### Added\n"
    '- **A keyboard shortcut for "Invert selection".** The field action shipped\n'
    "  with a right-click row and a working handler but with its shortcut written\n"
    "  into the source as an empty string.\n"
    "\n"
    "### Fixed\n"
    "- **Importing transforms adds the new alignment to the alignment menu.** Both\n"
    "  `Alignments > Import alignments` entries create an alignment and make it the\n"
    "  current one, and neither rebuilt the menus afterwards.\n"
)

# An older section below it, so `BETA_6` sits mid-file and carries the blank line
# that separates one section from the next. The assembled section is compared
# against it, and a section with nothing under it would not have that line.
OLDER = "## [1.20.0] - 2026-06-26\n\n### Changed\n- **Something older.** Text.\n"

EMPTY_CHANGELOG = HEADER + "\n" + BETA_6 + "\n" + OLDER


def write_fragment(directory, name, text):
    path = Path(directory) / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    """A changelog with an empty ``[Unreleased]`` and an empty fragment dir."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(EMPTY_CHANGELOG, encoding="utf-8")
    fragments = tmp_path / "changelog.d"
    fragments.mkdir()
    (fragments / "README.md").write_text("instructions\n", encoding="utf-8")
    return changelog, fragments


# --------------------------------------------------------------------------
# The no-op


def test_assembling_with_no_fragments_and_an_empty_unreleased_changes_nothing(repo):
    """The clean no-op: run it by mistake and the file is byte identical."""
    changelog, fragments = repo
    before = changelog.read_bytes()

    code = frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )

    assert code == 0
    assert changelog.read_bytes() == before


def test_the_readme_is_not_a_fragment(repo):
    """Otherwise the directory could never be empty and never no-op."""
    _, fragments = repo
    assert frag.fragment_paths(fragments) == []


def test_a_dotfile_is_not_a_fragment(repo):
    _, fragments = repo
    (fragments / ".DS_Store").write_text("", encoding="utf-8")
    assert frag.fragment_paths(fragments) == []


# --------------------------------------------------------------------------
# Collation


def test_two_authors_assemble_in_a_deterministic_order(repo):
    """Sorted by filename, so every machine and every checkout agrees.

    Written to the directory in the reverse of the expected order, so a run that
    trusted the filesystem's iteration order would come out backwards here.
    """
    changelog, fragments = repo
    write_fragment(
        fragments, "zoe-branch-ffffff.fixed.md", "- **Zoe's entry.** Text.\n"
    )
    write_fragment(
        fragments, "amy-branch-000000.fixed.md", "- **Amy's entry.** Text.\n"
    )

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )
    text = changelog.read_text(encoding="utf-8")

    assert text.index("Amy's entry") < text.index("Zoe's entry")


def test_the_order_does_not_depend_on_the_write_order(tmp_path):
    """The same two fragments, created in both orders, give the same section."""
    outputs = []
    for order in (("a-1.fixed.md", "b-2.fixed.md"), ("b-2.fixed.md", "a-1.fixed.md")):
        directory = tmp_path / ("run-" + order[0])
        directory.mkdir()
        for name in order:
            write_fragment(directory, name, f"- **{name}.** Text.\n")
        by_category = frag.categorize(frag.fragment_paths(directory))
        outputs.append(
            frag.assemble_text(EMPTY_CHANGELOG, "1.0.0", "2026-08-01", by_category)
        )
    assert outputs[0] == outputs[1]


def test_categories_land_under_their_headings_in_the_files_order(repo):
    """Added, Changed, Fixed, Removed, whatever order the fragments arrive in."""
    changelog, fragments = repo
    for category in ("removed", "fixed", "changed", "added"):
        write_fragment(
            fragments, f"x-{category}.{category}.md", f"- **{category} entry.** Text.\n"
        )

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )
    text = changelog.read_text(encoding="utf-8")

    positions = [
        text.index(f"### {h}") for h in ("Added", "Changed", "Fixed", "Removed")
    ]
    assert positions == sorted(positions)


def test_a_category_with_no_fragments_gets_no_heading(repo):
    changelog, fragments = repo
    write_fragment(fragments, "only-one-aaa.fixed.md", "- **One.** Text.\n")

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )
    text = changelog.read_text(encoding="utf-8")
    new_section = text.split("## [1.21.0-beta-7]")[1].split("## [1.21.0-beta-6]")[0]

    assert "### Fixed" in new_section
    assert "### Added" not in new_section


def test_entries_already_under_unreleased_are_carried_into_the_release(repo):
    """The reason the section is merged rather than built from fragments alone.

    Entries written before a tag and merged after it are parked under
    ``[Unreleased]`` by hand. An assembler that read only the directory would
    leave them there and cut a release that does not mention them.
    """
    changelog, fragments = repo
    changelog.write_text(
        HEADER + "\n### Fixed\n- **Parked by hand.** Text.\n\n" + BETA_6 + "\n" + OLDER,
        encoding="utf-8",
    )
    write_fragment(
        fragments, "from-a-branch-abc.fixed.md", "- **From a fragment.** Text.\n"
    )

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )
    text = changelog.read_text(encoding="utf-8")

    assert "Parked by hand" in text
    # The hand-written entry was there first and stays first, so assembling
    # twice in a row cannot reorder what the first pass produced.
    assert text.index("Parked by hand") < text.index("From a fragment")
    # And it is no longer under [Unreleased].
    unreleased = text.split("## [Unreleased]")[1].split("## [1.21.0-beta-7]")[0]
    assert unreleased.strip() == ""


def test_an_unreleased_section_with_entries_assembles_without_any_fragments(repo):
    """The no-op is "nothing to collate", not "no fragments"."""
    changelog, fragments = repo
    changelog.write_text(
        HEADER + "\n### Fixed\n- **Parked by hand.** Text.\n\n" + BETA_6 + "\n" + OLDER,
        encoding="utf-8",
    )

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )

    assert "## [1.21.0-beta-7] - 2026-08-01" in changelog.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The shape of the assembled section


def test_the_assembled_section_has_the_same_shape_as_the_one_below_it(repo):
    """Compared structurally against the real 1.21.0-beta-6 section.

    The comparison is on the sequence of line kinds, not on the prose: heading,
    blank, bucket, bullet lines, blank, bucket, bullet lines, blank. That is the
    only thing an assembler can get wrong, and reading it back off the existing
    section means the expectation cannot drift from the file.
    """
    changelog, fragments = repo
    write_fragment(
        fragments,
        "a-shortcut-000.added.md",
        '- **A keyboard shortcut for "Invert selection".** The field action shipped\n'
        "  with a right-click row and a working handler but with its shortcut written\n"
        "  into the source as an empty string.\n",
    )
    write_fragment(
        fragments,
        "b-transforms-111.fixed.md",
        "- **Importing transforms adds the new alignment to the alignment menu.** Both\n"
        "  `Alignments > Import alignments` entries create an alignment and make it the\n"
        "  current one, and neither rebuilt the menus afterwards.\n",
    )

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )
    text = changelog.read_text(encoding="utf-8")

    def kinds(section):
        out = []
        for line in section.splitlines():
            if line.startswith("## "):
                out.append("version")
            elif line.startswith("### "):
                out.append("bucket")
            elif line.startswith("- "):
                out.append("bullet")
            elif not line.strip():
                out.append("blank")
            else:
                out.append("continuation")
        return out

    # Both sections read back out of the same assembled file, so the expectation
    # cannot drift from what the file actually contains.
    assembled = (
        "## [1.21.0-beta-7]"
        + text.split("## [1.21.0-beta-7]")[1].split("## [1.21.0-beta-6]")[0]
    )
    existing = (
        "## [1.21.0-beta-6]"
        + text.split("## [1.21.0-beta-6]")[1].split("## [1.20.0]")[0]
    )

    assert kinds(assembled) == kinds(existing)


def test_the_version_heading_matches_the_files_format(repo):
    changelog, fragments = repo
    write_fragment(fragments, "one-aaa.fixed.md", "- **One.** Text.\n")

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )

    assert "## [1.21.0-beta-7] - 2026-08-01\n" in changelog.read_text(encoding="utf-8")


def test_a_multi_paragraph_fragment_survives_byte_for_byte(repo):
    """The tool concatenates and does not reformat. That is what keeps the voice.

    A fragment format that could only carry one line would satisfy the tooling
    and lose the thing that makes the file worth reading.
    """
    changelog, fragments = repo
    entry = (
        "- **A lead sentence naming the user-visible effect.** Then the mechanism,\n"
        "  hard-wrapped at 80 columns with a two-space continuation indent, running\n"
        "  to as many sentences as the mechanism needs.\n"
        "\n"
        "  A second paragraph, indented the same way, so the bullet stays one list\n"
        "  item.\n"
    )
    write_fragment(fragments, "prose-aaa.changed.md", entry)

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )

    assert entry.rstrip("\n") in changelog.read_text(encoding="utf-8")


def test_the_file_outside_the_new_section_is_untouched(repo):
    changelog, fragments = repo
    write_fragment(fragments, "one-aaa.fixed.md", "- **One.** Text.\n")

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )
    text = changelog.read_text(encoding="utf-8")

    assert text.startswith(HEADER)
    assert text.endswith("\n" + BETA_6 + "\n" + OLDER)


# --------------------------------------------------------------------------
# Consuming the fragments


def test_assembling_removes_the_fragments_it_consumed(repo):
    changelog, fragments = repo
    path = write_fragment(fragments, "one-aaa.fixed.md", "- **One.** Text.\n")

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
        ]
    )

    assert not path.exists()
    assert (fragments / "README.md").exists()


def test_a_dry_run_writes_nothing_and_keeps_the_fragments(repo, capsys):
    changelog, fragments = repo
    path = write_fragment(fragments, "one-aaa.fixed.md", "- **One.** Text.\n")
    before = changelog.read_bytes()

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "1.21.0-beta-7",
            "--date",
            "2026-08-01",
            "--dry-run",
        ]
    )

    assert changelog.read_bytes() == before
    assert path.exists()
    assert "## [1.21.0-beta-7] - 2026-08-01" in capsys.readouterr().out


def test_assembling_needs_no_tag_to_exist(repo):
    """The version is an argument. Nothing here reads git at all.

    Requiring a tag is what put eight entries in a build that does not contain
    them: the entries were written first and the tag arrived in between.
    """
    changelog, fragments = repo
    write_fragment(fragments, "one-aaa.fixed.md", "- **One.** Text.\n")

    frag.main(
        [
            "--dir",
            str(fragments),
            "assemble",
            "--changelog",
            str(changelog),
            "99.99.99",
            "--date",
            "2026-08-01",
        ]
    )

    assert "## [99.99.99] - 2026-08-01" in changelog.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Errors an author can fix


def test_an_unreadable_fragment_name_is_an_error_not_a_skip(repo):
    """A skipped fragment is a change that disappears from the record."""
    _, fragments = repo
    write_fragment(fragments, "no-category.md", "- **One.** Text.\n")

    with pytest.raises(frag.FragmentError) as excinfo:
        frag.categorize(frag.fragment_paths(fragments))

    assert "no-category.md" in str(excinfo.value)


def test_an_unknown_category_is_an_error(repo):
    _, fragments = repo
    write_fragment(fragments, "typo-aaa.fixt.md", "- **One.** Text.\n")

    with pytest.raises(frag.FragmentError):
        frag.categorize(frag.fragment_paths(fragments))


def test_a_fragment_that_is_not_a_list_item_is_an_error(repo):
    _, fragments = repo
    path = write_fragment(fragments, "prose-aaa.fixed.md", "Just some prose.\n")

    with pytest.raises(frag.FragmentError) as excinfo:
        frag.read_fragment(path)

    assert "list item" in str(excinfo.value)


def test_an_unindented_continuation_is_an_error(repo):
    _, fragments = repo
    path = write_fragment(
        fragments, "wrap-aaa.fixed.md", "- **One.** Text\nnot indented.\n"
    )

    with pytest.raises(frag.FragmentError):
        frag.read_fragment(path)


def test_an_empty_fragment_is_an_error(repo):
    _, fragments = repo
    path = write_fragment(fragments, "empty-aaa.fixed.md", "\n\n")

    with pytest.raises(frag.FragmentError):
        frag.read_fragment(path)


def test_a_changelog_with_no_unreleased_heading_is_an_error():
    with pytest.raises(frag.FragmentError) as excinfo:
        frag.split_unreleased("# Changelog\n\n## [1.0.0] - 2026-01-01\n")

    assert "[Unreleased]" in str(excinfo.value)


def test_the_cli_reports_an_error_and_exits_nonzero(repo, capsys):
    _, fragments = repo
    write_fragment(fragments, "no-category.md", "- **One.** Text.\n")

    code = frag.main(["--dir", str(fragments), "list"])

    assert code == 1
    assert "error:" in capsys.readouterr().err


# --------------------------------------------------------------------------
# Creating a fragment


def test_new_writes_a_template_and_prints_the_path(tmp_path, capsys):
    directory = tmp_path / "changelog.d"

    code = frag.main(["--dir", str(directory), "new", "fixed", "--slug", "a-bug"])

    assert code == 0
    printed = capsys.readouterr().out.strip()
    path = Path(printed)
    assert path.exists()
    assert path.name.startswith("a-bug-")
    assert path.name.endswith(".fixed.md")
    # The template is a valid fragment, so an author who edits nothing still
    # produces something the assembler accepts rather than an error at cut time.
    assert frag.read_fragment(path)


def test_two_authors_on_the_same_branch_name_get_different_files(tmp_path):
    """The random suffix, which is the point of it.

    Two open pull requests cannot come from the same branch of the same
    repository, but two people working from separate clones can pick the same
    branch name for the same bug, and that is a both-added collision again.
    """
    directory = tmp_path / "changelog.d"
    names = set()
    for _ in range(20):
        frag.main(["--dir", str(directory), "new", "fixed", "--slug", "same-branch"])
        names |= {p.name for p in frag.fragment_paths(directory)}
    assert len(names) == 20


def test_new_refuses_an_unknown_category(tmp_path):
    with pytest.raises(SystemExit):
        frag.main(["--dir", str(tmp_path), "new", "deprecated"])


def test_the_categories_are_the_headings_the_changelog_uses():
    """Pinned against the real file, so adding a category is a deliberate edit."""
    used = set()
    for line in (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            used.add(line[4:].strip())
    assert used <= set(frag.HEADINGS.values())
