"""The Windows in-place update payload: what the release builds and ships.

The Windows leg freezes the update helper into the app's _updater folder,
builds Setup.exe, and packs the same folder as
``PyReconstruct-<ver>-update-windows-x86_64[-Dev].tar.xz`` with its
``.tree.json`` (scripts/build_update_payload.py). The swap-windows job then
installs Setup.exe and swaps the payload in on a real Windows install
(tests/windows_swap_harness.py), and the release job leaves the payload out
if that failed. The manifest names the payload for Windows but keeps
in-place updates off.

These checks run anywhere: the payload unpacks to exactly the tree the helper
verifies, the names are the ones no installer matcher takes, the manifest
describes the payload only when it is there and belongs to this release, and
the workflow runs the pieces in the order that makes the installer and the
payload the same app.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.updater import apply as A

from test_old_clients_never_pick_update_assets import planned
from test_pruning_preserves_release_tags import workflow_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_update_payload as P  # noqa: E402

MANIFEST_SCRIPT = SCRIPTS / "release_update_files.py"
WORKFLOW = ROOT / ".github" / "workflows" / "build-installers.yml"
HELPER_SPEC = ROOT / "packaging" / "windows" / "pyreconstruct-updater.spec"
HARNESS = ROOT / "tests" / "windows_swap_harness.py"

STABLE, NIGHTLY = "1.24.0", "1.24.0.dev20260929"


def fake_app(root, flavor="stable"):
    """A small stand-in for dist/<app>: the program, the helper, and a payload folder."""
    name = P.app_name(flavor)
    app = root / name
    (app / "_internal" / "PySide6" / "plugins").mkdir(parents=True)
    (app / "_internal" / "empty").mkdir()
    (app / "_updater").mkdir()
    (app / f"{name}.exe").write_bytes(b"MZ program " + os.urandom(64))
    (app / "_updater" / "pyreconstruct-updater.exe").write_bytes(b"MZ helper " + os.urandom(64))
    (app / "_internal" / "python311.dll").write_bytes(os.urandom(4096))
    (app / "_internal" / "PySide6" / "plugins" / "qwindows.dll").write_bytes(os.urandom(1024))
    (app / "_internal" / "base_library.zip").write_bytes(b"")
    return app


def _members(archive):
    with tarfile.open(archive, "r:xz") as tar:
        return tar.getmembers()


# --- The payload -------------------------------------------------------------------

@pytest.mark.parametrize("version,flavor", [(STABLE, "stable"), (NIGHTLY, "dev")])
def test_the_payload_names_are_the_planned_ones(version, flavor):
    names = P.payload_names(version, flavor)
    assert set(names) <= set(planned(version, "-Dev" if flavor == "dev" else ""))


@pytest.mark.parametrize("flavor", ["stable", "dev"])
def test_the_archive_unpacks_to_exactly_the_tree_the_helper_checks(tmp_path, flavor):
    app = fake_app(tmp_path, flavor)
    archive, tree_path, tree = P.build(app, NIGHTLY, flavor, tmp_path / "out", mtime=1_700_000_000)

    assert (archive.name, tree_path.name) == P.payload_names(NIGHTLY, flavor)
    assert json.loads(tree_path.read_text(encoding="utf-8")) == tree
    assert tree_path.read_bytes().endswith(b"\n") and b"\r" not in tree_path.read_bytes()
    assert {k: tree[k] for k in ("format", "version", "flavor", "app_name", "bundle_id", "platform")} == {
        "format": A.FORMAT, "version": NIGHTLY, "flavor": flavor, "app_name": P.app_name(flavor),
        "bundle_id": None, "platform": "windows-x86_64",
    }

    members = _members(archive)
    assert [m.name for m in members] == [e["path"] for e in tree["files"]]
    assert all(m.uid == 0 and m.gid == 0 and m.uname == "" and m.mtime == 1_700_000_000 for m in members)

    new = tmp_path / "staging" / "new"
    new.mkdir(parents=True)
    with tarfile.open(archive, "r:xz") as tar:
        tar.extractall(new, filter="data")
    A.verify_tree(str(new), tree, windows=True, check_mode=False)
    listed = {e["path"] for e in tree["files"]}
    assert f"{P.app_name(flavor)}.exe" in listed and P.HELPER in listed
    assert "_internal/empty" in listed, "an empty folder is kept"


def test_the_tree_matches_the_folder_byte_for_byte(tmp_path):
    app = fake_app(tmp_path)
    _, _, tree = P.build(app, STABLE, "stable", tmp_path / "out")
    for e in tree["files"]:
        if e.get("type", "file") == "file":
            data = app.joinpath(*e["path"].split("/")).read_bytes()
            assert (e["size"], e["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())


def test_a_folder_without_the_helper_is_refused(tmp_path):
    """The version it installs could never update itself in place."""
    app = fake_app(tmp_path)
    shutil.rmtree(app / "_updater")
    with pytest.raises(SystemExit, match="pyreconstruct-updater.exe"):
        P.build(app, STABLE, "stable", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_folder_for_the_other_flavor_is_refused(tmp_path):
    app = fake_app(tmp_path, "stable")
    with pytest.raises(SystemExit, match="dev app"):
        P.build(app, NIGHTLY, "dev", tmp_path / "out")


@pytest.mark.skipif(os.name == "nt", reason="these names cannot be made on Windows")
@pytest.mark.parametrize("bad", ["NUL.dll", "trailing. ", "COM1"])
def test_a_name_the_helper_would_refuse_is_refused_here(tmp_path, bad):
    app = fake_app(tmp_path)
    (app / "_internal" / bad).write_bytes(b"x")
    with pytest.raises(SystemExit, match="helper would refuse"):
        P.build(app, STABLE, "stable", tmp_path / "out")


@pytest.mark.skipif(os.name == "nt", reason="needs a symlink")
def test_a_link_is_refused(tmp_path):
    app = fake_app(tmp_path)
    os.symlink("python311.dll", app / "_internal" / "python3.dll")
    with pytest.raises(SystemExit, match="files and folders only"):
        P.build(app, STABLE, "stable", tmp_path / "out")


# --- The manifest ------------------------------------------------------------------

def _dist_with_payload(tmp_path, version, flavor):
    dist = tmp_path / "dist"
    dist.mkdir()
    dev = "-Dev" if flavor == "dev" else ""
    setup = f"PyReconstruct-{version}-Windows-x86_64{dev}-Setup.exe"
    (dist / setup).write_bytes(os.urandom(1024))
    archive, tree_path, tree = P.build(fake_app(tmp_path, flavor), version, flavor, dist)
    return dist, setup, archive, tree_path, tree


def _manifest(dist, tag, flavor):
    r = subprocess.run([sys.executable, str(MANIFEST_SCRIPT), str(dist), "--tag", tag, "--flavor", flavor],
                       capture_output=True, text=True, timeout=60)
    return r, (json.loads((dist / "update-manifest.json").read_text()) if r.returncode == 0 else None)


@pytest.mark.parametrize("tag,version,flavor", [("v1.24.0", STABLE, "stable"),
                                                ("v1.24.0.dev20260929", NIGHTLY, "dev")])
def test_the_manifest_names_the_windows_payload_and_keeps_it_off(tmp_path, tag, version, flavor):
    dist, setup, archive, tree_path, tree = _dist_with_payload(tmp_path, version, flavor)
    r, manifest = _manifest(dist, tag, flavor)
    assert r.returncode == 0, r.stderr

    files = [e for e in tree["files"] if e.get("type", "file") == "file"]
    assert manifest["platforms"]["windows-x86_64"] == {
        "inplace": {"enabled": False},
        "min_client": version,
        "payload": {"name": archive.name, "size": archive.stat().st_size},
        "tree": {"name": tree_path.name, "size": tree_path.stat().st_size},
        "installed_size": sum(e["size"] for e in files),
        "files": len(files),
    }
    for other in ("macos-arm64", "macos-x86_64", "linux-x86_64"):
        assert manifest["platforms"][other] == {"inplace": {"enabled": False}, "min_client": version}

    listed = [line.split("  ", 1)[1] for line in (dist / "SHA256SUMS").read_text().splitlines()]
    assert archive.name in listed and tree_path.name in listed, "the signature covers the payload"


def test_no_payload_leaves_the_windows_entry_bare(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"PyReconstruct-{STABLE}-Windows-x86_64-Setup.exe").write_bytes(b"x")
    r, manifest = _manifest(dist, "v1.24.0", "stable")
    assert r.returncode == 0, r.stderr
    assert manifest["platforms"]["windows-x86_64"] == {"inplace": {"enabled": False}, "min_client": STABLE}


def _listed(dist):
    return [line.split("  ", 1)[1] for line in (dist / "SHA256SUMS").read_text().splitlines()]


@pytest.mark.parametrize("half", [0, 1])
def test_half_a_payload_is_not_published(tmp_path, half):
    dist, setup, archive, tree_path, _ = _dist_with_payload(tmp_path, STABLE, "stable")
    gone, left = (archive, tree_path) if half == 0 else (tree_path, archive)
    gone.unlink()
    (dist / f"{left.name}.sha256").write_text("x")
    r, manifest = _manifest(dist, "v1.24.0", "stable")
    assert r.returncode == 0, r.stderr
    assert "payload" not in manifest["platforms"]["windows-x86_64"]
    assert f"left {left.name} out of the release: it has no partner" in r.stdout
    assert not left.exists() and not (dist / f"{left.name}.sha256").exists()
    assert _listed(dist) == sorted(["update-manifest.json", setup], key=str.encode)


@pytest.mark.parametrize("key,value", [("version", "1.23.9"), ("flavor", "dev"),
                                       ("app_name", "PyReconstruct Dev"), ("platform", "macos-arm64")])
def test_a_tree_from_another_build_is_left_out_and_the_installers_ship(tmp_path, key, value):
    dist, setup, archive, tree_path, tree = _dist_with_payload(tmp_path, STABLE, "stable")
    tree_path.write_text(json.dumps(dict(tree, **{key: value})), encoding="utf-8")
    r, manifest = _manifest(dist, "v1.24.0", "stable")
    assert r.returncode == 0, r.stderr
    assert f"its tree.json has {key}" in r.stdout
    assert "payload" not in manifest["platforms"]["windows-x86_64"]
    assert not archive.exists() and not tree_path.exists()
    assert setup in _listed(dist) and archive.name not in _listed(dist)


@pytest.mark.parametrize("text", ["{not json", "[]", '{"files": []}'])
def test_a_broken_tree_is_left_out_and_the_installers_ship(tmp_path, text):
    dist, setup, archive, tree_path, tree = _dist_with_payload(tmp_path, STABLE, "stable")
    if text.startswith('{"files"'):
        text = json.dumps(dict(tree, files=[e for e in tree["files"] if e.get("type") == "dir"]))
    tree_path.write_text(text, encoding="utf-8")
    r, manifest = _manifest(dist, "v1.24.0", "stable")
    assert r.returncode == 0, r.stderr
    assert "payload" not in manifest["platforms"]["windows-x86_64"]
    assert not archive.exists() and not tree_path.exists()
    assert setup in _listed(dist)


def test_a_misnamed_payload_file_is_not_published(tmp_path):
    """Only this release's pair ships; any other payload name goes, with its .sha256."""
    dist, setup, archive, tree_path, _ = _dist_with_payload(tmp_path, STABLE, "stable")
    strays = [
        *P.payload_names("1.23.9", "stable"),                  # another version
        *P.payload_names(STABLE, "dev"),                       # the other flavor
        f"{archive.name}.partial",                             # a half-written archive
        f"PyReconstruct-{STABLE}-update-windows-x86_64.tar.gz",  # the wrong kind
    ]
    for name in strays:
        (dist / name).write_bytes(b"x")
        (dist / f"{name}.sha256").write_text("x")
    r, manifest = _manifest(dist, "v1.24.0", "stable")
    assert r.returncode == 0, r.stderr
    for name in strays:
        assert f"left {name} out of the release" in r.stdout
        assert not (dist / name).exists() and not (dist / f"{name}.sha256").exists()
    assert manifest["platforms"]["windows-x86_64"]["payload"]["name"] == archive.name
    assert sorted(_listed(dist), key=str.encode) == sorted(
        [setup, archive.name, tree_path.name, "update-manifest.json"], key=str.encode)


