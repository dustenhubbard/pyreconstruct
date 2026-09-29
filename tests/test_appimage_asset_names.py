"""No updater that has shipped offers a Linux AppImage as an update.

Every in-app updater matches release assets by a case-sensitive substring of
the platform tag (Windows-x86_64, macOS-arm64, macOS-x86_64, Linux-x86_64).
Up to 1.23.0 it took the first asset containing the tag, with no flavor check;
since then it also keys the flavor on the -Dev marker. The AppImages carry a
lowercase linux-x86_64 token, so neither matcher picks them on any platform,
including an AppImage build asking for Linux-x86_64. Replacing an installed
AppImage from inside the app is a separate change; until then the curl
installer is the upgrade path.
"""

import re
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.updater import updater as U

ROOT = Path(__file__).resolve().parents[1]
TAGS = ("Windows-x86_64", "macOS-arm64", "macOS-x86_64", "Linux-x86_64")
NAMES = (
    "PyReconstruct-1.24.0-linux-x86_64.AppImage",
    "PyReconstruct-1.24.0-linux-x86_64.AppImage.sha256",
    "PyReconstruct-1.25.0.dev20261001-linux-x86_64-Dev.AppImage",
    "PyReconstruct-1.25.0.dev20261001-linux-x86_64-Dev.AppImage.sha256",
)


def legacy_pick_asset(release, platform_tag):
    """The matcher in every release up to 1.23.0."""
    for a in release.get("assets", []):
        name = a.get("name", "")
        if platform_tag in name and not name.endswith(".sha256"):
            return a
    return None


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("dev", [False, True])
def test_no_matcher_picks_an_appimage(tag, dev):
    release = {"assets": [{"name": n} for n in NAMES]}
    assert U.pick_asset(release, tag, dev=dev) is None
    assert legacy_pick_asset(release, tag) is None


def test_the_build_and_the_installer_spell_the_same_names():
    build = (ROOT / "packaging" / "linux" / "make_appimage.sh").read_text()
    assert 'PyReconstruct-${PYR_PUBLIC}-linux-${ARCH}${SUFFIX}.AppImage' in build
    installer = (ROOT / "packaging" / "linux" / "install-appimage.sh").read_text()
    patterns = {("dev" if "-Dev" in p else "stable"): p
                for p in re.findall(r"ASSET_RE='([^']+)'", installer)}
    assert len(patterns) == 2
    assert re.match(patterns["stable"], NAMES[0]) and not re.match(patterns["stable"], NAMES[2])
    assert re.match(patterns["dev"], NAMES[2]) and not re.match(patterns["dev"], NAMES[0])
    assert not any(re.match(p, n) for p in patterns.values() for n in NAMES if n.endswith(".sha256"))


def test_readme_bump_moves_an_appimage_link_to_the_new_version():
    """A README link to the AppImage follows each stable release like the others."""
    import subprocess

    job = (ROOT / ".github" / "workflows" / "download-links-bump.yml").read_text()
    exprs = re.findall(r'^\s+-e "(.+)" \\$', job, re.M)
    assert len(exprs) == 3, exprs
    args = ["sed", "-E"]
    for e in exprs:
        args += ["-e", e.replace("${VERSION}", "1.25.0")]
    old = (
        "[PyReconstruct-1.24.0-linux-x86_64.AppImage]"
        "(https://github.com/dustenhubbard/PyReconstruct/releases/download/"
        "v1.24.0/PyReconstruct-1.24.0-linux-x86_64.AppImage)\n"
    )
    out = subprocess.run(args, input=old, capture_output=True, text=True, check=True).stdout
    assert out == old.replace("1.24.0", "1.25.0")


def test_release_leaves_out_an_appimage_that_failed_its_distro_tests():
    workflow = (ROOT / ".github" / "workflows" / "build-installers.yml").read_text()
    job = workflow[workflow.index("\n  release:\n"):]
    assert "needs: [build, build-linux, test-appimage, swap-windows]" in job
    hold = job.index("if: needs.test-appimage.result != 'success'")
    assert job.index("run: rm -f dist/*.AppImage dist/*.AppImage.sha256", hold) < job.index("- name: Generate checksums")
