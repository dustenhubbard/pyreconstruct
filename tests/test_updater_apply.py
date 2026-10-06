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
                 kill_wait=0.5, interval=0.01, poll=0.01, backoff_max=0.04)


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
    _write(root, "Contents/Resources/version.txt", version)
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
        self.selftest_logs = []
        self.selftest_code = 0
        self.registry_error = None
        self.healthy = {OLD_V: True, NEW_V: True}
        self.quits_on_start = set()
        self.launch_error = None
        self.registry = {}
        self.install_locations = {}
        self.rename_hook = None
        self.on_poll = None       # called on every processes_under, to change the world mid-wait
        self.slow_start = set()   # versions that report healthy only once the helper looks
        self.pending_health = {}
        self.start_times = {}
        self.install = None
        self.staging = None

    def spawn(self, exe):
        pid = self.next_pid
        self.next_pid += 1
        self.alive[pid] = exe
        self.start_times[pid] = f"started-{pid}"
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
        marker = self.w.install
        if os.path.isdir(marker):
            marker = next(m for m in (os.path.join(marker, "version.txt"),
                                      os.path.join(marker, "Contents", "Resources", "version.txt"))
                          if os.path.exists(m))
        with open(marker, "rb") as f:
            text = f.read().decode()
        version = OLD_V if OLD_V in text else NEW_V
        self.w.versions[pid] = version
        if version in self.w.quits_on_start:
            del self.w.alive[pid]
        elif self.w.healthy.get(version) and version in self.w.slow_start:
            self.w.pending_health[pid] = version
        elif self.w.healthy.get(version):
            A.write_health(self.w.staging, version, pid)
        return pid

    def run(self, argv, timeout, cwd, log=None):
        self.w.selftests.append(list(argv))
        self.w.selftest_logs.append(log)
        return self.w.selftest_code

    def processes_under(self, path):
        if self.w.on_poll:
            self.w.on_poll()
        for pid, version in list(self.w.pending_health.items()):
            if pid in self.w.alive:
                A.write_health(self.w.staging, version, pid)
            del self.w.pending_health[pid]
        return [p for p, exe in self.w.alive.items() if A._at_or_inside(exe, os.path.abspath(path))]

    def start_time(self, pid):
        return self.w.start_times.get(pid) if pid in self.w.alive else None

    def install_location(self, key):
        return self.w.install_locations.get(key)

    def set_display_version(self, key, version):
        if self.w.registry_error:
            raise self.w.registry_error
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
        if style == "windows":
            self.world.install_locations[UNINSTALL_KEY] = self.install + "\\"  # as Inno Setup writes it
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
    helper = win.world.spawn("still-running-helper")
    state["helper_pid"], state["helper_start"] = helper, win.world.start_times[helper]
    A.atomic_write_json(os.path.join(win.staging, "state.json"), state)

    result = win.applier().run()

    assert result["status"] == "busy"
    assert not os.path.lexists(win.install)  # it left the half-done swap to its owner
    assert win.read("state.json")["status"] == "running"


def test_recovery_ignores_a_reused_helper_pid(win):
    """The dead helper's pid now belongs to another process, which started later."""
    with pytest.raises(Crash):
        win.applier(crashing_at(("swap_out", "end"), "after")).run()
    state = win.read("state.json")
    stranger = win.world.spawn("some-other-program")
    state["helper_pid"], state["helper_start"] = stranger, "started-long-ago"
    A.atomic_write_json(os.path.join(win.staging, "state.json"), state)

    win.applier().run()

    assert win.settled() == "old"
    assert stranger in win.world.alive


def test_a_reused_launched_pid_is_neither_trusted_nor_killed(win):
    """The new version died with the helper, and its pid went to a stranger outside the install."""
    win.world.healthy[NEW_V] = False
    with pytest.raises(Crash):
        win.applier(crashing_at(("launch", "end"), "after")).run()
    pid = win.read("state.json")["launched_pid"]
    win.world.alive[pid] = os.path.join(os.sep, "usr", "bin", "stranger")

    result = win.applier(timings=replace(FAST, health=30)).run()

    assert result["status"] == "rolled_back"
    assert "quit before" in result["reason"]  # not a 30 second wait on the stranger
    assert pid not in win.world.kills and pid in win.world.alive
    assert win.settled() == "old"


