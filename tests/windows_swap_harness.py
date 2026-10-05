"""Swap a real Windows install in place, roll one back, and uninstall it.

Run by the swap-windows job in .github/workflows/build-installers.yml on a
windows-2022 runner, over the Windows leg's artifact:

    python tests/windows_swap_harness.py ARTIFACT_DIR

ARTIFACT_DIR holds the Setup.exe, the update archive, and its tree.json from
one build. Everything runs against a real per-user install: the installer, the
frozen helper it put in _updater, the uninstall registry entry, and the app
itself, started and stopped for real. In order:

1. Setup.exe installs silently for this user, and the install folder holds
   exactly what the payload's tree.json lists, plus the uninstaller. The
   frozen helper starts, refuses an empty staging folder, and says why in
   result.json, with no window.
2. An update. With the installed app running, the helper starts from the
   staging folder with the app's pid and waits; then the app is stopped, as
   if the user quit. The helper checks the unpacked payload against tree.json,
   runs the staged copy's self-test, carries the uninstaller over, swaps the
   folders, sets DisplayVersion, and starts the new version. The new version
   reports its own healthy start in health.json, and the helper deletes the
   backup.
3. A forced rollback. The same payload is staged again under a version
   number it does not carry, so the copy the helper starts finds no update
   waiting on it and never reports in. After its timeout the helper stops it,
   puts the old folder back, restores DisplayVersion, records the version as
   failed, and starts the old version again.
4. An uninstall. The uninstaller removes the install folder, the staging
   folder beside it, and its registry entry, though the folder at the install
   path is no longer the one Setup.exe wrote.

The payload is the same build as the installer, so both runs update to the
version already installed. Before each run DisplayVersion is set to a made-up
older version, which the plan names as the one it replaces; the helper never
compares the installed version with anything else. Which folder sits at the
install path is told by its NTFS file ID, since both trees are the same bytes.
"""

import argparse
import fnmatch
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY_PY = ROOT / "PyReconstruct" / "modules" / "backend" / "updater" / "apply.py"
HELPER_EXE = "pyreconstruct-updater.exe"
UNINSTALL = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
CARRY = ["unins*.*"]
FROM_UPDATE = "0.0.1"
FROM_ROLLBACK = "0.0.2"
UNAWAITED = "99.0.0"  # the version step 3 claims to install, which the build is not


