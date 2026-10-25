#!/usr/bin/env python3
"""Report ``changelog.d`` fragments that break the mechanical voice rules.

The nightly release body is the fragments, concatenated. On October 17, 2026 it
ran to 72 bullets: twelve opened a sentence with "Before,", the longest ran six
sentences, two said "the app", and the menu paths came in four spellings
(``Series > Options... > View``, ``Series ▸ Options...``, backticked, plain).
Each fragment had been read on its own, and the shape of the set was nobody's
job. ``changelog.d/README.md`` now states the rules; this checks the four a
program can decide, on the fragments a pull request adds or edits.

  1. One bold claim first, at most one plain sentence after it: two sentences
     in all, and the bold claim is one sentence.
  3. No sentence opens with "Before,". A fix says what works now.
  5. "PyReconstruct", never "the app".
  6. A menu path is written one way: ``Series ▸ Options ▸ View``. Not ``>``
     between the items, not in backticks, and no "..." after an item.

The numbers are the rules' numbers in the README; 2, 4 and 7 (internals, dev-cycle
fixes, one topic per fragment) take a reader. Code spans are left out of the
sentence count and the "Before," search, so a path like ``a.b/c.png`` is not a
sentence break; a backticked menu path is still a finding under rule 6.

Each finding is one line, ``path:line: rule N: what, and the fix``, plus a
GitHub annotation on that line of the fragment when run in Actions.

REPORT-ONLY. ``BLOCKING = False`` below means the exit code is 0 whatever is
found, and a finding arrives as a warning annotation and a job summary. Set
``BLOCKING = True`` to make it a gate.

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
ELLIPSIS_RE = re.compile(r"\.\.\.|…")

CODE_SPAN_RE = re.compile(r"`[^`\n]*`")

# A sentence ends at . ! or ? followed by space or the end, except inside an
# ellipsis ("Options..." is not three sentences) and after the abbreviations a
# fragment plausibly uses (St. Patrick's Day).
SENTENCE_END_RE = re.compile(r"(?<![.])(?:[!?]|\.(?!\.))(?=\s|$)")
ABBREVIATIONS = ("St.", "Dr.", "Mr.", "Mrs.", "Ms.", "No.", "vs.", "e.g.", "i.e.")

# "Before," at the start of the text, of a sentence, or right after the bold claim.
BEFORE_RE = re.compile(r"(?:^|[.!?]\s+|\*\*\s*)Before,")

THE_APP_RE = re.compile(r"\bthe app\b", re.IGNORECASE)

# ">" used as a menu separator: whitespace on either side, or between two code
# spans. "->" and "=>" are not menu paths.
GT_SEPARATOR_RE = re.compile(r"(?<![-=])(?:\s>\s|`\s*>\s*`)")
# A code span that is a menu path: it holds a separator, or an item ends in "...".
CODE_MENU_RE = re.compile(r"`[^`\n]*(?:▸|\s>\s|\.\.\.|…)[^`\n]*`")
# A code span holding an ellipsis: a menu item written the old way.
CODE_ELLIPSIS_RE = re.compile(r"`[^`\n]*(?:\.\.\.|…)[^`\n]*`")
# Backticked items joined by the separator: `File` ▸ `Save as`.
CODE_AROUND_SEP_RE = re.compile(r"`\s*▸|▸\s*`")


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

    # Rule 1: a bold claim first, one sentence, and at most one sentence after it.
    match = re.match(r"\*\*(.+?)\*\*", text)
    if not match:
        findings.append((1, "does not open with a bold claim; start with **what the user sees now.**"))
        rest = text
    else:
        claim = match.group(1)
        rest = text[match.end():]
        claim_sentences = sentence_count(claim)
        if claim_sentences > 1:
            findings.append((1, f"the bold claim is {claim_sentences} sentences; make it one headline"))
        after = sentence_count(rest)
        if after > 1:
            findings.append((1, f"{after} sentences follow the bold claim; at most one may"))

    # Rule 3: no "Before," sentence.
    if BEFORE_RE.search(_without_code(text)):
        findings.append((3, 'a sentence opens with "Before,"; say what works now, or put "no longer ..." in the claim'))

    # Rule 5: "the app".
    if THE_APP_RE.search(_without_code(text)):
        findings.append((5, 'says "the app"; write "PyReconstruct"'))

    # Rule 6: one menu-path form.
    if GT_SEPARATOR_RE.search(text):
        findings.append((6, f'menu path uses ">"; write it as Series {MENU_SEP} Options {MENU_SEP} View'))
    if CODE_MENU_RE.search(text) or CODE_AROUND_SEP_RE.search(text):
        findings.append((6, "menu path in backticks; write it plain, Series ▸ Options ▸ View"))
    if CODE_ELLIPSIS_RE.search(text) or any(
        (MENU_SEP in sentence or GT_SEPARATOR_RE.search(sentence)) and ELLIPSIS_RE.search(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", text)
    ):
        findings.append((6, 'menu path ends an item with "..."; drop it, Series ▸ Options ▸ View'))

    return findings


def check_file(path):
    """``(line, rule, message)`` for each finding in the fragment at ``path``."""
    text = Path(path).read_text(encoding="utf-8")
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
        print(f"{path}:{line}: rule {rule}: {message}")

    level = "error" if BLOCKING else "warning"
    title = "Fragment voice" if BLOCKING else "Fragment voice (report-only, not blocking)"
    for path, line, rule, message in findings:
        _annotate(level, path, line, title, f"rule {rule}: {message}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and findings:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n\n")
            fh.write("Rules 1, 3, 5 and 6 of changelog.d/README.md, checked by script.\n\n```\n")
            for path, line, rule, message in findings:
                fh.write(f"{path}:{line}: rule {rule}: {message}\n")
            fh.write("```\n")

    if not findings:
        print(f"fragment voice: ok ({len(paths)} fragment(s) read)")
        return 0
    print(f"fragment voice: {len(findings)} finding(s) in {len({f[0] for f in findings})} fragment(s)")
    return 1 if BLOCKING else 0


if __name__ == "__main__":
    sys.exit(main())
