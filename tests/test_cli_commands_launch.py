"""What a launch does to make the terminal commands reachable.

backend/func/cli_commands.py, with every side effect replaced: a temporary
folder stands in for /usr/local/bin, the administrator prompt runs the very
script it was handed with a plain ``sh`` (no prompt, no root), the registry
is a dictionary behind winreg's names, and the settings store is a
dictionary too. Nothing here reads or writes the real settings or PATH.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.func import cli_commands as C

posix_only = pytest.mark.skipif(os.name == "nt", reason="symlinks and sh")


class FakeSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


@pytest.fixture
def stable(monkeypatch):
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")


# ---- the launch argument ----------------------------------------------------------

def test_launch_file_is_absolute(tmp_path):
    assert C.launch_file(["series.jser"], cwd=str(tmp_path)) == str(tmp_path / "series.jser")
    assert C.launch_file(["sub/../a.jser"], cwd=str(tmp_path)) == str(tmp_path / "a.jser")
    assert C.launch_file([str(tmp_path / "b.jser")], cwd="/elsewhere") == str(tmp_path / "b.jser")


def test_launch_file_skips_options():
    assert C.launch_file(["-psn_0_12345"]) is None
    assert C.launch_file(["-psn_0_12345", "/x/a.jser"]) == os.path.abspath("/x/a.jser")
    assert C.launch_file([]) is None
    assert C.launch_file([""]) is None


def test_names_follow_the_flavor(stable, monkeypatch):
    assert C.command_names() == ("pyrecon", "pyreconstruct")
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    assert C.command_names() == ("pyrecon-dev", "pyreconstruct-dev")


# ---- Windows PATH strings ------------------------------------------------------------

BIN = r"C:\Users\me\AppData\Local\Programs\PyReconstruct\bin"


@pytest.mark.parametrize("value", [
    BIN,
    BIN + "\\",
    BIN.upper(),
    BIN.lower() + "\\",
    f'"{BIN}"',
    rf"C:\Windows;{BIN};D:\tools",
    rf" {BIN} ;D:\tools",
])
def test_path_has_entry_ignores_case_and_a_trailing_backslash(value):
    assert C.path_has_entry(value, BIN)
    assert C.path_has_entry(value, BIN + "\\")
    assert C.path_with_entry(value, BIN) == value


@pytest.mark.parametrize("value", [
    "", r"C:\Windows", BIN + "2", BIN[:-1], rf"{BIN}\sub", r"C:\Users\me\AppData\Local\Programs\PyReconstruct Dev\bin",
])
def test_path_has_entry_needs_the_same_folder(value):
    assert not C.path_has_entry(value, BIN)


def test_path_with_entry_appends_once():
    assert C.path_with_entry("", BIN) == BIN
    assert C.path_with_entry(None, BIN) == BIN
    assert C.path_with_entry(r"C:\Windows", BIN) == rf"C:\Windows;{BIN}"
    assert C.path_with_entry("C:\\Windows;", BIN) == rf"C:\Windows;{BIN}"
    once = C.path_with_entry(r"C:\Windows", BIN)
    assert C.path_with_entry(once, BIN.upper() + "\\") == once


def test_path_without_entry_removes_only_that_entry():
    value = rf"C:\Windows;{BIN.lower()}\;%USERPROFILE%\bin;;D:\tools;{BIN}"
    assert C.path_without_entry(value, BIN) == r"C:\Windows;%USERPROFILE%\bin;;D:\tools"
    assert C.path_without_entry(r"C:\Windows;D:\tools", BIN) == r"C:\Windows;D:\tools"
    # the Dev folder is a different entry
    dev_bin = BIN.replace("PyReconstruct", "PyReconstruct Dev")
    assert C.path_without_entry(f"{dev_bin};{BIN}", BIN) == dev_bin


class FakeWinreg:
    """winreg's names over one HKCU\\Environment dictionary of (value, type)."""
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    REG_DWORD = 4

    def __init__(self, path=None, kind=REG_EXPAND_SZ):
        self.env = {} if path is None else {"Path": (path, kind)}
        self.writes = 0

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, sub, reserved=0, access=0):
        assert (root, sub) == ("HKCU", "Environment")
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.env:
            raise FileNotFoundError(name)
        return self.env[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.env[name] = (value, kind)
        self.writes += 1


def test_windows_add_keeps_the_value_type_and_adds_once():
    reg = FakeWinreg(r"C:\Windows", FakeWinreg.REG_SZ)
    told = []
    assert C.windows_add_to_path(BIN, winreg=reg, broadcast=lambda: told.append(1))
    assert reg.env["Path"] == (rf"C:\Windows;{BIN}", FakeWinreg.REG_SZ)
    assert not C.windows_add_to_path(BIN.upper() + "\\", winreg=reg, broadcast=lambda: told.append(1))
    assert reg.writes == 1 and told == [1]


def test_windows_add_creates_an_expandable_value_when_there_is_none():
    reg = FakeWinreg()
    assert C.windows_add_to_path(BIN, winreg=reg, broadcast=lambda: None)
    assert reg.env["Path"] == (BIN, FakeWinreg.REG_EXPAND_SZ)


def test_windows_add_leaves_a_value_that_is_not_a_string():
    reg = FakeWinreg(7, FakeWinreg.REG_DWORD)
    assert not C.windows_add_to_path(BIN, winreg=reg, broadcast=lambda: None)
    assert reg.writes == 0


def windows_install(tmp_path, name="PyReconstruct", long_="pyreconstruct"):
    folder = tmp_path / name
    (folder / "bin").mkdir(parents=True)
    (folder / f"{name}.exe").write_bytes(b"")
    (folder / "unins000.exe").write_bytes(b"")
    (folder / "bin" / f"{long_}.cmd").write_text("@echo off\r\n")
    return folder


def test_windows_ensure_runs_once(stable, tmp_path):
    folder = windows_install(tmp_path)
    reg = FakeWinreg(r"C:\Windows")
    settings = FakeSettings()
    exe = str(folder / "PyReconstruct.exe")
    assert C.windows_ensure(settings, executable=exe, winreg=reg, broadcast=lambda: None)
    assert C.path_has_entry(reg.env["Path"][0], str((folder / "bin").resolve()))
    assert settings.values[C.ADDED_KEY] is True
    # the user took it off PATH again: not put back
    reg.env["Path"] = (r"C:\Windows", FakeWinreg.REG_EXPAND_SZ)
    assert not C.windows_ensure(settings, executable=exe, winreg=reg, broadcast=lambda: None)
    assert reg.env["Path"][0] == r"C:\Windows"


def test_windows_ensure_skips_a_copy_that_was_not_installed(stable, tmp_path):
    folder = windows_install(tmp_path)
    (folder / "unins000.exe").unlink()
    reg = FakeWinreg(r"C:\Windows")
    settings = FakeSettings()
    assert not C.windows_ensure(settings, executable=str(folder / "PyReconstruct.exe"), winreg=reg)
    assert reg.writes == 0 and C.ADDED_KEY not in settings.values


def test_windows_ensure_needs_this_flavor_s_commands(dev, tmp_path):
    folder = windows_install(tmp_path, "PyReconstruct Dev", long_="pyreconstruct")  # the stable name
    reg = FakeWinreg(r"C:\Windows")
    assert not C.windows_ensure(FakeSettings(), executable=str(folder / "PyReconstruct Dev.exe"), winreg=reg)
    assert reg.writes == 0


# ---- macOS links ------------------------------------------------------------------------

@pytest.fixture
def mac(tmp_path, stable):
    """An installed bundle under <home>/Applications and an empty folder
    standing in for /usr/local/bin."""
    home = tmp_path / "home"
    bundle = home / "Applications" / "PyReconstruct.app"
    bin_dir = bundle / "Contents" / "Resources" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pyreconstruct").write_text("#!/bin/sh\n")
    os.symlink("pyreconstruct", bin_dir / "pyrecon")
    link_dir = tmp_path / "usr-local-bin"
    link_dir.mkdir()
    return {"home": home, "bundle": bundle, "bin": bin_dir, "links": link_dir, "settings": FakeSettings()}


def sh_runner(calls):
    """Run the admin script with plain sh, recording it and the prompt."""
    def run(script, prompt):
        calls.append((script, prompt))
        return subprocess.run(["sh", "-c", script], capture_output=True).returncode == 0
    return run


def offer(mac, admin=True):
    return C.macos_offer(mac["bundle"], mac["settings"], link_dir=mac["links"],
                         is_admin=lambda: admin, home=mac["home"])


def link_to(mac, name):
    return os.readlink(mac["links"] / name)


@pytest.mark.parametrize("path,ok", [
    ("/Applications/PyReconstruct.app", True),
    ("/Applications/Science/PyReconstruct Dev.app", True),
    ("/home/me/Applications/PyReconstruct.app", True),
    ("/Volumes/PyReconstruct/PyReconstruct.app", False),
    ("/private/var/folders/x/AppTranslocation/ABC/d/PyReconstruct.app", False),
    ("/home/me/Downloads/PyReconstruct.app", False),
    ("/ApplicationsX/PyReconstruct.app", False),
    ("/Applications", False),
])
def test_only_an_installed_bundle_gets_links(path, ok):
    assert C.macos_bundle_is_installed(path, home="/home/me") is ok


@posix_only
def test_first_launch_makes_both_links(mac):
    fixes = offer(mac)
    assert [Path(link).name for link, _, _ in fixes] == ["pyrecon", "pyreconstruct"]
    calls = []
    assert C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=sh_runner(calls))
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")
    assert len(calls) == 1  # one prompt for both
    assert "pyrecon and pyreconstruct" in calls[0][1]
    assert C.DECLINED_KEY not in mac["settings"].values


