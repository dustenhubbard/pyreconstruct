"""Channel-selection logic for the GitHub-Releases updater.

The updater serves two channels: ``release`` (stable, e.g. v1.20.0) and
``prerelease`` (early builds). The UI overhaul ships first as semver
pre-releases -- ``v1.30.0-alpha.1 -> -alpha.N -> -beta.1 -> -rc.1 -> v1.30.0``
final -- published as GitHub *pre-releases*. These tests pin the pure selection
functions (no Qt, no network) so the channel a user picks always resolves to the
right release and pre-releases order alpha < beta < rc < final, independent of
the order GitHub happens to return them in.
"""
import itertools

import pytest

from PyReconstruct.modules.backend.updater import updater as U
from PyReconstruct.modules.backend.updater.updater import (
    pick_release, pick_asset, asset_version, compare_versions, check_for_update,
    _release_version,
)

from packaging.version import Version


# --- fixtures: minimal GitHub release/asset dicts -----------------------------

def rel(tag, *, prerelease=False, draft=False, assets=None):
    """A GitHub release dict, trimmed to the keys the updater reads."""
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "assets": assets or [],
    }


def asset(name):
    return {"name": name, "browser_download_url": f"https://example/{name}"}


# Tags as a maintainer would cut them, in their intended chronological order.
ALPHA1 = rel("v1.30.0-alpha.1", prerelease=True)
ALPHA2 = rel("v1.30.0-alpha.2", prerelease=True)
BETA1 = rel("v1.30.0-beta.1", prerelease=True)
RC1 = rel("v1.30.0-rc.1", prerelease=True)
FINAL = rel("v1.30.0")               # the eventual stable v1.30.0
STABLE = rel("v1.20.0")              # current perf release


def tag_of(release):
    return release["tag_name"] if release else None


# --- semver ordering of pre-releases ------------------------------------------

PRE_CHAIN = [ALPHA1, ALPHA2, BETA1, RC1, FINAL]


@pytest.mark.parametrize("perm", list(itertools.permutations(PRE_CHAIN[:4])))
def test_prerelease_channel_picks_highest_semver_regardless_of_list_order(perm):
    """alpha.1 < alpha.2 < beta.1 < rc.1 -> rc.1 wins from any shuffling.

    GitHub usually returns newest-first, but the selection must not *depend* on
    that: feed every ordering of the four pre-releases and rc.1 must always win.
    """
    assert tag_of(pick_release(list(perm), "prerelease")) == "v1.30.0-rc.1"


def test_final_outranks_every_prerelease_on_prerelease_channel():
    """Once v1.30.0 final exists it wins on prerelease too (1.30.0 > 1.30.0rc1)."""
    assert tag_of(pick_release(PRE_CHAIN, "prerelease")) == "v1.30.0"


def test_alpha_ordering_is_numeric_not_lexical():
    """alpha.10 must outrank alpha.2 (numeric), not sort as a string."""
    a2 = rel("v1.30.0-alpha.2", prerelease=True)
    a10 = rel("v1.30.0-alpha.10", prerelease=True)
    assert tag_of(pick_release([a2, a10], "prerelease")) == "v1.30.0-alpha.10"
    assert tag_of(pick_release([a10, a2], "prerelease")) == "v1.30.0-alpha.10"


# --- the headline opt-in scenario ---------------------------------------------

def test_prerelease_user_gets_alpha_while_release_user_stays_on_stable():
    """The core promise: while v1.30.0-alpha.1 is out and stable is still v1.20.0,
    a prerelease user is offered the alpha and a release user stays on v1.20.0."""
    releases = [ALPHA1, STABLE]                       # alpha is newer by creation
    assert tag_of(pick_release(releases, "prerelease")) == "v1.30.0-alpha.1"
    assert tag_of(pick_release(releases, "release")) == "v1.20.0"


def test_switching_channels_flips_the_selected_release():
    """Same release list, channel is the only variable -> the toggle works."""
    releases = [RC1, STABLE]
    on_release = pick_release(releases, "release")
    on_prerelease = pick_release(releases, "prerelease")
    assert tag_of(on_release) == "v1.20.0"
    assert tag_of(on_prerelease) == "v1.30.0-rc.1"
    # and back again is deterministic, not stateful
    assert tag_of(pick_release(releases, "release")) == "v1.20.0"


# --- channel filtering rules --------------------------------------------------

def test_release_channel_never_serves_a_prerelease():
    assert tag_of(pick_release([ALPHA1, BETA1, RC1], "release")) is None


def test_release_channel_picks_highest_stable_not_list_order():
    """A late-published hotfix lower than the newest stable must not win."""
    v1200 = rel("v1.20.0")
    v1191 = rel("v1.19.1")                 # cut later, but a lower version
    assert tag_of(pick_release([v1191, v1200], "release")) == "v1.20.0"


