"""The in-place swap engine leaves one whole version at the install path, never a mix.

``backend/updater/apply.py`` renames a staged build into the install folder
at quit and puts the old one back if the new one does not start. A user's
install is on the line, so these tests run it against fake install folders
laid out like the real ones (a Windows onedir folder with its uninstaller, a
macOS bundle with framework links) and a fake platform standing in for
processes, launching, and the registry.

The central check kills the helper at every journal write, both just before
the write lands and just after, then runs it again. Whatever the moment, the
second run has to leave the old install or the new one in place byte for
byte, with state.json saying which. The rest covers each way a run ends
early: a self-test that fails, a new version that never reports healthy, a
locked folder, a second rename that fails, and every input the helper must
refuse before it touches anything.
"""
import json
import os
import plistlib
import stat
import sys
import time
from dataclasses import replace

import pytest

from PyReconstruct.modules.backend.updater import apply as A

OLD_V, NEW_V = "1.23.0", "1.24.0"
STABLE_ID = "edu.utexas.synapseweb.pyreconstruct"
DEV_ID = "edu.utexas.synapseweb.pyreconstruct.dev"
UNINSTALL_KEY = A._UNINSTALL_KEY_PREFIX + "{A1B2C3D4-E5F6-47A8-9B0C-1D2E3F4A5B6C}_is1"

FAST = A.Timings(pid_exit=2, selftest=5, health=2, lock_retry=0.05, lock_wait=0.2,
                 kill_wait=0.5, interval=0.01, poll=0.01)


def _can_symlink(tmp_path_factory):
    probe = tmp_path_factory.mktemp("probe")
    try:
        os.symlink("target", probe / "link")
    except (OSError, NotImplementedError):
        return False
    return True


@pytest.fixture(scope="session")
def can_symlink(tmp_path_factory):
    return _can_symlink(tmp_path_factory)


# --- Fake install folders --------------------------------------------------------

def _write(root, rel, content, mode=0o644):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content.encode() if isinstance(content, str) else content)
    os.chmod(path, mode)


def windows_tree(root, version, app_name="PyReconstruct"):
    """A PyInstaller onedir folder, cut down. Files differ between versions, and each has one the other lacks."""
    _write(root, f"{app_name}.exe", f"exe {version}", 0o755)
    _write(root, "_internal/base_library.zip", f"stdlib {version} " * 50)
    _write(root, "_internal/PySide6/Qt6Core.dll", f"qt {version}", 0o755)
    _write(root, "version.txt", version)
    if version == OLD_V:
        _write(root, "_internal/dropped_in_new.pyd", "old only")
    else:
        _write(root, "_internal/added_in_new.pyd", "new only")


def macos_tree(root, version, links, app_name="PyReconstruct", bundle_id=STABLE_ID):
    """A .app bundle, cut down, with the framework links a real one carries."""
    info = {"CFBundleIdentifier": bundle_id, "CFBundleExecutable": app_name,
            "CFBundleName": app_name, "CFBundleShortVersionString": version}
    _write(root, "Contents/Info.plist", plistlib.dumps(info))
    _write(root, f"Contents/MacOS/{app_name}", f"exe {version}", 0o755)
    fw = "Contents/Frameworks/Python.framework"
    _write(root, f"{fw}/Versions/A/Python", f"libpython {version}", 0o755)
    _write(root, "version.txt", version)
    os.makedirs(os.path.join(root, "Contents", "Resources", "empty"))
    if links:
        os.symlink("A", os.path.join(root, *f"{fw}/Versions/Current".split("/")))
        os.symlink("Versions/Current/Python", os.path.join(root, *f"{fw}/Python".split("/")))


