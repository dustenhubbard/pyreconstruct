"""The terminal commands written into a frozen build (packaging/make_cli_shims.py).

The generator is checked for the names and the layout per flavor and
platform. The macOS command is a POSIX sh script, so it runs here for real
against a stand-in bundle, with a stub ``open`` first on PATH that records
what it was handed: an absolute path, the bundle it found by following its
links, and nothing at all for a file that is not there.
"""

import importlib.util
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "make_cli_shims.py"

_spec = importlib.util.spec_from_file_location("make_cli_shims", SCRIPT)
shims = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shims)

posix_only = pytest.mark.skipif(os.name == "nt", reason="the macOS command is a sh script")


# ---- names and layout ---------------------------------------------------------

def test_each_flavor_has_its_own_two_names():
    assert shims.command_names("stable") == ("pyrecon", "pyreconstruct")
    assert shims.command_names("dev") == ("pyrecon-dev", "pyreconstruct-dev")
    assert not set(shims.command_names("stable")) & set(shims.command_names("dev"))


def test_the_flavor_comes_from_the_build_name():
    assert shims.flavor_of("dist/PyReconstruct.app") == "stable"
    assert shims.flavor_of("dist/PyReconstruct Dev.app") == "dev"
    assert shims.flavor_of("dist/PyReconstruct") == "stable"
    assert shims.flavor_of("dist/PyReconstruct Dev") == "dev"
    with pytest.raises(ValueError):
        shims.flavor_of("dist/Something.app")


def test_the_names_match_the_app_side():
    from PyReconstruct.modules.backend.func import cli_commands
    assert cli_commands.command_names(dev=False) == shims.command_names("stable")
    assert cli_commands.command_names(dev=True) == shims.command_names("dev")


def fake_bundle(parent, name="PyReconstruct", version="1.25.0.dev202610211200"):
    app = Path(parent) / f"{name}.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": "x", "PyReconstructVersion": version}, f)
    return app


@posix_only
@pytest.mark.parametrize("name,short,long_", [
    ("PyReconstruct", "pyrecon", "pyreconstruct"),
    ("PyReconstruct Dev", "pyrecon-dev", "pyreconstruct-dev"),
])
def test_macos_layout(tmp_path, name, short, long_):
    app = fake_bundle(tmp_path, name)
    shims.write_shims(app, "macos")
    bin_dir = app / "Contents" / "Resources" / "bin"
    assert sorted(p.name for p in bin_dir.iterdir()) == sorted([short, long_])
    script = bin_dir / long_
    assert not script.is_symlink()
    assert script.stat().st_mode & stat.S_IXUSR
    assert script.read_text().startswith("#!/bin/sh\n")
    assert f"app='{name}'" in script.read_text()
    # the short name is a link beside it, relative, so it stays inside the bundle
    assert os.readlink(bin_dir / short) == long_


def test_windows_layout(tmp_path):
    folder = tmp_path / "PyReconstruct Dev"
    folder.mkdir()
    shims.write_shims(folder, "windows", version="1.25.0.dev202610211200")
    names = sorted(p.name for p in (folder / "bin").iterdir())
    assert names == ["pyrecon-dev.cmd", "pyreconstruct-dev.cmd"]
    text = (folder / "bin" / "pyrecon-dev.cmd").read_bytes().decode("ascii")
    assert "\n" not in text.replace("\r\n", "")  # CRLF throughout
    assert 'set "APP_EXE=%~dp0..\\PyReconstruct Dev.exe"' in text
    assert 'if not exist "%~f1" goto missing' in text
    assert 'start "" "%APP_EXE%" "%~f1"' in text
    assert "echo PyReconstruct Dev 1.25.0.dev202610211200" in text
    # no parenthesized block, where a ")" in a path would end the block
    assert "(" not in text


def test_windows_refuses_a_version_cmd_would_misread():
    for bad in ("", "1.0 & del x", "1.0%PATH%", "1.0)"):
        with pytest.raises(ValueError):
            shims.windows_shim("stable", "pyrecon", bad)