def test_semver_prerelease_tag_kept_off_stable_even_if_flag_forgotten():
    """Defense-in-depth: a -alpha tag mistakenly published with prerelease=False
    must still be excluded from the stable channel by its semver tag."""
    leaky = rel("v1.30.0-alpha.1", prerelease=False)   # maintainer forgot the box
    assert tag_of(pick_release([leaky, STABLE], "release")) == "v1.20.0"
    # but a prerelease user can still receive it
    assert tag_of(pick_release([leaky, STABLE], "prerelease")) == "v1.30.0-alpha.1"


def test_drafts_are_ignored_on_both_channels():
    draft_pre = rel("v1.30.0-alpha.2", prerelease=True, draft=True)
    draft_stable = rel("v1.21.0", draft=True)
    assert tag_of(pick_release([draft_pre, ALPHA1], "prerelease")) == "v1.30.0-alpha.1"
    assert tag_of(pick_release([draft_stable, STABLE], "release")) == "v1.20.0"


@pytest.mark.parametrize("releases", [None, [], [rel("v1.0.0", draft=True)]])
def test_no_eligible_release_returns_none(releases):
    assert pick_release(releases, "release") is None
    assert pick_release(releases, "prerelease") is None


# --- legacy channel names + rolling-build fallback ----------------------------

def test_legacy_channel_names_are_accepted():
    """Installs predating the rename stored 'stable'/'edge'."""
    releases = [ALPHA1, STABLE]
    assert tag_of(pick_release(releases, "stable")) == "v1.20.0"
    assert tag_of(pick_release(releases, "edge")) == "v1.30.0-alpha.1"


def test_rolling_prerelease_tag_used_only_as_fallback():
    """The legacy rolling 'prerelease' tag (not a valid semver) is a fallback:
    a real semver pre-release outranks it, but with nothing else it is served."""
    rolling = rel("prerelease", prerelease=True)
    assert tag_of(pick_release([rolling], "prerelease")) == "prerelease"
    assert tag_of(pick_release([rolling, ALPHA1], "prerelease")) == "v1.30.0-alpha.1"


# --- asset selection + version parsing ----------------------------------------

def test_pick_asset_matches_platform_and_skips_checksum_sibling():
    r = rel("v1.30.0-alpha.1", prerelease=True, assets=[
        asset("PyReconstruct-1.30.0a1-Windows-x86_64.exe"),
        asset("PyReconstruct-1.30.0a1-Linux-x86_64.AppImage"),
        asset("PyReconstruct-1.30.0a1-Linux-x86_64.AppImage.sha256"),
    ])
    a = pick_asset(r, "Linux-x86_64")
    assert a["name"] == "PyReconstruct-1.30.0a1-Linux-x86_64.AppImage"
    assert pick_asset(r, "macOS-arm64") is None
    assert pick_asset(None, "Linux-x86_64") is None


@pytest.mark.parametrize("name,expected", [
    ("PyReconstruct-1.20.0-Windows-x86_64.exe", "1.20.0"),
    ("PyReconstruct-1.30.0a1-macOS-arm64.dmg", "1.30.0a1"),
    ("PyReconstruct-1.30.0-alpha.1-Linux-x86_64.AppImage", "1.30.0a1"),
    ("PyReconstruct-1.30.0a1.dev5+gabc-Linux-x86_64.AppImage", "1.30.0a1.dev5+gabc"),
])
def test_asset_version_parsing(name, expected):
    assert asset_version(name) == Version(expected)


def test_asset_version_returns_none_for_unparseable():
    assert asset_version("not-an-installer.zip") is None
    assert asset_version(None) is None


# --- compare_versions ---------------------------------------------------------

@pytest.mark.parametrize("remote,local,expected", [
    ("1.30.0a1", "1.20.0", "newer"),     # prerelease user offered the alpha
    ("1.30.0a2", "1.30.0a1", "newer"),   # next alpha
    ("1.30.0", "1.30.0rc1", "newer"),    # final supersedes rc
    ("1.20.0", "1.20.0", "same"),
    ("1.20.0", "1.30.0a1", "older"),     # switched back to release while on an alpha
    # a rolling .devN build (+local stripped, .devN kept) reads as older than the
    # released alpha of the same number -- correct PEP 440 ordering; pinned so a
    # refactor of compare_versions can't silently flip it.
    ("1.30.0a2.dev5+gabc", "1.30.0a2", "older"),
])
def test_compare_versions(remote, local, expected):
    assert compare_versions(Version(remote), Version(local)) == expected


def test_compare_versions_ignores_local_build_segment():
    """A clean CI build at the same commit must not read as a downgrade."""
    assert compare_versions(Version("1.30.0a1"), Version("1.30.0a1+gdeadbee")) == "same"


def test_compare_versions_unknown_when_either_missing():
    assert compare_versions(None, Version("1.0.0")) == "unknown"
    assert compare_versions(Version("1.0.0"), None) == "unknown"


# --- end-to-end check_for_update (mocked platform/version, no network) --------

def _patch_install_info(monkeypatch, local_ver, plat="Linux-x86_64"):
    mod = "PyReconstruct.modules.backend.updater.install_info"
    monkeypatch.setattr(f"{mod}.current_version", lambda: Version(local_ver))
    monkeypatch.setattr(f"{mod}.platform_asset_tag", lambda: plat)


