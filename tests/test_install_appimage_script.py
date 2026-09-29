"""packaging/linux/install-appimage.sh against a stand-in for the GitHub API.

The script is what `curl ... | bash` runs, so it is exercised the same way: as
a shell program, under bash and under a plain POSIX sh, with HOME pointed at a
temporary folder. The "AppImage" it downloads is a small shell script that
answers --appimage-extract the way the real runtime does and records every
other launch, so the tests can check the launcher really runs the file that
was installed. A fake uname and getconf make the Linux checks pass on any
host, so this runs on a macOS laptop as well as on CI.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from linux_installer_harness import FakeGitHub, asset_name, release

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "linux" / "install-appimage.sh"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell installer")

SHELLS = [s for s in ("bash", "dash") if shutil.which(s)]
if not SHELLS:  # pragma: no cover
    SHELLS = ["sh"]

STABLE_ID = "edu.utexas.synapseweb.pyreconstruct"
DEV_ID = "edu.utexas.synapseweb.pyreconstruct.dev"


def fake_appimage(label, app_id):
    """Bytes of a stand-in AppImage. ``label`` makes each build's bytes distinct."""
    desktop = (
        "[Desktop Entry]\\nType=Application\\nName=App\\nExec=cmd %%f\\n"
        f"Icon={app_id}\\nMimeType=application/x-pyreconstruct-jser;\\n"
    )
    return f"""#!/bin/sh
# fake AppImage {label}
if [ "$1" = "--appimage-extract" ]; then
  d=squashfs-root/usr/share
  mkdir -p "$d/applications" "$d/icons/hicolor/512x512/apps" "$d/mime/packages"
  printf '{desktop}' > "$d/applications/{app_id}.desktop"
  printf 'PNG {label}' > "$d/icons/hicolor/512x512/apps/{app_id}.png"
  printf '<mime-info/>' > "$d/mime/packages/{app_id}.xml"
  exit 0
fi
printf '%s|%s|%s\\n' "{label}" "${{APPIMAGE_EXTRACT_AND_RUN:-}}" "$*" >> "$HOME/launches.log"
""".encode()


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "uname").write_text(
        '#!/bin/sh\ncase "$1" in -m) echo "${FAKE_ARCH:-x86_64}";; *) echo Linux;; esac\n')
    (fakebin / "getconf").write_text(
        '#!/bin/sh\n[ "$1" = GNU_LIBC_VERSION ] && echo "glibc ${FAKE_GLIBC:-2.35}"\n')
    for f in fakebin.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    e = {
        "HOME": str(home),
        "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}",
        "LANG": "C",
    }
    return e


def run(env, gh, *args, shell="bash", extra=None, check=True):
    e = {**env, "PYRECON_RELEASES_API": gh.api, **(extra or {})}
    p = subprocess.run([shell, str(SCRIPT), *args], env=e, capture_output=True,
                       text=True, timeout=60)
    if check and p.returncode != 0:
        raise AssertionError(f"exit {p.returncode}\n{p.stderr}")
    return p


def paths(env, flavor):
    home = Path(env["HOME"])
    share = home / ".local" / "share"
    if flavor == "dev":
        name, app_id, cmd, local = "PyReconstruct Dev", DEV_ID, "pyreconstruct-dev", "PyReconstruct-Dev.AppImage"
    else:
        name, app_id, cmd, local = "PyReconstruct", STABLE_ID, "pyreconstruct", "PyReconstruct.AppImage"
    return {
        "root": share / name,
        "appimage": share / name / local,
        "marker": share / name / ".appimage-install",
        "launcher": home / ".local" / "bin" / cmd,
        "desktop": share / "applications" / f"{app_id}.desktop",
        "icon": share / "icons" / "hicolor" / "512x512" / "apps" / f"{app_id}.png",
        "mime": share / "mime" / "packages" / f"{app_id}.xml",
    }


def launches(env):
    log = Path(env["HOME"]) / "launches.log"
    return log.read_text().splitlines() if log.exists() else []