def test_refuses_a_build_that_already_has_commands(tmp_path):
    app = fake_bundle(tmp_path)
    shims.write_shims(app, "macos")
    with pytest.raises(FileExistsError):
        shims.write_shims(app, "macos")


# ---- the macOS command, run for real ------------------------------------------

@pytest.fixture
def mac(tmp_path):
    """A stand-in bundle in a folder with a space, its commands, and a stub
    ``open`` that records its arguments one per line."""
    apps = tmp_path / "My Apps"
    apps.mkdir()
    app = fake_bundle(apps)
    shims.write_shims(app, "macos")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    log = tmp_path / "open.log"
    (fakebin / "open").write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > "{log}"\n')
    (fakebin / "open").chmod(0o755)
    env = {"PATH": f"{fakebin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(tmp_path), "LANG": "C"}
    return {"app": app, "bin": app / "Contents" / "Resources" / "bin", "log": log, "env": env,
            "tmp": tmp_path}


def run_cmd(mac, command, *args, cwd=None):
    return subprocess.run([str(command), *args], env=mac["env"], cwd=cwd or mac["tmp"],
                          capture_output=True, text=True, timeout=30)


def opened(mac):
    return mac["log"].read_text().splitlines() if mac["log"].exists() else None


def same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


@posix_only
def test_a_relative_path_is_handed_over_absolute(mac):
    work = mac["tmp"] / "work"
    work.mkdir()
    (work / "series.jser").write_text("{}")
    p = run_cmd(mac, mac["bin"] / "pyrecon", "series.jser", cwd=work)
    assert p.returncode == 0, p.stderr
    a, bundle, path = opened(mac)
    assert a == "-a"
    assert same(bundle, mac["app"])
    assert os.path.isabs(path) and same(path, work / "series.jser")


@posix_only
def test_spaces_in_the_file_and_the_bundle_path(mac):
    folder = mac["tmp"] / "lab data" / "rat 3"
    folder.mkdir(parents=True)
    (folder / "my series.jser").write_text("{}")
    p = run_cmd(mac, mac["bin"] / "pyreconstruct", "rat 3/my series.jser", cwd=folder.parent)
    assert p.returncode == 0, p.stderr
    a, bundle, path = opened(mac)
    assert same(bundle, mac["app"]) and " " in bundle
    assert same(path, folder / "my series.jser")


@posix_only
def test_a_missing_file_exits_1_and_opens_nothing(mac):
    p = run_cmd(mac, mac["bin"] / "pyrecon", "nope.jser")
    assert p.returncode == 1
    assert "no such file: nope.jser" in p.stderr
    assert opened(mac) is None


@posix_only
def test_a_folder_is_not_a_series(mac):
    (mac["tmp"] / "folder.jser").mkdir()
    p = run_cmd(mac, mac["bin"] / "pyrecon", "folder.jser")
    assert p.returncode == 1
    assert opened(mac) is None


@posix_only
def test_it_follows_links_from_a_folder_on_path(mac):
    """~/.local/bin/pyrecon -> <bundle>/.../bin/pyrecon -> pyreconstruct."""
    link_dir = mac["tmp"] / "local-bin"
    link_dir.mkdir()
    os.symlink(mac["bin"] / "pyrecon", link_dir / "pyrecon")
    # and a relative link, one more hop away
    os.symlink("pyrecon", link_dir / "pr")
    (mac["tmp"] / "a.jser").write_text("{}")
    mac["env"]["PATH"] = f"{link_dir}{os.pathsep}{mac['env']['PATH']}"
    for name in ("pyrecon", "pr"):
        mac["log"].unlink(missing_ok=True)
        p = subprocess.run([name, "a.jser"], env=mac["env"], cwd=mac["tmp"],
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr
        a, bundle, path = opened(mac)
        assert same(bundle, mac["app"])
        assert same(path, mac["tmp"] / "a.jser")


@posix_only
def test_no_argument_starts_the_app(mac):
    p = run_cmd(mac, mac["bin"] / "pyrecon")
    assert p.returncode == 0, p.stderr
    a, bundle = opened(mac)
    assert a == "-a" and same(bundle, mac["app"])


@posix_only
def test_an_option_is_not_a_file(mac):
    p = run_cmd(mac, mac["bin"] / "pyrecon", "--frobnicate")
    assert p.returncode == 2
    assert opened(mac) is None
    p = run_cmd(mac, mac["bin"] / "pyrecon", "--help")
    assert p.returncode == 0 and "usage: pyreconstruct" in p.stdout


@posix_only
def test_a_script_outside_a_bundle_says_so(mac, tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    shutil.copy2(mac["bin"] / "pyreconstruct", loose / "pyreconstruct")
    p = run_cmd(mac, loose / "pyreconstruct")
    assert p.returncode == 1
    assert "cannot find PyReconstruct" in p.stderr
    assert opened(mac) is None


@pytest.mark.skipif(not os.path.exists("/usr/libexec/PlistBuddy"), reason="macOS PlistBuddy")
def test_version_reads_the_bundle(mac):
    p = run_cmd(mac, mac["bin"] / "pyrecon", "--version")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "PyReconstruct 1.25.0.dev202610211200"
    assert shims.check_shims(mac["app"], "macos") == []


@pytest.mark.skipif(sys.platform != "win32", reason="runs a .cmd")
def test_windows_check_runs_each_command(tmp_path):  # pragma: no cover - Windows CI only
    folder = tmp_path / "PyReconstruct"
    folder.mkdir()
    shims.write_shims(folder, "windows", version="1.24.0")
    assert shims.check_shims(folder, "windows", "1.24.0") == []


# ---- the macOS seal -------------------------------------------------------------

codesign_only = pytest.mark.skipif(shutil.which("codesign") is None, reason="macOS codesign")


def sealed_bundle(parent, name="PyReconstruct"):
    """A stand-in bundle with a real executable, sealed ad hoc the way
    PyInstaller leaves a build no identity signed."""
    app = fake_bundle(parent, name)
    exe = app / "Contents" / "MacOS" / name
    shutil.copyfile("/usr/bin/true", exe)
    exe.chmod(0o755)
    with open(app / "Contents" / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    info.update(CFBundleExecutable=name, CFBundleIdentifier="edu.example.sealtest",
                CFBundlePackageType="APPL")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    (app / "Contents" / "Resources").mkdir()
    (app / "Contents" / "Resources" / "data.txt").write_text("sealed\n")
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True,
                   capture_output=True, timeout=60)
    return app


def verify(app):
    return subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)],
                          capture_output=True, text=True, timeout=60)


