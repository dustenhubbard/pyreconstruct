"""The frozen macOS app ejects the installer image it was copied from.

No real hdiutil and no real /Volumes: the "volumes" are temp folders and
hdiutil is a fake that answers ``info -plist`` and records each detach.
"""

import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.func import installer_image as II

BID = "edu.utexas.synapseweb.pyreconstruct"
VER = "1.25.0"


def make_app(parent, name="PyReconstruct", bid=BID, ver=VER):
    app = parent / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    exe = app / "Contents" / "MacOS" / name
    exe.write_text("")
    info = {"CFBundleIdentifier": bid, "CFBundleVersion": "1.25.0"}
    if ver is not None:
        info["PyReconstructVersion"] = ver
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    return exe


def make_installer(volume, guide=False, **app):
    """A volume laid out the way make_dmg.sh builds the release image."""
    make_app(volume, **app)
    (volume / "Applications").symlink_to("/Applications")
    (volume / ".DS_Store").write_bytes(b"")
    (volume / ".background.tiff").write_bytes(b"")
    if guide:
        (volume / II.GUIDE).write_text("<html></html>")
    return volume


class FakeHdiutil:
    def __init__(self, images, detach_error=None, info_error=None):
        self.images = images
        self.detach_error = detach_error
        self.info_error = info_error
        self.detached = []

    def __call__(self, args):
        if args == ["info", "-plist"]:
            if self.info_error:
                raise self.info_error
            return plistlib.dumps({"images": self.images})
        assert args[0] == "detach" and len(args) == 2, args
        if self.detach_error:
            raise self.detach_error
        self.detached.append(args[1])
        return b""


def image(*mounts, writeable=False):
    entities = [{"dev-entry": "/dev/disk9"}]
    entities += [{"dev-entry": f"/dev/disk9s{i}", "mount-point": str(m)}
                 for i, m in enumerate(mounts, 1)]
    return {"writeable": writeable, "system-entities": entities}


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setenv("PYRECON_FORCE_FROZEN", "1")


@pytest.fixture
def layout(tmp_path):
    """An installed app in Applications and a mounted image holding its twin."""
    installed = make_app(tmp_path / "Applications")
    volume = make_installer(tmp_path / "Volumes" / "PyReconstruct")
    return installed, volume


def run(exe, hd, platform="darwin", **kw):
    return II.eject_installer_image(platform=platform, executable=str(exe),
                                    hdiutil=hd, **kw)


def test_ejects_the_matching_installer_image(frozen, layout):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == [str(volume)]
    assert hd.detached == [str(volume)]


def test_ejects_an_installer_image_with_the_first_launch_guide(frozen, tmp_path):
    installed = make_app(tmp_path / "Applications")
    volume = make_installer(tmp_path / "Volumes" / "PyReconstruct", guide=True)
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == [str(volume)]


def test_leaves_other_images_mounted(frozen, layout, tmp_path):
    installed, volume = layout
    other = tmp_path / "Volumes" / "Something"
    other.mkdir()
    (other / "readme.txt").write_text("x")
    hd = FakeHdiutil([image(other), image(volume)])
    assert run(installed, hd) == [str(volume)]


def test_never_ejects_the_image_the_app_runs_from(frozen, layout):
    _installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(volume / "PyReconstruct.app" / "Contents" / "MacOS" / "PyReconstruct", hd) == []
    assert hd.detached == []


def test_translocated_app_ejects_nothing(frozen, layout, tmp_path):
    _installed, volume = layout
    exe = make_app(tmp_path / "private" / "var" / "AppTranslocation" / "ABC" / "d")
    hd = FakeHdiutil([image(volume)])
    assert run(exe, hd) == []


def test_writable_image_is_never_a_candidate(frozen, layout):
    installed, volume = layout
    hd = FakeHdiutil([image(volume, writeable=True)])
    assert run(installed, hd) == []


@pytest.mark.parametrize("bid,ver", [
    (BID, "1.24.0"),                 # an older copy, with a newer image open
    (BID + ".dev", VER),             # the other flavor
])
def test_a_different_app_on_the_image_is_left_alone(frozen, tmp_path, bid, ver):
    installed = make_app(tmp_path / "Applications")
    volume = make_installer(tmp_path / "Volumes" / "PyReconstruct", bid=bid, ver=ver)
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []


@pytest.mark.parametrize("change", [
    "app only",            # a backup of the app, nothing else at the root
    "extra file",          # the installer layout plus a user's file
    "extra app",           # two apps at the root
    "link elsewhere",      # Applications is not the /Applications link
    "folder not link",     # Applications is a real folder
])
def test_a_backup_of_the_same_version_is_not_an_installer(frozen, tmp_path, change):
    installed = make_app(tmp_path / "Applications")
    volume = tmp_path / "Volumes" / "Backup"
    if change == "app only":
        make_app(volume)
    elif change == "link elsewhere":
        make_app(volume)
        (volume / "Applications").symlink_to(tmp_path / "Applications")
    elif change == "folder not link":
        make_app(volume)
        (volume / "Applications").mkdir()
    else:
        make_installer(volume)
        if change == "extra file":
            (volume / "notes.txt").write_text("x")
        else:
            make_app(volume, name="PyReconstruct copy")
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []
    assert hd.detached == []