def stable_release(tag, label=None, **kw):
    v = tag.lstrip("v")
    return release(tag, assets={
        asset_name(v, "stable"): fake_appimage(label or tag, STABLE_ID),
        f"PyReconstruct-{v}-Windows-x86_64-Setup.exe": b"exe",
    }, **kw)


def dev_release(tag, label=None, **kw):
    v = tag.lstrip("v")
    return release(tag, prerelease=True, assets={
        asset_name(v, "dev"): fake_appimage(label or tag, DEV_ID),
        f"PyReconstruct-{v}-macOS-arm64-Dev.dmg": b"dmg",
    }, **kw)


# ---- install ----------------------------------------------------------------
@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("pretty", [False, True])
def test_stable_install_lays_out_every_file(env, shell, pretty):
    with FakeGitHub([dev_release("v1.25.0.dev20261001"), stable_release("v1.24.0")],
                    pretty=pretty) as gh:
        p = run(env, gh, shell=shell)
    f = paths(env, "stable")
    assert f["appimage"].read_bytes() == fake_appimage("v1.24.0", STABLE_ID)
    assert os.access(f["appimage"], os.X_OK)
    assert "tag=v1.24.0" in f["marker"].read_text()
    desktop = f["desktop"].read_text()
    assert f'Exec="{f["launcher"]}" %f' in desktop
    assert f"TryExec={f['launcher']}" in desktop
    assert "Exec=cmd" not in desktop
    assert f["icon"].read_text() == "PNG v1.24.0"
    assert f["mime"].exists()
    assert "--uninstall" in p.stderr and "--dev" not in p.stderr.split("Uninstall:")[1]
    # the launcher runs the installed file, and says so without FUSE
    subprocess.run([str(f["launcher"]), "--selftest"], env=env, check=True)
    label, extract, argv = launches(env)[-1].split("|")
    assert (label, argv) == ("v1.24.0", "--selftest")
    if not Path("/dev/fuse").exists():
        assert extract == "1"


@pytest.mark.parametrize("shell", SHELLS)
def test_dev_installs_beside_stable_and_leaves_it_alone(env, shell):
    rels = [dev_release("v1.25.0.dev20261001"), stable_release("v1.24.0")]
    with FakeGitHub(rels) as gh:
        run(env, gh, shell=shell)
        stable_before = {k: v.read_bytes() for k, v in paths(env, "stable").items() if v.is_file()}
        p = run(env, gh, "--dev", shell=shell)
    d = paths(env, "dev")
    assert d["appimage"].read_bytes() == fake_appimage("v1.25.0.dev20261001", DEV_ID)
    assert "tag=v1.25.0.dev20261001" in d["marker"].read_text()
    assert d["launcher"].name == "pyreconstruct-dev"
    assert f'Exec="{d["launcher"]}" %f' in d["desktop"].read_text()
    assert {k: v.read_bytes() for k, v in paths(env, "stable").items() if v.is_file()} == stable_before
    assert "--uninstall --dev" in p.stderr


def test_dev_takes_only_a_nightly(env):
    """Newer stable, release candidate, rolling tag and draft are all passed over."""
    rels = [
        stable_release("v1.26.0"),
        release("v1.26.0rc1", prerelease=True,
                assets={asset_name("1.26.0rc1", "dev"): fake_appimage("rc", DEV_ID)}),
        release("prerelease", prerelease=True,
                assets={"PyReconstruct-9.9.9-linux-x86_64-Dev.AppImage": fake_appimage("roll", DEV_ID)}),
        dev_release("v1.26.0.dev20261003", draft=True),
        dev_release("v1.25.0.dev20261002"),
        dev_release("v1.25.0.dev20261001"),
    ]
    with FakeGitHub(rels) as gh:
        run(env, gh, "--dev")
    assert "tag=v1.25.0.dev20261002" in paths(env, "dev")["marker"].read_text()


