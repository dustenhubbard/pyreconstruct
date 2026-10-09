#!/usr/bin/env python3
"""Pick the stable tag a release's compare link starts from.

Usage:
    <existing tags, one per line, on stdin> | python3 previous_stable_tag.py v1.24.0

Given the tag being released as argv[1] and a newline-separated list of
existing tags on stdin, print the highest stable tag (a clean ``vX.Y.Z``)
whose version is below the released tag's ``X.Y.Z``. Print nothing when there
is none, or when argv[1] is not a release tag this repo uses.

The released tag may be a stable or a pre-release of ``X.Y.Z``, in any form
the repo has tagged:

  * stable:              v1.24.0
  * PEP 440-normalized:  v1.24.0rc1, v1.24.0a1, v1.24.0b2
  * dashed semver:       v1.24.0-rc.1, v1.24.0-beta.2, v1.23.0-beta-6
  * nightlies:           v1.24.0.dev20261008, v1.25.0.dev202610090706

Only stable tags are ever picked. A sort over every tag, as
``git tag --sort=-version:refname`` does, puts v1.23.0-beta-6 between v1.24.0
and v1.23.0, so the link for v1.24.0 started at the last beta.

Used by .github/workflows/build-installers.yml for the stable release notes.
Stdlib only.
"""

import re
import sys

STABLE_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# The same pre-release suffixes scripts/prune_prereleases.py recognizes.
PRERELEASE_RE = re.compile(
    r"^v(\d+)\.(\d+)\.(\d+)(?:(?:a|b|rc)\d+|-(?:alpha|beta|rc)(?:[-.]\d+)?|\.dev\d+)$"
)


def release_version(tag: str) -> tuple[int, int, int] | None:
    """Return the X.Y.Z of a stable or pre-release tag, or None."""
    m = STABLE_RE.match(tag) or PRERELEASE_RE.match(tag)
    if m is None:
        return None
    return tuple(int(part) for part in m.groups())


def previous_stable(current: str, tags: list[str]) -> str | None:
    """Return the highest stable tag below current's X.Y.Z, or None."""
    version = release_version(current)
    if version is None:
        return None
    older = []
    for tag in tags:
        m = STABLE_RE.match(tag)
        if m is None:
            continue
        tag_version = tuple(int(part) for part in m.groups())
        if tag_version < version:
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