def test_recovery_adopts_a_new_version_launched_by_the_dead_run(win):
    """The helper died after starting the new version but before recording its pid."""
    win.world.slow_start.add(NEW_V)
    with pytest.raises(Crash):
        win.applier(crashing_at(("launch", "end"), "before")).run()
    assert win.read("state.json")["launched_pid"] is None

    assert win.applier().run()["status"] == "updated"

    new_launches = [p for p, v in win.world.versions.items() if v == NEW_V]
    assert len(new_launches) == 1, "started a second copy"
    assert new_launches[0] in win.world.alive and new_launches[0] not in win.world.kills
    assert win.settled() == "new"


def test_a_second_helper_touches_nothing(win):
    held = A.take_lock(win.staging)
    assert held is not None
    try:
        result = win.applier().run()
    finally:
        A.release_lock(held)

    assert result["status"] == "busy"
    _untouched(win)
    for name in ("state.json", "result.json", "helper.log"):
        assert not os.path.exists(os.path.join(win.staging, name)), name
    assert win.applier().run()["status"] == "updated"  # the lock goes with its holder


def test_restore_keeps_trying_until_the_old_version_is_back(win):
    """Nothing starts another helper once PyReconstruct is gone, so this run must not give up."""
    win.world.healthy[NEW_V] = False
    fails = []

    def hook(src, dst):
        if src == os.path.join(win.staging, "old") and len(fails) < 12:
            fails.append(src)
            raise PermissionError(32, "in use", src)

    win.world.rename_hook = hook
    result = win.applier(timings=replace(FAST, health=0.05, lock_retry=0.01)).run()

    assert result["status"] == "rolled_back"
    assert len(fails) == 12
    assert win.settled() == "old"
    with open(os.path.join(win.staging, "helper.log"), encoding="utf-8") as f:
        assert f.read().count("putting the old version back, try") == 12


def test_a_stuck_run_keeps_its_backup(win):
    """After a stuck end, old/ may be the only copy of the install."""
    old = os.path.join(win.staging, "old")
    _write(old, "only-copy.txt", "precious")
    A.atomic_write_json(os.path.join(win.staging, "state.json"),
                        {"format": 1, "status": "done", "result": "stuck", "installed": None})

    result = win.applier().run()

    assert result["status"] == "refused"
    with open(os.path.join(old, "only-copy.txt")) as f:
        assert f.read() == "precious"


def test_a_stale_backup_is_cleared_even_when_the_run_refuses(win):
    """A refusal writes a new result, so the backup of a finished update must go before any check."""
    old = os.path.join(win.staging, "old")
    _write(old, "stale.txt", "x")
    _write(os.path.join(win.staging, "rejected"), "stale.txt", "x")
    A.atomic_write_json(os.path.join(win.staging, "state.json"),
                        {"format": 1, "status": "done", "result": "updated", "installed": "new"})
    A.atomic_write_json(os.path.join(win.staging, "failed-versions.json"), {"versions": [NEW_V]})

    assert win.applier().run()["status"] == "refused"
    assert not os.path.lexists(old)
    assert not os.path.lexists(os.path.join(win.staging, "rejected"))

    os.remove(os.path.join(win.staging, "failed-versions.json"))
    assert win.applier().run()["status"] == "updated"
    assert win.settled() == "new"


def test_moving_the_new_version_aside_keeps_trying(win):
    """A rollback stuck on a locked new version still ends with the old version running."""
    win.world.healthy[NEW_V] = False
    fails = []

    def hook(src, dst):
        if dst == os.path.join(win.staging, "rejected") and len(fails) < 12:
            fails.append(src)
            raise PermissionError(32, "in use", src)

    win.world.rename_hook = hook
    result = win.applier(timings=replace(FAST, health=0.05, lock_retry=0.01)).run()

    assert result["status"] == "rolled_back"
    assert len(fails) == 12
    assert win.settled() == "old"
    assert win.world.versions[max(win.world.versions)] == OLD_V  # relaunched last
    with open(os.path.join(win.staging, "helper.log"), encoding="utf-8") as f:
        assert f.read().count("moving the new version aside, try") == 12


def test_a_registry_error_never_rolls_back_the_update(win):
    win.world.registry_error = RuntimeError("not an OSError")
    assert win.applier().run()["status"] == "updated"
    assert win.settled() == "new"
    with open(os.path.join(win.staging, "helper.log"), encoding="utf-8") as f:
        assert "not an OSError" in f.read()


