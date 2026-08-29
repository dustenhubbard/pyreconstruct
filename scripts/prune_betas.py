#!/usr/bin/env python3
"""Select the beta releases the prune-betas workflow should delete.

Usage:
    <releases, one "tag prerelease_flag" per line, on stdin>
        | python3 prune_betas.py

Input lines are "<tag> <true|false>", as `gh api .../releases` emits them
(drafts already excluded by the caller). Printed, one per line: the beta
tags to delete. Two rules, in order:

1. OVERTAKEN: a beta whose base version is at or below the newest stable
   is stale; nobody should install a beta of a version that already
   shipped. (The original rule.)
2. SUPERSEDED: within a base version still ahead of stable, only the
   NEWEST TWO betas stay -- the one the updater offers plus one rollback
   in case the newest turns out bad (his call, 2026-08-28; Patrick's
   beta-3 mass-delete crash is why the rollback margin exists). Older
   siblings serve nobody and cluttered the releases sidebar.

Guardrails unchanged from the shell logic this replaces: only tags shaped
vX.Y.Z-beta-N are ever selected, stables and oddly-shaped tags are never
touched, and with no stable release at all nothing is pruned. Stdlib only,
like its sibling prune_prereleases.py, so the workflow needs no
environment and the tests need no GitHub.
"""

import re
import sys

STABLE_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
BETA_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-beta-(\d+)$")

KEEP_PER_LINE = 2


def select_prunable(release_lines: list[str]) -> list[str]:
    """The beta tags to delete, given "<tag> <prerelease flag>" lines."""
    stables = []
    betas = []
    for line in release_lines:
        parts = line.split()
        if len(parts) != 2:
            continue
        tag, prerelease = parts
        if prerelease == "false":
            m = STABLE_RE.match(tag)
            if m:
                stables.append(tuple(int(g) for g in m.groups()))
        else:
            m = BETA_RE.match(tag)
            if m:
                base = tuple(int(g) for g in m.groups()[:3])
                betas.append((base, int(m.group(4)), tag))

    if not stables:
        return []  # no stable release; nothing is provably stale
    newest_stable = max(stables)

    prunable = []
    by_base = {}
    for base, number, tag in betas:
        if base <= newest_stable:
            prunable.append(tag)  # overtaken by a shipped stable
        else:
            by_base.setdefault(base, []).append((number, tag))

    for base, siblings in by_base.items():
        siblings.sort()
        for _number, tag in siblings[:-KEEP_PER_LINE]:
            prunable.append(tag)  # superseded within its own line

    return prunable


def main() -> int:
    lines = [line.strip() for line in sys.stdin if line.strip()]
    for tag in select_prunable(lines):
        print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