def snapshot(root):
    """Everything that makes a tree what it is: kinds, bytes, modes, link targets."""
    if os.path.isfile(root):
        with open(root, "rb") as f:
            return {".": ("file", f.read())}
    out = {}
    for rel, st in A._walk(root).items():
        full = os.path.join(root, *rel.split("/"))
        if stat.S_ISLNK(st.st_mode):
            out[rel] = ("link", os.readlink(full))
        elif stat.S_ISDIR(st.st_mode):
            out[rel] = ("dir",)
        else:
            with open(full, "rb") as f:
                out[rel] = ("file", f.read(), stat.S_IMODE(st.st_mode) if os.name != "nt" else None)
    return out


class World:
    """The processes, registry, and file-system quirks the fake platform reports."""

    def __init__(self):
        self.next_pid = 40000
        self.alive = {}           # pid -> executable path
        self.launches = []
        self.versions = {}        # launched pid -> the version it runs
        self.kills = []
        self.selftests = []
        self.selftest_code = 0
        self.healthy = {OLD_V: True, NEW_V: True}
        self.quits_on_start = set()
        self.launch_error = None
        self.registry = {}
        self.rename_hook = None
        self.install = None
        self.staging = None

    def spawn(self, exe):
        pid = self.next_pid
        self.next_pid += 1
        self.alive[pid] = exe
        return pid


class FakePlatform(A.Platform):

    def __init__(self, world):
        self.w = world

    def pid_alive(self, pid):
        return pid in self.w.alive

    def kill(self, pid, force=False):
        self.w.kills.append(pid)
        self.w.alive.pop(pid, None)

    def launch(self, argv, cwd):
        if self.w.launch_error:
            raise self.w.launch_error
        self.w.launches.append(list(argv))
        pid = self.w.spawn(argv[0])
        marker = os.path.join(self.w.install, "version.txt") if os.path.isdir(self.w.install) else self.w.install
        with open(marker, "rb") as f:
            text = f.read().decode()
        version = OLD_V if OLD_V in text else NEW_V
        self.w.versions[pid] = version
        if version in self.w.quits_on_start:
            del self.w.alive[pid]
        elif self.w.healthy.get(version):
            A.write_health(self.w.staging, version, pid)
        return pid

    def run(self, argv, timeout, cwd):
        self.w.selftests.append(list(argv))
        return self.w.selftest_code

    def processes_under(self, path):
        return [p for p, exe in self.w.alive.items() if A._inside(exe, os.path.abspath(path))]

    def set_display_version(self, key, version):
        self.w.registry[key] = version

    def rename(self, src, dst):
        if self.w.rename_hook:
            self.w.rename_hook(src, dst)
        os.rename(src, dst)