def test_an_unreadable_uninstall_entry_never_rolls_back_the_update(win, monkeypatch):
    def broken(self, key):
        raise ValueError("bad registry data")

    monkeypatch.setattr(FakePlatform, "install_location", broken)
    assert win.applier().run()["status"] == "updated"
    assert win.world.registry == {}


@pytest.mark.skipif(os.name != "nt", reason="the Windows registry")
def test_real_registry_round_trip_on_a_throwaway_key(tmp_path):
    """The real reads and writes, on a key made for this test under HKCU and deleted after."""
    import uuid
    import winreg
    parent = "Software\\PyReconstruct-apply-test"
    key = f"{parent}\\{uuid.uuid4()}_is1"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(tmp_path) + "\\")
    try:
        plat = A.WindowsPlatform()
        assert plat.install_location(key) == str(tmp_path) + "\\"
        plat.set_display_version(key, NEW_V)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            assert winreg.QueryValueEx(k, "DisplayVersion")[0] == NEW_V
        assert plat.install_location(key + "-missing") is None
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, parent)
        except OSError:
            pass


def test_a_leftover_backup_after_an_update_is_cleared(win):
    old = os.path.join(win.staging, "old")
    _write(old, "stale.txt", "x")
    A.atomic_write_json(os.path.join(win.staging, "state.json"),
                        {"format": 1, "status": "done", "result": "updated", "installed": "new"})
    assert win.applier().run()["status"] == "updated"
    assert not os.path.lexists(old)


# --- Early ends ---------------------------------------------------------------------------

def test_selftest_output_goes_to_its_log_in_staging(win):
    win.applier().run()
    assert win.world.selftest_logs == [os.path.join(win.staging, "selftest.log")]


def test_failed_selftest_touches_nothing(win):
    win.world.selftest_code = 1
    result = win.applier().run()
    assert result["status"] == "selftest_failed"
    assert result["installed"] == "old" and result["offer_installer"] is True
    _untouched(win)
    assert win.read("failed-versions.json")["versions"] == [NEW_V]


def test_selftest_timeout_defers_and_three_offer_the_installer(win):
    """A first Defender scan can be slow, so a timeout is not held against the version."""
    win.world.selftest_code = None
    for count in (1, 2, 3):
        result = win.applier().run()
        assert result["status"] == "deferred" and "timed out" in result["reason"]
        assert result["deferrals"] == count
        assert result["offer_installer"] is (count >= A.MAX_DEFERRALS)
        _untouched(win)
    assert win.read("failed-versions.json") is None


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


# --- The new version reports its own start --------------------------------------------

class ReportingPlatform(FakePlatform):
    """Each launched copy reports in the way the app does, through report_started, if it lives."""

    def __init__(self, world):
        super().__init__(world)
        world.healthy = {OLD_V: False, NEW_V: False}  # no shortcut: only report_started writes
        self.reports = []

    def launch(self, argv, cwd):
        pid = super().launch(argv, cwd)
        if pid in self.w.alive:
            version = self.w.versions[pid]
            self.reports.append((version, A.report_started(self.w.install, "PyReconstruct", version)))
        return pid


def _waiting_journal(s, edit=None):
    """A journal like the helper's while it waits for the new version to report in."""
    state = {"format": A.FORMAT, "status": "running", "step": "health", "phase": "begin",
             "plan": dict(s.plan)}
    if edit:
        edit(state, s)
    A.atomic_write_json(os.path.join(s.staging, "state.json"), state)


def test_the_new_version_reports_its_own_start(win):
    platform = ReportingPlatform(win.world)
    result = A.Applier(win.staging, platform, FAST, host="windows").run()

    assert platform.reports == [(NEW_V, True)]
    assert result["status"] == "updated"
    assert win.settled() == "new"


def test_a_new_version_that_dies_before_reporting_is_rolled_back(win):
    win.world.quits_on_start.add(NEW_V)
    platform = ReportingPlatform(win.world)
    result = A.Applier(win.staging, platform, replace(FAST, health=30), host="windows").run()

    assert result["status"] == "rolled_back"
    assert win.settled() == "old"
    # the old version, started again, checked in and was told nobody waits on it
    assert platform.reports == [(OLD_V, False)]
    assert win.read("health.json") is None
    assert win.read("failed-versions.json")["versions"] == [NEW_V]