@codesign_only
@pytest.mark.parametrize("name", ["PyReconstruct", "PyReconstruct Dev"])
def test_an_ad_hoc_sealed_bundle_stays_sealed(tmp_path, name):
    app = sealed_bundle(tmp_path, name)
    assert verify(app).returncode == 0
    shims.write_shims(app, "macos")
    done = verify(app)
    assert done.returncode == 0, done.stderr
    assert shims._signature(app) == "adhoc"
    assert shims.check_shims(app, "macos") == []


@codesign_only
def test_check_reports_a_broken_seal(tmp_path):
    app = sealed_bundle(tmp_path)
    shims.write_shims(app, "macos")
    (app / "Contents" / "Resources" / "late.txt").write_text("added after the seal\n")
    problems = shims.check_shims(app, "macos")
    assert len(problems) == 1
    assert "codesign --verify --deep --strict" in problems[0]
    assert "late.txt" in problems[0]


def test_a_bundle_signed_with_an_identity_is_refused(tmp_path, monkeypatch):
    app = fake_bundle(tmp_path)
    monkeypatch.setattr(shims, "_signature", lambda build: "identity")
    with pytest.raises(ValueError, match="before signing"):
        shims.write_shims(app, "macos")
    assert not (app / "Contents" / "Resources" / "bin").exists()


def test_an_unsigned_bundle_is_not_signed(tmp_path, monkeypatch):
    app = fake_bundle(tmp_path)
    monkeypatch.setattr(shims, "_signature", lambda build: None)
    monkeypatch.setattr(shims, "_reseal_adhoc", lambda build: pytest.fail("signed an unsigned bundle"))
    shims.write_shims(app, "macos")
    assert (app / "Contents" / "Resources" / "bin" / "pyreconstruct").exists()