@pytest.mark.parametrize("fail_at", ["archive", "tree", "rename"])
def test_a_failed_build_leaves_no_payload_file(tmp_path, monkeypatch, fail_at):
    """The Windows leg then uploads Setup.exe alone, with no half of a payload beside it."""
    app = fake_app(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "Setup.exe").write_bytes(b"x")
    # A payload of the same name from an earlier run goes too, so no stale half survives.
    for name in P.payload_names(STABLE, "stable"):
        (out / name).write_bytes(b"old")

    def boom(*a, **k):
        raise OSError("disk full")

    if fail_at == "archive":
        calls = []
        real = tarfile.TarFile.addfile

        def addfile(self, *a, **k):
            calls.append(1)
            if len(calls) > 2:
                boom()
            return real(self, *a, **k)
        monkeypatch.setattr(tarfile.TarFile, "addfile", addfile)
    elif fail_at == "tree":
        monkeypatch.setattr(Path, "write_text", boom)
    else:
        real_replace = os.replace

        def replace(src, dst):
            if str(dst).endswith(".tree.json"):
                boom()
            return real_replace(src, dst)
        monkeypatch.setattr(P.os, "replace", replace)

    with pytest.raises(OSError, match="disk full"):
        P.build(app, STABLE, "stable", out)
    assert sorted(p.name for p in out.iterdir()) == ["Setup.exe"]


