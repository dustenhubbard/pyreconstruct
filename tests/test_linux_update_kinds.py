"""The two Linux installs update by running their installer again (#427).

install.sh builds a venv and leaves ``.pyreconstruct-install`` beside it;
install-appimage.sh downloads an AppImage and leaves ``.appimage-install``
beside it. Before this, ``install_kind`` knew only ``frozen`` and ``source``,
so an install.sh copy read as ``source`` and **Help > Check for updates...**
opened the pip prompt that ``cli.update`` then refused, and an AppImage read
as ``frozen`` and was told no installer existed for its platform.

Covered here: how each kind is detected, what the Help menu and the startup
check do for each (no source prompt, no download, the right command per
flavor), and the refusal ``cli.update`` gives.
"""

import sys

import pytest
from packaging.version import Version

from PyReconstruct import cli
from PyReconstruct.modules.backend.updater import install_info as II
from PyReconstruct.modules.backend.updater import updater as U

STABLE_CMD = "curl -fsSL https://pyreconstruct.org/install.sh | bash"
DEV_CMD = "curl -fsSL https://pyreconstruct.org/install.sh | bash -s -- --dev"
SOURCE_CMD = "curl -fsSL https://pyreconstruct.org/install-from-source.sh | bash"


def source_cmd(tag):
    """The install.sh command pinned to one release (install.sh's --ref)."""
    return f"{SOURCE_CMD} -s -- --ref {tag}"


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #

@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A clean process: not frozen, on Linux, with its own venv and data home."""
    root = tmp_path / "PyReconstruct"
    venv = root / "venv"
    (venv / "bin").mkdir(parents=True)
    data = tmp_path / "share"
    data.mkdir()
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "executable", str(venv / "bin" / "python"))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("PYRECON_FORCE_FROZEN", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(data))

    class M:
        pass

    m = M()
    m.root, m.venv, m.data, m.tmp = root, venv, data, tmp_path
    m.frozen = lambda: monkeypatch.setattr(sys, "frozen", True, raising=False)
    m.env = monkeypatch.setenv
    return m


def test_plain_source_stays_source(machine):
    assert II.install_kind() == "source"


def test_plain_frozen_stays_frozen(machine):
    machine.frozen()
    assert II.install_kind() == "frozen"


def test_the_install_sh_marker_beside_the_venv_is_a_linux_installer(machine):
    (machine.root / ".pyreconstruct-install").write_text(str(machine.root))
    assert II.install_kind() == "linux-installer"


def test_the_install_sh_marker_is_found_from_the_interpreter_path(machine, monkeypatch):
    """A prefix that says nothing still leaves the interpreter's own folder."""
    monkeypatch.setattr(sys, "prefix", str(machine.tmp / "elsewhere"))
    (machine.root / ".pyreconstruct-install").write_text(str(machine.root))
    assert II.install_kind() == "linux-installer"


def test_a_frozen_linux_build_with_appimage_set_is_an_appimage(machine):
    machine.frozen()
    machine.env("APPIMAGE", str(machine.tmp / "anywhere" / "PyReconstruct.AppImage"))
    assert II.install_kind() == "appimage"


def test_the_appimage_marker_in_the_install_folder_is_an_appimage(machine):
    machine.frozen()
    folder = machine.data / "PyReconstruct"
    folder.mkdir()
    (folder / ".appimage-install").write_text("flavor=stable\n")
    assert II.install_kind() == "appimage"


def test_the_dev_appimage_marker_is_read_from_the_dev_folder(machine):
    machine.frozen()
    machine.env("PYRECON_APP_NAME", "PyReconstruct Dev")
    (machine.data / "PyReconstruct").mkdir()
    (machine.data / "PyReconstruct" / ".appimage-install").write_text("flavor=stable\n")
    assert II.install_kind() == "frozen"   # the stable app's marker is not Dev's
    (machine.data / "PyReconstruct Dev").mkdir()
    (machine.data / "PyReconstruct Dev" / ".appimage-install").write_text("flavor=dev\n")
    assert II.install_kind() == "appimage"