@posix_only
def test_nothing_to_do_when_the_links_are_right(mac):
    for name in ("pyrecon", "pyreconstruct"):
        os.symlink(mac["bin"] / name, mac["links"] / name)
    assert offer(mac) is None


@posix_only
def test_a_moved_app_gets_its_links_back(mac, tmp_path):
    old = tmp_path / "gone" / "PyReconstruct.app" / "Contents" / "Resources" / "bin"
    for name in ("pyrecon", "pyreconstruct"):
        os.symlink(old / name, mac["links"] / name)
    states = C.macos_link_states(mac["bundle"], mac["links"])
    assert {n: s[0] for n, s in states.items()} == {"pyrecon": "moved", "pyreconstruct": "moved"}
    fixes = offer(mac)
    assert C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=sh_runner([]))
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")


@posix_only
def test_another_copy_that_still_exists_keeps_its_links(mac, tmp_path):
    other = tmp_path / "Other" / "PyReconstruct.app" / "Contents" / "Resources" / "bin"
    other.mkdir(parents=True)
    (other / "pyrecon").write_text("")
    os.symlink(other / "pyrecon", mac["links"] / "pyrecon")
    os.symlink(mac["bin"] / "pyreconstruct", mac["links"] / "pyreconstruct")
    assert C.macos_link_states(mac["bundle"], mac["links"])["pyrecon"][0] == "other"
    assert offer(mac) is None


