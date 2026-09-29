"""No client, old or new, ever takes an in-place update file for its installer.

In-place updates add files to every release: an update archive, per-platform
file trees, a manifest, and a signed checksum list. Clients already in the
field pick their installer by looking for the first asset whose name contains
the platform tag ('Windows-x86_64', 'macOS-arm64', 'macOS-x86_64'), and the
GitHub API lists assets by name, case-insensitively. If a new file's name
contained a tag and sorted before the installer, an old client would download
it and hand it to the OS as an installer.

The planned names use lowercase platform tokens so the old substring match can
never see them. The 1.23.0 matcher is copied here verbatim (it is what stable
users run today) and checked against every planned name, alone and inside a
full, name-sorted asset list, next to the current matcher. The current matcher
also accepts only installer suffixes, so a future file that did carry a tag
would still not be picked by clients from this version on.
"""
import re

import pytest
from packaging.version import InvalidVersion, Version

from PyReconstruct.modules.backend.updater import updater as U


# --- The 1.23.0 matcher, verbatim from v1.23.0:updater.py -------------------

_ASSET_VERSION_RE = re.compile(r"PyReconstruct-(?P<ver>.+?)-(?:Windows|macOS|Linux)\b")


def old_pick_asset(release, platform_tag):
    if not release:
        return None
    for a in release.get("assets", []):
        name = a.get("name", "")
        if platform_tag in name and not name.endswith(".sha256"):
            return a
    return None


def old_asset_version(asset_name):
    m = _ASSET_VERSION_RE.match(asset_name or "")
    if not m:
        return None
    try:
        return Version(m.group("ver"))
    except InvalidVersion:
        return None


# --- Asset names ------------------------------------------------------------

STABLE = "1.24.0"
NIGHTLY = "1.24.0.dev20260928"
FLAVORS = [(STABLE, ""), (NIGHTLY, "-Dev")]
PLATFORM_TAGS = ["Windows-x86_64", "macOS-arm64", "macOS-x86_64"]
LINUX_TAGS = ["Linux-x86_64", "Linux-arm64"]


def installers(ver, dev):
    """The installers a release ships today, keyed by the tag that picks each."""
    return {
        "Windows-x86_64": f"PyReconstruct-{ver}-Windows-x86_64{dev}-Setup.exe",
        "macOS-arm64": f"PyReconstruct-{ver}-macOS-arm64{dev}.dmg",
        "macOS-x86_64": f"PyReconstruct-{ver}-macOS-x86_64{dev}.dmg",
        "Linux": f"PyReconstruct-{ver}-Linux-installer{dev}.tar.gz",
    }


def planned(ver, dev):
    """Every file the in-place update design adds to a release."""
    return [
        f"PyReconstruct-{ver}-update-windows-x86_64{dev}.tar.xz",
        f"PyReconstruct-{ver}-update-windows-x86_64{dev}.tree.json",
        f"PyReconstruct-{ver}-update-macos-arm64{dev}.tree.json",
        f"PyReconstruct-{ver}-update-macos-x86_64{dev}.tree.json",
        "update-manifest.json",
        "SHA256SUMS",
        "SHA256SUMS.minisig",
    ]


def full_release(ver, dev):
    """Today's assets plus the planned ones, each with its .sha256, in API order."""
    files = list(installers(ver, dev).values()) + planned(ver, dev)
    names = files + [f"{n}.sha256" for n in files]
    return _rel(ver, sorted(names, key=str.lower))


def _rel(ver, names):
    return {
        "tag_name": f"v{ver}",
        "prerelease": ver == NIGHTLY,
        "draft": False,
        "assets": [{"name": n, "browser_download_url": f"https://github.com/x/{n}"}
                   for n in names],
    }


def _new_pick(release, tag, dev):
    return U.pick_asset(release, tag, dev=bool(dev))


ALL_PLANNED = sorted({n for ver, dev in FLAVORS for n in planned(ver, dev)})


# --- The planned files are never picked --------------------------------------

@pytest.mark.parametrize("name", ALL_PLANNED)
@pytest.mark.parametrize("tag", PLATFORM_TAGS + LINUX_TAGS)
def test_no_matcher_picks_a_planned_file(name, tag):
    for candidate in (name, f"{name}.sha256"):
        release = _rel(STABLE, [candidate])
        assert old_pick_asset(release, tag) is None
        assert U.pick_asset(release, tag, dev=False) is None
        assert U.pick_asset(release, tag, dev=True) is None


@pytest.mark.parametrize("name", ALL_PLANNED)
def test_no_planned_file_parses_as_a_versioned_asset(name):
    assert old_asset_version(name) is None
    assert U.asset_version(name) is None


# --- Full releases still resolve to the installer ----------------------------

def test_the_full_list_is_in_api_order():
    """GitHub sorts by name ignoring case: Linux, macOS, update, Windows."""
    names = [a["name"] for a in full_release(STABLE, "")["assets"]]
    assert names == sorted(names, key=str.lower)
    first_update = names.index(f"PyReconstruct-{STABLE}-update-macos-arm64.tree.json")
    windows = names.index(installers(STABLE, "")["Windows-x86_64"])
    assert first_update < windows


