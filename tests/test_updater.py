"""Unit tests for the in-app updater's pure functions (no network).

The updater backend was written to be testable in isolation (stdlib + packaging
only, no Qt). These pin the selection/version/checksum logic so the update path
can't silently regress.
"""
import pytest
from packaging.version import Version

from PyReconstruct.modules.backend.updater import updater as U
from PyReconstruct.modules.backend.updater import install_info as II


# ---- fixtures ---------------------------------------------------------------
def _rel(tag, *, prerelease=False, draft=False, assets=()):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft,
            "assets": [{"name": n, "browser_download_url": f"https://x/{n}"} for n in assets]}

RELEASES = [
    _rel("prerelease", prerelease=True, assets=["PyReconstruct-1.21.dev3-Windows-x86_64.exe"]),
    _rel("v1.20.0", assets=["PyReconstruct-1.20.0-Windows-x86_64.exe",
                            "PyReconstruct-1.20.0-Windows-x86_64.exe.sha256",
                            "PyReconstruct-1.20.0-macOS-arm64.dmg"]),
    _rel("v1.19.0", assets=["PyReconstruct-1.19.0-Windows-x86_64.exe"]),
]


# ---- pick_release -----------------------------------------------------------
def test_pick_release_release_channel_skips_prerelease_and_draft():
    r = U.pick_release(RELEASES, "release")
    assert r["tag_name"] == "v1.20.0"

def test_pick_release_prerelease_picks_newest_over_stale_rolling_tag():
    # The pre-release channel selects the newest prerelease-flagged release
    # (GitHub returns newest-first). A newer semver pre-release must win over a
    # stale rolling 'prerelease' release rather than being shadowed by it.
    rels = [
        _rel("v1.20.4-rc.1", prerelease=True),
        _rel("prerelease", prerelease=True),
        _rel("v1.20.0"),
    ]
    assert U.pick_release(rels, "prerelease")["tag_name"] == "v1.20.4-rc.1"

def test_pick_release_prerelease_falls_back_to_newest_prerelease():
    rels = [_rel("v1.20.0"), _rel("v1.21.0rc1", prerelease=True)]
    assert U.pick_release(rels, "prerelease")["tag_name"] == "v1.21.0rc1"

@pytest.mark.parametrize("legacy,canonical", [("stable", "release"), ("edge", "prerelease")])
def test_pick_release_maps_legacy_channels(legacy, canonical):
    assert U.pick_release(RELEASES, legacy) == U.pick_release(RELEASES, canonical)

def test_pick_release_excludes_drafts():
    rels = [_rel("v2.0.0", draft=True), _rel("v1.20.0")]
    assert U.pick_release(rels, "release")["tag_name"] == "v1.20.0"

def test_pick_release_empty():
    assert U.pick_release([], "release") is None
    assert U.pick_release(None, "prerelease") is None


# ---- pick_asset -------------------------------------------------------------
def test_pick_asset_matches_platform_and_skips_sha256():
    rel = U.pick_release(RELEASES, "release")
    a = U.pick_asset(rel, "Windows-x86_64")
    assert a["name"] == "PyReconstruct-1.20.0-Windows-x86_64.exe"

def test_pick_asset_picks_macos():
    rel = U.pick_release(RELEASES, "release")
    assert U.pick_asset(rel, "macOS-arm64")["name"].endswith("macOS-arm64.dmg")

def test_pick_asset_no_match_or_no_release():
    rel = U.pick_release(RELEASES, "release")
    assert U.pick_asset(rel, "Linux-x86_64") is None
    assert U.pick_asset(None, "Windows-x86_64") is None


# A release that ships BOTH macOS arches (the dual-runner CI build): each arch
# must resolve to its own dmg with no cross-arch mismatch. This is the guarantee
# the substring match in pick_asset relies on -- "x86_64" and "arm64" are not
# substrings of each other, and the "macOS-" label keeps the Windows x86_64
# asset from matching a macOS tag -- so an Intel Mac never offers the arm64 dmg
# and an Apple Silicon Mac never offers the x86_64 dmg.
_DUAL_MAC_RELEASE = _rel(
    "v1.21.0",
    assets=[
        "PyReconstruct-1.21.0-Windows-x86_64-Setup.exe",
        "PyReconstruct-1.21.0-Windows-x86_64-Setup.exe.sha256",
        "PyReconstruct-1.21.0-macOS-arm64.dmg",
        "PyReconstruct-1.21.0-macOS-arm64.dmg.sha256",
        "PyReconstruct-1.21.0-macOS-x86_64.dmg",
        "PyReconstruct-1.21.0-macOS-x86_64.dmg.sha256",
    ],
)

@pytest.mark.parametrize("tag,expected", [
    ("macOS-arm64",  "PyReconstruct-1.21.0-macOS-arm64.dmg"),
    ("macOS-x86_64", "PyReconstruct-1.21.0-macOS-x86_64.dmg"),
])
def test_pick_asset_dual_macos_arches_no_cross_match(tag, expected):
    a = U.pick_asset(_DUAL_MAC_RELEASE, tag)
    assert a["name"] == expected
    assert not a["name"].endswith(".sha256")

def test_pick_asset_intel_mac_tag_does_not_grab_arm64_or_windows():
    # End-to-end-ish: the running-platform tag an Intel Mac would compute.
    a = U.pick_asset(_DUAL_MAC_RELEASE, "macOS-x86_64")
    assert "arm64" not in a["name"] and "Windows" not in a["name"]