@pytest.mark.parametrize("step", ["launch", "health"])
def test_report_started_writes_while_the_helper_waits(win, step):
    _waiting_journal(win, lambda state, s: state.update(step=step))
    assert A.report_started(win.install, "PyReconstruct", NEW_V) is True
    report = win.read("health.json")
    assert report["version"] == NEW_V and report["pid"] == os.getpid()


_NOT_AWAITED = {
    "finished": lambda state, s: state.update(status="done"),
    "before-swap": lambda state, s: state.update(step="selftest"),
    "rollback": lambda state, s: state.update(step="rb_launch"),
    "after-health": lambda state, s: state.update(step="cleanup"),
    "other-version": lambda state, s: state["plan"].update(to_version="1.24.1"),
    "other-install": lambda state, s: state["plan"].update(install=os.path.join(s.parent, "Other")),
    "no-plan": lambda state, s: state.update(plan=None),
}


@pytest.mark.parametrize("case", list(_NOT_AWAITED))
def test_report_started_writes_nothing_unless_this_launch_is_awaited(win, case):
    _waiting_journal(win, _NOT_AWAITED[case])
    assert A.report_started(win.install, "PyReconstruct", NEW_V) is False
    assert win.read("health.json") is None


def test_report_started_without_a_staging_folder_writes_nothing(tmp_path):
    install = tmp_path / "PyReconstruct"
    install.mkdir()
    assert A.report_started(str(install), "PyReconstruct", NEW_V) is False
    assert os.listdir(tmp_path) == ["PyReconstruct"]


@pytest.fixture
def frozen_windows_app(win, monkeypatch):
    """report_update_started's view of the world: a frozen Windows build running from ``win.install``."""
    from PyReconstruct.modules.backend.updater import install_info
    monkeypatch.setattr(install_info, "is_frozen", lambda: True)
    monkeypatch.setattr(install_info, "os_key", lambda: "windows")
    monkeypatch.setattr(install_info, "current_version_str", lambda: NEW_V + "+g1a2b3c4")
    monkeypatch.setattr(sys, "executable", os.path.join(win.install, "PyReconstruct.exe"))
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    return install_info


def test_app_reports_its_public_version_from_the_install_folder(win, frozen_windows_app):
    from PyReconstruct.modules.backend.updater.updater import report_update_started
    _waiting_journal(win)
    assert report_update_started() is True
    assert win.read("health.json")["version"] == NEW_V


@pytest.mark.parametrize("build", ["source", "macos"])
def test_app_reports_only_from_a_frozen_windows_build(win, frozen_windows_app, monkeypatch, build):
    from PyReconstruct.modules.backend.updater.updater import report_update_started
    if build == "source":
        monkeypatch.setattr(frozen_windows_app, "is_frozen", lambda: False)
    else:
        monkeypatch.setattr(frozen_windows_app, "os_key", lambda: "macos")
    _waiting_journal(win)
    assert report_update_started() is False
    assert win.read("health.json") is None


def test_app_report_never_raises(win, frozen_windows_app, monkeypatch):
    from PyReconstruct.modules.backend.updater.updater import report_update_started

    def broken(*args):
        raise OSError("disk gone")

    monkeypatch.setattr(A, "report_started", broken)
    _waiting_journal(win)
    assert report_update_started() is False


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
    # a retry window far longer than three tries take, however slow the runner
    assert win.applier(timings=replace(FAST, lock_retry=5)).run()["status"] == "updated"
    assert len(tries) == 3


def test_lock_held_by_a_process_is_waited_out(win):
    """Past the plain retry window, a process still running from the folder keeps it waiting.

    The worker starts after the helper's check that nothing runs from the
    install, as one could, and holds the folder until it exits.
    """
    holder = None
    tries = []

    def hook(src, dst):
        nonlocal holder
        if src != win.install:
            return
        if holder is None:
            holder = win.world.spawn(os.path.join(win.install, "_internal", "worker.exe"))
        if holder in win.world.alive:
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


def test_a_second_running_copy_defers_the_swap(tmp_path):
    """macOS renames a folder with a program running from it without complaint, so the helper checks."""
    s = Setup(tmp_path, "macos")
    other = s.world.spawn(s.exe(s.install))
    result = s.applier().run()
    assert result["status"] == "deferred"
    assert "still running" in result["reason"]
    _untouched(s)
    assert other in s.world.alive