@posix_only
def test_files_that_are_not_ours_are_never_touched(mac):
    (mac["links"] / "pyrecon").write_text("someone else's pyrecon\n")
    os.symlink("/usr/bin/true", mac["links"] / "pyreconstruct")
    states = C.macos_link_states(mac["bundle"], mac["links"])
    assert {n: s[0] for n, s in states.items()} == {"pyrecon": "foreign", "pyreconstruct": "foreign"}
    assert offer(mac) is None
    assert (mac["links"] / "pyrecon").read_text() == "someone else's pyrecon\n"
    assert link_to(mac, "pyreconstruct") == "/usr/bin/true"


@posix_only
def test_a_foreign_name_is_skipped_and_the_other_is_made(mac):
    (mac["links"] / "pyrecon").mkdir()
    fixes = offer(mac)
    assert [Path(link).name for link, _, _ in fixes] == ["pyreconstruct"]
    assert C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=sh_runner([]))
    assert (mac["links"] / "pyrecon").is_dir() and not (mac["links"] / "pyrecon").is_symlink()
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")


@posix_only
def test_the_script_refuses_a_name_that_changed_since_the_check(mac, tmp_path):
    fixes = offer(mac)
    (mac["links"] / "pyrecon").write_text("arrived meanwhile\n")
    assert not C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=sh_runner([]))
    assert (mac["links"] / "pyrecon").read_text() == "arrived meanwhile\n"
    assert mac["settings"].values[C.DECLINED_KEY] is True

    # a moved link repointed meanwhile is left as found, too
    os.remove(mac["links"] / "pyrecon")
    gone = tmp_path / "gone" / "PyReconstruct.app" / "Contents" / "Resources" / "bin" / "pyrecon"
    os.symlink(gone, mac["links"] / "pyrecon")
    fixes = C.macos_fixes(C.macos_link_states(mac["bundle"], mac["links"]))
    os.remove(mac["links"] / "pyrecon")
    os.symlink("/usr/bin/true", mac["links"] / "pyrecon")
    assert not C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=sh_runner([]))
    assert link_to(mac, "pyrecon") == "/usr/bin/true"