# --- The helper and the workflow -----------------------------------------------------

def test_the_helper_is_apply_py_alone_with_no_window_and_no_dialog():
    spec = HELPER_SPEC.read_text(encoding="utf-8")
    assert '"PyReconstruct" / "modules" / "backend" / "updater" / "apply.py"' in spec
    assert 'name="pyreconstruct-updater"' in spec
    assert "console=False" in spec
    assert "disable_windowed_traceback=True" in spec
    assert "upx=False" in spec
    # one file: the binaries and data go into the EXE, and there is no COLLECT
    assert "a.binaries,\n    a.datas," in spec and "COLLECT(" not in spec


def test_every_part_uses_one_helper_path():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert P.HELPER == "_updater/pyreconstruct-updater.exe"
    assert 'Copy-Item "build\\updater-dist\\pyreconstruct-updater.exe" "dist\\$app\\_updater\\"' in workflow
    assert 'HELPER_EXE = "pyreconstruct-updater.exe"' in HARNESS.read_text(encoding="utf-8")
    iss = (ROOT / "packaging" / "windows" / "PyReconstruct.iss").read_text(encoding="utf-8")
    assert r'Name: "{app}\_updater"' in iss


def _step_order(job):
    """The step names of one job, in order."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = re.split(r"\n  [a-z-]+:\n", workflow.split(f"\n  {job}:\n", 1)[1], maxsplit=1)[0]
    return [line.strip()[len("- name: "):] for line in body.splitlines()
            if line.strip().startswith("- name: ")]


def test_the_installer_and_the_payload_are_built_from_the_same_folder():
    steps = _step_order("build")
    order = [
        "PyInstaller freeze",
        "Freeze the in-place update helper (Windows)",
        "Report the frozen app's size (Windows)",
        "Frozen self-test (Windows) — catches windowed-only import bugs",
        "Build Windows installer (Inno Setup)",
        "Build the in-place update payload (Windows)",
    ]
    assert [s for s in steps if s in order] == order


def test_the_release_waits_for_the_swap_test_and_holds_back_a_failed_payload():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "needs: [build, build-linux, test-appimage, swap-windows]" in workflow
    swap = workflow.split("\n  swap-windows:\n", 1)[1].split("\n  release:\n", 1)[0]
    assert "runs-on: windows-2022" in swap
    assert "needs: build" in swap
    assert "python tests/windows_swap_harness.py artifact" in swap
    assert "name: installer-Windows-x86_64" in swap
    steps = _step_order("release")
    assert steps.index("Hold back a Windows update payload that failed its swap test") < steps.index(
        "Generate checksums") < steps.index("Write the update manifest and SHA256SUMS")
    assert "if: needs.swap-windows.result != 'success'" in workflow


@pytest.mark.skipif(os.name == "nt", reason="runs the workflow's shell step")
def test_the_hold_back_step_removes_the_payload_and_nothing_else(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    keep = [f"PyReconstruct-{NIGHTLY}-Windows-x86_64-Dev-Setup.exe",
            f"PyReconstruct-{NIGHTLY}-macOS-arm64-Dev.dmg",
            f"PyReconstruct-{NIGHTLY}-linux-x86_64-Dev.AppImage"]
    drop = list(P.payload_names(NIGHTLY, "dev")) + list(P.payload_names(STABLE, "stable"))
    for n in keep + drop:
        (dist / n).write_bytes(b"x")
    script = workflow_script(WORKFLOW.name, "Hold back a Windows update payload that failed its swap test")
    subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=tmp_path, check=True, timeout=60)
    assert sorted(p.name for p in dist.iterdir()) == sorted(keep)


def _step(job, name):
    """One step's text, from its name line to the next step."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = workflow.split(f"\n  {job}:\n", 1)[1]
    return body.split(f"- name: {name}\n", 1)[1].split("\n      - ", 1)[0]


def test_a_failed_helper_or_payload_never_costs_the_release_its_setup_exe():
    helper = _step("build", "Freeze the in-place update helper (Windows)")
    assert "id: helper" in helper and "continue-on-error: true" in helper
    assert 'Remove-Item -LiteralPath "dist\\$app\\_updater" -Recurse' in helper, \
        "a failed freeze leaves no half-copied helper for Setup.exe to install"

    payload = _step("build", "Build the in-place update payload (Windows)")
    assert "id: payload" in payload and "continue-on-error: true" in payload
    assert "if: runner.os == 'Windows' && steps.helper.outcome == 'success'" in payload
    assert 'Remove-Item "dist-assets\\PyReconstruct-*-update-windows-*"' in payload

    # Everything from the helper to the upload either cannot fail on the
    # helper's account or carries on past it, and the upload itself waits on
    # neither step.
    upload = WORKFLOW.read_text(encoding="utf-8").split("- uses: actions/upload-artifact@v7\n", 1)[1]
    upload = upload.split("\n\n", 1)[0]
    assert "steps.helper" not in upload and "steps.payload" not in upload
    assert "path: dist-assets/*" in upload