class Setup:
    """One fake install with a staged update next to it, and the snapshots to judge the end state by."""

    def __init__(self, tmp_path, style, links=False):
        self.style = style
        self.parent = str(tmp_path / "Programs")
        os.makedirs(self.parent)
        self.world = World()
        if style == "windows":
            self.install = os.path.join(self.parent, "PyReconstruct")
            windows_tree(self.install, OLD_V)
            _write(self.install, "unins000.exe", "inno uninstaller", 0o755)
            _write(self.install, "unins000.dat", "inno log")
        elif style == "macos":
            self.install = os.path.join(self.parent, "PyReconstruct.app")
            macos_tree(self.install, OLD_V, links)
        else:  # one file, the shape of the Linux AppImage
            self.install = os.path.join(self.parent, "PyReconstruct.AppImage")
            _write(self.parent, "PyReconstruct.AppImage", f"appimage {OLD_V}", 0o755)
        self.staging = os.path.join(self.parent, ".PyReconstruct-update")
        os.makedirs(self.staging)
        self.new = os.path.join(self.staging, "new")
        if style == "windows":
            windows_tree(self.new, NEW_V)
        elif style == "macos":
            macos_tree(self.new, NEW_V, links)
        else:
            _write(self.staging, "new", f"appimage {NEW_V}", 0o755)
        self.old_snap = snapshot(self.install)
        self.staged_snap = snapshot(self.new)
        self.new_snap = dict(self.staged_snap)
        if style == "windows":
            for name in ("unins000.exe", "unins000.dat"):
                self.new_snap[name] = self.old_snap[name]
        self.world.install = self.install
        self.world.staging = self.staging
        app_pid = self.world.spawn(self.install)
        del self.world.alive[app_pid]  # the app has already quit
        self.plan = {
            "format": 1, "platform": {"windows": "windows", "macos": "macos"}.get(style, "linux"),
            "kind": "file" if style == "file" else "folder",
            "install": self.install, "app_name": "PyReconstruct", "flavor": "stable",
            "bundle_id": STABLE_ID if style == "macos" else None,
            "from_version": OLD_V, "to_version": NEW_V, "pid": app_pid,
            "exe": {"windows": "PyReconstruct.exe", "macos": "Contents/MacOS/PyReconstruct"}.get(style, "."),
            "args": [os.path.join(str(tmp_path), "series.jser")],
            "carry": ["unins*.*"] if style == "windows" else [],
            "registry_key": UNINSTALL_KEY if style == "windows" else None,
        }
        self.write_plan()
        self.write_tree()

    def write_plan(self, **changes):
        self.plan.update(changes)
        A.atomic_write_json(os.path.join(self.staging, "plan.json"), self.plan)

    def write_tree(self, **identity):
        header = {"version": NEW_V, "flavor": "stable", "app_name": "PyReconstruct",
                  "bundle_id": self.plan["bundle_id"], "platform": self.plan["platform"]}
        header.update(identity)
        self.tree = A.build_tree(self.new, **header)
        A.atomic_write_json(os.path.join(self.staging, "tree.json"), self.tree)

    def applier(self, cls=A.Applier, timings=FAST, **kw):
        return cls(self.staging, FakePlatform(self.world), timings, host=self.plan["platform"], **kw)

    def read(self, name):
        return A.read_json(os.path.join(self.staging, name))

    def exe(self, root):
        if self.plan["kind"] == "file":
            return root
        return os.path.join(root, *self.plan["exe"].split("/"))

    def settled(self):
        """Which whole version is at the install path; fails on anything else."""
        state = self.read("state.json")
        assert state["status"] == "done", state
        now = snapshot(self.install) if os.path.lexists(self.install) else None
        if now == self.old_snap:
            which = "old"
        elif now == self.new_snap:
            which = "new"
        else:
            pytest.fail(f"the install is neither version: {sorted(now or {})}")
        assert state["installed"] == which
        assert self.read("result.json")["installed"] == which
        assert not os.path.lexists(os.path.join(self.staging, "rejected"))
        if which == "new":
            assert not os.path.lexists(os.path.join(self.staging, "old"))
        return which


@pytest.fixture
def win(tmp_path):
    return Setup(tmp_path, "windows")


def _untouched(s):
    assert snapshot(s.install) == s.old_snap
    assert snapshot(s.new) == s.staged_snap
    assert not os.path.lexists(os.path.join(s.staging, "old"))
    assert s.world.launches == []
    assert s.world.registry == {}


# --- A real swap --------------------------------------------------------------------

def test_windows_swap_puts_the_new_folder_in_place(win):
    result = win.applier().run()

    assert result["status"] == "updated"
    assert win.settled() == "new"
    # the uninstaller came along, so Settings > Apps can still remove it
    assert snapshot(win.install)["unins000.dat"] == win.old_snap["unins000.dat"]
    assert win.world.selftests == [[win.exe(win.new), "--selftest"]]
    assert win.world.launches == [[win.exe(win.install), win.plan["args"][0]]]
    assert win.world.registry == {UNINSTALL_KEY: NEW_V}
    assert not os.path.lexists(win.new)
    assert result["offer_installer"] is False
    state = win.read("state.json")
    assert state["step"] == "finish" and state["result"] == "updated"


def test_macos_swap_keeps_the_bundle_links(tmp_path, can_symlink):
    s = Setup(tmp_path, "macos", links=can_symlink)
    assert s.applier().run()["status"] == "updated"
    assert s.settled() == "new"
    if can_symlink:
        link = os.path.join(s.install, "Contents", "Frameworks", "Python.framework", "Python")
        assert os.readlink(link).replace(os.sep, "/") == "Versions/Current/Python"