@posix_only
def test_a_decline_stops_the_asking(mac):
    assert offer(mac) is not None
    C.macos_decline(mac["settings"])
    assert offer(mac) is None


@posix_only
def test_a_canceled_prompt_counts_as_a_decline(mac):
    fixes = offer(mac)
    assert not C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=lambda s, p: False)
    assert offer(mac) is None
    assert not any(mac["links"].iterdir())


@posix_only
def test_a_prompt_that_raises_counts_as_a_decline(mac):
    def boom(script, prompt):
        raise OSError("osascript is missing")
    fixes = offer(mac)
    assert not C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=boom)
    assert offer(mac) is None


@posix_only
def test_a_user_who_is_not_an_administrator_is_not_asked(mac):
    assert offer(mac, admin=False) is None
    assert C.DECLINED_KEY not in mac["settings"].values  # asked once they can say yes


@posix_only
def test_a_bundle_outside_applications_is_not_offered(mac, tmp_path):
    loose = tmp_path / "Downloads" / "PyReconstruct.app"
    loose.mkdir(parents=True)
    assert C.macos_offer(loose, mac["settings"], link_dir=mac["links"], is_admin=lambda: True,
                         home=mac["home"]) is None


@posix_only
def test_dev_uses_its_own_names_beside_stable(mac, monkeypatch, tmp_path):
    for name in ("pyrecon", "pyreconstruct"):
        os.symlink(mac["bin"] / name, mac["links"] / name)
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    dev_bundle = mac["home"] / "Applications" / "PyReconstruct Dev.app"
    fixes = C.macos_offer(dev_bundle, FakeSettings(), link_dir=mac["links"], is_admin=lambda: True,
                          home=mac["home"])
    assert [Path(link).name for link, _, _ in fixes] == ["pyrecon-dev", "pyreconstruct-dev"]
    assert C.macos_apply(fixes, FakeSettings(), link_dir=mac["links"], runner=sh_runner([]))
    assert sorted(p.name for p in mac["links"].iterdir()) == [
        "pyrecon", "pyrecon-dev", "pyreconstruct", "pyreconstruct-dev"]
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")