def test_appimage_set_on_a_frozen_mac_build_is_still_frozen(machine, monkeypatch):
    machine.frozen()
    monkeypatch.setattr(sys, "platform", "darwin")
    machine.env("APPIMAGE", "/tmp/PyReconstruct.AppImage")
    assert II.install_kind() == "frozen"


def test_a_frozen_appimage_wins_over_a_stray_install_sh_marker(machine):
    machine.frozen()
    (machine.root / ".pyreconstruct-install").write_text(str(machine.root))
    machine.env("APPIMAGE", "/tmp/PyReconstruct.AppImage")
    assert II.install_kind() == "appimage"


def test_a_source_run_that_inherited_appimage_is_not_an_appimage(machine):
    """A terminal opened from an AppImage passes ``APPIMAGE`` to whatever it
    starts, and the AppImage's marker can sit on the same machine."""
    machine.env("APPIMAGE", "/tmp/PyReconstruct.AppImage")
    (machine.data / "PyReconstruct").mkdir()
    (machine.data / "PyReconstruct" / ".appimage-install").write_text("x\n")
    assert II.install_kind() == "source"
    (machine.root / ".pyreconstruct-install").write_text(str(machine.root))
    assert II.install_kind() == "linux-installer"


# --------------------------------------------------------------------------- #
# what the release feed offers each kind
# --------------------------------------------------------------------------- #

def _rel(tag, prerelease=False, assets=()):
    return {"tag_name": tag, "prerelease": prerelease, "draft": False,
            "html_url": f"https://github.com/x/releases/tag/{tag}",
            "assets": [{"name": n, "size": 1,
                        "browser_download_url": f"https://github.com/x/{n}"}
                       for n in assets]}


def _stable(ver, appimage=True):
    names = [f"PyReconstruct-{ver}-Linux-installer.tar.gz",
             f"PyReconstruct-{ver}-macOS-arm64.dmg"]
    if appimage:
        names += [f"PyReconstruct-{ver}-linux-x86_64.AppImage",
                  f"PyReconstruct-{ver}-linux-x86_64.AppImage.sha256"]
    return _rel(f"v{ver}", assets=names)


def _nightly(ver, appimage=True):
    names = [f"PyReconstruct-{ver}-Linux-installer-Dev.tar.gz"]
    if appimage:
        names += [f"PyReconstruct-{ver}-linux-x86_64-Dev.AppImage"]
    return _rel(f"v{ver}", prerelease=True, assets=names)


FEED = [_nightly("1.25.0.dev20261001"), _stable("1.24.0"), _stable("1.23.0")]


@pytest.fixture
def running(monkeypatch):
    def at(version):
        monkeypatch.setattr(II, "current_version", lambda: Version(version))
    return at


def test_a_stable_appimage_is_offered_the_stable_command(running):
    running("1.23.0")
    info = U.check_for_reinstall("release", "appimage", releases=FEED)
    assert (info["status"], info["remote_version"]) == ("newer", "1.24.0")
    assert info["command"] == STABLE_CMD
    assert info["asset"] is None


def test_a_dev_appimage_is_offered_the_dev_command(running):
    running("1.24.0.dev20260920")
    info = U.check_for_reinstall("prerelease", "appimage", releases=FEED)
    assert (info["status"], info["remote_version"]) == ("newer", "1.25.0.dev20261001")
    assert info["command"] == DEV_CMD


def test_a_stable_release_with_no_appimage_offers_nothing(running):
    """install-appimage.sh takes the latest stable only, so an older one
    with an AppImage is not what the command would install."""
    running("1.23.0")
    info = U.check_for_reinstall("release", "appimage",
                                 releases=[_stable("1.24.0", appimage=False), _stable("1.23.1")])
    assert info["remote_version"] is None
    assert info["release"]["tag_name"] == "v1.24.0"


