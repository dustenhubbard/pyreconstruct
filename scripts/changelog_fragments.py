#!/usr/bin/env python3
"""Create and collate the one-file-per-change entries in ``changelog.d/``.

Seven pull requests conflicted in ``CHANGELOG.md`` and in nothing else in a
single afternoon. Every code file merged cleanly; every one of the seven was a
both-added collision on the same ``### Fixed`` heading, and each cost a rebase,
a full suite run and a continuous integration cycle. Separately,
``v1.21.0-beta-6`` was tagged and then eight pull requests merged whose entries
had been written before the tag existed. A rebase carries text where it was
written, so the entries landed inside the beta-6 section and the file claimed
they shipped in a build that does not contain them.

One file per change removes both. Nothing shares a file, so nothing collides,
and nothing is filed under a release until someone assembles the release.

A fragment is the markdown bullet itself, byte for byte as it will appear in
``CHANGELOG.md``. There is no intermediate format and no reflowing step: this
script concatenates, it does not rewrite. That is what keeps the file's voice
intact, because the voice is the author's own hard-wrapped prose and anything
that reformats it would flatten it.

The category lives in the filename, as the last dotted field before ``.md``::

    changelog.d/stale-color-render-9c1f04.fixed.md   ->  ### Fixed

The rest of the name is an identifier and nothing reads it. ``new`` builds it
from the current branch plus six random hex characters, so two authors cannot
land on the same path even when they picked the same branch name on two
different clones, which is the one case a branch-derived name alone does not
cover.

Usage::

    changelog_fragments.py new fixed [--slug SLUG]
    changelog_fragments.py list
    changelog_fragments.py assemble 1.21.0 [--date YYYY-MM-DD] [--dry-run]

``assemble`` takes the version as an argument and never consults ``git tag``,
so the section can be written and reviewed before anything is tagged, which is
the order the misfiled entries above were produced by getting backwards.

Stdlib only, so this runs with no project environment at all.
"""

import argparse
import datetime as _datetime
import os
import re
import sys
from pathlib import Path

FRAGMENT_DIR = "changelog.d"
CHANGELOG = "CHANGELOG.md"
UNRELEASED_HEADING = "## [Unreleased]"

# The four headings this file has ever used, in the order it uses them. Keep a
# Changelog also defines `Deprecated` and `Security`; neither has appeared here,
# and offering a category the file has never had invites an entry under a
# heading no reader expects. To add one, add it here and it works everywhere:
# `new` accepts it, `assemble` places it, and the README lists it.
CATEGORIES = ("added", "changed", "fixed", "removed")
HEADINGS = {name: name.capitalize() for name in CATEGORIES}

# `<anything>.<category>.md`. The category is the last dotted field, so a slug
# may itself contain dots without becoming ambiguous.
FRAGMENT_RE = re.compile(r"^(?P<slug>.+)\.(?P<category>[a-z]+)\.md$")

# Files that live in the directory and are not fragments.
NOT_FRAGMENTS = {"README.md"}

TEMPLATE = """- **A short lead sentence naming the user-visible effect, in bold, \
ending in a
  period.** Then the mechanism, in ordinary prose: what the code was doing, why
  that produced the effect above, and what it does now. Hard-wrap at 80
  columns and indent continuation lines by two spaces.

  A fragment may run to more than one paragraph. Indent the blank line's
  neighbors by two spaces and the bullet stays a single list item.
"""


class FragmentError(Exception):
    """Anything the author can fix by editing a filename or a file."""


# --------------------------------------------------------------------------
# Reading the directory