def test_dev_falls_back_to_the_newest_nightly_with_an_appimage(env):
    rels = [
        release("v1.25.0.dev20261002", prerelease=True, assets={"PyReconstruct-1.25.0.dev20261002-macOS-arm64-Dev.dmg": b"x"}),
        dev_release("v1.25.0.dev20261001"),
    ]
    with FakeGitHub(rels) as gh:
        p = run(env, gh, "--dev")
    assert "tag=v1.25.0.dev20261001" in paths(env, "dev")["marker"].read_text()
    assert "v1.25.0.dev20261002" in p.stderr and "no Linux AppImage" in p.stderr


def test_stable_never_takes_the_dev_asset(env):
    rel = release("v1.24.0", assets={asset_name("1.24.0", "dev"): fake_appimage("d", DEV_ID)})
    with FakeGitHub([rel]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1
    assert "has no Linux AppImage" in p.stderr
    assert not paths(env, "stable")["root"].exists()


def test_no_stable_release_at_all_is_a_clear_error(env):
    with FakeGitHub([dev_release("v1.25.0.dev20261001")]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1 and "error: could not read the release list" in p.stderr


def test_rate_limited_api_is_a_clear_error(env):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        gh.fail_api = True
        p = run(env, gh, check=False)
    assert p.returncode == 1 and "GITHUB_TOKEN" in p.stderr


# ---- verification -------------------------------------------------------------
def test_checksum_mismatch_installs_nothing_and_keeps_the_old_build(env):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        run(env, gh)
    f = paths(env, "stable")
    good = f["appimage"].read_bytes()
    bad = stable_release("v1.24.1")
    name = asset_name("1.24.1", "stable")
    bad["files"][name + ".sha256"] = (hashlib.sha256(b"other").hexdigest() + f"  {name}\n").encode()
    with FakeGitHub([bad]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1 and "does not match its published checksum" in p.stderr
    assert f["appimage"].read_bytes() == good
    assert "tag=v1.24.0" in f["marker"].read_text()
    assert [x.name for x in f["root"].iterdir() if x.name.startswith(".work")] == []


def test_missing_checksum_refuses(env):
    rel = release("v1.24.0", assets={asset_name("1.24.0", "stable"): fake_appimage("x", STABLE_ID)}, sha=False)
    with FakeGitHub([rel]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1 and ".sha256" in p.stderr
    assert not paths(env, "stable")["appimage"].exists()


# ---- upgrade and re-run ------------------------------------------------------
def test_rerun_upgrades_and_a_current_install_downloads_nothing(env):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        run(env, gh)
    with FakeGitHub([stable_release("v1.24.1"), stable_release("v1.24.0")]) as gh:
        run(env, gh)
        first = list(gh.requests)
        p = run(env, gh)
        second = gh.requests[len(first):]
    f = paths(env, "stable")
    assert f["appimage"].read_bytes() == fake_appimage("v1.24.1", STABLE_ID)
    assert "tag=v1.24.1" in f["marker"].read_text()
    assert any(r.endswith(".AppImage") for r in first)
    assert not any(r.endswith(".AppImage") for r in second)
    assert "already installed" in p.stderr


# ---- uninstall -----------------------------------------------------------------
@pytest.mark.parametrize("shell", SHELLS)
def test_uninstall_removes_one_flavor_only(env, shell):
    with FakeGitHub([dev_release("v1.25.0.dev20261001"), stable_release("v1.24.0")]) as gh:
        run(env, gh, shell=shell)
        run(env, gh, "--dev", shell=shell)
        run(env, gh, "--uninstall", "--dev", shell=shell)
        again = run(env, gh, "--uninstall", "--dev", shell=shell)
    assert not any(v.exists() for v in paths(env, "dev").values())
    assert all(v.exists() for v in paths(env, "stable").values())
    assert "not installed" in again.stderr


def test_uninstall_keeps_a_launcher_it_did_not_write(env):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        run(env, gh)
        f = paths(env, "stable")
        f["launcher"].write_text("#!/bin/sh\necho mine\n")
        p = run(env, gh, "--uninstall")
    assert f["launcher"].read_text() == "#!/bin/sh\necho mine\n"
    assert "did not write it" in p.stderr
    assert not f["appimage"].exists()


def test_uninstall_waits_for_a_running_install(env):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        run(env, gh)
        f = paths(env, "stable")
        (f["root"] / ".install-lock").mkdir()
        p = run(env, gh, "--uninstall", check=False)
    assert p.returncode == 1 and "seems to be running" in p.stderr
    assert f["appimage"].exists() and (f["root"] / ".install-lock").is_dir()


# ---- refusals ------------------------------------------------------------------
def test_refuses_to_overwrite_a_script_based_install(env):
    root = paths(env, "stable")["root"]
    root.mkdir(parents=True)
    (root / ".pyreconstruct-install").write_text(str(root) + "\n")
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1 and "uninstall.sh" in p.stderr
    assert not paths(env, "stable")["appimage"].exists()


def test_refuses_a_foreign_launcher(env):
    launcher = paths(env, "stable")["launcher"]
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1 and "did not write it" in p.stderr


@pytest.mark.parametrize("extra,message", [
    ({"FAKE_ARCH": "aarch64"}, "only an x86_64 AppImage"),
    ({"FAKE_GLIBC": "2.27"}, "needs glibc 2.28"),
])
def test_refuses_an_unsupported_machine(env, extra, message):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        p = run(env, gh, extra=extra, check=False)
    assert p.returncode == 1 and message in p.stderr
    assert gh.requests == []


def test_refuses_plain_http_off_localhost(env):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        p = run(env, gh, extra={"PYRECON_RELEASES_API": "http://example.com/repos/x/y"}, check=False)
    assert p.returncode == 1 and "non-https" in p.stderr


def test_unknown_option_prints_usage(env):
    p = subprocess.run(["bash", str(SCRIPT), "--bogus"], env=env, capture_output=True, text=True)
    assert p.returncode == 2 and "Usage:" in p.stderr


def test_a_first_install_that_stops_early_leaves_no_folder(env):
    bin_dir = Path(env["HOME"]) / ".local" / "bin"
    bin_dir.parent.mkdir(parents=True)
    bin_dir.write_text("not a folder")
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        p = run(env, gh, check=False)
    assert p.returncode == 1 and "cannot write" in p.stderr
    assert not paths(env, "stable")["root"].exists()


def test_every_curl_call_keeps_redirects_on_https():
    calls = [l for l in SCRIPT.read_text().splitlines()
             if "curl -f" in l and not l.lstrip().startswith("#") and "$INSTALLER_URL" not in l]
    assert len(calls) == 3, calls
    for line in calls:
        assert line.count("curl -f") == line.count("--proto-redir =https"), line


@pytest.mark.skipif(sys.version_info[:2] != (3, 11), reason="install.sh needs a Python 3.11")
def test_source_installer_refuses_to_install_over_the_appimage(env):
    root = paths(env, "stable")["root"]
    root.mkdir(parents=True)
    (root / ".appimage-install").write_text("flavor=stable\n")
    p = subprocess.run(["bash", str(ROOT / "packaging" / "linux" / "install.sh")],
                       env={**env, "PYRECON_PYTHON": sys.executable},
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1 and "--uninstall" in p.stderr, p.stderr
    assert sorted(x.name for x in root.iterdir()) == [".appimage-install"]


@pytest.mark.skipif(sys.version_info[:2] != (3, 11), reason="install.sh needs a Python 3.11")
def test_source_installer_with_a_prefix_keeps_the_appimage_launcher(env, tmp_path):
    with FakeGitHub([stable_release("v1.24.0")]) as gh:
        run(env, gh)
    launcher = paths(env, "stable")["launcher"]
    before = launcher.read_text()
    other = tmp_path / "elsewhere"
    p = subprocess.run(["bash", str(ROOT / "packaging" / "linux" / "install.sh"), "--prefix", str(other)],
                       env={**env, "PYRECON_PYTHON": sys.executable},
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 1 and "--uninstall" in p.stderr, p.stderr
    assert launcher.read_text() == before