def test_a_second_copy_that_quits_is_waited_for(tmp_path):
    s = Setup(tmp_path, "macos")
    other = s.world.spawn(s.exe(s.install))
    polls = []

    def quits_later():
        polls.append(1)
        if len(polls) == 5:
            s.world.alive.pop(other, None)

    s.world.on_poll = quits_later
    assert s.applier(timings=replace(FAST, lock_wait=10)).run()["status"] == "updated"
    assert s.settled() == "new"


def test_display_version_is_written_only_for_this_install(win):
    win.world.install_locations[UNINSTALL_KEY] = os.path.join(os.sep, "Somewhere", "Else") + "\\"
    assert win.applier().run()["status"] == "updated"
    assert win.world.registry == {}
    with open(os.path.join(win.staging, "helper.log"), encoding="utf-8") as f:
        assert "DisplayVersion not set to" in f.read()


def test_display_version_matches_the_install_in_any_case(win):
    win.world.install_locations[UNINSTALL_KEY] = win.install.upper().replace("/", "\\") + "\\"
    assert win.applier().run()["status"] == "updated"
    assert win.world.registry == {UNINSTALL_KEY: NEW_V}


def test_display_version_is_skipped_when_the_entry_has_no_location(win):
    del win.world.install_locations[UNINSTALL_KEY]
    assert win.applier().run()["status"] == "updated"
    assert win.world.registry == {}


def test_main_takes_a_relative_staging_path(win, monkeypatch):
    """Resolved once, before the change of folder, so the helper and its working folder agree."""
    seen = []

    class Recorder:
        def __init__(self, staging, platform, **kw):
            seen.append((os.getcwd(), os.path.abspath(staging)))

        def run(self):
            return {"installed": "old"}

    monkeypatch.chdir(win.parent)
    monkeypatch.setattr(A, "Applier", Recorder)
    A.main([A.APPLY_ARG, os.path.basename(win.staging)])
    [(cwd, staging)] = seen
    assert os.path.realpath(cwd) == os.path.realpath(staging) == os.path.realpath(win.staging)


def test_main_leaves_the_install_as_its_working_folder(win, monkeypatch):
    """Windows cannot rename a folder that is some process's working folder, the helper's included."""
    seen = []

    class Recorder:
        def __init__(self, staging, platform, **kw):
            seen.append(os.getcwd())

        def run(self):
            return {"installed": "old"}

    monkeypatch.chdir(win.install)
    monkeypatch.setattr(A, "Applier", Recorder)
    assert A.main([A.APPLY_ARG, win.staging]) == 1
    assert [os.path.realpath(p) for p in seen] == [os.path.realpath(win.staging)]


# --- Refusals: nothing is touched --------------------------------------------------------

def test_refuses_an_install_holding_someone_elses_files(win):
    """A series saved inside the install folder would be deleted with the old version."""
    _write(win.install, "my work/cells.jser", '{"series": "mine"}')
    win.old_snap = snapshot(win.install)
    _refused(win)
    assert win.read("result.json")["offer_installer"] is True
    with open(os.path.join(win.install, "my work", "cells.jser")) as f:
        assert f.read() == '{"series": "mine"}'


def test_refuses_a_bundle_with_anything_beside_contents(tmp_path):
    s = Setup(tmp_path, "macos")
    _write(s.install, "notes.txt", "mine")
    s.old_snap = snapshot(s.install)
    _refused(s, "notes.txt")


def test_known_install_entries_in_any_case_are_not_foreign(win):
    """Windows names match in any case, and the updater's own folder is expected."""
    os.rename(os.path.join(win.install, "unins000.dat"), os.path.join(win.install, "UNINS000.DAT"))
    os.makedirs(os.path.join(win.install, "_updater"))
    _write(win.install, "_updater/pyreconstruct-updater.exe", "helper")
    assert win.applier().run()["status"] == "updated"


def _refused(s, fragment="the update would remove"):
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