def test_one_file_swap_fits_the_same_engine(tmp_path):
    """The Linux AppImage will be one file, not a folder. The same steps swap it."""
    s = Setup(tmp_path, "file")
    assert s.applier().run()["status"] == "updated"
    assert s.settled() == "new"
    assert s.world.launches == [[s.install, s.plan["args"][0]]]


def test_running_again_after_a_finished_update_keeps_its_result(win):
    """A second helper run finds nothing staged. It must not report the old version back in place."""
    win.applier().run()
    result = win.applier().run()
    assert result["status"] == "nothing_staged"
    assert win.settled() == "new"
    assert win.read("result.json")["status"] == "updated"


def test_journal_is_replaced_whole_and_leaves_no_temp_files(win):
    win.applier().run()
    assert sorted(n for n in os.listdir(win.staging) if n.endswith(".tmp")) == []


def test_waits_for_the_app_to_exit_first(win):
    pid = win.world.spawn(win.install)
    win.write_plan(pid=pid)
    result = win.applier().run()
    assert result["status"] == "deferred"
    assert "did not exit" in result["reason"]
    _untouched(win)


# --- A crash at every step, then a recovery run ---------------------------------------

class Crash(BaseException):
    """The helper process dying. BaseException, so no handler in apply.py can catch it."""


def crashing_at(point, when):
    class CrashingApplier(A.Applier):
        def _journal(self, step, phase, **extra):
            hit = (step, phase) == point
            if hit and when == "before":
                raise Crash
            super()._journal(step, phase, **extra)
            if hit and when == "after":
                raise Crash
    return CrashingApplier


HEALTHY_POINTS = [(s, p) for s in A.FORWARD for p in ("begin", "end")] + [("finish", "end")]
_HEALTH = A.FORWARD.index("health")
UNHEALTHY_POINTS = (
    [(s, p) for s in A.FORWARD[:_HEALTH] for p in ("begin", "end")] + [("health", "begin")]
    + [(s, p) for s in A.ROLLBACK for p in ("begin", "end")] + [("finish", "end")]
)


def _expected_after_crash(point, when):
    """Old until the second rename is known to have happened; new from then on."""
    order = [(pt, w) for pt in HEALTHY_POINTS for w in ("before", "after")]
    return "new" if order.index((point, when)) >= order.index((("swap_in", "end"), "before")) else "old"


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("point", HEALTHY_POINTS, ids=lambda p: f"{p[0]}-{p[1]}")
@pytest.mark.parametrize("style", ["windows", "macos"])
def test_crash_then_recovery_leaves_one_whole_version(tmp_path, can_symlink, style, point, when):
    s = Setup(tmp_path, style, links=can_symlink)
    with pytest.raises(Crash):
        s.applier(crashing_at(point, when)).run()

    s.applier().run()

    which = s.settled()
    if point == ("wait", "begin") and when == "before":
        # nothing was journaled, so the second run is simply the first one
        assert which == "new"
    else:
        assert which == _expected_after_crash(point, when)
    if which == "old":
        # the staged tree is back as tree.json lists it, so the next quit applies it
        assert s.read("result.json")["status"] == "interrupted"
        assert snapshot(s.new) == s.staged_snap
        assert s.applier().run()["status"] == "updated"
        assert s.settled() == "new"


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("point", UNHEALTHY_POINTS, ids=lambda p: f"{p[0]}-{p[1]}")
def test_crash_during_a_rollback_still_ends_on_the_old_version(win, point, when):
    win.world.healthy[NEW_V] = False
    timings = replace(FAST, health=0.05)
    with pytest.raises(Crash):
        win.applier(crashing_at(point, when), timings=timings).run()

    win.applier(timings=timings).run()

    assert win.settled() == "old"
    # no copy of the new version is left running
    assert [p for p in win.world.alive if win.world.versions.get(p) == NEW_V] == []


