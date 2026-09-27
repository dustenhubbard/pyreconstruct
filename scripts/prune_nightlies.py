#!/usr/bin/env python3
"""Select the nightly releases the prune-nightlies workflow should delete.

Usage:
    <releases, one "tag prerelease_flag" per line, on stdin>
        | python3 prune_nightlies.py

Input lines are "<tag> <true|false>", as `gh api .../releases` emits them
(drafts already excluded by the caller). Printed, one per line: the tags
identifying releases to delete. Git tags themselves are retained as
release-history evidence. Two rules, in order:

1. OVERTAKEN: a nightly whose base version is at or below the newest stable
   is stale; v1.24.0.dev20260928 previews 1.24.0, and once v1.24.0 has
   shipped nobody should install the preview.
2. SUPERSEDED: of the nightlies still ahead of stable, only the NEWEST SEVEN
   stay (by date, then by version), a week of rollback room in case a night's
   build turns out bad. Older ones serve nobody and clutter the releases
   sidebar. This counts across base versions: a planned major line and the
   regular minor line share the seven.

The retired vX.Y.Z-beta-N shape is still recognized, for rule 1 only, so the
pre-releases left over from that channel are cleaned up as their stables
ship. Nothing new is ever tagged in that shape.

Guardrails: only tags shaped vX.Y.Z.devYYYYMMDD or vX.Y.Z-beta-N are ever
selected, stables and oddly-shaped tags are never touched, and with no stable
release at all nothing is pruned. Stdlib only, like its sibling
prune_prereleases.py, so the workflow needs no environment and the tests
need no GitHub.
"""

import re
import sys

STABLE_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
NIGHTLY_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)\.dev(\d{8})$")
LEGACY_BETA_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-beta-(\d+)$")

KEEP_NIGHTLIES = 7


def select_prunable(release_lines: list[str]) -> list[str]:
    """The tags to delete, given "<tag> <prerelease flag>" lines."""
    stables = []
    nightlies = []
    legacy_betas = []
    for line in release_lines:
        parts = line.split()
        if len(parts) != 2:
            continue
        tag, prerelease = parts
        if prerelease == "false":
            m = STABLE_RE.match(tag)
            if m:
                stables.append(tuple(int(g) for g in m.groups()))
            continue
        m = NIGHTLY_RE.match(tag)
        if m:
            base = tuple(int(g) for g in m.groups()[:3])
            nightlies.append((int(m.group(4)), base, tag))
            continue
        m = LEGACY_BETA_RE.match(tag)
        if m:
            legacy_betas.append((tuple(int(g) for g in m.groups()[:3]), tag))

    if not stables:
        return []  # no stable release; nothing is provably stale
    newest_stable = max(stables)

    prunable = []
    ahead = []
    for date, base, tag in nightlies:
        if base <= newest_stable:
            prunable.append(tag)  # overtaken by a shipped stable
        else:
            ahead.append((date, base, tag))

    ahead.sort()
    for _date, _base, tag in ahead[:-KEEP_NIGHTLIES]:
        prunable.append(tag)  # superseded: older than the newest seven

    for base, tag in legacy_betas:
        if base <= newest_stable:
            prunable.append(tag)  # a leftover from the retired channel

    return prunable


def main() -> int:
    lines = [line.strip() for line in sys.stdin if line.strip()]
    for tag in select_prunable(lines):
        print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
