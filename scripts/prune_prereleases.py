#!/usr/bin/env python3
"""Select the pre-release tags superseded by a freshly published stable tag.

Usage:
    <existing tags, one per line, on stdin> | python3 prune_prereleases.py v1.21.0

Given a stable tag (a clean ``vX.Y.Z``) as argv[1] and a newline-separated
list of existing tags on stdin, print -- one per line -- only the tags that
are pre-releases of that SAME ``X.Y.Z`` version line, in either form this
repo has tagged them:

  * PEP 440-normalized:  v1.21.0rc1, v1.21.0a1, v1.21.0b2
  * dashed semver:       v1.21.0-rc.1, v1.21.0-alpha.1, v1.21.0-beta.2

The stable tag itself is never selected (a pre-release suffix is required),
and tags of any other version line (v1.20.5rc1, v1.22.0rc1, v1.21.10rc1)
never match: the pattern is anchored on the exact, escaped ``X.Y.Z``.

Used by .github/workflows/build-installers.yml to prune superseded
pre-releases when a stable release is published. Stdlib only.
"""

import re
import sys

STABLE_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")

# Pre-release suffixes appended to the exact X.Y.Z:
#   PEP 440 compact: a<N> / b<N> / rc<N>
#   dashed semver:   -alpha / -beta / -rc, optionally followed by a number with
#                    either a '.' or '-' separator (-beta.2 or -beta-2).
PRERELEASE_SUFFIX = r"(?:(?:a|b|rc)\d+|-(?:alpha|beta|rc)(?:[-.]\d+)?)"


def select_superseded(stable_tag: str, tags: list[str]) -> list[str]:
    """Return the tags that are pre-releases of stable_tag's version line."""
    m = STABLE_RE.match(stable_tag)
    if m is None:
        raise ValueError(
            f"not a stable vX.Y.Z tag: {stable_tag!r} "
            "(refusing to prune for a non-stable trigger)"
        )
    pattern = re.compile(rf"^v{re.escape(m.group(1))}{PRERELEASE_SUFFIX}$")
    return [t for t in tags if pattern.match(t)]


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 2
    tags = [line.strip() for line in sys.stdin if line.strip()]
    try:
        superseded = select_superseded(sys.argv[1], tags)
    except ValueError as err:
        sys.stderr.write(f"prune_prereleases: {err}\n")
        return 2
    for tag in superseded:
        print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