def test_recovery_removes_a_half_deleted_backup(win):
    with pytest.raises(Crash):
        win.applier(crashing_at(("cleanup", "begin"), "after")).run()
    old = os.path.join(win.staging, "old")
    os.remove(os.path.join(old, "version.txt"))  # the delete had got part way
    win.applier().run()
    assert win.settled() == "new"


def test_recovery_waits_while_the_first_helper_is_alive(win):
    with pytest.raises(Crash):
        win.applier(crashing_at(("swap_out", "end"), "after")).run()
    state = win.read("state.json")
    state["helper_pid"] = win.world.spawn("still-running-helper")
    A.atomic_write_json(os.path.join(win.staging, "state.json"), state)

    result = win.applier().run()

    assert result["status"] == "busy"
    assert not os.path.lexists(win.install)  # it left the half-done swap to its owner
    assert win.read("state.json")["status"] == "running"


# --- Early ends ---------------------------------------------------------------------------

def test_failed_selftest_touches_nothing(win):
    win.world.selftest_code = 1
    result = win.applier().run()
    assert result["status"] == "selftest_failed"
    assert result["installed"] == "old" and result["offer_installer"] is True
    _untouched(win)
    assert win.read("failed-versions.json")["versions"] == [NEW_V]


def test_selftest_timeout_counts_as_a_failure(win):
    win.world.selftest_code = None
    assert win.applier().run()["status"] == "selftest_failed"
    _untouched(win)


def test_health_timeout_rolls_back(win):
    win.world.healthy[NEW_V] = False
    result = win.applier(timings=replace(FAST, health=0.2)).run()

    assert result["status"] == "rolled_back"
    assert win.settled() == "old"
    [new_pid] = [p for p, v in win.world.versions.items() if v == NEW_V]
    assert new_pid in win.world.kills
    assert win.world.launches == [[win.exe(win.install), win.plan["args"][0]]] * 2
    assert win.world.registry == {UNINSTALL_KEY: OLD_V}
    assert win.read("failed-versions.json")["versions"] == [NEW_V]
    assert result["offer_installer"] is True


def test_new_version_that_quits_rolls_back_without_waiting_out_the_timeout(win):
    win.world.quits_on_start.add(NEW_V)
    start = time.monotonic()
    result = win.applier(timings=replace(FAST, health=30)).run()
    assert result["status"] == "rolled_back"
    assert time.monotonic() - start < 10
    assert win.settled() == "old"


def test_launch_error_rolls_back(win):
    win.world.launch_error = RuntimeError("no such program")
    assert win.applier().run()["status"] == "rolled_back"
    assert win.settled() == "old"


def test_failed_version_is_not_tried_again(win):
    win.world.healthy[NEW_V] = False
    win.applier(timings=replace(FAST, health=0.05)).run()
    win.world.healthy[NEW_V] = True
    windows_tree(win.new, NEW_V)  # stage it again

    result = win.applier().run()

    assert result["status"] == "refused"
    assert "failed before" in result["reason"]


def _locked(path):
    def hook(src, dst):
        if os.path.normcase(src) == os.path.normcase(path):
            raise PermissionError(32, "The process cannot access the file", src)
    return hook


def test_locked_install_defers_then_offers_the_installer(win):
    win.world.rename_hook = _locked(win.install)
    for count in (1, 2, 3):
        result = win.applier().run()
        assert result["status"] == "deferred"
        assert result["deferrals"] == count
        assert result["offer_installer"] is (count >= A.MAX_DEFERRALS)
        _untouched(win)  # carried files were taken back out of new/


def test_lock_that_clears_is_retried(win):
    tries = []

    def hook(src, dst):
        if src == win.install and len(tries) < 3:
            tries.append(src)
            raise PermissionError(32, "in use", src)

    win.world.rename_hook = hook
    assert win.applier().run()["status"] == "updated"
    assert len(tries) == 3