@posix_only
def test_paths_with_quotes_and_spaces_reach_the_script_intact(mac, tmp_path):
    odd = tmp_path / "it's \"odd\" $HOME" / "Applications" / "PyReconstruct.app"
    shutil.copytree(mac["bundle"], odd, symlinks=True)
    fixes = C.macos_offer(odd, mac["settings"], link_dir=mac["links"], is_admin=lambda: True,
                          home=odd.parent.parent)
    assert C.macos_apply(fixes, mac["settings"], link_dir=mac["links"], runner=sh_runner([]))
    assert link_to(mac, "pyrecon") == str(odd / "Contents" / "Resources" / "bin" / "pyrecon")


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("osascript"), reason="macOS osascript")
def test_the_applescript_string_round_trips():
    text = 'ln -s \'/a b/it\'"\'"\'s\' "x\\y"\nnext line'
    out = subprocess.run(["osascript", "-e", f"return {C._applescript_string(text)}"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.rstrip("\n").replace("\r", "\n") == text


def test_the_admin_command_is_one_osascript_call():
    argv = C.osascript_argv("true", "PyReconstruct wants to add commands.")
    assert argv[:2] == ["osascript", "-e"] and len(argv) == 3
    assert argv[2].startswith('do shell script "true" with administrator privileges')
    assert argv[2].endswith('with prompt "PyReconstruct wants to add commands."')


# ---- Linux AppImage installs -------------------------------------------------------------

@pytest.fixture
def linux(tmp_path, stable):
    home = tmp_path / "home"
    root = home / ".local" / "share" / "PyReconstruct"
    root.mkdir(parents=True)
    image = root / "PyReconstruct.AppImage"
    image.write_text("")
    (root / ".appimage-install").write_text("flavor=stable\n")
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pyreconstruct").write_text(f"#!/bin/sh\n# PyReconstruct launcher, {C.LAUNCHER_TAG}.\n")
    env = {"HOME": str(home), "APPIMAGE": str(image)}
    return {"env": env, "bin": bin_dir, "root": root, "settings": FakeSettings()}


@posix_only
def test_linux_adds_the_short_name_once(linux):
    assert C.linux_ensure(linux["settings"], env=linux["env"])
    assert os.readlink(linux["bin"] / "pyrecon") == "pyreconstruct"
    assert linux["settings"].values[C.ADDED_KEY] is True
    os.remove(linux["bin"] / "pyrecon")
    assert not C.linux_ensure(linux["settings"], env=linux["env"])  # removed on purpose: stays removed
    assert not os.path.lexists(linux["bin"] / "pyrecon")


@posix_only
def test_linux_keeps_a_file_that_is_not_ours(linux):
    (linux["bin"] / "pyrecon").write_text("mine\n")
    assert not C.linux_ensure(linux["settings"], env=linux["env"])
    assert (linux["bin"] / "pyrecon").read_text() == "mine\n"


@posix_only
@pytest.mark.parametrize("change", ["no marker", "other image", "foreign launcher", "no launcher"])
def test_linux_needs_the_installer_s_own_install(linux, change, tmp_path):
    if change == "no marker":
        (linux["root"] / ".appimage-install").unlink()
    elif change == "other image":
        other = tmp_path / "Downloads" / "PyReconstruct.AppImage"
        other.parent.mkdir()
        other.write_text("")
        linux["env"]["APPIMAGE"] = str(other)
    elif change == "foreign launcher":
        (linux["bin"] / "pyreconstruct").write_text("#!/bin/sh\nexec something\n")
    else:
        (linux["bin"] / "pyreconstruct").unlink()
    assert not C.linux_ensure(linux["settings"], env=linux["env"])
    assert not os.path.lexists(linux["bin"] / "pyrecon")
    assert C.ADDED_KEY not in linux["settings"].values


@posix_only
def test_linux_dev_uses_its_own_names(tmp_path, dev):
    home = tmp_path / "home"
    root = home / "data" / "PyReconstruct Dev"
    root.mkdir(parents=True)
    (root / "PyReconstruct-Dev.AppImage").write_text("")
    (root / ".appimage-install").write_text("flavor=dev\n")
    bin_dir = home / "xbin"
    bin_dir.mkdir()
    (bin_dir / "pyreconstruct-dev").write_text(f"# {C.LAUNCHER_TAG}\n")
    env = {"HOME": str(home), "APPIMAGE": str(root / "PyReconstruct-Dev.AppImage"),
           "XDG_DATA_HOME": str(home / "data"), "XDG_BIN_HOME": str(bin_dir)}
    assert C.linux_ensure(FakeSettings(), env=env)
    assert os.readlink(bin_dir / "pyrecon-dev") == "pyreconstruct-dev"


def test_an_unfrozen_run_does_nothing(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    settings = FakeSettings()
    assert C.ensure_silent(settings) is False
    assert C.macos_pending(settings) is None
    assert settings.values == {}


# ---- the macOS question (run.py) --------------------------------------------------------

@pytest.fixture
def question(qapp, monkeypatch):
    """askForMacTerminalCommands with a pending offer and a stand-in message box
    that answers with ``answer['button']``."""
    import threading

    from PySide6 import QtWidgets
    from PySide6.QtWidgets import QWidget

    import PyReconstruct.run as run_mod

    answer = {"button": "Add Commands"}
    shown = []
    applied = []
    settings = FakeSettings()
    fixes = [("/usr/local/bin/pyrecon", "/Applications/PyReconstruct.app/Contents/Resources/bin/pyrecon", None)]

    class Box:
        Question = QtWidgets.QMessageBox.Question
        AcceptRole = QtWidgets.QMessageBox.AcceptRole
        RejectRole = QtWidgets.QMessageBox.RejectRole

        def __init__(self, parent):
            self.buttons = {}
            self.clicked = None

        def setWindowTitle(self, t):
            self.title = t

        def setIcon(self, i):
            pass

        def setText(self, t):
            self.text = t

        def setInformativeText(self, t):
            self.info = t

        def addButton(self, label, role):
            self.buttons[label] = object()
            return self.buttons[label]

        def setDefaultButton(self, b):
            pass

        def exec(self):
            shown.append(self)
            self.clicked = self.buttons[answer["button"]]

        def clickedButton(self):
            return self.clicked

    done = threading.Event()

    def fake_apply(f, s):
        applied.append(f)
        done.set()

    monkeypatch.setattr(QtWidgets, "QMessageBox", Box)
    monkeypatch.setattr(C, "macos_pending", lambda: ("/Applications/PyReconstruct.app", fixes, settings))
    monkeypatch.setattr(C, "macos_apply", fake_apply)
    monkeypatch.setattr(C, "open_settings", lambda: settings)
    window = QWidget()
    yield {"ask": lambda: run_mod.askForMacTerminalCommands(window), "answer": answer, "shown": shown,
           "applied": applied, "settings": settings, "fixes": fixes, "done": done}
    window.deleteLater()


@pytest.mark.gui
def test_yes_runs_the_admin_step_off_the_gui_thread(question, stable):
    question["ask"]()
    assert question["done"].wait(5)
    assert question["applied"] == [question["fixes"]]
    box = question["shown"][0]
    assert box.text == "Add the pyrecon and pyreconstruct commands to Terminal?"
    assert "PyReconstruct will not ask again" in box.info
    assert C.DECLINED_KEY not in question["settings"].values


@pytest.mark.gui
def test_skip_records_the_decline(question):
    question["answer"]["button"] = "Skip"
    question["ask"]()
    assert question["settings"].values[C.DECLINED_KEY] is True
    assert not question["done"].wait(0.2) and question["applied"] == []


@pytest.mark.gui
def test_the_question_waits_for_another_dialog(question, qapp):
    from PySide6.QtWidgets import QDialog
    other = QDialog()
    other.show()
    try:
        question["ask"]()
        assert question["shown"] == []
    finally:
        other.close()
        other.deleteLater()


@pytest.mark.gui
def test_a_failure_in_the_question_never_raises(qapp, monkeypatch):
    import PyReconstruct.run as run_mod

    def boom():
        raise RuntimeError("no")
    monkeypatch.setattr(C, "macos_pending", boom)
    logged = []
    monkeypatch.setattr(C, "log_problem", logged.append)
    run_mod.askForMacTerminalCommands(None)
    assert logged and "no" in logged[0]


def test_run_hands_over_an_absolute_launch_file():
    src = (Path(C.__file__).parents[3] / "run.py").read_text()
    assert "runPyReconstruct(launch_file(sys.argv[1:]))" in src


def test_the_linux_names_match_the_installer():
    script = (Path(C.__file__).parents[4] / "packaging" / "linux" / "install-appimage.sh").read_text()
    assert f'MARKER="$APPROOT/{C.APPIMAGE_MARKER}"' in script
    assert f'LAUNCHER_TAG="{C.LAUNCHER_TAG}"' in script
    for short, long_ in (C.command_names(dev=False), C.command_names(dev=True)):
        assert f'COMMAND="{long_}"\n  SHORT_COMMAND="{short}"' in script
    from PyReconstruct.modules.backend.updater.install_info import APPIMAGE_MARKER
    assert APPIMAGE_MARKER == C.APPIMAGE_MARKER
