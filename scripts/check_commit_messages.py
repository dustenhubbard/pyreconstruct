#!/usr/bin/env python3
"""Report commit messages on main that break the commit message rules.

    python3 scripts/check_commit_messages.py <before> <after>

Reads every commit in ``<before>..<after>`` from the local clone, so the
checkout needs the full history (``fetch-depth: 0``). The output is a JSON list
with one object per commit that breaks a rule: ``{"sha": ..., "subject": ...,
"problems": [...]}``. An empty list means every message passed.

The rules are checked before a commit is made, on the machine that makes it.
A squash merge from the web page, or from a machine without that check, lands
on main unchecked. This runs after the fact, on every push to main, so such a
message is found the same day. It only reports; ``main-message-watch.yml``
opens an issue for each hit, and nothing is blocked or reverted.

The rules are the ones the pre-commit check applies to this repository, copied
here: the patterns, and the 70 and 700 character caps. The one difference is
that the " (#123)" GitHub adds to a squash subject is not counted in the
subject. ``tests/test_check_commit_messages.py`` compares the copy with the
original when it is given the original's path.

The repository variable ``MESSAGE_SCAN_EXTRA``, when set, is one more
case-insensitive regular expression. A hit on it, on a name or on an
attribution line is reported without the matched text, so the issue does not
repeat it.

Stdlib only, like the other scripts the workflows run.
"""

import base64
import json
import os
import re
import subprocess
import sys

SUBJECT_MAX = 70
BODY_MAX = 700


def _encoded(text):
    """Compile a pattern stored in base64, so this file does not itself carry
    the words the pattern looks for."""
    return re.compile(base64.b64decode(text).decode("ascii"), re.IGNORECASE)


# An attribution trailer anywhere in the message, a tool session line or link,
# or a "generated with" line.
ATTRIBUTION = _encoded(
    "Y28tYXV0aG9yZWQtYnlccyo6fGNsYXVkZS1zZXNzaW9ufGdlbmVyYXRlZCB3aXRoXHMrXFs/"
    "Y2xhdWRlfGNsYXVkZVwuYWkvY29kZXxub3JlcGx5QGFudGhyb3BpYw=="
)

# A tool or process name, as a whole word.
NAMES = _encoded(
    "KD88IVtBLVphLXowLTldKShjbGF1ZGV8ZmFibGV8b3B1c3xhZHZlcnNhcmlhbCkoPyFbQS1a"
    "YS16MC05XSk="
)

# GitHub ends a squash subject with " (#123)". The cap is on the title before it.
PR_SUFFIX = re.compile(r" \(#\d+\)$")

# An em dash, or `--` with whitespace or a line edge on both sides. A flag such
# as `--draft` has no space after the hyphens and passes.
EM_DASH = re.compile(r"\u2014|(?:^|\s)--(?:\s|$)")

THIRD_PERSON = re.compile(
    r"\bhis (call|ask|pick|word|report|click[- ]test|refinement|framing|priority)\b"
    r"|\bon his (call|word)\b"
    r"|\bhe (agreed|asked|wants|wanted|said|reported|picked|click[- ]tested)\b"
    r"|\bthe maintainer'?s? (call|ask|pick|word|decision|intent)\b"
    r"|\bdeferred on his\b"
    r"|\bper (his|today's) (call|word)\b",
    re.IGNORECASE,
)

STOCK_PHRASES = re.compile(
    r"\bdelve\b"
    r"|\bit'?s worth noting\b"
    r"|\bworth noting that\b"
    r"|\bat the end of the day\b"
    r"|\bparadigm shift\b"
    r"|\bdouble[- ]click on\b"
    r"|\blean into\b"
    r"|\bgreat question\b"
    r"|\bnot (?:just|only) [^.\n]{1,80}?\b(?:but also|but|it'?s|it is)\b",
    re.IGNORECASE,
)

ZERO_SHA = re.compile(r"^0+$")


def split_message(message):
    """Return the subject line and the body, the body stripped of blank edges."""
    lines = message.strip().splitlines()
    if not lines:
        return "", ""
    return lines[0], "\n".join(lines[1:]).strip()


def problems_in(message, extra=None):
    """Return a list of the rules ``message`` breaks, each as a short phrase."""
    subject, body = split_message(message)
    found = []
    if ATTRIBUTION.search(message):
        found.append("has an attribution trailer, a session line or a generated-with line")
    if NAMES.search(message):
        found.append("names a tool or process")
    if EM_DASH.search(message):
        found.append("has an em dash or a spaced double hyphen")
    title = PR_SUFFIX.sub("", subject)
    if len(title) > SUBJECT_MAX:
        found.append(f"subject is {len(title)} characters; the cap is {SUBJECT_MAX}")
    if len(body) > BODY_MAX:
        found.append(f"body is {len(body)} characters; the cap is {BODY_MAX}")
    m = THIRD_PERSON.search(message)
    if m:
        found.append(f"names the owner in the third person ('{m.group(0)}')")
    m = STOCK_PHRASES.search(message)
    if m:
        found.append(f"has a stock phrase ('{m.group(0)}')")
    if extra is not None and extra.search(message):
        found.append("matches the MESSAGE_SCAN_EXTRA pattern")
    return found


def extra_pattern(environ=os.environ):
    """Compile ``MESSAGE_SCAN_EXTRA``, or return None when it is unset or empty."""
    raw = environ.get("MESSAGE_SCAN_EXTRA", "").strip()
    return re.compile(raw, re.IGNORECASE) if raw else None


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def commits_between(before, after):
    """Every commit in ``before..after``, as ``{"sha", "message"}`` dicts.

    With no usable ``before`` (a new branch, or a commit this clone does not
    have), only ``after`` itself is checked, and a warning says so.
    """
    usable = not ZERO_SHA.match(before) and subprocess.run(
        ["git", "cat-file", "-e", f"{before}^{{commit}}"], capture_output=True
    ).returncode == 0
    if usable:
        span = [f"{before}..{after}"]
    else:
        print(f"::warning::No usable base {before}; checking {after} alone.", file=sys.stderr)
        span = ["-1", after]
    out = _git("log", "-z", "--format=%H%n%B", *span)
    commits = []
    for record in out.split("\0"):
        if record.strip():
            sha, _, message = record.lstrip("\n").partition("\n")
            commits.append({"sha": sha, "message": message})
    expected = int(_git("rev-list", "--count", *span))
    if len(commits) != expected:
        raise RuntimeError(f"read {len(commits)} commits, expected {expected}")
    return commits


def scan(commits, extra=None):
    hits = []
    for commit in commits:
        found = problems_in(commit["message"], extra)
        if found:
            subject, _ = split_message(commit["message"])
            hits.append({"sha": commit["sha"], "subject": subject, "problems": found})
    return hits


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    commits = commits_between(argv[1], argv[2])
    print(f"{len(commits)} commit(s) to check", file=sys.stderr)
    json.dump(scan(commits, extra_pattern()), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