def test_two_installer_images_eject_neither(frozen, tmp_path, capsys):
    installed = make_app(tmp_path / "Applications")
    one = make_installer(tmp_path / "Volumes" / "PyReconstruct")
    two = make_installer(tmp_path / "Volumes" / "PyReconstruct 1")
    hd = FakeHdiutil([image(one), image(two)])
    assert run(installed, hd) == []
    assert hd.detached == []
    assert "2 candidates, ejecting none" in capsys.readouterr().err


def test_a_sibling_volume_of_the_running_apps_image_is_left_alone(frozen, tmp_path):
    # hdiutil detach takes the whole image, so a second volume on the image
    # the app runs from must not qualify.
    running = tmp_path / "Volumes" / "Work"
    exe = make_app(running)
    sibling = make_installer(tmp_path / "Volumes" / "PyReconstruct")
    hd = FakeHdiutil([image(running, sibling)])
    assert run(exe, hd) == []
    assert hd.detached == []


def test_an_image_with_two_volumes_is_left_alone(frozen, layout, tmp_path):
    installed, volume = layout
    other = tmp_path / "Volumes" / "Data"
    other.mkdir()
    hd = FakeHdiutil([image(volume, other)])
    assert run(installed, hd) == []


def test_a_volume_holding_a_project_is_left_alone(frozen, tmp_path):
    # A data volume carrying a copy of the app next to a series and its images.
    installed = make_app(tmp_path / "Applications")
    volume = make_installer(tmp_path / "Volumes" / "Data")
    (volume / "cells.jser").write_text("{}")
    (volume / "images").mkdir()
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []


@pytest.mark.parametrize("rel", [".cells/cells.ser", ".images", ".images/1.png"])
def test_an_open_series_or_image_folder_keeps_its_volume(frozen, layout, rel):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, protected=[str(volume / rel)]) == []
    assert hd.detached == []


def test_unrelated_protected_paths_do_not_block_the_eject(frozen, layout, tmp_path):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    protected = ["", str(tmp_path / "Projects" / "cells.jser")]
    assert run(installed, hd, protected=protected) == [str(volume)]


def test_startup_passes_the_open_series_paths(monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as MW

    sent = []
    monkeypatch.setattr(II, "eject_installer_image_in_background", sent.append)
    series = SimpleNamespace(jser_fp="/V/cells.jser", filepath="/V/.cells/cells.ser",
                             src_dir="/V/images", zarr_overlay_fp=None)
    window = SimpleNamespace(series=series,
                             field=SimpleNamespace(section=SimpleNamespace(src_fp="/V/images/1.png")))
    MW.MainWindow.ejectInstallerImageStartup(window)
    assert sent == [["/V/cells.jser", "/V/.cells/cells.ser", "/V/images", "/V/images/1.png"]]


def test_startup_ejects_nothing_when_the_series_cannot_be_read(monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as MW

    sent = []
    monkeypatch.setattr(II, "eject_installer_image_in_background", sent.append)
    MW.MainWindow.ejectInstallerImageStartup(SimpleNamespace(series=None))
    assert sent == []


@pytest.mark.parametrize("missing", ["candidate", "running app"])
def test_pyreconstruct_version_is_required(frozen, tmp_path, missing):
    installed = make_app(tmp_path / "Applications",
                         ver=None if missing == "running app" else VER)
    volume = make_installer(tmp_path / "Volumes" / "PyReconstruct",
                            ver=None if missing == "candidate" else VER)
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []


def test_only_on_macos(frozen, layout):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, platform="win32") == []
    assert run(installed, hd, platform="linux") == []
    assert hd.detached == []


def test_not_from_source(monkeypatch, layout):
    monkeypatch.delenv("PYRECON_FORCE_FROZEN", raising=False)
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []


def test_not_outside_an_app_bundle(frozen, layout, tmp_path):
    _installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(tmp_path / "bin" / "python3", hd) == []


def test_busy_volume_is_logged_not_raised(frozen, layout, capsys):
    installed, volume = layout
    busy = subprocess.CalledProcessError(16, ["hdiutil", "detach"], stderr=b"Resource busy")
    hd = FakeHdiutil([image(volume)], detach_error=busy)
    assert run(installed, hd) == []
    err = capsys.readouterr().err
    assert f"could not eject {volume}" in err and "Resource busy" in err


def test_hdiutil_failure_is_logged_not_raised(frozen, layout, capsys):
    installed, _volume = layout
    hd = FakeHdiutil([], info_error=FileNotFoundError("hdiutil"))
    assert run(installed, hd) == []
    assert "installer image: skipped" in capsys.readouterr().err