@pytest.mark.parametrize("name", ["COM\u00b9.txt", "com\u00b2", "LPT\u00b3.log", "lpt\u00b9"])
def test_superscript_device_names_are_unsafe_on_windows(name):
    with pytest.raises(A.Refused, match="unsafe path"):
        A.safe_parts(f"_internal/{name}", windows=True)
    assert A.safe_parts(f"_internal/{name}") == ["_internal", name]


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
    # A framework build (the macOS runner's) re-execs from
    # .../Resources/Python.app/Contents/MacOS/Python, so search the whole install.
    home = os.path.realpath(sys.base_prefix)

    assert plat.run([exe, "-c", "raise SystemExit(3)"], 30, str(tmp_path)) == 3
    start = time.monotonic()
    assert plat.run([exe, "-c", "import time; time.sleep(30)"], 0.5, str(tmp_path)) is None
    assert time.monotonic() - start < 20

    pid = plat.launch([exe, "-c", "import time; time.sleep(60)"], str(tmp_path))
    try:
        assert plat.pid_alive(pid)
        assert not plat.wait_pid(pid, 0.2, 0.05)
        deadline = time.monotonic() + 10
        while pid not in plat.processes_under(home) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert pid in plat.processes_under(home)
        assert pid not in plat.processes_under(str(tmp_path))
        started = plat.start_time(pid)
        assert started is not None and plat.start_time(pid) == started
        assert plat.start_time(os.getpid()) not in (None, started)
    finally:
        plat.kill(pid, force=True)
    assert plat.wait_pid(pid, 10, 0.05)
    assert not plat.pid_alive(pid)


def test_real_run_writes_output_to_the_log_file(tmp_path):
    log = str(tmp_path / "selftest.log")
    plat = A.default_platform()
    code = "import sys; print('selftest ok'); print('to stderr', file=sys.stderr)"
    assert plat.run([_python(), "-c", code], 30, str(tmp_path), log=log) == 0
    with open(log, encoding="utf-8") as f:
        text = f.read()
    assert "selftest ok" in text and "to stderr" in text


def test_a_grandchild_holding_the_output_cannot_hang_the_helper(tmp_path):
    """The self-test times out, is killed, and leaves behind a child of its own that still has its output."""
    import threading
    pidfile = tmp_path / "grandchild.pid"
    code = ("import subprocess, sys, time;"
            " g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
            f" open({str(pidfile)!r}, 'w').write(str(g.pid)); print('started', flush=True); time.sleep(120)")
    plat = A.default_platform()
    outcome = []
    worker = threading.Thread(daemon=True, target=lambda: outcome.append(
        plat.run([_python(), "-c", code], 3, str(tmp_path), log=str(tmp_path / "selftest.log"))))
    try:
        worker.start()
        worker.join(60)
        assert not worker.is_alive(), "the helper is still waiting on the self-test's output"
        assert outcome == [None]
    finally:
        if pidfile.exists():
            plat.kill(int(pidfile.read_text()), force=True)


def test_children_start_free_of_the_helpers_pyinstaller_state(tmp_path, monkeypatch):
    """A frozen helper's own _MEIPASS and _PYI_ variables would point a frozen child at the wrong folder."""
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", str(tmp_path))
    monkeypatch.setenv("_MEIPASS2", str(tmp_path))
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "0")
    check = ("import os, sys; bad = [k for k in os.environ if k.upper().startswith(('_PYI_', '_MEIPASS'))];"
             " ok = os.environ.get('PYINSTALLER_RESET_ENVIRONMENT') == '1' and not bad;")
    plat = A.default_platform()

    assert plat.run([_python(), "-c", check + " sys.exit(0 if ok else 7)"], 30, str(tmp_path)) == 0

    out = tmp_path / "launched.txt"
    pid = plat.launch([_python(), "-c", check + f" open({str(out)!r}, 'w').write(str(ok))"], str(tmp_path))
    assert plat.wait_pid(pid, 30, 0.05)
    assert out.read_text() == "True"


def test_build_tree_round_trips_through_verify(tmp_path, can_symlink):
    root = str(tmp_path / "PyReconstruct.app")
    macos_tree(root, NEW_V, can_symlink)
    tree = A.build_tree(root, version=NEW_V, flavor="stable", app_name="PyReconstruct", bundle_id=STABLE_ID)
    A.verify_tree(root, json.loads(json.dumps(tree)))
    assert {"path": "Contents/Resources/empty", "type": "dir",
            "mode": stat.S_IMODE(os.stat(os.path.join(root, "Contents", "Resources", "empty")).st_mode)} \
        in tree["files"]
