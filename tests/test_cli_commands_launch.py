"""What a launch does to make the terminal commands reachable.

backend/func/cli_commands.py, with every side effect replaced: a temporary
folder stands in for the home folder (its .local/bin and shell startup
files), the registry is a dictionary behind winreg's names, and the settings
store is a dictionary too. Nothing here reads or writes the real settings,
startup files or PATH.
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
    """An installed bundle under <home>/Applications; <home>/.local/bin does
    not exist yet."""
    home = tmp_path / "home"
    bundle = home / "Applications" / "PyReconstruct.app"
    bin_dir = bundle / "Contents" / "Resources" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pyreconstruct").write_text("#!/bin/sh\n")
    (bin_dir / "pyreconstruct").chmod(0o755)
    os.symlink("pyreconstruct", bin_dir / "pyrecon")
    return {"home": home, "bundle": bundle, "bin": bin_dir, "links": home / ".local" / "bin",
            "settings": FakeSettings()}


def ensure(mac, shell="zsh", bundle=None, settings=None):
    return C.macos_ensure(settings or mac["settings"], bundle or mac["bundle"], home=mac["home"],
                          shell=shell, env={})


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
def test_first_launch_makes_both_links_and_the_path_line(mac):
    assert ensure(mac)
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")
    profile = (mac["home"] / ".zprofile").read_text()
    assert C.PROFILE_TAG in profile
    assert 'export PATH="$HOME/.local/bin:$PATH"' in profile
    assert mac["settings"].values[C.ADDED_KEY] is True


def needs(shell):
    return pytest.mark.skipif(os.name == "nt" or not shutil.which(shell, path=C.SYSTEM_PATH),
                              reason=f"no {shell}")


@needs("zsh")
@needs("bash")
@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_the_path_line_lands_in_a_working_login_shell(mac, shell):
    ensure(mac, shell=shell)
    out = subprocess.run([shell, "-lc", "command -v pyrecon"], capture_output=True, text=True,
                         env={"HOME": str(mac["home"]), "PATH": "/usr/bin:/bin"}, timeout=30)
    assert out.stdout.strip() == str(mac["links"] / "pyrecon")


@needs("sh")
def test_the_path_line_never_doubles_an_entry():
    script = f'PATH=/bin; HOME=/h; {C.PROFILE_LINE}; {C.PROFILE_LINE}; printf %s "$PATH"'
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=30)
    assert out.stdout == "/h/.local/bin:/bin"


@posix_only
def test_a_second_launch_changes_nothing(mac):
    assert ensure(mac)
    before = (mac["home"] / ".zprofile").read_text()
    assert not ensure(mac)
    assert (mac["home"] / ".zprofile").read_text() == before


@posix_only
def test_a_removed_path_line_stays_removed(mac):
    ensure(mac)
    (mac["home"] / ".zprofile").write_text("")
    assert not ensure(mac)
    assert (mac["home"] / ".zprofile").read_text() == ""


@needs("zsh")
@needs("bash")
@pytest.mark.parametrize("shell,name,line,target", [
    ("zsh", ".zshenv", 'path=("$HOME/.local/bin" $path)', ".zprofile"),
    ("zsh", ".zprofile", 'export PATH="$HOME/.local/bin:$PATH"', ".zprofile"),
    ("bash", ".bash_profile", 'PATH=~/.local/bin:$PATH', ".bash_profile"),
])
def test_a_login_shell_that_has_local_bin_is_left_alone(mac, shell, name, line, target):
    mac["home"].mkdir(exist_ok=True)
    (mac["home"] / name).write_text(line + "\n")
    assert ensure(mac, shell=shell)
    assert C.PROFILE_TAG not in ((mac["home"] / target).read_text()
                                 if (mac["home"] / target).exists() else "")
    assert mac["settings"].values[C.ADDED_KEY] is True


@posix_only
def test_the_line_goes_after_what_is_there(mac):
    (mac["home"] / ".zprofile").write_text("export EDITOR=vi")
    ensure(mac)
    lines = (mac["home"] / ".zprofile").read_text().splitlines()
    assert lines[0] == "export EDITOR=vi" and lines[2] == C.PROFILE_TAG


@posix_only
def test_zdotdir_is_followed(mac, tmp_path):
    zdot = tmp_path / "zdot"
    zdot.mkdir()
    C.macos_ensure(mac["settings"], mac["bundle"], home=mac["home"], shell="zsh",
                   env={"ZDOTDIR": str(zdot)})
    assert C.PROFILE_TAG in (zdot / ".zprofile").read_text()
    assert not (mac["home"] / ".zprofile").exists()


@posix_only
def test_bash_uses_the_file_a_login_bash_reads(mac):
    (mac["home"] / ".profile").write_text("# mine\n")
    ensure(mac, shell="bash")
    assert C.PROFILE_TAG in (mac["home"] / ".profile").read_text()
    assert not (mac["home"] / ".bash_profile").exists()


@posix_only
def test_bash_with_no_startup_file_gets_a_bash_profile(mac):
    ensure(mac, shell="bash")
    assert C.PROFILE_TAG in (mac["home"] / ".bash_profile").read_text()


@needs("bash")
def test_a_bashrc_a_login_bash_skips_does_not_count(mac):
    mac["home"].mkdir(exist_ok=True)
    (mac["home"] / ".bashrc").write_text('export PATH="$HOME/.local/bin:$PATH"\n')
    ensure(mac, shell="bash")
    assert C.PROFILE_TAG in (mac["home"] / ".bash_profile").read_text()


@needs("zsh")
@needs("bash")
@pytest.mark.parametrize("shell,name", [("zsh", ".zshenv"), ("bash", ".bash_profile")])
@pytest.mark.parametrize("line", [
    "# someday: ~/.local/bin",
    "   # someday: ~/.local/bin",
    "export EDITOR=vi # someday add ~/.local/bin",
    "export EDITOR=vi\t# ~/.local/bin",
    "export EDITOR=vi;# ~/.local/bin",
    'if false; then export PATH="$HOME/.local/bin:$PATH"; fi',
])
def test_a_line_that_does_not_set_path_does_not_count(mac, shell, name, line):
    mac["home"].mkdir(exist_ok=True)
    (mac["home"] / name).write_text(line + "\n")
    ensure(mac, shell=shell)
    target = ".zprofile" if shell == "zsh" else ".bash_profile"
    assert C.PROFILE_TAG in (mac["home"] / target).read_text()


@posix_only
@pytest.mark.parametrize("body", ["exit 1", "sleep 30", None])
def test_a_shell_that_cannot_say_still_gets_the_lines(mac, tmp_path, body):
    fake = tmp_path / "fake" / "zsh"
    fake.parent.mkdir()
    if body is not None:  # None: the shell is not there at all
        fake.write_text(f"#!/bin/sh\n{body}\n")
        fake.chmod(0o755)
    assert C.macos_ensure(mac["settings"], mac["bundle"], home=mac["home"], shell=str(fake),
                          env={}, timeout=1)
    assert C.PROFILE_TAG in (mac["home"] / ".zprofile").read_text()


@posix_only
def test_another_shell_gets_links_but_no_startup_line(mac):
    assert ensure(mac, shell="fish")
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert not any(p.name.startswith(".") for p in mac["home"].iterdir() if p.is_file())


@posix_only
def test_nothing_to_do_when_the_links_are_right(mac):
    mac["links"].mkdir(parents=True)
    for name in ("pyrecon", "pyreconstruct"):
        os.symlink(mac["bin"] / name, mac["links"] / name)
    mac["settings"].setValue(C.ADDED_KEY, True)
    assert not ensure(mac)


@posix_only
def test_a_moved_app_gets_its_links_back(mac, tmp_path):
    mac["links"].mkdir(parents=True)
    old = tmp_path / "gone" / "PyReconstruct.app" / "Contents" / "Resources" / "bin"
    for name in ("pyrecon", "pyreconstruct"):
        os.symlink(old / name, mac["links"] / name)
    states = C.macos_link_states(mac["bundle"], mac["links"])
    assert {n: s[0] for n, s in states.items()} == {"pyrecon": "moved", "pyreconstruct": "moved"}
    mac["settings"].setValue(C.ADDED_KEY, True)
    assert ensure(mac)
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")
    assert sorted(p.name for p in mac["links"].iterdir()) == ["pyrecon", "pyreconstruct"]


@posix_only
def test_a_moved_link_fix_leaves_a_user_file_with_the_old_temp_name(mac, tmp_path):
    mac["links"].mkdir(parents=True)
    old = tmp_path / "gone" / "PyReconstruct.app" / "Contents" / "Resources" / "bin"
    os.symlink(old / "pyrecon", mac["links"] / "pyrecon")
    (mac["links"] / "pyrecon.pyrecon-tmp").write_text("mine\n")
    ensure(mac)
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert (mac["links"] / "pyrecon.pyrecon-tmp").read_text() == "mine\n"
    assert sorted(p.name for p in mac["links"].iterdir()) == [
        "pyrecon", "pyrecon.pyrecon-tmp", "pyreconstruct"]


@posix_only
def test_another_copy_that_still_exists_keeps_its_links(mac, tmp_path):
    mac["links"].mkdir(parents=True)
    other = tmp_path / "Other" / "PyReconstruct.app" / "Contents" / "Resources" / "bin"
    other.mkdir(parents=True)
    (other / "pyrecon").write_text("")
    os.symlink(other / "pyrecon", mac["links"] / "pyrecon")
    assert C.macos_link_states(mac["bundle"], mac["links"])["pyrecon"][0] == "other"
    ensure(mac)
    assert link_to(mac, "pyrecon") == str(other / "pyrecon")
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")


@posix_only
def test_files_that_are_not_ours_are_never_touched(mac):
    mac["links"].mkdir(parents=True)
    (mac["links"] / "pyrecon").write_text("someone else's pyrecon\n")
    os.symlink("/usr/bin/true", mac["links"] / "pyreconstruct")
    states = C.macos_link_states(mac["bundle"], mac["links"])
    assert {n: s[0] for n, s in states.items()} == {"pyrecon": "foreign", "pyreconstruct": "foreign"}
    assert not ensure(mac)
    assert (mac["links"] / "pyrecon").read_text() == "someone else's pyrecon\n"
    assert link_to(mac, "pyreconstruct") == "/usr/bin/true"
    # no command of ours is there, so the startup files are not touched either
    assert not (mac["home"] / ".zprofile").exists()
    assert C.ADDED_KEY not in mac["settings"].values


@posix_only
def test_a_foreign_name_is_skipped_and_the_other_is_made(mac):
    (mac["links"] / "pyrecon").mkdir(parents=True)
    assert ensure(mac)
    assert (mac["links"] / "pyrecon").is_dir() and not (mac["links"] / "pyrecon").is_symlink()
    assert link_to(mac, "pyreconstruct") == str(mac["bin"] / "pyreconstruct")


@posix_only
def test_a_name_that_changed_since_the_check_is_skipped(mac, tmp_path):
    mac["links"].mkdir(parents=True)
    fixes = C.macos_fixes(C.macos_link_states(mac["bundle"], mac["links"]))
    (mac["links"] / "pyrecon").write_text("arrived meanwhile\n")
    assert C.macos_make_links(fixes) == 1
    assert (mac["links"] / "pyrecon").read_text() == "arrived meanwhile\n"

    # a moved link repointed meanwhile is left as found, too
    os.remove(mac["links"] / "pyrecon")
    gone = tmp_path / "gone" / "PyReconstruct.app" / "Contents" / "Resources" / "bin" / "pyrecon"
    os.symlink(gone, mac["links"] / "pyrecon")
    fixes = C.macos_fixes(C.macos_link_states(mac["bundle"], mac["links"]))
    os.remove(mac["links"] / "pyrecon")
    os.symlink("/usr/bin/true", mac["links"] / "pyrecon")
    assert C.macos_make_links(fixes) == 0
    assert link_to(mac, "pyrecon") == "/usr/bin/true"


@posix_only
def test_a_bundle_outside_applications_gets_nothing(mac, tmp_path):
    loose = tmp_path / "Downloads" / "PyReconstruct.app"
    loose.mkdir(parents=True)
    assert not ensure(mac, bundle=loose)
    assert not mac["links"].exists()
    assert not C.macos_ensure(mac["settings"], None, home=mac["home"], shell="zsh", env={})


@posix_only
def test_dev_uses_its_own_names_beside_stable(mac, monkeypatch):
    ensure(mac)
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    dev_bundle = mac["home"] / "Applications" / "PyReconstruct Dev.app"
    dev_bin = dev_bundle / "Contents" / "Resources" / "bin"
    dev_bin.mkdir(parents=True)
    assert ensure(mac, bundle=dev_bundle, settings=FakeSettings())
    assert sorted(p.name for p in mac["links"].iterdir()) == [
        "pyrecon", "pyrecon-dev", "pyreconstruct", "pyreconstruct-dev"]
    assert link_to(mac, "pyrecon") == str(mac["bin"] / "pyrecon")
    assert link_to(mac, "pyrecon-dev") == str(dev_bin / "pyrecon-dev")
    assert (mac["home"] / ".zprofile").read_text().count(C.PROFILE_TAG) == 1


@posix_only
def test_paths_with_quotes_and_spaces_reach_the_link_intact(mac, tmp_path):
    home = tmp_path / "it's \"odd\" $HOME"
    odd = home / "Applications" / "PyReconstruct.app"
    shutil.copytree(mac["bundle"], odd, symlinks=True)
    assert C.macos_ensure(FakeSettings(), odd, home=home, shell="zsh", env={})
    assert os.readlink(home / ".local" / "bin" / "pyrecon") == str(odd / "Contents" / "Resources" / "bin" / "pyrecon")


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
    assert settings.values == {}


def test_a_frozen_mac_launch_runs_the_mac_step(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    seen = []
    monkeypatch.setattr(C, "own_macos_bundle", lambda: "/Applications/PyReconstruct.app")
    monkeypatch.setattr(C, "macos_ensure", lambda s, b: seen.append(b) or True)
    assert C.ensure_silent(FakeSettings()) is True
    assert seen == ["/Applications/PyReconstruct.app"]


# ---- run.py ---------------------------------------------------------------------------------

def test_run_sets_the_commands_up_without_a_question():
    src = (Path(C.__file__).parents[3] / "run.py").read_text()
    assert "target=ensure_silent" in src
    assert "QMessageBox" not in src.split("def runPyReconstruct")[0]


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