def test_lock_held_by_a_process_is_waited_out(win):
    """Past the plain retry window, a process still running from the folder keeps it waiting."""
    holder = win.world.spawn(os.path.join(win.install, "_internal", "worker.exe"))
    tries = []

    def hook(src, dst):
        if src == win.install and holder in win.world.alive:
            tries.append(src)
            if len(tries) >= 30:
                del win.world.alive[holder]  # the worker exits
            raise PermissionError(32, "in use", src)

    win.world.rename_hook = hook
    timings = replace(FAST, lock_retry=0.02, lock_wait=10)
    assert win.applier(timings=timings).run()["status"] == "updated"
    assert len(tries) == 30


def test_second_rename_failure_puts_the_old_version_back(win):
    win.world.rename_hook = _locked(win.new)
    result = win.applier().run()
    assert result["status"] == "deferred"
    assert win.settled() == "old"
    _untouched(win)


# --- Refusals: nothing is touched --------------------------------------------------------

def _refused(s, fragment):
    result = s.applier().run()
    assert result["status"] == "refused", result
    assert fragment in result["reason"], result["reason"]
    _untouched(s)
    assert s.world.selftests == []


@pytest.mark.parametrize("path", [
    "../evil.dll", "_internal/../../evil.dll", "/etc/passwd", "C:/Windows/evil.dll",
    "C:evil.dll", "_internal\\..\\..\\evil.dll", "//server/share/evil.dll",
    "_internal//evil.dll", "./evil.dll", "_internal/.",
])
def test_refuses_tree_paths_that_escape(win, path):
    win.tree["files"].append({"path": path, "size": 1, "sha256": "0" * 64, "mode": 0o644})
    A.atomic_write_json(os.path.join(win.staging, "tree.json"), win.tree)
    _refused(win, "path in tree")


def test_refuses_windows_device_names_in_a_windows_tree(win):
    win.tree["files"].append({"path": "_internal/NUL.txt", "size": 1, "sha256": "0" * 64, "mode": 0o644})
    A.atomic_write_json(os.path.join(win.staging, "tree.json"), win.tree)
    _refused(win, "unsafe path")


def test_refuses_names_that_are_one_file_on_windows_and_macos(win):
    entry = dict(next(e for e in win.tree["files"] if e["path"] == "version.txt"))
    entry["path"] = "VERSION.txt"
    win.tree["files"].append(entry)
    A.atomic_write_json(os.path.join(win.staging, "tree.json"), win.tree)
    _refused(win, "duplicate path")


@pytest.mark.parametrize("target", ["../../../outside", "/etc", "C:/Windows", ".."])
def test_refuses_listed_links_that_point_outside(tmp_path, target):
    s = Setup(tmp_path, "macos")
    s.tree["files"].append({"path": "Contents/evil", "type": "symlink", "target": target})
    A.atomic_write_json(os.path.join(s.staging, "tree.json"), s.tree)
    _refused(s, "link")


@pytest.mark.skipif(os.name == "nt", reason="Windows collapses '..' by name before following links")
def test_refuses_a_link_chain_that_climbs_out_on_disk(tmp_path, can_symlink):
    """By name 'd/../../x' stays inside; on disk 'd' is another link, and the chain climbs out."""
    if not can_symlink:
        pytest.skip("this runner cannot create symlinks")
    s = Setup(tmp_path, "macos", links=True)
    os.makedirs(os.path.join(s.new, "z"))
    _write(s.new, "z/keep", "x")
    base = os.path.join(s.new, "Contents", "Resources")
    os.symlink("../../z", os.path.join(base, "d"))
    os.symlink("d/../../x", os.path.join(base, "e"))
    s.staged_snap = snapshot(s.new)
    s.write_tree()
    _refused(s, "points outside")


def test_refuses_an_unlisted_link_in_the_staged_tree(tmp_path, can_symlink):
    if not can_symlink:
        pytest.skip("this runner cannot create symlinks")
    s = Setup(tmp_path, "macos", links=True)
    os.symlink("../../..", os.path.join(s.new, "Contents", "sneaky"))
    s.staged_snap = snapshot(s.new)
    _refused(s, "unlisted")


