#!/usr/bin/env python3
"""Pick the stable tag a stable release's compare link starts from.

Usage:
    <existing tags, one per line, on stdin> | python3 previous_stable_tag.py v1.24.0

Given the stable tag being released (a clean ``vX.Y.Z``) as argv[1] and a
newline-separated list of existing tags on stdin, print the highest stable tag
whose version is below it. Print nothing when there is none, or when argv[1]
is not a stable tag.

Only stable tags are ever picked. A sort over every tag, as
``git tag --sort=-version:refname`` does, puts v1.23.0-beta-6 between v1.24.0
and v1.23.0, so the link for v1.24.0 started at the last beta.

Used by .github/workflows/build-installers.yml for the stable release notes; a
beta or rc there still compares from the tag just before it. Stdlib only.
"""

import re
import sys

# ASCII digits only, as the workflow's own stable check ([0-9]) matches.
STABLE_RE = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")


def stable_version(tag: str) -> tuple[int, int, int] | None:
    """Return the X.Y.Z of a stable tag, or None."""
    m = STABLE_RE.match(tag)
    if m is None:
        return None
    return tuple(int(part) for part in m.groups())


def previous_stable(current: str, tags: list[str]) -> str | None:
    """Return the highest stable tag below the stable tag current, or None."""
    version = stable_version(current)
    if version is None:
        return None
    older = []
    for tag in tags:
        tag_version = stable_version(tag)
        if tag_version is not None and tag_version < version:
            older.append((tag_version, tag))
    return max(older)[1] if older else None


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 2
    tags = [line.strip() for line in sys.stdin if line.strip()]
    previous = previous_stable(sys.argv[1], tags)
    if previous:
        print(previous)
    return 0


if __name__ == "__main__":
    sys.exit(main())
