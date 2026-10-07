#!/usr/bin/env python3
"""Print every change since the last stable release, for a nightly's release body.

A nightly is the last stable plus whatever has landed on ``main`` since, and
the since part lives in three places at once: the ``changelog.d/`` fragments
waiting to be assembled, anything parked under ``## [Unreleased]`` in
``CHANGELOG.md``, and a release section already written into ``CHANGELOG.md``
ahead of its tag (the notes for a stable are prepared and reviewed on ``main``
before the tag exists, and a nightly built in that window carries them). The
``Help > What's new`` dialog in the Dev app links the nightly's release page as
the live changelog, so that page has to carry all three.

This collates them with the same code the stable release uses
(``changelog_fragments.py``: the same buckets, the same heading order, entries
already in the file before fragments) and prints one section::

    ## Changes since [v1.23.0](https://github.com/owner/repo/releases/tag/v1.23.0)

    ### Added
    - **One bullet per change, on one line.** ...

Fragments are hard-wrapped at 80 columns with two-space continuation lines,
and a GitHub release body renders every newline as a line break, so a bullet's
wrapped prose is joined onto one line. Only prose is joined, and only where
nothing before it in the bullet could have changed what it is: a bullet's
paragraphs are joined from the top for as long as each one is plain prose
(see ``join_wrapped``), and from the first one that is not (a nested list,
code, a table, a heading, a quote, HTML), the rest of the bullet is left
exactly as written. Joining lines of one paragraph changes only line breaks,
so whatever Markdown goes in, the same structure comes out.

Prints nothing and exits 0 when there is nothing since the stable, so the
caller can test the output for emptiness. A fragment the assembler refuses (a
name that says nothing) is an error here, exit 1, and the caller decides what
a nightly does about it; the stable assembly still fails on it.

Usage::

    changes_since_stable.py --stable v1.23.0 --repository owner/repo
                            [--changelog CHANGELOG.md] [--dir changelog.d]

``--stable`` is the newest stable tag in the nightly's own history, as the
workflow finds it with ``git tag --merged``; an empty value means no stable
exists yet, and then only the fragments and ``[Unreleased]`` are printed under
a heading that names no tag. Stdlib only, like the assembler it imports.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import changelog_fragments as frag  # noqa: E402

# `## [1.24.0] - 2026-10-08`, as the assembler writes it; the dash may be an
# em dash in older sections, and the date is not needed here.
SECTION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]")

# A bulleted item with text, at the left margin, which is where every
# fragment's bullet starts. Nothing above it can hold it as content, since it
# ends any item or paragraph before it; an empty or numbered item can be a
# paragraph's lazy line instead. One space after the marker puts its text two
# columns in, where ``in_bullet`` expects it. A rule made of dashes or stars is
# not an item, though it starts like one.
ITEM_RE = re.compile(r"^[-*+] \S")
RULE_RE = re.compile(r"^([-*_])(?:[ \t]*\1){2,}[ \t]*$")
BULLET = "- "  # the bullet whose prose is joined: a dash, one space, text
INDENT = "  "  # where that bullet's text, and each wrapped line of it, starts

# The first character of a line of plain prose: one that cannot start a list,
# code, a heading, a rule, a quote, a table, HTML or a link definition, nor
# turn the line before into a heading or a table header. A letter; a number
# that is not a numbered item's; emphasis or code that opens a span; an
# opening bracket or quote. A line inside a paragraph may also start with
# ``[`` (a link definition cannot interrupt a paragraph, though a footnote's
# may), with an issue number (``#`` is a heading only with a space after it)
# or with punctuation.
PROSE_START_RE = re.compile(
    r"^(?:[^\W\d_]|\d+(?!\d|[.)](?:\s|$))|[*_]{1,2}[^\s*_]|`(?!``)|[(\"'“‘!])"
)
PROSE_INSIDE_RE = re.compile(rf"(?:{PROSE_START_RE.pattern[1:]}|\[(?!\^)|#\d|[).,;?/%&@])")


def is_prose(text, first):
    """Whether ``text`` (a line with its indentation removed) is plain prose,
    as the first line of a paragraph or as a line inside one. A line ending
    in a hard break (two spaces or a backslash) is not: joining would lose it."""
    pattern = PROSE_START_RE if first else PROSE_INSIDE_RE
    return bool(pattern.match(text)) and not text.endswith(("  ", "\\"))


def is_item(line):
    return bool(ITEM_RE.match(line)) and not RULE_RE.match(line)


def in_bullet(line):
    """Whether ``line`` is indented at least as far as a ``- `` bullet's text,
    and so belongs to the bullet above it whatever it is."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip()) >= len(INDENT)


def version_key(text):
    """A sortable key for ``X.Y.Z`` or ``X.Y.Z<suffix>``, or None.

    A suffix (``-beta-1``, ``rc1``) sorts below the plain release of the same
    three numbers, which is the one ordering fact this script needs: a beta
    written above the last stable is since it, and the stable itself is not.
    """
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(.*)$", text.strip())
    if not match:
        return None
    major, minor, patch, suffix = match.groups()
    suffix = suffix.lstrip("-.")
    return (int(major), int(minor), int(patch), 0 if suffix else 1, suffix)