def test_refuses_staging_that_is_not_next_to_the_install(tmp_path):
    s = Setup(tmp_path, "windows")
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    moved = str(elsewhere / ".PyReconstruct-update")
    os.rename(s.staging, moved)
    s.staging = moved
    s.new = os.path.join(moved, "new")
    _refused(s, "not next to the install")


def test_refuses_staging_named_for_another_app(win):
    other = os.path.join(win.parent, ".PyReconstruct Dev-update")
    os.rename(win.staging, other)
    win.staging, win.new = other, os.path.join(other, "new")
    _refused(win, "not next to the install")


def test_refuses_a_dev_tree_for_a_stable_install(win):
    win.write_tree(flavor="dev", app_name="PyReconstruct Dev")
    _refused(win, "flavor")


def test_refuses_a_tree_for_another_app_name(win):
    win.write_tree(app_name="PyReconstruct Dev")
    _refused(win, "app_name")


def test_refuses_a_dev_plan_over_a_stable_install(win):
    """Staging, plan, and tree all say Dev, but the folder being replaced holds stable's program."""
    dev = os.path.join(win.parent, ".PyReconstruct Dev-update")
    os.rename(win.staging, dev)
    win.staging, win.new = dev, os.path.join(dev, "new")
    win.write_plan(app_name="PyReconstruct Dev", flavor="dev")
    _refused(win, "the install is not PyReconstruct Dev")


def test_refuses_a_stable_plan_over_a_dev_bundle(tmp_path):
    s = Setup(tmp_path, "macos")
    info = os.path.join(s.install, "Contents", "Info.plist")
    with open(info, "rb") as f:
        data = plistlib.load(f)
    data["CFBundleIdentifier"] = DEV_ID
    with open(info, "wb") as f:
        plistlib.dump(data, f)
    s.old_snap = snapshot(s.install)
    _refused(s, "the install has a different bundle id")


def test_refuses_a_tree_listed_for_another_bundle_id(tmp_path):
    s = Setup(tmp_path, "macos")
    s.write_tree(bundle_id=DEV_ID)
    _refused(s, "bundle_id")


def test_refuses_a_bundle_with_another_bundle_id(tmp_path):
    s = Setup(tmp_path, "macos")
    info = os.path.join(s.new, "Contents", "Info.plist")
    with open(info, "rb") as f:
        data = plistlib.load(f)
    data["CFBundleIdentifier"] = DEV_ID
    with open(info, "wb") as f:
        plistlib.dump(data, f)
    s.staged_snap = snapshot(s.new)
    s.write_tree()  # tree.json matches the disk; only the bundle itself says Dev
    _refused(s, "bundle id")


def test_refuses_a_plan_whose_flavor_and_name_disagree(win):
    win.write_plan(flavor="dev")
    _refused(win, "does not match app name")


def test_tree_verify_catches_one_changed_byte(win):
    path = os.path.join(win.new, "_internal", "base_library.zip")
    with open(path, "r+b") as f:
        f.seek(100)
        byte = f.read(1)
        f.seek(100)
        f.write(bytes([byte[0] ^ 1]))
    win.staged_snap = snapshot(win.new)
    _refused(win, "does not match its checksum")


def test_tree_verify_catches_an_extra_file(win):
    _write(win.new, "_internal/injected.dll", "x")
    win.staged_snap = snapshot(win.new)
    _refused(win, "unlisted entry: _internal/injected.dll")


def test_tree_verify_catches_a_missing_file(win):
    os.remove(os.path.join(win.new, "_internal", "added_in_new.pyd"))
    win.staged_snap = snapshot(win.new)
    _refused(win, "missing _internal/added_in_new.pyd")


