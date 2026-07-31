#!/usr/bin/env python3
"""Report a pull request that changes the application without recording it.

Fifty commits landed between ``v1.21.0-beta-5`` and the beta-6 notes cut, and
eight of them touched ``CHANGELOG.md``. Twenty-eight touched
``PyReconstruct/``; twenty-two of those twenty-eight had no changelog change,
and twenty-one of those twenty-two were given an entry weeks later, by hand,
when someone sat down to assemble the release notes. Nothing required an entry
at the time, so the record drifted and nobody found out until the file no
longer described the release.

The rule this implements is narrow on purpose: a pull request that touches
``PyReconstruct/`` should also touch ``CHANGELOG.md``. Three ways out, all
cheap:

  * touch ``CHANGELOG.md``;
  * change nothing outside ``tests/`` and ``.github/``, which is exempt
    automatically;
  * write an opt-out line in the pull request body and say why.

The opt-out is a body line rather than a label. A label needs write access to
the repository, so an outside contributor cannot apply one and has to wait for
somebody who can; a body line is available to whoever opened the pull request.
A label also carries no reason, and a reason is the whole point: a reviewer
reading the body should be able to see that the author decided there was
nothing to record, not that the author forgot. The line is matched
case-insensitively and needs text after the colon::

    No changelog entry: internal refactor, no user-visible behavior change

REPORT-ONLY. ``BLOCKING = False`` below means this script exits 0 whatever it
finds, and the finding arrives as a warning annotation and a job summary. Set
``BLOCKING = True`` to make it a gate. Do that only if the warnings turn out to
be genuine omissions; if it starts firing on changes that legitimately have
nothing to record, the scope is wrong and belongs in this file, not in a habit
of ignoring the annotation.

Usage::

    check_changelog_entry.py --changed-files FILE --body FILE [--changelog PATH]

``--changed-files`` is a newline-separated list of repository-relative paths.
``--body`` is the pull request body. Stdlib only, so this runs with no project
environment at all.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Flip to True to make this a gate. This is the only line that needs to change:
# it switches the exit code from 0 to 1 on a finding, and the GitHub annotation
# from `warning` to `error`.
BLOCKING = False

APP_PREFIX = "PyReconstruct/"
CHANGELOG = "CHANGELOG.md"
EXEMPT_PREFIXES = ("tests/", ".github/")

# `No changelog entry: <reason>`, optionally as a markdown list item, anywhere
# in the body. A reason is required: a bare marker with nothing after the colon
# is a checkbox, not a decision, and does not count.
OPT_OUT_RE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?no[ \t]+changelog[ \t]+entry[ \t]*:[ \t]*(\S.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

OPT_OUT_EXAMPLE = "No changelog entry: <why this has nothing to record>"

# The house style, written out rather than sampled from the file: the real
# bullets are hard-wrapped, so no single line of CHANGELOG.md is a usable
# example and a sampled one comes out cut off mid-sentence.
ENTRY_SHAPE = "- **Short title, bold, ending in a period.** What changed and why."

# The buckets an entry can go in. Used when the topmost section has none of its
# own yet, which is the normal state of `## [Unreleased]` right after a release.
KEEP_A_CHANGELOG_SECTIONS = ("Added", "Changed", "Fixed", "Removed")


def _top_section(changelog_text):
    """``(heading, subsections)`` for the topmost ``##`` section.

    ``heading`` is the section an entry belongs under right now, and
    ``subsections`` are its ``###`` buckets. Falls back to the Keep a Changelog
    set when the section is empty or the file is unreadable, so the message is
    never blank and never tells anyone to go and read a convention first.
    """
    heading = None
    subsections = []
    for line in (changelog_text or "").splitlines():
        if line.startswith("## "):
            if heading is not None:
                break
            heading = line[3:].strip()
        elif heading is not None and line.startswith("### "):
            name = line[4:].strip()
            if name and name not in subsections:
                subsections.append(name)
    return heading or "[Unreleased]", subsections or list(KEEP_A_CHANGELOG_SECTIONS)


def evaluate(changed_files, pr_body):
    """Decide whether this change needs a changelog entry it does not have.

    Returns ``(status, detail)``. ``status`` is one of:

      ``no-app-change``  nothing under ``PyReconstruct/`` changed
      ``exempt``         nothing outside ``tests/`` and ``.github/`` changed
      ``recorded``       ``CHANGELOG.md`` is in the change
      ``opted-out``      the body carries the opt-out line; detail is the reason
      ``missing``        the finding
    """
    files = [f.strip() for f in changed_files if f and f.strip()]

    # Checked before the scope rule so that a tests/ + .github/ change is
    # reported as exempt rather than as out of scope. Today the two are
    # equivalent, since neither prefix can contain a PyReconstruct/ path, and
    # the redundancy is deliberate: it keeps the exemption from disappearing
    # silently if the scope prefix is ever widened.
    if files and all(f.startswith(EXEMPT_PREFIXES) for f in files):
        return "exempt", ""

    if not any(f.startswith(APP_PREFIX) for f in files):
        return "no-app-change", ""

    if CHANGELOG in files:
        return "recorded", ""

    match = OPT_OUT_RE.search(pr_body or "")
    if match:
        return "opted-out", match.group(1).strip()

    return "missing", ""


def _message(changed_files, changelog_text):
    """The finding, written so the fix takes seconds and needs nothing read."""
    app_files = sorted(f for f in changed_files if f.strip().startswith(APP_PREFIX))
    shown = app_files[:5]
    more = len(app_files) - len(shown)
    heading, subsections = _top_section(changelog_text)
    lines = [
        f"This changes {len(app_files)} file(s) under {APP_PREFIX} and does not "
        f"touch {CHANGELOG}.",
        "",
        "Changed:",
    ]
    lines += [f"  {f}" for f in shown]
    if more:
        lines.append(f"  ... and {more} more")
    lines += [
        "",
        f"Add an entry to {CHANGELOG}, under `## {heading}`, in one of:",
        "  " + "  ".join(subsections),
        "",
        "Shape of an entry:",
        f"  {ENTRY_SHAPE}",
        "",
        "Or, if there is genuinely nothing to record, put this line in the "
        "pull request body:",
        f"  {OPT_OUT_EXAMPLE}",
    ]
    return "\n".join(lines)


def _emit(level, title, body):
    """A GitHub annotation plus a job summary, and the same text on stdout."""
    print(f"{title}\n\n{body}\n")
    one_line = body.replace("\n", "%0A")
    print(f"::{level} title={title}::{one_line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n\n```\n{body}\n```\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", required=True, type=Path)
    parser.add_argument("--body", required=True, type=Path)
    parser.add_argument("--changelog", type=Path, default=Path(CHANGELOG))
    args = parser.parse_args(argv)

    changed_files = args.changed_files.read_text(encoding="utf-8").splitlines()
    pr_body = args.body.read_text(encoding="utf-8") if args.body.exists() else ""
    try:
        changelog_text = args.changelog.read_text(encoding="utf-8")
    except OSError:
        changelog_text = ""

    status, detail = evaluate(changed_files, pr_body)

    if status == "missing":
        level = "error" if BLOCKING else "warning"
        title = (
            "Missing changelog entry"
            if BLOCKING
            else "Missing changelog entry (report-only, not blocking)"
        )
        _emit(level, title, _message(changed_files, changelog_text))
        return 1 if BLOCKING else 0

    explanation = {
        "no-app-change": f"nothing under {APP_PREFIX} changed",
        "exempt": "nothing changed outside " + " and ".join(EXEMPT_PREFIXES),
        "recorded": f"{CHANGELOG} is part of this change",
        "opted-out": f"opted out in the pull request body: {detail}",
    }[status]
    print(f"changelog check: ok ({explanation})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
