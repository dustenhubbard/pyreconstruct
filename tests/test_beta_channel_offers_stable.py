"""The Beta channel must be a superset of Stable, not a set disjoint from it.

The bug this pins was live in production on 2026-08-05 and is invisible from the
inside. v1.21.0 shipped as a stable cut from a release branch, the four superseded
1.21.0 beta releases were retired at publish, and from that moment every
Beta-channel user was offered **nothing at all**: `pick_release(releases,
"prerelease")` scanned for a release flagged `prerelease` and returned `None` when
there was none, with no fallback to stable. `check_for_update` then reported
`status="unknown"` with no asset, so the app showed no update prompt and no error
either. A tester's only route to the release everyone else had was to know, without
being told, to change a setting.

So the rule, and the reason it is worth a test rather than a comment: a user on Beta
is asking for the newest thing that exists, and when the newest thing is a stable
release, withholding it strands them. Beta means earlier access, not a different
lane.

`_newer_of` compares TAG versions rather than asset versions, because
`pick_release` is pure over the release dicts and never touches assets. Every tag
shape this project publishes parses under `packaging` once the leading `v` is
dropped: `v1.21.0`, `v1.21.0-beta-7` (to `1.21.0b7`), `v1.30.0-alpha.2`, `v1.21.0rc1`.
A tag that is not a version at all, such as the retired rolling `prerelease` tag,
yields `None` and is treated as "cannot compare" rather than as "older".
"""
import pytest

from PyReconstruct.modules.backend.updater.updater import pick_release


def _rel(tag, prerelease=False, draft=False):
    """The three keys `pick_release` reads off a GitHub release object."""
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft}


def _tags(releases, channel):
    picked = pick_release(releases, channel)
    return picked["tag_name"] if picked else None


# ---------------------------------------------------------------------------
# the regression itself
# ---------------------------------------------------------------------------

def test_beta_is_offered_the_stable_release_when_no_prerelease_exists():
    """The exact production state after v1.21.0's publish-and-prune."""
    live = [_rel("v1.21.0"), _rel("v1.20.4"), _rel("v1.20.3")]

    assert _tags(live, "prerelease") == "v1.21.0"
    assert _tags(live, "release") == "v1.21.0"


def test_beta_is_offered_the_stable_release_when_the_newest_prerelease_is_older():
    """A stale pre-release must not shadow a newer stable one.

    This is the same bug one step later: leaving an old beta published would have
    made the channel non-empty while still offering testers something behind.
    """
    live = [_rel("v1.21.0"), _rel("v1.21.0-beta-7", prerelease=True)]

    assert _tags(live, "prerelease") == "v1.21.0"


# ---------------------------------------------------------------------------
# and none of the existing behavior moves
# ---------------------------------------------------------------------------

def test_a_newer_prerelease_still_wins_for_beta():
    live = [
        _rel("v1.22.0-beta-1", prerelease=True),
        _rel("v1.21.0"),
        _rel("v1.20.4"),
    ]

    assert _tags(live, "prerelease") == "v1.22.0-beta-1"
    assert _tags(live, "release") == "v1.21.0"


def test_stable_never_offers_a_prerelease():
    live = [_rel("v1.22.0-beta-1", prerelease=True), _rel("v1.21.0")]

    assert _tags(live, "release") == "v1.21.0"


def test_a_tie_goes_to_the_prerelease():
    """Same version on both: the pre-release has the narrower audience.

    A Beta user asked for that audience, so the tie is not arbitrary.
    """
    live = [_rel("v1.21.0"), _rel("v1.21.0", prerelease=True)]

    assert pick_release(live, "prerelease")["prerelease"] is True


def test_drafts_are_ignored_on_both_channels():
    live = [_rel("v1.99.0", draft=True), _rel("v1.99.0-beta-1", prerelease=True, draft=True),
            _rel("v1.21.0")]

    assert _tags(live, "prerelease") == "v1.21.0"
    assert _tags(live, "release") == "v1.21.0"


def test_the_retired_rolling_tag_is_still_excluded():
    """`ROLLING_TAG` is not a version, so it must not become the Beta answer.

    It is also the case that exercises `_tag_version` returning None: the
    comparison cannot be made, and the code must not read that as "older".
    """
    live = [_rel("prerelease", prerelease=True), _rel("v1.21.0")]

    assert _tags(live, "prerelease") == "v1.21.0"


def test_an_unparseable_prerelease_tag_is_still_preferred_over_nothing():
    """No stable to compare against, so the pre-release is all there is."""
    live = [_rel("v1.22.0-nightly-build", prerelease=True)]

    assert _tags(live, "prerelease") == "v1.22.0-nightly-build"


@pytest.mark.parametrize("channel", ["prerelease", "release", "stable", "edge", "developer"])
def test_no_releases_at_all_returns_none(channel):
    """Including the legacy channel names, which `normalize_channel` remaps."""
    assert pick_release([], channel) is None
    assert pick_release(None, channel) is None
