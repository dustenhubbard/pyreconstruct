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
        self.timeouts = []

    def __call__(self, args, timeout=None):
        self.timeouts.append(timeout)
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
def test_the_file_to_open_keeps_its_volume(frozen, layout, rel):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, open_paths=[str(volume / rel)]) == []
    assert hd.detached == []


def test_unrelated_open_paths_do_not_block_the_eject(frozen, layout, tmp_path):
    installed, volume = layout
    hd = FakeHdiutil([image(volume)])
    paths = ["", str(tmp_path / "Projects" / "cells.jser")]
    assert run(installed, hd, open_paths=paths) == [str(volume)]


def test_an_open_path_in_other_letter_case_keeps_its_volume(frozen, layout):
    # HFS+ and default APFS ignore case, so this names the same folder.
    installed, volume = layout
    other_case = volume.parent / volume.name.swapcase() / "PyReconstruct.app"
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd, open_paths=[str(other_case)]) == []
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


# The hidden root entries an installer image may hold.

@pytest.mark.parametrize("name", [
    ".DS_Store", ".background.tiff", ".background.png", ".VolumeIcon.icns",
    ".fseventsd", ".Trashes", ".Spotlight-V100",
])
def test_hidden_entries_dmgbuild_and_macos_write_are_allowed(frozen, layout, name):
    installed, volume = layout
    entry = volume / name
    if name in (".fseventsd", ".Trashes", ".Spotlight-V100"):
        entry.mkdir()
    elif not entry.exists():
        entry.write_bytes(b"")
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == [str(volume)]


@pytest.mark.parametrize("name,folder", [
    (".cells", True),         # the hidden folder a series keeps beside its .jser
    (".images", True),
    (".notes.txt", False),
])
def test_a_stray_hidden_root_entry_blocks_the_eject(frozen, layout, name, folder):
    installed, volume = layout
    if folder:
        (volume / name).mkdir()
        (volume / name / "1.png").write_bytes(b"")
    else:
        (volume / name).write_text("x")
    hd = FakeHdiutil([image(volume)])
    assert run(installed, hd) == []
    assert hd.detached == []


# Every hdiutil call shares one time budget.

class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_each_call_gets_what_is_left_of_the_budget(frozen, layout):
    installed, volume = layout
    clock = Clock()

    class Slow(FakeHdiutil):
        def __call__(self, args, timeout):
            clock.now += 1.5
            return super().__call__(args, timeout)

    hd = Slow([image(volume)])
    assert run(installed, hd, budget=4, clock=clock) == [str(volume)]
    assert hd.timeouts == [4, 2.5]


def test_no_detach_once_the_budget_is_spent(frozen, layout, capsys):
    installed, volume = layout
    clock = Clock()

    class Slow(FakeHdiutil):
        def __call__(self, args, timeout):
            clock.now += timeout          # info used all of it
            return super().__call__(args, timeout)

    hd = Slow([image(volume)])
    assert run(installed, hd, budget=4, clock=clock) == []
    assert hd.detached == []
    assert hd.timeouts == [4]
    assert f"could not eject {volume}" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="needs a shell script on PATH")
def test_a_slow_hdiutil_is_killed_at_its_timeout(tmp_path, monkeypatch):
    # A stand-in hdiutil that never answers. It records its own process id,
    # so the test can check that the child it started is gone.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "pid"
    fake = bin_dir / "hdiutil"
    fake.write_text(f'#!/bin/sh\necho $$ > "{pid_file}"\nexec sleep 30\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        II._hdiutil(["info", "-plist"], 0.5)
    assert time.monotonic() - start < 10
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


# run.py runs the eject once, before the first window.

@pytest.fixture
def launch(monkeypatch, tmp_path):
    """runPyReconstruct with stand-ins for Qt, the window and settings."""
    import PyReconstruct.run as run_mod
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.backend.updater import updater
    from PyReconstruct.modules.constants import settings_domain
    from PyReconstruct.modules.gui import utils
    from PyReconstruct.modules.gui.main import first_launch

    events = []

    class App:
        def __init__(self, argv):
            pass

        def installEventFilter(self, f):
            pass

        def processEvents(self):
            pass

        def setStyle(self, style):
            pass

        def exec(self):
            return 0

    class Window:
        restarts = 1

        def __init__(self, filename):
            events.append(("window", filename))
            self.restart_mainwindow = Window.restarts > 0
            Window.restarts -= 1
            self.series = SimpleNamespace(isWelcomeSeries=lambda: True)

    for module, name, value in [
        (logging_setup, "install_file_logging", lambda: None),
        (settings_domain, "fold_flavor_settings_once", lambda: None),
        (first_launch, "reset_whats_new_popup_startup", lambda: None),
        (utils, "MenuShortcutSpacingStyle", lambda: None),
        (updater, "report_update_started", lambda: None),
        (run_mod, "QApplication", App),
        (run_mod.main, "MainWindow", Window),
        (run_mod, "importlib", SimpleNamespace(reload=lambda m: m)),
    ]:
        monkeypatch.setattr(module, name, value)

    installed = make_app(tmp_path / "Applications")
    volume = make_installer(tmp_path / "Volumes" / "PyReconstruct")
    monkeypatch.setenv("PYRECON_FORCE_FROZEN", "1")
    monkeypatch.setattr(II, "sys", SimpleNamespace(platform="darwin",
                                                   executable=str(installed)))
    return SimpleNamespace(run=run_mod.runPyReconstruct, events=events,
                           volume=volume)


def test_launch_ejects_before_the_window_and_not_on_restart(launch, monkeypatch):
    hd = FakeHdiutil([image(launch.volume)])

    def recording(args, timeout):
        launch.events.append(("hdiutil", args[0]))
        return hd(args, timeout)

    monkeypatch.setattr(II, "_hdiutil", recording)
    launch.run()
    assert launch.events == [("hdiutil", "info"), ("hdiutil", "detach"),
                             ("window", None), ("window", None)]
    assert hd.detached == [str(launch.volume)]


def test_launch_keeps_the_image_holding_the_file_to_open(launch, monkeypatch):
    jser = launch.volume / "PyReconstruct.app" / "Contents" / "Resources" / "cells.jser"
    hd = FakeHdiutil([image(launch.volume)])
    monkeypatch.setattr(II, "_hdiutil", hd)
    launch.run(str(jser))
    assert hd.detached == []
    assert launch.events == [("window", str(jser))] * 2


def test_launch_never_detaches_after_a_timeout(launch, monkeypatch):
    # hdiutil info outlasts the whole budget; the window opens and no detach
    # is ever asked for, then or later.
    hd = FakeHdiutil([image(launch.volume)])

    def slow(args, timeout):
        launch.events.append(("hdiutil", args[0]))
        time.sleep(timeout + 0.05)
        return hd(args, timeout)

    monkeypatch.setattr(II, "_hdiutil", slow)
    monkeypatch.setattr(II, "_BUDGET", 0.2)
    launch.run()
    time.sleep(0.3)
    assert launch.events == [("hdiutil", "info"), ("window", None), ("window", None)]
    assert hd.detached == []