def _load_apply():
    spec = importlib.util.spec_from_file_location("pyreconstruct_apply", APPLY_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = _load_apply()


class Failed(Exception):
    pass


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def check(condition, message):
    if not condition:
        raise Failed(message)
    log(f"ok: {message}")


def find_one(folder, pattern):
    hits = sorted(Path(folder).glob(pattern))
    if len(hits) != 1:
        raise Failed(f"expected one {pattern} in {folder}, found {[h.name for h in hits]}")
    return hits[0]


def wait_until(condition, timeout, what, interval=1.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise Failed(f"timed out after {timeout:.0f} s waiting for {what}")
        time.sleep(interval)


# --- The registry ---------------------------------------------------------------

def uninstall_entry(app_name):
    """(key, InstallLocation) of this app's per-user Inno Setup entry, or None."""
    import winreg
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL)
    except OSError:
        return None
    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                return None
            index += 1
            if not name.endswith("_is1"):
                continue
            with winreg.OpenKey(root, name) as key:
                try:
                    location = winreg.QueryValueEx(key, "InstallLocation")[0]
                except OSError:
                    continue
            if isinstance(location, str) and Path(location.rstrip("\\")).name == app_name:
                return f"{UNINSTALL}\\{name}", location


def display_version(key):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        return winreg.QueryValueEx(k, "DisplayVersion")[0]


# --- Trees and processes -----------------------------------------------------------

def _listing(entries):
    return {e["path"]: (e.get("type", "file"), e.get("size"), e.get("sha256")) for e in entries}


def check_matches_tree(folder, tree, what):
    """The folder holds exactly the tree's files, byte for byte, plus the uninstaller."""
    actual = A.build_tree(str(folder), version="-", flavor="-", app_name="-")["files"]
    carried = sorted(e["path"] for e in actual
                     if "/" not in e["path"] and any(fnmatch.fnmatch(e["path"].lower(), p) for p in CARRY))
    got = _listing(e for e in actual if e["path"] not in carried)
    want = _listing(tree["files"])
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    changed = sorted(p for p in set(want) & set(got) if want[p] != got[p])
    check(not (missing or extra or changed),
          f"{what} matches tree.json ({len(want)} entries; missing {missing[:3]}, "
          f"extra {extra[:3]}, changed {changed[:3]})")
    return carried


def file_id(path):
    return os.stat(path).st_ino


def stop_everything_under(platform, folder):
    pids = platform.processes_under(str(folder))
    for pid in pids:
        platform.kill(pid, force=True)
    for pid in pids:
        platform.wait_pid(pid, 30)
    return pids


# --- Staging -------------------------------------------------------------------

def stage(staging, install, archive, tree_path, plan):
    staging.mkdir(exist_ok=True)
    new = staging / A.NEW
    if new.exists():
        shutil.rmtree(new)
    new.mkdir()
    started = time.monotonic()
    with tarfile.open(archive, "r:xz") as tar:
        tar.extractall(new, filter="data")
    log(f"unpacked {archive.name} in {time.monotonic() - started:.0f} s")
    shutil.copyfile(tree_path, staging / A.TREE)
    A.atomic_write_json(str(staging / A.PLAN), plan)
    helper = staging / "helper"
    helper.mkdir(exist_ok=True)
    shutil.copy2(install / "_updater" / HELPER_EXE, helper / HELPER_EXE)
    return helper / HELPER_EXE


def start_helper(helper, staging, pid=None):
    argv = [str(helper), str(staging)] + (["--pid", str(pid)] if pid else [])
    log(f"starting {argv}")
    return subprocess.Popen(argv, cwd=str(staging))


def show(staging):
    for name in (A.RESULT, A.STATE, A.LOG, A.SELFTEST_LOG):
        path = staging / name
        if path.exists():
            print(f"----- {name} -----")
            print(path.read_text(encoding="utf-8", errors="replace")[-8000:])


# --- The run ----------------------------------------------------------------------

def run(artifacts, workdir):
    platform = A.WindowsPlatform()
    setup = find_one(artifacts, "PyReconstruct-*-Windows-x86_64*-Setup.exe")
    archive = find_one(artifacts, "PyReconstruct-*-update-windows-x86_64*.tar.xz")
    tree_path = find_one(artifacts, "PyReconstruct-*-update-windows-x86_64*.tree.json")
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    name, version, flavor = tree["app_name"], tree["version"], tree["flavor"]
    log(f"{name} {version} ({flavor}): {setup.name}, {archive.name}")
    check(archive.name.startswith(f"PyReconstruct-{version}-") and setup.name.startswith(f"PyReconstruct-{version}-"),
          "the installer, the archive, and tree.json are one version")
    check(uninstall_entry(name) is None, f"{name} is not installed yet")

    # 1. Install
    done = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                           f"/LOG={workdir / 'setup.log'}"], timeout=900)
    check(done.returncode == 0, f"Setup.exe exited {done.returncode}")
    entry = uninstall_entry(name)
    check(entry is not None, "Setup.exe wrote a per-user uninstall entry")
    key, location = entry
    install = Path(location.rstrip("\\"))
    staging = install.parent / f".{name}-update"
    log(f"installed at {install}; uninstall key {key}")
    check(display_version(key) == version, f"DisplayVersion is {version}")
    carried = check_matches_tree(install, tree, "the installed folder")
    check("unins000.exe" in carried and "unins000.dat" in carried, f"the uninstaller is in place: {carried}")

    empty = workdir / f".{name}-update"
    empty.mkdir()
    shutil.copy2(install / "_updater" / HELPER_EXE, workdir / HELPER_EXE)
    code = subprocess.run([str(workdir / HELPER_EXE), str(empty)], timeout=120).returncode
    result = A.read_json(str(empty / A.RESULT), {})
    check(code == 1 and result.get("status") == "refused" and "plan.json" in result.get("reason", ""),
          f"the frozen helper runs and refuses an empty staging folder (exit {code}, {result})")

    plan = {
        "format": A.FORMAT, "platform": "windows", "kind": "folder", "install": str(install),
        "app_name": name, "flavor": flavor, "bundle_id": None, "to_version": version,
        "exe": f"{name}.exe", "args": [], "selftest_args": ["--selftest"], "carry": CARRY,
        "registry_key": key,
    }

    # 2. An update, from a running app that then quits
    platform.set_display_version(key, FROM_UPDATE)
    app = subprocess.Popen([str(install / f"{name}.exe")], cwd=str(install.parent), env=A.child_env())
    time.sleep(15)
    check(app.poll() is None, f"the installed app is running (pid {app.pid})")
    helper = stage(staging, install, archive, tree_path, dict(plan, from_version=FROM_UPDATE, pid=app.pid))
    new_id = file_id(staging / A.NEW)
    old_id = file_id(install)
    proc = start_helper(helper, staging, app.pid)
    time.sleep(5)
    check(proc.poll() is None and not (staging / A.OLD).exists(),
          "the helper waits while the app runs and has moved nothing")
    app.kill()
    app.wait(60)
    log("stopped the app, as if the user quit")

    code = proc.wait(900)
    result = A.read_json(str(staging / A.RESULT), {})
    check(code == 0 and result.get("status") == "updated" and result.get("installed") == "new",
          f"the update went in (exit {code}, {result.get('status')}, {result.get('reason')!r})")
    report = A.read_json(str(staging / A.HEALTH), {})
    state = A.read_json(str(staging / A.STATE), {})
    check(report.get("version") == version, f"the new version reported its own start ({report})")
    log(f"health.json came from pid {report.get('pid')}; the helper launched pid {state.get('launched_pid')}")
    check(file_id(install) == new_id and file_id(install) != old_id, "the staged folder is now the install")
    check(not (staging / A.OLD).exists() and not (staging / A.NEW).exists(), "the backup is gone")
    check(display_version(key) == version, f"DisplayVersion went from {FROM_UPDATE} to {version}")
    carried = check_matches_tree(install, tree, "the updated install")
    check("unins000.exe" in carried and "unins000.dat" in carried, f"the uninstaller came along: {carried}")
    stopped = stop_everything_under(platform, install)
    check(bool(stopped), f"the new version was running from the install (pids {stopped})")

    # 3. A forced rollback: the new version never reports a healthy start
    platform.set_display_version(key, FROM_ROLLBACK)
    unawaited_tree = workdir / "unawaited.tree.json"
    unawaited_tree.write_text(json.dumps(dict(tree, version=UNAWAITED)), encoding="utf-8")
    helper = stage(staging, install, archive, unawaited_tree,
                   dict(plan, from_version=FROM_ROLLBACK, to_version=UNAWAITED, pid=None))
    before_id = file_id(install)
    proc = start_helper(helper, staging)
    code = proc.wait(900)
    result = A.read_json(str(staging / A.RESULT), {})
    check(code == 1 and result.get("status") == "rolled_back" and result.get("installed") == "old",
          f"the update was rolled back (exit {code}, {result.get('status')}, {result.get('reason')!r})")
    reason = result.get("reason", "")
    check("did not start in time" in reason or "quit before it finished starting" in reason,
          f"because the new version never reported in ({reason!r})")
    check(result.get("offer_installer") is True, "and the app would offer the installer next")
    check(file_id(install) == before_id, "the folder from before is back at the install path")
    for leftover in (A.OLD, A.NEW, A.REJECTED):
        check(not (staging / leftover).exists(), f"no {leftover}/ is left in staging")
    check(display_version(key) == FROM_ROLLBACK, f"DisplayVersion is back to {FROM_ROLLBACK}")
    failed = A.read_json(str(staging / A.FAILED_VERSIONS), {})
    check(UNAWAITED in failed.get("versions", []), f"{UNAWAITED} is recorded as failed")
    check_matches_tree(install, tree, "the restored install")
    stopped = stop_everything_under(platform, install)
    check(bool(stopped), f"the old version was started again (pids {stopped})")

    # 4. Uninstall
    subprocess.run([str(install / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)

    def uninstalled():
        return not install.exists() and not staging.exists() and uninstall_entry(name) is None

    try:
        wait_until(uninstalled, 300, "the uninstaller to finish")
    except Failed:
        left = [str(p) for base in (install, staging) if base.exists() for p in base.rglob("*")][:20]
        raise Failed(f"the uninstall left {left or 'the registry entry'} behind")
    log("ok: the uninstall removed the install, the staging folder, and the registry entry")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("artifacts", type=Path, help="the Windows leg's artifact folder")
    args = ap.parse_args(argv)
    if os.name != "nt":
        raise SystemExit("this runs on Windows only")
    workdir = Path(tempfile.mkdtemp(prefix="swap-"))
    try:
        run(args.artifacts.resolve(), workdir)
    except Exception as e:
        log(f"FAILED: {e}")
        entry = None
        try:
            entry = uninstall_entry(json.loads(find_one(
                args.artifacts, "*.tree.json").read_text(encoding="utf-8"))["app_name"])
        except Exception:
            pass
        if entry:
            install = Path(entry[1].rstrip("\\"))
            show(install.parent / f".{install.name}-update")
            stop_everything_under(A.WindowsPlatform(), install)
        if (workdir / "setup.log").exists():
            print("----- setup.log (tail) -----")
            print((workdir / "setup.log").read_text(encoding="utf-8", errors="replace")[-4000:])
        return 1
    log("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
