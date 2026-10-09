"""The frozen macOS app ejects the installer image of its own build.

No real hdiutil and no real /Volumes: the "volumes" are temp folders and
hdiutil is a fake that answers ``info -plist`` and records each detach. Each
folder under ``Volumes`` gets its own device number from the ``devices``
fixture, matched without regard to case as on HFS+ and default APFS.
"""

import os
import plistlib
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.func import installer_image as II

REAL_ST_DEV = getattr(II, "_st_dev", None)

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


@pytest.fixture(autouse=True)
def devices(monkeypatch, tmp_path):
    """Give each folder under tmp_path/Volumes its own device number."""
    volumes = str(tmp_path / "Volumes").casefold() + os.sep
    ids = {}

    def st_dev(path):
        p = os.path.abspath(path).casefold()
        if not p.startswith(volumes):
            return 0
        return ids.setdefault(p[len(volumes):].split(os.sep)[0], len(ids) + 1)

    monkeypatch.setattr(II, "_st_dev", st_dev, raising=False)


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


@pytest.mark.parametrize("rel", [
    "PyReconstruct.app/Contents/Resources/cells.jser",
    "PyReconstruct.app/Contents/Resources/images",
    "PyReconstruct.app/Contents/Resources/images/1.png",
])
def test_an_open_series_or_image_folder_keeps_its_volume(frozen, layout, rel):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, open_paths=lambda: [str(volume / rel)]) == []
    assert hd.detached == []


def test_unrelated_open_paths_do_not_block_the_eject(frozen, layout, tmp_path):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    paths = ["", str(tmp_path / "Projects" / "cells.jser")]
    assert run(installed, hd, open_paths=lambda: paths) == [str(volume)]


def test_unknown_open_paths_eject_nothing(frozen, layout):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, open_paths=lambda: None) == []
    assert hd.detached == []


def test_open_paths_are_read_after_the_image_is_found(frozen, layout):
    installed, volume = layout
    order = []

    class Recording(FakeHdiutil):
        def __call__(self, args):
            order.append(args[0])
            return super().__call__(args)

    def open_paths():
        order.append("open paths")
        return []

    assert run(installed, Recording([image(volume)]), open_paths=open_paths) == [str(volume)]
    assert order == ["info", "open paths", "detach"]


def test_an_open_path_in_other_letter_case_keeps_its_volume(frozen, layout):
    # HFS+ and default APFS ignore case, so this names the same folder.
    installed, volume = layout
    other_case = volume.parent / volume.name.swapcase() / "PyReconstruct.app"
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, open_paths=lambda: [str(other_case)]) == []
    assert hd.detached == []


def _case_insensitive(folder):
    probe = folder / "CaseProbe"
    probe.write_text("")
    return (folder / "caseprobe").exists()


def test_the_running_app_in_other_letter_case_keeps_its_volume(frozen, layout):
    _installed, volume = layout
    if not _case_insensitive(volume.parent):
        pytest.skip("needs a case-insensitive file system")
    exe = (volume.parent / volume.name.swapcase() / "PyReconstruct.app"
           / "Contents" / "MacOS" / "PyReconstruct")
    hd = FakeHdiutil([image(volume)])
    assert run(exe, hd) == []
    assert hd.detached == []


def test_device_number_of_a_missing_path_is_its_parents(tmp_path):
    assert REAL_ST_DEV(str(tmp_path / "missing" / "deeper")) == os.stat(tmp_path).st_dev


def test_device_number_ignores_letter_case_where_the_file_system_does(tmp_path):
    folder = tmp_path / "Installer"
    folder.mkdir()
    if not _case_insensitive(tmp_path):
        pytest.skip("needs a case-insensitive file system")
    assert REAL_ST_DEV(str(tmp_path / "installer")) == os.stat(folder).st_dev


def test_an_unreadable_mount_keeps_the_image(frozen, layout, monkeypatch):
    installed, volume = layout

    def st_dev(path):
        raise PermissionError(path)

    monkeypatch.setattr(II, "_st_dev", st_dev)
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []
    assert hd.detached == []