def test_a_dev_appimage_takes_the_newest_nightly_that_has_one(running):
    running("1.24.0.dev20260901")
    feed = [_nightly("1.25.0.dev20261002", appimage=False), _nightly("1.25.0.dev20261001")]
    info = U.check_for_reinstall("prerelease", "appimage", releases=feed)
    assert info["remote_version"] == "1.25.0.dev20261001"


def test_an_install_sh_copy_compares_against_the_release_tag(running):
    running("1.23.1.dev4")
    info = U.check_for_reinstall("release", "linux-installer", releases=FEED)
    assert (info["status"], info["remote_version"]) == ("newer", "1.24.0")
    assert info["command"] == source_cmd("v1.24.0")


def test_the_install_sh_command_installs_the_release_it_names(running):
    """Without --ref, install.sh installs the newest main. A stable tag that
    is not on main would then install something that still reads as older,
    and the check would offer the same update again forever."""
    running("1.22.2")
    feed = [_nightly("1.23.0.dev20261001"), _stable("1.22.3")]
    stable = U.check_for_reinstall("release", "linux-installer", releases=feed)
    assert stable["remote_version"] == "1.22.3"
    assert stable["command"] == source_cmd("v1.22.3")
    nightly = U.check_for_reinstall("prerelease", "linux-installer", releases=feed)
    assert nightly["remote_version"] == "1.23.0.dev20261001"
    assert nightly["command"] == source_cmd("v1.23.0.dev20261001")


def test_install_sh_has_one_command_for_both_flavors():
    assert U.reinstall_command("linux-installer", dev=True) == SOURCE_CMD
    assert U.reinstall_command("linux-installer", dev=False) == SOURCE_CMD
    assert U.reinstall_command("linux-installer", dev=True, ref="v1.24.0") == source_cmd("v1.24.0")
    assert U.reinstall_command("appimage", ref="v1.24.0") == STABLE_CMD
    assert U.reinstall_command("frozen") is None


def test_the_commands_name_scripts_the_site_publishes():
    """docs.yml publishes these two names; see test_install_urls_on_site.py."""
    import pathlib
    docs = (pathlib.Path(__file__).parent.parent / ".github" / "workflows" / "docs.yml").read_text()
    assert "site/install.sh" in docs and "site/install-from-source.sh" in docs


# --------------------------------------------------------------------------- #
# the Help menu and the startup check, on the real window
# --------------------------------------------------------------------------- #

@pytest.fixture
def routes(main_window, main_window_dialogs, monkeypatch):
    """Drive the real window's update routes with the feed faked and every
    download path booby-trapped."""
    from PyReconstruct.modules.gui.dialog import update_dialog as UD
    from PyReconstruct.modules.gui.main import main_window as MW

    shown = []

    def boom(*a, **k):
        raise AssertionError("no download or source update may start")

    monkeypatch.setattr(MW, "check_for_update", boom)
    monkeypatch.setattr(MW, "download_asset", boom)
    monkeypatch.setattr(MW.MainWindow, "_updateFromSource", boom)
    monkeypatch.setattr(UD, "UpdateDialog", boom)
    monkeypatch.setattr(UD, "download_asset", boom)

    def fake_exec(dialog):
        shown.append({
            "title": dialog.windowTitle(),
            "command": dialog.command_field.text(),
            "read_only": dialog.command_field.isReadOnly(),
            "dialog": dialog,
        })
        return 1

    monkeypatch.setattr(UD.ReinstallDialog, "exec", fake_exec)

    def sync_check(self, channel, on_result, on_error, kind=None):
        assert kind in II.REINSTALL_KINDS
        on_result(U.check_for_reinstall(channel, kind, releases=FEED))

    monkeypatch.setattr(MW.MainWindow, "_runUpdateCheck", sync_check)
    monkeypatch.setattr(II, "current_version", lambda: Version("1.23.0"))

    class R:
        pass

    r = R()
    r.window, r.dialogs, r.shown, r.MW = main_window, main_window_dialogs, shown, MW

    def use(kind, flavor=None, version="1.23.0"):
        monkeypatch.setattr(MW, "install_kind", lambda: kind)
        monkeypatch.setattr(II, "current_version", lambda: Version(version))
        if flavor:
            monkeypatch.setenv("PYRECON_APP_NAME", flavor)
        else:
            monkeypatch.delenv("PYRECON_APP_NAME", raising=False)

    r.use = use
    return r