def test_pick_asset_arm64_only_release_gives_intel_mac_no_false_update():
    # The Intel build leg is additive: if it is unavailable, a release ships
    # arm64-only. An Intel Mac (tag macOS-x86_64) must then get NO asset, never
    # the arm64 dmg -- arm64 can't run on Intel (Rosetta translates x86_64 ->
    # arm64, not the reverse), so a false match would be an unrunnable download.
    rel = U.pick_release(RELEASES, "release")  # v1.20.0: macOS-arm64 dmg only
    assert U.pick_asset(rel, "macOS-x86_64") is None
    assert U.pick_asset(rel, "macOS-arm64")["name"].endswith("macOS-arm64.dmg")


# ---- asset_version ----------------------------------------------------------
@pytest.mark.parametrize("name,ver", [
    ("PyReconstruct-1.20.0-Windows-x86_64.exe", "1.20.0"),
    ("PyReconstruct-1.21.dev3-macOS-arm64.dmg", "1.21.dev3"),
    ("PyReconstruct-2.0.0rc1-Linux-x86_64.AppImage", "2.0.0rc1"),
])
def test_asset_version_parses(name, ver):
    assert U.asset_version(name) == Version(ver)

@pytest.mark.parametrize("name", ["", "garbage.exe", "PyReconstruct-notaver-Windows-x86_64.exe", None])
def test_asset_version_bad(name):
    assert U.asset_version(name) is None


# ---- compare_versions -------------------------------------------------------
@pytest.mark.parametrize("remote,local,expected", [
    ("1.21.0", "1.20.0", "newer"),
    ("1.20.0", "1.20.0", "same"),
    ("1.19.0", "1.20.0", "older"),
])
def test_compare_versions(remote, local, expected):
    assert U.compare_versions(Version(remote), Version(local)) == expected

def test_compare_versions_ignores_local_dirty_suffix():
    # setuptools-scm dirty build at the same commit must NOT read as a downgrade
    assert U.compare_versions(Version("1.20.0"), Version("1.20.0+g1a2b3c4.d20260627")) == "same"

def test_compare_versions_unknown_on_none():
    assert U.compare_versions(None, Version("1.20.0")) == "unknown"
    assert U.compare_versions(Version("1.20.0"), None) == "unknown"


# ---- fetch_checksum (monkeypatched network) ---------------------------------
def test_fetch_checksum_sibling_sha256(monkeypatch):
    monkeypatch.setattr(U, "_download_text", lambda url, timeout=15: "abc123  PyReconstruct-1.20.0-Windows-x86_64.exe\n")
    rel = U.pick_release(RELEASES, "release")
    status, digest = U.fetch_checksum(rel, "PyReconstruct-1.20.0-Windows-x86_64.exe")
    assert status == "ok" and digest == "abc123"

def test_fetch_checksum_manifest(monkeypatch):
    rel = _rel("v1.20.0", assets=["PyReconstruct-1.20.0-Windows-x86_64.exe", "SHA256SUMS"])
    monkeypatch.setattr(U, "_download_text",
                        lambda url, timeout=15: "deadbeef *PyReconstruct-1.20.0-Windows-x86_64.exe\nother 0\n")
    status, digest = U.fetch_checksum(rel, "PyReconstruct-1.20.0-Windows-x86_64.exe")
    assert status == "ok" and digest == "deadbeef"

def test_fetch_checksum_manifest_missing_entry(monkeypatch):
    rel = _rel("v1.20.0", assets=["PyReconstruct-1.20.0-Windows-x86_64.exe", "SHA256SUMS"])
    monkeypatch.setattr(U, "_download_text", lambda url, timeout=15: "deadbeef something-else\n")
    assert U.fetch_checksum(rel, "PyReconstruct-1.20.0-Windows-x86_64.exe")[0] == "missing"

def test_fetch_checksum_none_published():
    rel = _rel("v1.20.0", assets=["PyReconstruct-1.20.0-Windows-x86_64.exe"])
    assert U.fetch_checksum(rel, "PyReconstruct-1.20.0-Windows-x86_64.exe") == ("missing", None)

def test_fetch_checksum_published_but_unfetchable_is_error(monkeypatch):
    def boom(url, timeout=15):
        raise OSError("network down")
    monkeypatch.setattr(U, "_download_text", boom)
    rel = U.pick_release(RELEASES, "release")  # has the .sha256 sibling
    assert U.fetch_checksum(rel, "PyReconstruct-1.20.0-Windows-x86_64.exe") == ("error", None)


# ---- install_info platform tags ---------------------------------------------
@pytest.mark.parametrize("machine,expected", [
    ("AMD64", "x86_64"), ("x86_64", "x86_64"), ("arm64", "arm64"),
    ("aarch64", "arm64"), ("weird", "weird"),
])
def test_arch_key(monkeypatch, machine, expected):
    monkeypatch.setattr(II._platform, "machine", lambda: machine)
    assert II.arch_key() == expected

def test_platform_asset_tag_shape():
    tag = II.platform_asset_tag()
    label, _, arch = tag.partition("-")
    assert label in ("Windows", "macOS", "Linux") and arch

@pytest.mark.parametrize("machine,expected_dmg", [
    ("x86_64", "PyReconstruct-1.21.0-macOS-x86_64.dmg"),
    ("arm64",  "PyReconstruct-1.21.0-macOS-arm64.dmg"),
])
def test_platform_asset_tag_drives_pick_asset_on_macos(monkeypatch, machine, expected_dmg):
    # Simulate the running machine: macOS on the given CPU arch. The tag the app
    # computes must select that arch's dmg out of a dual-arch release.
    monkeypatch.setattr(II.sys, "platform", "darwin")
    monkeypatch.setattr(II._platform, "machine", lambda: machine)
    tag = II.platform_asset_tag()
    assert U.pick_asset(_DUAL_MAC_RELEASE, tag)["name"] == expected_dmg