def test_check_for_update_offers_alpha_to_prerelease_user(monkeypatch):
    _patch_install_info(monkeypatch, "1.20.0")
    releases = [
        rel("v1.30.0-alpha.1", prerelease=True,
            assets=[asset("PyReconstruct-1.30.0a1-Linux-x86_64.AppImage")]),
        rel("v1.20.0", assets=[asset("PyReconstruct-1.20.0-Linux-x86_64.AppImage")]),
    ]
    info = check_for_update("prerelease", releases=releases)
    assert info["remote_version"] == "1.30.0a1"
    assert info["status"] == "newer"


def test_check_for_update_keeps_release_user_on_stable(monkeypatch):
    _patch_install_info(monkeypatch, "1.20.0")
    releases = [
        rel("v1.30.0-alpha.1", prerelease=True,
            assets=[asset("PyReconstruct-1.30.0a1-Linux-x86_64.AppImage")]),
        rel("v1.20.0", assets=[asset("PyReconstruct-1.20.0-Linux-x86_64.AppImage")]),
    ]
    info = check_for_update("release", releases=releases)
    assert info["remote_version"] == "1.20.0"
    assert info["status"] == "same"


def test_check_for_update_reports_no_asset_for_other_platform(monkeypatch):
    _patch_install_info(monkeypatch, "1.20.0", plat="macOS-arm64")
    releases = [rel("v1.30.0-alpha.1", prerelease=True,
                    assets=[asset("PyReconstruct-1.30.0a1-Linux-x86_64.AppImage")])]
    info = check_for_update("prerelease", releases=releases)
    assert info["asset"] is None


# --- CI tag classifier (mirror of build-installers.yml) -----------------------
#
# The release workflow decides stable-vs-prerelease purely from the tag with
#   if [[ "$GITHUB_REF_NAME" == *-* ]]; then prerelease=true; else false
# i.e. "a hyphen after the version marks a pre-release". Mirror that here AND
# cross-check it against the updater's own semver view, so the CI gate and the
# updater can never disagree about what counts as a pre-release.

@pytest.mark.parametrize("tag,is_prerelease", [
    ("v1.20.0", False),
    ("v1.30.0", False),
    ("v1.30.0-alpha.1", True),
    ("v1.30.0-beta.1", True),
    ("v1.30.0-rc.1", True),
])
def test_ci_tag_classifier_agrees_with_updater_semver(tag, is_prerelease):
    ci_says_prerelease = "-" in tag                      # the bash `== *-*` rule
    assert ci_says_prerelease == is_prerelease
    v = _release_version({"tag_name": tag})              # the updater's view
    assert v is not None
    assert v.is_prerelease == is_prerelease


# --- in-app toggle contract (Qt; offscreen) -----------------------------------
#
# all_options.py maps the "Update channel" radio to the stored channel with
#   self.series.setOption("update_channel", "release" if response[0][0][1] else "prerelease")
# where `response` is the QuickDialog's `self.responses`: a tuple of one entry
# per input field. The radio is field 0, and a radio InputField returns
# [(label, isChecked), ...]; so response[0][0][1] is "is the FIRST radio
# (Release) checked". Pin that two-level contract so a future dialog refactor
# can't silently invert or break the channel toggle.

def _channel_from_radio_response(response):
    """Exactly the expression used in all_options.OptionWidget.setOption."""
    return "release" if response[0][0][1] else "prerelease"


def test_radio_response_shape_drives_channel_toggle(qapp):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QRadioButton
    from PyReconstruct.modules.gui.dialog.quick_dialog import InputField

    def field_response(selected_index):
        """Build the radio exactly as quick_dialog does and return its
        InputField response (the inner [(label, checked), ...] list)."""
        w = QWidget()
        layout = QVBoxLayout()
        for i, label in enumerate(("Release (recommended)",
                                   "Pre-release (experimental) — try upcoming features early")):
            b = QRadioButton(label, w)
            b.setChecked(i == selected_index)
            layout.addWidget(b)
        w.setLayout(layout)
        r, ok = InputField("radio", w).getResponse()
        assert ok
        return r

    # QuickDialog wraps each field's response in `self.responses` (a tuple of
    # per-field responses); the updates widget has just the radio, so it's field 0.
    resp_release = (field_response(0),)
    resp_prerelease = (field_response(1),)
    # shape: list of (label, isChecked) with Release first
    assert [c for _, c in resp_release[0]] == [True, False]
    assert [c for _, c in resp_prerelease[0]] == [False, True]
    # and the all_options mapping resolves each to the right channel, both ways
    assert _channel_from_radio_response(resp_release) == "release"
    assert _channel_from_radio_response(resp_prerelease) == "prerelease"


def test_default_channel_is_stable():
    """A fresh install must default to the stable channel."""
    from PyReconstruct.modules.datatypes.default_settings import default_settings
    assert default_settings["update_channel"] == "release"