@pytest.mark.skipif(os.name == "nt", reason="Windows keeps no mode bits")
def test_tree_verify_catches_a_changed_mode(tmp_path):
    s = Setup(tmp_path, "macos")
    os.chmod(os.path.join(s.new, "Contents", "MacOS", "PyReconstruct"), 0o777)
    s.staged_snap = snapshot(s.new)
    _refused(s, "wrong mode")


def test_refuses_a_setuid_mode_in_the_tree(win):
    entry = next(e for e in win.tree["files"] if e["path"] == "version.txt")
    entry["mode"] = 0o4755
    A.atomic_write_json(os.path.join(win.staging, "tree.json"), win.tree)
    _refused(win, "bad mode")


def test_refuses_a_plan_for_another_platform(win):
    result = A.Applier(win.staging, FakePlatform(win.world), FAST, host="macos").run()
    assert result["status"] == "refused"
    _untouched(win)


def test_refuses_a_registry_key_outside_the_uninstall_list(win):
    win.write_plan(registry_key="Software\\Classes\\exefile\\shell\\open\\command")
    _refused(win, "registry_key")


def test_refuses_a_leftover_backup_with_no_finished_journal(win):
    os.makedirs(os.path.join(win.staging, "old"))
    result = win.applier().run()
    assert result["status"] == "refused"
    assert "backup from an earlier run" in result["reason"]
    assert snapshot(win.install) == win.old_snap


def test_refuses_a_missing_plan(tmp_path):
    staging = tmp_path / ".PyReconstruct-update"
    staging.mkdir()
    result = A.Applier(str(staging), FakePlatform(World()), FAST).run()
    assert result["status"] == "refused"
    assert A.read_json(str(staging / "result.json"))["status"] == "refused"


# --- Pieces -------------------------------------------------------------------------------

def test_atomic_write_keeps_the_old_file_when_the_replace_fails(tmp_path, monkeypatch):
    path = str(tmp_path / "state.json")
    A.atomic_write_json(path, {"step": "one"})

    def fail(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(A.os, "replace", fail)
    with pytest.raises(OSError):
        A.atomic_write_json(path, {"step": "two"})
    monkeypatch.undo()
    assert A.read_json(path) == {"step": "one"}
    assert os.listdir(tmp_path) == ["state.json"]


def _python():
    """A real interpreter, not a venv launcher, so its pid is the process that runs."""
    return os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable)


def test_real_platform_runs_waits_and_kills(tmp_path):
    """The OS layer itself, with a Python child standing in for the app. No registry."""
    plat = A.default_platform()
    exe = _python()

    assert plat.run([exe, "-c", "raise SystemExit(3)"], 30, str(tmp_path)) == 3
    start = time.monotonic()
    assert plat.run([exe, "-c", "import time; time.sleep(30)"], 0.5, str(tmp_path)) is None
    assert time.monotonic() - start < 20

    pid = plat.launch([exe, "-c", "import time; time.sleep(60)"], str(tmp_path))
    try:
        assert plat.pid_alive(pid)
        assert not plat.wait_pid(pid, 0.2, 0.05)
        deadline = time.monotonic() + 10
        while pid not in plat.processes_under(os.path.dirname(exe)) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert pid in plat.processes_under(os.path.dirname(exe))
        assert pid not in plat.processes_under(str(tmp_path))
    finally:
        plat.kill(pid, force=True)
    assert plat.wait_pid(pid, 10, 0.05)
    assert not plat.pid_alive(pid)


def test_build_tree_round_trips_through_verify(tmp_path, can_symlink):
    root = str(tmp_path / "PyReconstruct.app")
    macos_tree(root, NEW_V, can_symlink)
    tree = A.build_tree(root, version=NEW_V, flavor="stable", app_name="PyReconstruct", bundle_id=STABLE_ID)
    A.verify_tree(root, json.loads(json.dumps(tree)))
    assert {"path": "Contents/Resources/empty", "type": "dir",
            "mode": stat.S_IMODE(os.stat(os.path.join(root, "Contents", "Resources", "empty")).st_mode)} \
        in tree["files"]