@pytest.mark.gui
@pytest.mark.parametrize("kind,flavor,version,command,title", [
    ("appimage", None, "1.23.0", STABLE_CMD, "PyReconstruct Update"),
    ("appimage", "PyReconstruct Dev", "1.24.0.dev20260901", DEV_CMD, "PyReconstruct Dev Update"),
    ("linux-installer", None, "1.23.0", source_cmd("v1.24.0"), "PyReconstruct Update"),
    ("linux-installer", "PyReconstruct Dev", "1.24.0.dev20260901",
     source_cmd("v1.25.0.dev20261001"), "PyReconstruct Dev Update"),
])
def test_help_check_for_updates_shows_the_command(routes, kind, flavor, version, command, title):
    routes.use(kind, flavor, version)
    routes.window.checkForUpdates()

    assert routes.dialogs.dialogs == []          # no "Update from source" prompt
    assert [s["command"] for s in routes.shown] == [command]
    assert routes.shown[0]["title"] == title
    assert routes.shown[0]["read_only"] is True
    assert routes.window._pending_installer is None


@pytest.mark.gui
@pytest.mark.parametrize("kind", ["appimage", "linux-installer"])
def test_help_check_for_updates_says_up_to_date(routes, kind):
    routes.use(kind, version="1.24.0")
    routes.window.checkForUpdates()
    assert routes.shown == []
    assert routes.dialogs.notices == ["You're already up to date (version 1.24.0)."]


@pytest.mark.gui
def test_help_check_with_nothing_on_the_channel_names_the_flavor(routes, monkeypatch):
    routes.use("appimage", "PyReconstruct Dev", "1.24.0.dev20260901")

    def sync_check(self, channel, on_result, on_error, kind=None):
        on_result(U.check_for_reinstall(channel, kind, releases=[_stable("1.24.0")]))

    monkeypatch.setattr(routes.MW.MainWindow, "_runUpdateCheck", sync_check)
    routes.window.checkForUpdates()
    assert routes.shown == []
    assert routes.dialogs.notices == ["No Nightly update is available for PyReconstruct Dev yet."]


@pytest.mark.gui
@pytest.mark.parametrize("kind,flavor,command", [
    ("appimage", None, STABLE_CMD),
    ("appimage", "PyReconstruct Dev", DEV_CMD),
    ("linux-installer", None, source_cmd("v1.24.0")),
])
def test_the_startup_check_shows_a_notice_that_opens_the_command(
    routes, kind, flavor, command
):
    """No dialog at launch (#430): a status bar notice, and clicking it runs
    the manual check, which shows the command."""
    from PySide6.QtCore import QSettings
    routes.use(kind, flavor, "1.23.0" if not flavor else "1.24.0.dev20260901")
    for app in ("PyReconstruct", "PyReconstruct Dev"):
        QSettings("KHLab", app).remove("last_update_check_epoch")
        QSettings("KHLab", app).remove("update_notice_version")
    routes.window.series.setOption("update_check_on_startup", True)

    try:
        routes.window.checkForUpdatesStartup()

        assert routes.dialogs.dialogs == []
        assert routes.shown == []
        notice = routes.window.update_notice
        assert not notice.isHidden()
        assert notice.text().startswith("Update available: ")

        routes.window.openUpdateNotice()

        assert notice.isHidden()
        assert [s["command"] for s in routes.shown] == [command]
    finally:
        for app in ("PyReconstruct", "PyReconstruct Dev"):
            QSettings("KHLab", app).remove("update_notice_version")