def fragment_paths(directory):
    """Every fragment in ``directory``, sorted by filename.

    Sorted by the raw filename rather than by modification time or by the order
    the filesystem hands them over, so two authors' fragments assemble in the
    same order on every machine and in every checkout.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.name in NOT_FRAGMENTS or path.name.startswith("."):
            continue
        if not path.is_file():
            continue
        found.append(path)
    return found


def categorize(paths):
    """``{category: [path, ...]}``, or raise on a name that says nothing.

    An unreadable name is an error rather than a skip. A fragment silently
    ignored at assembly time is a change that vanishes from the record, which is
    the failure this directory exists to prevent.
    """
    by_category = {name: [] for name in CATEGORIES}
    bad = []
    for path in paths:
        match = FRAGMENT_RE.match(path.name)
        if not match or match.group("category") not in CATEGORIES:
            bad.append(path.name)
            continue
        by_category[match.group("category")].append(path)
    if bad:
        raise FragmentError(
            "Not a fragment name: "
            + ", ".join(sorted(bad))
            + "\nExpected <slug>.<category>.md with category one of: "
            + " ".join(CATEGORIES)
        )
    return by_category


def read_fragment(path):
    """The bullet text, with surrounding blank lines removed.

    Validated only for the shape that makes it a list item, because everything
    else about it is prose and prose is not this script's business.
    """
    text = path.read_text(encoding="utf-8")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise FragmentError(f"{path} is empty.")
    if not lines[0].startswith("- "):
        raise FragmentError(
            f"{path} does not start with a markdown list item.\n"
            "The first line has to begin with '- '."
        )
    for line in lines[1:]:
        if line.strip() and not line.startswith(("  ", "- ")):
            raise FragmentError(
                f"{path}: continuation lines are indented by two spaces.\n"
                f"This one is not: {line!r}"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Reading and rewriting CHANGELOG.md


def split_unreleased(text):
    """``(head, body, tail)`` around the ``## [Unreleased]`` section.

    ``head`` ends with the heading itself, ``body`` is what currently sits under
    it, and ``tail`` starts at the next ``##``. The body matters: right now it
    is where entries written before a tag are parked, and an assembler that
    dropped them would reintroduce the problem from the other direction.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == UNRELEASED_HEADING:
            start = index
            break
    if start is None:
        raise FragmentError(
            f"{CHANGELOG} has no '{UNRELEASED_HEADING}' heading, so there is "
            "nowhere to put the new section."
        )
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[: start + 1], lines[start + 1 : end], lines[end:]


def bucketize(body):
    """``({heading: text}, [heading, ...])`` for the lines under a section."""
    buckets = {}
    order = []
    current = None
    for line in body:
        if line.startswith("### "):
            current = line[4:].strip()
            if current not in buckets:
                buckets[current] = []
                order.append(current)
        elif current is not None:
            buckets[current].append(line)
        elif line.strip():
            raise FragmentError(
                f"{UNRELEASED_HEADING} has text that is not under a '###' "
                f"heading: {line!r}"
            )
    trimmed = {}
    for heading, lines in buckets.items():
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            trimmed[heading] = "\n".join(lines)
    return trimmed, [h for h in order if h in trimmed]


def collate(existing, existing_order, by_category):
    """``[(heading, text), ...]`` in the order the file uses.

    Entries already under ``[Unreleased]`` come before fragments in the same
    bucket: they were written first, and keeping them first means assembling
    twice in a row cannot reorder what the first pass produced.
    """
    sections = []
    seen = set()
    for category in CATEGORIES:
        heading = HEADINGS[category]
        parts = []
        if heading in existing:
            parts.append(existing[heading])
        for path in by_category.get(category, []):
            parts.append(read_fragment(path))
        if parts:
            sections.append((heading, "\n".join(parts)))
        seen.add(heading)
    # A heading the file grew without this script knowing about it. Carried
    # through rather than dropped, because dropping it loses an entry.
    for heading in existing_order:
        if heading not in seen:
            sections.append((heading, existing[heading]))
    return sections


def render(version, date, sections):
    """The new section, shaped exactly like the ones already in the file."""
    out = [f"## [{version}] - {date}", ""]
    for heading, text in sections:
        out.append(f"### {heading}")
        out.extend(text.splitlines())
        out.append("")
    return out


