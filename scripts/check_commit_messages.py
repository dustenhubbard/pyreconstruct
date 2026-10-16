#!/usr/bin/env python3
"""Report commit messages on main that break the commit message rules.

    python3 scripts/check_commit_messages.py <commits.json>

``commits.json`` is a JSON list of objects with ``sha`` and ``message``, the
shape ``gh api repos/OWNER/REPO/compare/A...B --jq '[.commits[] | {sha,
message: .commit.message}]'`` prints. The output is a JSON list with one object
per commit that breaks a rule: ``{"sha": ..., "subject": ..., "problems":
[...]}``. An empty list means every message passed.

The rules are checked before a commit is made, on the machine that makes it.
A squash merge from the web page, or from a machine without that check, lands
on main unchecked. This runs after the fact, on every push to main, so such a
message is found the same day. It only reports; ``main-message-watch.yml``
opens an issue for each hit, and nothing is blocked or reverted.

The rules:

  * no ``Co-authored-by:`` trailer (merge-evidence.yml refuses it on pull
    request commits; this catches it in a squash body);
  * no "Generated with [...]" line and no link to a tool session;
  * no em dash, and no spaced double hyphen standing in for one;
  * a subject of 70 characters at most, not counting the " (#123)" GitHub
    adds to a squash subject, and a body of 700 at most;
  * no third-person phrase about the owner ("his call", "he asked"): the
    repository speaks in the first person;
  * none of a short list of stock phrases ("delve", "it's worth noting").

The repository variable ``MESSAGE_SCAN_EXTRA``, when set, is one more
case-insensitive regular expression. A hit on it is reported without the
matched text, so the issue does not repeat it.

Stdlib only, like the other scripts the workflows run.
"""

import json
import os
import re
import sys

SUBJECT_MAX = 70
BODY_MAX = 700

TRAILER = re.compile(r"(^|\n)co-authored-by[ \t]*:", re.IGNORECASE)

# A "Generated with [Tool](link)" line, or a link to a tool's session page, as a
# pull request body template adds them. Matched by shape, not by tool name.
ATTRIBUTION = re.compile(r"\bgenerated (?:with|by) \[|/session_[A-Za-z0-9]", re.IGNORECASE)

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
    if TRAILER.search(message):
        found.append("has a Co-authored-by trailer")
    if ATTRIBUTION.search(message):
        found.append("has a tool attribution line or session link")
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


def scan(commits, extra=None):
    hits = []
    for commit in commits:
        found = problems_in(commit["message"], extra)
        if found:
            subject, _ = split_message(commit["message"])
            hits.append({"sha": commit["sha"], "subject": subject, "problems": found})
    return hits


def main(argv):
    if len(argv) != 2:
        sys.stderr.write(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        commits = json.load(f)
    json.dump(scan(commits, extra_pattern()), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
