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
and a GitHub release body renders every newline as a line break, so each
bullet's continuation lines are joined onto its first line. A nested list
item, a code block (fenced or indented), a heading, a rule, a table row, a
blockquote and an HTML block keep their own lines: joining those would flatten
a valid list into one run-on sentence, or code and headings into prose. A
second paragraph inside a bullet (after a blank line) stays a paragraph of its
own.

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

# Lines that keep their own line when wrapped prose around them is joined.
# A list item or a blockquote may still take a wrapped continuation (a lazy
# one, in CommonMark's word); a heading, a rule or setext underline, and a
# table row may not, since joining onto them changes what they are.
LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+|$)")
QUOTE_RE = re.compile(r"^\s*>")
STANDALONE_RE = re.compile(
    r"^\s*(?:#{1,6}(?:\s|$)|(?:-\s*){3,}$|(?:\*\s*){3,}$|(?:_\s*){3,}$|=+\s*$|\|)"
)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# The HTML blocks that may interrupt a paragraph (CommonMark 4.6, kinds 1, 2
# and 6), each with what ends it; an empty end is a blank line.
HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|"
    "colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|"
    "form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|"
    "menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|"
    "summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul"
)
HTML_STARTS = (
    (re.compile(r"^\s*<(?:script|pre|style|textarea)(?:\s|>|$)", re.I), "</"),
    (re.compile(r"^\s*<!--"), "-->"),
    (re.compile(rf"^\s*</?(?:{HTML_BLOCK_TAGS})(?:\s|/?>|$)", re.I), ""),
)


def indent_of(line):
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())


def html_block(line):
    """What ends the HTML block ``line`` opens, or None when it opens none."""
    for start, end in HTML_STARTS:
        if start.match(line):
            return end
    return None


def html_ends(end, line):
    if end == "</":
        return re.search(r"</(?:script|pre|style|textarea)>", line, re.I) is not None
    return not line.strip() if end == "" else end in line


def closes(fence, line):
    """Whether ``line`` closes a block opened by ``fence``: the same character,
    at least as many of it, and nothing else on the line (CommonMark 4.5)."""
    stripped = line.strip()
    return set(stripped) == {fence[0]} and len(stripped) >= len(fence)


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
    """Each bullet's continuation lines joined onto its first line.

    A continuation line is an indented line of prose. It joins onto the line
    before it when that line is prose too, or a list item or blockquote it
    wraps. Code passes through untouched: a fenced block until a fence of the
    opening kind and at least its length closes it, and an indented block (four
    columns past the list item it sits in, where a paragraph cannot run on into
    it) until a line indented less. So does an HTML block, until its end.
    """
    out = []
    joinable = False  # the line before may take a continuation
    fence = None  # the opening fence, inside a fenced block
    code_indent = None  # the indentation of an indented code block, inside one
    html_end = None  # what ends the HTML block, inside one
    items = []  # where each open list item's content starts, innermost last
    for line in lines:
        if fence is not None:
            out.append(line)
            if closes(fence, line):
                fence = None
            continue
        if html_end is not None:
            out.append(line)
            if html_ends(html_end, line):
                html_end = None
            continue
        indent = indent_of(line)
        if code_indent is not None:
            if not line.strip() or indent >= code_indent:
                out.append(line)
                continue
            code_indent = None
        if not line.strip():
            out.append(line)
            joinable = False
            continue
        if not joinable:
            # Not a run-on line, so its indentation says which item it is in.
            while items and indent < items[-1]:
                items.pop()
            code_at = (items[-1] if items else 0) + 4
            if indent >= code_at:
                code_indent = code_at
                out.append(line)
                continue
        opening = FENCE_RE.match(line)
        if opening:
            fence = opening.group(1)
            out.append(line)
            joinable = False
            continue
        end = html_block(line)
        if end is not None:
            out.append(line)
            joinable = False
            if not html_ends(end, line):
                html_end = end
            continue
        if STANDALONE_RE.match(line):
            out.append(line)
            joinable = False
            continue
        item = LIST_ITEM_RE.match(line.expandtabs(4))
        if item:
            marker, spaces = item.end(2), len(item.group(3))
            while items and indent < items[-1]:
                items.pop()
            items.append(marker + (spaces if 1 <= spaces <= 4 else 1))
        elif line.startswith("  ") and joinable and not QUOTE_RE.match(line):
            out[-1] = out[-1] + " " + line.strip()
            continue
        out.append(line)
        joinable = True
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
