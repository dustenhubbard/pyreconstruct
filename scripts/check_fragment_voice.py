#!/usr/bin/env python3
"""Report ``changelog.d`` fragments that break the mechanical voice rules.

``changelog.d/README.md`` states the rules a fragment follows. Four of them a
program can decide, and this checks those on the fragments a pull request adds
or edits; the others (internals, dev-cycle fixes, one topic per fragment) take a
reader. The numbers are the README's.

  1. One bold claim first, then plain text: at most one sentence after the
     claim, the claim itself one sentence, and no second bold run.
  3. No sentence opens with "Before,". A fix says what works now.
  5. "PyReconstruct", never "the app".
  6. A menu path is written one way: ``Series ▸ Options ▸ View``. Not ``>``
     between the items, not in backticks, and no "..." after an item.

Code spans are left out of the sentence count and the "Before," search, so a
path like ``a.b/c.png`` is not a sentence break. For rule 6 a menu path is text
in menu-path shape: capitalized items around a separator, an item ending in
"...", or a backticked capitalized item ending in "...". A comparison such as
``15 > 10`` or a file name such as ``a...b.png`` is not one.

Each finding is one line, ``path:line: rule N: what, and the fix``, plus a
GitHub annotation on that line of the fragment when run in Actions. A fragment
that cannot be read (not UTF-8, missing) is reported the same way instead of
stopping the run.

REPORT-ONLY. ``BLOCKING = False`` below means the exit code is 0 whatever is
found, and a finding arrives as a warning annotation and a job summary. Set
``BLOCKING = True`` to make it a gate: findings and unreadable fragments then
exit 1.

Usage::

    check_fragment_voice.py --changed-files FILE   # fragments a pull request touched
    check_fragment_voice.py PATH [PATH ...]        # these fragments, or a directory

``--changed-files`` is a newline-separated list of repository-relative paths;
fragments in it that no longer exist (deleted by an assemble) are skipped.
Stdlib only, so this runs with no project environment at all.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Flip to True to make this a gate: the exit code becomes 1 on a finding and
# the annotation level `error`.
BLOCKING = False

FRAGMENT_DIR = "changelog.d"
NOT_FRAGMENTS = {"README.md"}

MENU_SEP = "▸"
HOUSE_FORM = f"Series {MENU_SEP} Options {MENU_SEP} View"

CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# A sentence ends at . ! or ? followed by space or the end, except inside an
# ellipsis ("Options..." is not three sentences) and after the abbreviations a
# fragment plausibly uses (St. Patrick's Day).
SENTENCE_END_RE = re.compile(r"(?<![.])(?:[!?]|\.(?!\.))(?=\s|$)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
ABBREVIATIONS = ("St.", "Dr.", "Mr.", "Mrs.", "Ms.", "No.", "vs.", "e.g.", "i.e.")

# "Before," at the start of the text, of a sentence, or right after the bold claim.
BEFORE_RE = re.compile(r"(?:^|[.!?]\s+|\*\*\s*)Before,")

THE_APP_RE = re.compile(r"\bthe app\b", re.IGNORECASE)

# Rule 6 patterns. A menu item is a capitalized word run, optionally in
# backticks, optionally ending in "...": `Options`, Options..., `Save as...`.
ELLIPSIS = r"(?:\.\.\.|…)"
ITEM = r"[A-Z][A-Za-z0-9'’]*(?:[ ][A-Za-z0-9'’#{}]+)*"
# ">" as the separator between two items: a letter or an ellipsis before it,
# a capitalized item after it. "15 > 10" has digits on both sides.
GT_SEPARATOR_RE = re.compile(r"(?:[A-Za-z]|" + ELLIPSIS + r")`?\s>\s`?[A-Z]")
# A code span that is a menu path: a path with a separator inside the
# backticks, or a lone capitalized item ending in "...".
CODE_MENU_RE = re.compile(
    r"`" + ITEM + ELLIPSIS + r"?(?:\s*(?:▸|>)\s*" + ITEM + ELLIPSIS + r"?)+`"
    r"|`" + ITEM + ELLIPSIS + r"`"
)
# Backticked items joined by a separator: `File` ▸ `Save as`, `Help` > `What's new`.
CODE_AROUND_SEP_RE = re.compile(
    r"`\s*▸|▸\s*`|`" + ITEM + ELLIPSIS + r"?`\s>\s`" + ITEM
)
# "..." on a menu item: before a separator (Options... ▸ View), after one
# (▸ View log file...), or on a lone backticked item (CODE_MENU_RE above).
ELLIPSIS_ON_ITEM_RE = re.compile(
    ELLIPSIS + r"`?\s*(?:▸|>)\s`?[A-Z]"
    r"|(?:▸|(?:[A-Za-z]|" + ELLIPSIS + r")`?\s>)\s*`?" + ITEM + ELLIPSIS
)
CODE_ITEM_ELLIPSIS_RE = re.compile(r"`" + ITEM + ELLIPSIS + r"`")


def is_fragment(path):
    """Whether ``path`` is a fragment file under ``changelog.d``."""
    p = Path(path)
    return (
        len(p.parts) == 2
        and p.parts[0] == FRAGMENT_DIR
        and p.suffix == ".md"
        and p.name not in NOT_FRAGMENTS
    )


def bullets(text):
    """``(line number, flattened bullet text)`` for each top-level bullet.

    A bullet starts at a line beginning ``- `` in column 0; its hard-wrapped
    continuation lines are joined with single spaces. Lines before the first
    bullet are ignored.
    """
    found = []
    start, parts = None, []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("- "):
            if parts:
                found.append((start, " ".join(parts)))
            start, parts = number, [line[2:].strip()]
        elif parts and line.strip():
            parts.append(line.strip())
    if parts:
        found.append((start, " ".join(parts)))
    return found


def _without_code(text):
    return CODE_SPAN_RE.sub("CODE", text)


def _without_abbreviations(text):
    for abbr in ABBREVIATIONS:
        text = text.replace(abbr, abbr.replace(".", ""))
    return text


def sentence_count(text):
    """How many sentences ``text`` holds; a trailing fragment counts as one."""
    plain = _without_abbreviations(_without_code(text)).strip()
    if not plain:
        return 0
    ends = len(SENTENCE_END_RE.findall(plain))
    if not SENTENCE_END_RE.search(plain[-1:]):
        ends += 1
    return ends


def check_bullet(text):
    """The findings for one flattened bullet, as ``(rule, message)`` pairs."""
    findings = []

    # Rule 1: a bold claim first, one sentence, then plain text of at most one sentence.
    match = BOLD_RE.match(text)
    if not match:
        findings.append((1, "does not open with a bold claim; start with **what the user sees now.**"))
    else:
        claim = match.group(1)
        rest = text[match.end():]
        claim_sentences = sentence_count(claim)
        if claim_sentences > 1:
            findings.append((1, f"the bold claim is {claim_sentences} sentences; make it one headline"))
        after = sentence_count(rest)
        if after > 1:
            findings.append((1, f"{after} sentences follow the bold claim; at most one may"))
        if BOLD_RE.search(_without_code(rest)):
            findings.append((1, "a second bold run follows the claim; one bold claim, then plain text"))

    # Rule 3: no "Before," sentence.
    if BEFORE_RE.search(_without_code(text)):
        findings.append((3, 'a sentence opens with "Before,"; say what works now, or put "no longer ..." in the claim'))

    # Rule 5: "the app".
    if THE_APP_RE.search(_without_code(text)):
        findings.append((5, 'says "the app"; write "PyReconstruct"'))

    # Rule 6: one menu-path form.
    if GT_SEPARATOR_RE.search(text):
        findings.append((6, f'menu path uses ">"; write it as {HOUSE_FORM}'))
    if CODE_MENU_RE.search(text) or CODE_AROUND_SEP_RE.search(text):
        findings.append((6, f"menu path in backticks; write it plain, {HOUSE_FORM}"))
    if ELLIPSIS_ON_ITEM_RE.search(text) or CODE_ITEM_ELLIPSIS_RE.search(text):
        findings.append((6, f'menu path ends an item with "..."; drop it, {HOUSE_FORM}'))

    return findings


def check_file(path):
    """``(line, rule, message)`` for each finding in the fragment at ``path``.

    A file that cannot be read or decoded is one finding on line 1 with the
    rule ``"read"``, so a bad byte in one fragment reports instead of stopping
    the run.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [(1, "read", f"could not be read as UTF-8 text ({exc}); save it as UTF-8")]
    results = []
    for line, bullet in bullets(text):
        for rule, message in check_bullet(bullet):
            results.append((line, rule, message))
    return results