@pytest.mark.gui
def test_the_startup_check_is_silent_when_up_to_date(routes):
    from PySide6.QtCore import QSettings
    routes.use("appimage", version="1.24.0")
    QSettings("KHLab", "PyReconstruct").remove("last_update_check_epoch")
    routes.window.series.setOption("update_check_on_startup", True)

    routes.window.checkForUpdatesStartup()

    assert routes.shown == []
    assert routes.dialogs.notices == []
    assert routes.window.update_notice.isHidden()


@pytest.mark.gui
def test_the_copy_button_puts_the_command_on_the_clipboard(routes, qapp):
    routes.use("appimage", "PyReconstruct Dev", "1.24.0.dev20260901")
    routes.window.checkForUpdates()
    dialog = routes.shown[0]["dialog"]
    dialog.copy_btn.click()
    assert qapp.clipboard().text() == DEV_CMD
    dialog.deleteLater()


# --------------------------------------------------------------------------- #
# cli.update
# --------------------------------------------------------------------------- #

def _forbid_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"subprocess.run must not be called: {a}")
    monkeypatch.setattr(cli.subprocess, "run", boom)


@pytest.mark.parametrize("flavor,command", [(None, STABLE_CMD), ("PyReconstruct Dev", DEV_CMD)])
def test_cli_update_refuses_an_appimage_with_its_command(machine, monkeypatch, flavor, command):
    machine.frozen()
    machine.env("APPIMAGE", "/tmp/PyReconstruct.AppImage")
    if flavor:
        machine.env("PYRECON_APP_NAME", flavor)
    _forbid_subprocess(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cli.update()
    name = flavor or "PyReconstruct"
    assert str(e.value) == (
        f"This copy of {name} is managed by its AppImage installer.\n"
        "To update, run this command in a terminal:\n"
        f"  {command}"
    )


@pytest.mark.parametrize("flavor,tag", [
    (None, "v1.24.0"), ("PyReconstruct Dev", "v1.25.0.dev20261001"),
])
def test_cli_update_refuses_an_install_sh_copy_with_its_command(machine, monkeypatch, flavor, tag):
    (machine.root / ".pyreconstruct-install").write_text(str(machine.root))
    if flavor:
        machine.env("PYRECON_APP_NAME", flavor)
    monkeypatch.setattr(U, "fetch_releases", lambda *a, **k: FEED)
    _forbid_subprocess(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cli.update()
    name = flavor or "PyReconstruct"
    assert str(e.value) == (
        f"This copy of {name} is managed by its Linux installer.\n"
        "To update, run this command in a terminal:\n"
        f"  {source_cmd(tag)}"
    )


def test_cli_update_on_an_install_sh_copy_offline_asks_for_the_tag(machine, monkeypatch):
    """The command never falls back to the newest main when the feed is out
    of reach; it asks for a release tag instead."""
    (machine.root / ".pyreconstruct-install").write_text(str(machine.root))

    def offline(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(U, "fetch_releases", offline)
    _forbid_subprocess(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cli.update()
    msg = str(e.value)
    assert f"  {source_cmd('<release tag>')}\n" in msg
    assert "/releases" in msg
    assert f"  {SOURCE_CMD}\n" not in msg and not msg.endswith(SOURCE_CMD)


def test_cli_update_on_plain_frozen_is_unchanged(machine, monkeypatch, capsys):
    machine.frozen()
    _forbid_subprocess(monkeypatch)
    cli.update()
    assert "packaged build" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# what an AppImage keeps from being a frozen build
# --------------------------------------------------------------------------- #

def test_an_appimage_still_refuses_an_unsigned_release(monkeypatch):
    """It read as ``frozen`` before; the new kind must not relax the rule."""
    monkeypatch.setattr(II, "install_kind", lambda: "appimage")
    monkeypatch.setattr(U, "fetch_signed_checksum", lambda r, n: ("absent", None))
    assert U.verified_checksum({}, "x") == ("unsigned", None)