@pytest.mark.parametrize("ver,dev", FLAVORS)
@pytest.mark.parametrize("tag", PLATFORM_TAGS)
@pytest.mark.parametrize("order", ["api", "reversed"])
def test_both_matchers_pick_the_installer_from_a_full_release(ver, dev, tag, order):
    release = full_release(ver, dev)
    if order == "reversed":
        release["assets"] = release["assets"][::-1]
    expected = installers(ver, dev)[tag]

    assert old_pick_asset(release, tag)["name"] == expected
    assert _new_pick(release, tag, dev)["name"] == expected
    assert old_asset_version(expected) == Version(ver)
    assert U.asset_version(expected) == Version(ver)


@pytest.mark.parametrize("ver,dev", FLAVORS)
@pytest.mark.parametrize("tag", PLATFORM_TAGS)
def test_the_current_matcher_never_crosses_flavors(ver, dev, tag):
    other = "" if dev else "-Dev"
    assert U.pick_asset(full_release(ver, dev), tag, dev=bool(other)) is None


@pytest.mark.parametrize("ver,dev", FLAVORS)
@pytest.mark.parametrize("tag", LINUX_TAGS)
def test_linux_is_unchanged(ver, dev, tag):
    """The Linux tarball is named 'Linux-installer', never 'Linux-<arch>'.

    So neither matcher has ever offered Linux an asset, and adding the planned
    files does not change that.
    """
    release = full_release(ver, dev)
    assert old_pick_asset(release, tag) is None
    assert _new_pick(release, tag, dev) is None
    linux = installers(ver, dev)["Linux"]
    assert old_asset_version(linux) == Version(ver)
    assert U.asset_version(linux) == Version(ver)


# --- The current matcher takes installers only ------------------------------

@pytest.mark.parametrize("dev", ["", "-Dev"])
@pytest.mark.parametrize("tag,name", [
    ("Windows-x86_64", "PyReconstruct-{v}-Windows-x86_64{d}.tar.xz"),
    ("Windows-x86_64", "PyReconstruct-{v}-Windows-x86_64{d}.tree.json"),
    ("Windows-x86_64", "PyReconstruct-{v}-Windows-x86_64{d}.zip"),
    ("Windows-x86_64", "PyReconstruct-{v}-Windows-x86_64{d}.exe"),
    ("macOS-arm64", "PyReconstruct-{v}-macOS-arm64{d}.tree.json"),
    ("macOS-arm64", "PyReconstruct-{v}-macOS-arm64{d}.zip"),
    ("macOS-x86_64", "PyReconstruct-{v}-macOS-x86_64{d}.dmg.minisig"),
    ("Linux-x86_64", "PyReconstruct-{v}-Linux-x86_64{d}.AppImage"),
])
def test_a_tagged_non_installer_is_never_picked(tag, name, dev):
    """Defense in depth: a future file carrying a tag still is not an installer.

    The 1.23.0 matcher would take any of these, so they must never ship; the
    current matcher refuses them, so clients from this version on are safe
    even if one did.
    """
    name = name.format(v=STABLE, d=dev)
    release = _rel(STABLE, [name, f"{name}.sha256"])
    assert old_pick_asset(release, tag)["name"] == name
    assert U.pick_asset(release, tag, dev=bool(dev)) is None


# --- What the release job writes today ---------------------------------------

@pytest.mark.parametrize("ver,dev", FLAVORS)
def test_the_files_the_release_job_adds_are_planned_names(tmp_path, ver, dev):
    """Run the release job's script on a fake dist folder and check what it adds.

    Each new file must be one of the planned names above, so every check in
    this module covers it, and neither matcher may take it from the full list.
    SHA256SUMS.minisig comes from the signing step, so its name is read from
    the workflow, and both names are the ones the updater looks for.
    """
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "release_update_files.py"
    dist = tmp_path / "dist"
    dist.mkdir()
    for name in installers(ver, dev).values():
        (dist / name).write_bytes(b"x")
        (dist / f"{name}.sha256").write_text("0" * 64 + f"  {name}\n")
    before = {p.name for p in dist.iterdir()}
    flavor = "dev" if dev else "stable"
    subprocess.run([sys.executable, str(script), str(dist), "--tag", f"v{ver}", "--flavor", flavor],
                   check=True, capture_output=True, timeout=60)
    added = {p.name for p in dist.iterdir()} - before
    workflow = (script.parents[1] / ".github" / "workflows" / "build-installers.yml").read_text()
    assert f"-m dist/{U.SUMS_ASSET} -x dist/{U.SIGNATURE_ASSET} " in workflow
    added.add(U.SIGNATURE_ASSET)
    assert added == {"update-manifest.json", "SHA256SUMS", "SHA256SUMS.minisig"}
    assert added <= set(planned(ver, dev))

    release = _rel(ver, sorted(before | added, key=str.lower))
    for tag in PLATFORM_TAGS:
        assert old_pick_asset(release, tag)["name"] == installers(ver, dev)[tag]
        assert _new_pick(release, tag, dev)["name"] == installers(ver, dev)[tag]
        for name in added:
            assert old_pick_asset(_rel(ver, [name]), tag) is None