def test_open_paths_lists_the_series_files_and_images():
    from PyReconstruct.modules.gui.main import main_window as MW

    series = SimpleNamespace(jser_fp="/V/cells.jser", filepath="/V/.cells/cells.ser",
                             src_dir="/V/images", zarr_overlay_fp=None)
    window = SimpleNamespace(series=series,
                             field=SimpleNamespace(section=SimpleNamespace(src_fp="/V/images/1.png")))
    assert MW.MainWindow.openPaths(window) == [
        "/V/cells.jser", "/V/.cells/cells.ser", "/V/images", "/V/images/1.png"]


def test_open_paths_is_none_when_the_series_cannot_be_read():
    from PyReconstruct.modules.gui.main import main_window as MW

    assert MW.MainWindow.openPaths(SimpleNamespace(series=None)) is None


# The tests below run the eject against a real MainWindow. The worker is the
# real background thread; only hdiutil, the platform and the app's location
# are stand-ins, so the window's own startup handler drives it.

class HeldHdiutil(FakeHdiutil):
    """A fake hdiutil whose ``info`` waits until the test releases it."""

    def __init__(self, images):
        super().__init__(images)
        self.listing = threading.Event()
        self.release = threading.Event()

    def __call__(self, args):
        if args[0] == "info":
            self.listing.set()
            assert self.release.wait(10)
        return super().__call__(args)


@pytest.fixture
def held(monkeypatch, tmp_path, main_window):
    """A mounted installer image whose discovery the test holds open."""
    from PySide6.QtCore import QCoreApplication, QEvent

    # A window from an earlier test still has its startup timer until it is
    # deleted, and it would start a second worker here.
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    installed = make_app(tmp_path / "Applications")
    volume = make_installer(tmp_path / "Volumes" / "PyReconstruct")
    hd = HeldHdiutil([image(volume)])
    real = II.eject_installer_image
    calls = []

    def eject_once(**kw):
        # this window's startup timer may call too; one worker is enough
        calls.append(kw)
        if len(calls) > 1:
            return []
        return real(platform="darwin", executable=str(installed), hdiutil=hd, **kw)

    monkeypatch.setattr(II, "eject_installer_image", eject_once)
    monkeypatch.setattr(II, "is_frozen", lambda: True)
    monkeypatch.setattr(II, "sys", SimpleNamespace(platform="darwin",
                                                   executable=sys.executable))
    return SimpleNamespace(volume=volume, hd=hd)


def _finish(qapp, held):
    """Release discovery and run the GUI thread until the worker ends."""
    held.hd.release.set()
    deadline = time.monotonic() + 20
    while any(t.name == "eject-installer-image" for t in threading.enumerate()):
        assert time.monotonic() < deadline, "eject worker did not finish"
        qapp.processEvents()
        time.sleep(0.01)


@pytest.mark.gui
def test_window_ejects_the_installer_image(held, qapp, main_window):
    main_window.ejectInstallerImageStartup()
    assert held.hd.listing.wait(10)
    _finish(qapp, held)
    assert held.hd.detached == [str(held.volume)]


@pytest.mark.gui
def test_image_folder_changed_onto_the_image_during_discovery_keeps_it(
        held, qapp, main_window):
    images = held.volume / "PyReconstruct.app" / "Contents" / "Resources" / "images"
    images.mkdir(parents=True)
    main_window.ejectInstallerImageStartup()
    assert held.hd.listing.wait(10)
    main_window.changeSrcDir(str(images))
    _finish(qapp, held)
    assert held.hd.detached == []


@pytest.mark.gui
def test_image_folder_on_the_image_in_other_letter_case_keeps_it(
        held, qapp, main_window):
    images = (held.volume.parent / held.volume.name.swapcase()
              / "PyReconstruct.app" / "Contents" / "Resources" / "images")
    main_window.changeSrcDir(str(images))
    main_window.ejectInstallerImageStartup()
    assert held.hd.listing.wait(10)
    _finish(qapp, held)
    assert held.hd.detached == []


@pytest.mark.gui
def test_a_window_that_does_not_answer_ejects_nothing(main_window):
    # the GUI thread is busy in this test, so the queued read never runs
    box = []
    worker = threading.Thread(
        target=lambda: box.append(main_window.openPathsForWorker(timeout=0.2)))
    worker.start()
    worker.join(5)
    assert box == [None]


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