def sections(changelog_text):
    """``[(version, [body lines]), ...]`` for every ``## [...]`` heading, in file order."""
    found = []
    current = None
    for line in changelog_text.splitlines():
        match = SECTION_RE.match(line)
        if match:
            current = (match.group("version"), [])
            found.append(current)
        elif line.startswith("## "):
            current = None
        elif current is not None:
            current[1].append(line)
    return found


def sections_since(changelog_text, stable):
    """The bodies of the release sections above ``stable``, oldest first.

    Oldest first so that, merged ahead of ``[Unreleased]`` and the fragments,
    every bucket reads in the order the changes landed. ``[Unreleased]`` is not
    among them: the assembler reads that one itself. Without a stable there is
    no line to be above, and nothing is returned.
    """
    floor = version_key(stable) if stable else None
    if floor is None:
        return []
    above = []
    for version, body in sections(changelog_text):
        key = version_key(version)
        if key is not None and key > floor:
            above.append(body)
    above.reverse()
    return above


def merge_buckets(bodies):
    """``bucketize`` several section bodies into one ``({heading: text}, [heading, ...])``."""
    merged = {}
    order = []
    for body in bodies:
        buckets, headings = frag.bucketize(body)
        for heading in headings:
            if heading not in merged:
                merged[heading] = []
                order.append(heading)
            merged[heading].append(buckets[heading])
    return {h: "\n".join(parts) for h, parts in merged.items()}, order


def join_wrapped(lines):
    """Each bullet's wrapped prose joined onto one line, and nothing else changed.

    A bullet here is a ``- `` item at the left margin with text on its first
    line, and every line after it indented as far as its text. Its
    paragraphs (runs of lines between blank ones) are joined from the top for
    as long as each is plain prose: every line indented two spaces, the width
    of ``- ``, and starting the way only prose can start (``is_prose``). Each
    joined paragraph has only plain paragraphs before it in its bullet, so it
    cannot be inside code or HTML, and a line of prose can neither start a
    block nor change the line before it. From the first paragraph that is not
    plain, the rest of the bullet is left as written. So is everything after a
    line indented less than a bullet's text that does not start a bullet: it
    may have ended the bullet above and opened code or HTML that runs on past
    it.
    """
    out = []
    at = 0
    while at < len(lines):
        line = lines[at]
        if not line.strip():
            out.append(line)
            at += 1
            continue
        if not is_item(line):
            out.extend(lines[at:])
            break
        end = at + 1
        while end < len(lines) and (not lines[end].strip() or in_bullet(lines[end])):
            end += 1
        # A paragraph that runs straight into a line outside the bullet may be
        # that line's: a table header, or a lazy line before a setext underline.
        runs_on = end < len(lines) and lines[end - 1].strip() and not is_item(lines[end])
        out.extend(join_bullet(lines[at:end], runs_on))
        at = end
    return out


def join_bullet(bullet, runs_on):
    """One bullet's lines, its leading plain paragraphs joined (``join_wrapped``)."""
    out = []
    at = 0
    while at < len(bullet):
        if not bullet[at].strip():
            out.append(bullet[at])
            at += 1
            continue
        end = at
        while end < len(bullet) and bullet[end].strip():
            end += 1
        paragraph = bullet[at:end]
        first = paragraph[0]
        lead = BULLET if at == 0 else INDENT
        plain = (
            first.startswith(lead)
            and is_prose(first[len(lead):], first=True)
            and all(
                line.startswith(INDENT) and is_prose(line[len(INDENT):], first=False)
                for line in paragraph[1:]
            )
            and not (end == len(bullet) and runs_on)
        )
        if not plain:
            out.extend(bullet[at:])
            break
        out.append(" ".join([first] + [line.strip() for line in paragraph[1:]]))
        at = end
    return out


def heading(stable, repository):
    if not stable:
        return "## Changes since the last stable release"
    if repository:
        return (
            f"## Changes since [{stable}]"
            f"(https://github.com/{repository}/releases/tag/{stable})"
        )
    return f"## Changes since {stable}"


def changes_since_stable(changelog_text, fragment_dir, stable, repository=None):
    """The whole section as text, or ``""`` when nothing has landed since the stable."""
    _head, unreleased, _tail = frag.split_unreleased(changelog_text)
    bodies = sections_since(changelog_text, stable) + [unreleased]
    existing, order = merge_buckets(bodies)
    by_category = frag.categorize(frag.fragment_paths(fragment_dir))
    collated = frag.collate(existing, order, by_category)
    if not collated:
        return ""
    out = [heading(stable, repository), ""]
    for bucket, text in collated:
        out.append(f"### {bucket}")
        out.extend(join_wrapped(text.splitlines()))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--stable", default="", help="the newest stable tag in this commit's history, or empty")
    parser.add_argument("--repository", default="", help="owner/repo, for the heading's link")
    parser.add_argument("--changelog", default=frag.CHANGELOG)
    parser.add_argument("--dir", default=frag.FRAGMENT_DIR, help="the fragment directory")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        text = Path(args.changelog).read_text(encoding="utf-8")
        sys.stdout.write(changes_since_stable(text, args.dir, args.stable, args.repository))
    except (OSError, frag.FragmentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
