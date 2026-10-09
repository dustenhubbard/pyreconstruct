"""The frozen macOS app ejects the installer image it was copied from.

No real hdiutil and no real /Volumes: the "volumes" are temp folders and
hdiutil is a fake that answers ``info -plist`` and records each detach.
"""

import plistlib
import subprocess

import pytest

from PyReconstruct.modules.backend.func import installer_image as II

BID = "edu.utexas.synapseweb.pyreconstruct"
VER = "1.25.0"


def make_app(parent, name="PyReconstruct", bid=BID, ver=VER):
    app = parent / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    exe = app / "Contents" / "MacOS" / name
    exe.write_text("")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": bid, "PyReconstructVersion": ver,
                       "CFBundleVersion": "1.25.0"}, f)
    return exe


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


def image(mount, writeable=False):
    return {"writeable": writeable, "system-entities": [
        {"dev-entry": "/dev/disk9"},
        {"dev-entry": "/dev/disk9s1", "mount-point": str(mount)},
    ]}


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setenv("PYRECON_FORCE_FROZEN", "1")


@pytest.fixture
def layout(tmp_path):
    """An installed app in Applications and a mounted image holding its twin."""
    installed = make_app(tmp_path / "Applications")
    volume = tmp_path / "Volumes" / "PyReconstruct"
    make_app(volume)
    (volume / "Applications").symlink_to(tmp_path / "Applications")
    return installed, volume


def run(exe, hd, platform="darwin"):
    return II.eject_installer_image(platform=platform, executable=str(exe), hdiutil=hd)


def test_ejects_the_matching_installer_image(frozen, layout):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == [str(volume)]
    assert hd.detached == [str(volume)]


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
    volume = tmp_path / "Volumes" / "PyReconstruct"
    make_app(volume, bid=bid, ver=ver)
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