def fragment_paths(args):
    """The fragments to check, from the paths given or the changed-files list."""
    paths = []
    if args.changed_files:
        listed = args.changed_files.read_text(encoding="utf-8").splitlines()
        for entry in listed:
            entry = entry.strip()
            if entry and is_fragment(entry) and Path(entry).exists():
                paths.append(Path(entry))
    for given in args.paths:
        p = Path(given)
        if p.is_dir():
            paths.extend(
                sorted(f for f in p.iterdir() if f.suffix == ".md" and f.name not in NOT_FRAGMENTS)
            )
        else:
            paths.append(p)
    return paths


def _rule_text(rule):
    return "not read" if rule == "read" else f"rule {rule}"


def _annotate(level, path, line, title, message):
    print(f"::{level} file={path},line={line},title={title}::{message}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="fragment files or a directory of them")
    parser.add_argument(
        "--changed-files",
        type=Path,
        help="a newline-separated list of changed paths; only fragments in it are read",
    )
    args = parser.parse_args(argv)

    paths = fragment_paths(args)
    findings = []
    for path in paths:
        for line, rule, message in check_file(path):
            findings.append((str(path), line, rule, message))

    for path, line, rule, message in findings:
        print(f"{path}:{line}: {_rule_text(rule)}: {message}")

    level = "error" if BLOCKING else "warning"
    title = "Fragment voice" if BLOCKING else "Fragment voice (report-only, not blocking)"
    for path, line, rule, message in findings:
        _annotate(level, path, line, title, f"{_rule_text(rule)}: {message}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and findings:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n\n")
            fh.write("Rules 1, 3, 5 and 6 of changelog.d/README.md, checked by script.\n\n```\n")
            for path, line, rule, message in findings:
                fh.write(f"{path}:{line}: {_rule_text(rule)}: {message}\n")
            fh.write("```\n")

    if not findings:
        print(f"fragment voice: ok ({len(paths)} fragment(s) read)")
        return 0
    print(f"fragment voice: {len(findings)} finding(s) in {len({f[0] for f in findings})} fragment(s)")
    return 1 if BLOCKING else 0


if __name__ == "__main__":
    sys.exit(main())
