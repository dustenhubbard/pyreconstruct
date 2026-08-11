#!/usr/bin/env python3
"""Select orphaned ``untagged-*`` placeholder tags left behind by draft releases.

Usage:
    <existing tags, one per line, on stdin> | \
        python3 prune_untagged_placeholders.py <file of tag names in use>

GitHub mints a placeholder tag named ``untagged-<40 hex>`` whenever a release is
created as a DRAFT: a draft has no real tag yet, so the release has to point at
something. Publishing the draft creates the real ``vX.Y.Z`` tag and leaves the
placeholder behind, pointing at the same commit, referenced by nothing.

That leftover is not cosmetic. ``vcs-versioning`` derives the package version from
``git describe``, and it cannot parse ``untagged-87b5beb96d79ab5ff1c1``::

    ValueError: Can't parse version from tag 'untagged-87b5beb96d79ab5ff1c1'

So every branch whose nearest tag is the placeholder fails to BUILD -- not to
version wrongly, to fail outright. One such tag from the v1.21.1 draft broke
``uv run`` on a dev machine three days after the release.

``prune_prereleases.py`` cannot catch these: it selects by version line, anchored
on an exact ``X.Y.Z``, and a placeholder name has no version in it at all.

WHAT THIS PRINTS, AND WHAT IT DELIBERATELY DOES NOT
---------------------------------------------------
Printed: tags matching the placeholder shape EXACTLY, that no release refers to.

Never printed:

* Anything not matching ``untagged-<hex>``. A hand-made tag that merely starts
  with the word is not a GitHub placeholder and is left alone.
* A placeholder a release still points at -- which is what protects a LIVE draft.
  A draft's placeholder is load-bearing: delete it and the draft release breaks.
  The caller must therefore pass the tag names of ALL releases INCLUDING DRAFTS
  (``gh api repos/{repo}/releases`` returns drafts for a token with push access;
  ``gh release list`` alone is not a safe source).
* Anything at all when the in-use list is EMPTY. An empty list is far more likely
  to mean the API call failed than that the repo genuinely has no releases, and
  the failure mode of guessing wrong is deleting every placeholder including a
  live draft's. Exits 0 having printed nothing, so a broken lookup is a no-op
  rather than a mass deletion.

Stdlib only, like its sibling. Used by .github/workflows/build-installers.yml.
"""

import re
import sys

# GitHub's placeholder: the literal prefix plus a hex blob. Anchored at both ends
# so `untagged-things-i-mean-to-keep` is not swept up. The length is not pinned:
# the observed form is 20 hex characters, older ones differ, and the prefix plus
# "hex only, nothing else" is already specific enough to be unambiguous.
PLACEHOLDER_RE = re.compile(r"^untagged-[0-9a-f]+$")


def select(existing, in_use):
    """Return the placeholder tags in `existing` that nothing in `in_use` claims."""
    claimed = {t.strip() for t in in_use if t.strip()}
    if not claimed:
        return []
    out = []
    for tag in existing:
        tag = tag.strip()
        if tag and PLACEHOLDER_RE.match(tag) and tag not in claimed:
            out.append(tag)
    return out


def main(argv):
    if len(argv) != 2:
        sys.stderr.write(__doc__.split("\n\n")[1] + "\n")
        return 2
    try:
        with open(argv[1]) as fh:
            in_use = fh.read().splitlines()
    except OSError as exc:
        sys.stderr.write("cannot read the in-use tag list: {}\n".format(exc))
        return 2

    for tag in select(sys.stdin.read().splitlines(), in_use):
        print(tag)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