def assemble_text(changelog_text, version, date, by_category):
    """The whole rewritten file, or ``None`` when there is nothing to do."""
    head, body, tail = split_unreleased(changelog_text)
    existing, existing_order = bucketize(body)
    sections = collate(existing, existing_order, by_category)
    if not sections:
        return None
    lines = head + [""] + render(version, date, sections) + tail
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Subcommands


def _slug_from_branch():
    """The current branch, flattened, or ``entry`` when there is no branch.

    Read from ``.git`` directly rather than by running ``git``, so the script
    keeps working where ``git`` is absent and so it never shells out.
    """
    head = Path(".git")
    if head.is_file():  # a worktree: `.git` is a file pointing at the real dir
        try:
            head = Path(head.read_text(encoding="utf-8").split(":", 1)[1].strip())
        except (OSError, IndexError):
            return "entry"
    head = head / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "entry"
    if not ref.startswith("ref: refs/heads/"):
        return "entry"
    name = ref[len("ref: refs/heads/") :]
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "entry"


def cmd_new(args):
    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    slug = args.slug or _slug_from_branch()
    slug = re.sub(r"[^a-z0-9.-]+", "-", slug.lower()).strip("-") or "entry"
    token = os.urandom(3).hex()
    path = directory / f"{slug}-{token}.{args.category}.md"
    if path.exists():  # a 1-in-16-million coincidence, not a reason to clobber
        raise FragmentError(f"{path} already exists.")
    path.write_text(TEMPLATE, encoding="utf-8")
    print(path)
    return 0


def cmd_list(args):
    by_category = categorize(fragment_paths(args.dir))
    total = 0
    for category in CATEGORIES:
        paths = by_category[category]
        if not paths:
            continue
        print(f"### {HEADINGS[category]}")
        for path in paths:
            print(f"  {path.name}")
        total += len(paths)
    print(f"{total} fragment(s) in {args.dir}/")
    return 0


def cmd_assemble(args):
    changelog = Path(args.changelog)
    by_category = categorize(fragment_paths(args.dir))
    consumed = [p for paths in by_category.values() for p in paths]

    date = args.date or _datetime.date.today().isoformat()
    text = changelog.read_text(encoding="utf-8")
    new_text = assemble_text(text, args.version, date, by_category)

    if new_text is None:
        print(
            f"Nothing to assemble: no fragments in {args.dir}/ and nothing "
            f"under {UNRELEASED_HEADING}. {changelog} is unchanged."
        )
        return 0

    if args.dry_run:
        head, body, tail = split_unreleased(text)
        existing, existing_order = bucketize(body)
        sys.stdout.write(
            "\n".join(
                render(
                    args.version,
                    date,
                    collate(existing, existing_order, by_category),
                )
            )
            + "\n"
        )
        print(f"(dry run: {changelog} not written, {len(consumed)} fragment(s) kept)")
        return 0

    changelog.write_text(new_text, encoding="utf-8")
    for path in consumed:
        path.unlink()
    print(
        f"Wrote ## [{args.version}] - {date} to {changelog} and removed "
        f"{len(consumed)} fragment(s)."
    )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=FRAGMENT_DIR,
        help=f"the fragment directory (default: {FRAGMENT_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="write an empty fragment and print its path")
    new.add_argument("category", choices=CATEGORIES)
    new.add_argument("--slug", help="defaults to the current branch name")
    new.set_defaults(func=cmd_new)

    listing = sub.add_parser("list", help="show the fragments waiting to be assembled")
    listing.set_defaults(func=cmd_list)

    assemble = sub.add_parser(
        "assemble", help="collate the fragments under a new version heading"
    )
    assemble.add_argument("version", help="for example 1.21.0 or 1.21.0-beta-7")
    assemble.add_argument("--date", help="ISO date for the heading (default: today)")
    assemble.add_argument("--changelog", default=CHANGELOG)
    assemble.add_argument(
        "--dry-run",
        action="store_true",
        help="print the section and change nothing",
    )
    assemble.set_defaults(func=cmd_assemble)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FragmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
