"""Swap a staged build into place at quit, and put the old one back if it fails.

This is the helper side of an in-place update. The app downloads, verifies,
and unpacks the new version into a staging folder next to the install, writes
``plan.json`` there, starts this helper, and quits. The helper waits for the
app to exit, checks the staged tree once more, runs its self-test, renames the
install to a backup and the new tree into its place, and launches the new
version. If the new version does not report a healthy start in time, the
helper kills it, renames the backup back, relaunches the old version, and
records the failed version so it is not tried in place again.

Stdlib only, on purpose. On Windows this file is frozen on its own as
``pyreconstruct-updater.exe`` and run from the staging folder, because the
running app would lock its own install folder. On macOS and Linux the
installed app runs it through the ``__apply_update__`` check at the top of
``run.py``, before any Qt import.

Crash safety comes from ``state.json``, a journal written atomically before
and after every step. A helper that dies part way (power loss, a kill, a
crash) leaves the journal behind, and the next run finishes or undoes the
swap from wherever it stopped. Every step is safe to repeat, and the steps
that move folders look at what is actually on disk rather than trusting the
journal alone, because a process can die between a rename and the journal
write that records it. The one window this cannot close is the moment between
the two renames, when neither version sits at the install path; the next run
closes it by renaming the backup back.

Staging layout, ``<parent>/.<AppName>-update/``::

    plan.json            what to do, written by the app
    tree.json            path, size, sha256, and mode of every staged file
    new/                 the staged tree (a folder, or one file later on Linux)
    old/                 the backup of the install during a swap
    rejected/            a failed new version while it is rolled back
    state.json           the journal
    health.json          written by the new version once it starts cleanly
    result.json          what happened, for the app to read at next launch
    failed-versions.json versions that failed and are not retried in place
    deferrals.json       how many times a locked install put this version off
    helper.lock          held by the running helper, so only one runs at a time
    helper.log           a line per step, for bug reports
    selftest.log         what the self-test printed

The OS-specific parts (waiting on and killing processes, launching, the
Windows uninstall registry entry) sit behind ``Platform`` so tests can drive
every path with a fake.

Every program the helper starts (the self-test, the new version, the old one
on a rollback) gets ``PYINSTALLER_RESET_ENVIRONMENT=1`` and none of the
``_PYI_*`` or ``_MEIPASS*`` variables a frozen parent passes down, so a frozen
child sets itself up from its own folder rather than the helper's.

On macOS the new version is started by running ``Contents/MacOS/<app>``
directly, because that gives the helper the process ID it health-checks and,
on a rollback, stops. Step 7 of the build plan (the macOS helper) should
decide between that and ``open -n -a``, which is how Finder starts an app but
returns no process ID, in which case the ID would come from health.json.
"""

import argparse
import fnmatch
import hashlib
import json
import ntpath
import os
import plistlib
import stat
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass

FORMAT = 1

# The first argument that sends ``run.py`` here instead of the GUI.
APPLY_ARG = "__apply_update__"

PLAN = "plan.json"
TREE = "tree.json"
STATE = "state.json"
HEALTH = "health.json"
RESULT = "result.json"
FAILED_VERSIONS = "failed-versions.json"
DEFERRALS = "deferrals.json"
LOG = "helper.log"
LOCK = "helper.lock"
SELFTEST_LOG = "selftest.log"
NEW = "new"
OLD = "old"
REJECTED = "rejected"

# The forward steps, in order. Each is journaled "begin" and "end".
FORWARD = (
    "wait",      # the app's process exits
    "verify",    # the staged tree matches tree.json and the plan's identity
    "selftest",  # the staged copy passes --selftest
    "carry",     # named files from the install are copied into the new tree
    "swap_out",  # install -> old/
    "swap_in",   # new/ -> install
    "registry",  # Windows DisplayVersion
    "launch",    # the new version starts
    "health",    # the new version writes health.json
    "cleanup",   # old/ is deleted
)

# The rollback steps, run when the new version fails after the swap.
ROLLBACK = (
    "rb_kill",      # the new version's processes are stopped
    "rb_aside",     # install -> rejected/
    "rb_restore",   # old/ -> install
    "rb_registry",  # DisplayVersion back to the old version
    "rb_record",    # the version goes into failed-versions.json
    "rb_launch",    # the old version starts again
    "rb_cleanup",   # rejected/ is deleted
)

# A locked install puts the update off to the next quit. After this many
# deferrals of one version the app offers the installer instead.
MAX_DEFERRALS = 3

# Results after which the app should offer the full installer.
_OFFER_INSTALLER = {"refused", "selftest_failed", "rolled_back", "stuck"}

_UNINSTALL_KEY_PREFIX = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class Refused(Exception):
    """An input failed a safety check. Nothing has been touched."""


@dataclass
class Timings:
    """Every wait the helper makes, in seconds. Tests shrink them."""

    pid_exit: float = 600.0    # the app saving and quitting
    selftest: float = 120.0
    health: float = 180.0      # 180 on Windows, 120 on macOS (default_timings)
    lock_retry: float = 60.0   # retry a locked rename this long in any case
    lock_wait: float = 600.0   # then keep retrying while processes still hold it
    kill_wait: float = 10.0    # a stopped process takes this long to exit
    interval: float = 1.0      # between rename retries
    poll: float = 0.25         # between process and health checks
    backoff_max: float = 30.0  # longest pause between tries at putting the old version back


def default_timings(host=None):
    host = host or os_key()
    return Timings(health=180.0 if host == "windows" else 120.0)


def os_key():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- Files -------------------------------------------------------------------

def _fsync_dir(path):
    """Make a rename in ``path`` durable. POSIX only; Windows has no directory handle for this."""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(path, data):
    """Write JSON so a reader sees the old file or the new one, never half of either.

    Temp file in the same folder, fsync, then ``os.replace``. On Windows the
    replace fails while another process has the target open for a moment (the
    app reading it, an indexer), so it retries briefly.
    """
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(folder)


def read_json(path, default=None):
    """The parsed file, or ``default`` if it is missing or not valid JSON."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _remove(path):
    """Delete a file, a link, or a whole tree. Read-only files on Windows are made writable first."""
    if not os.path.lexists(path):
        return

    def _writable_and_retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        func(p)

    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onerror=_writable_and_retry)
    else:
        try:
            os.unlink(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            os.unlink(path)


def write_health(staging, version, pid=None):
    """What the new version calls after its first event-loop pass: "I started cleanly"."""
    atomic_write_json(os.path.join(staging, HEALTH), {
        "format": FORMAT,
        "version": version,
        "pid": os.getpid() if pid is None else pid,
        "at": _now(),
    })


# --- Path safety ---------------------------------------------------------------

def safe_parts(rel, windows=False):
    """Split a tree-relative path, refusing anything that could land outside the tree.

    Paths in tree.json always use "/". Refused: empty, absolute, a drive letter
    or any colon (also Windows alternate streams), a backslash, "." or ".."
    or empty components, and NUL. For a Windows tree also device names such
    as NUL or COM1 and names ending in a dot or space, which Windows opens as
    something other than the file listed.
    """
    if not isinstance(rel, str) or not rel:
        raise Refused(f"bad path in tree: {rel!r}")
    if "\x00" in rel or "\\" in rel or ":" in rel:
        raise Refused(f"unsafe path in tree: {rel!r}")
    if rel.startswith("/") or ntpath.isabs(rel) or ntpath.splitdrive(rel)[0]:
        raise Refused(f"absolute path in tree: {rel!r}")
    parts = rel.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise Refused(f"unsafe path in tree: {rel!r}")
        if windows and (part.split(".")[0].upper() in _WINDOWS_RESERVED or part != part.rstrip(" .")):
            raise Refused(f"unsafe path in tree: {rel!r}")
    return parts


def _link_target_parts(link_parts, target):
    """Resolve a symlink target by name alone; refuse one that climbs out or points at the root."""
    if not isinstance(target, str) or not target:
        raise Refused(f"bad link target for {'/'.join(link_parts)}")
    if "\x00" in target or "\\" in target or ":" in target:
        raise Refused(f"unsafe link target {target!r}")
    if target.startswith("/") or ntpath.isabs(target) or ntpath.splitdrive(target)[0]:
        raise Refused(f"absolute link target {target!r}")
    stack = list(link_parts[:-1])
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise Refused(f"link {'/'.join(link_parts)} points outside the tree")
            stack.pop()
        else:
            stack.append(part)
    if not stack:
        raise Refused(f"link {'/'.join(link_parts)} points at the tree root")
    return stack


def child_env(base=None):
    """The environment for a program the helper starts, free of this process's PyInstaller state."""
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.upper().startswith(("_PYI_", "_MEIPASS")):
            del env[key]
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _norm_win(path):
    """A path as Windows compares it: backslashes, no trailing separator, case folded."""
    path = ntpath.normpath(path.strip())
    if len(path) > 3:
        path = path.rstrip("\\")
    return ntpath.normcase(path)


def _at_or_inside(path, root):
    return os.path.normcase(path) == os.path.normcase(root) or _inside(path, root)


def _inside(path, root):
    path = os.path.normcase(path)
    root = os.path.normcase(root)
    try:
        return os.path.commonpath([path, root]) == root and path != root
    except ValueError:  # different drives
        return False


# --- The tree manifest ----------------------------------------------------------

def _walk(root):
    """Every entry under ``root`` as {relative path: lstat}, never following links."""
    found = {}
    pending = [("", root)]
    while pending:
        rel, folder = pending.pop()
        with os.scandir(folder) as it:
            for entry in it:
                r = f"{rel}/{entry.name}" if rel else entry.name
                st = entry.stat(follow_symlinks=False)
                found[r] = st
                if stat.S_ISDIR(st.st_mode):
                    pending.append((r, entry.path))
    return found


def build_tree(root, *, version, flavor, app_name, bundle_id=None, platform=None):
    """The tree.json for ``root``: every file, link, and empty folder.

    Used by the release build and by the tests. A single file (the Linux
    AppImage later) is one entry with the path ".".
    """
    header = {
        "format": FORMAT, "version": version, "flavor": flavor,
        "app_name": app_name, "bundle_id": bundle_id,
    }
    if platform:
        header["platform"] = platform
    if os.path.isfile(root) and not os.path.islink(root):
        st = os.stat(root)
        header["files"] = [{
            "path": ".", "size": st.st_size, "sha256": _sha256(root),
            "mode": stat.S_IMODE(st.st_mode),
        }]
        return header
    entries = []
    walked = _walk(root)
    parents = {r.rsplit("/", 1)[0] for r in walked if "/" in r}
    for rel in sorted(walked):
        st = walked[rel]
        full = os.path.join(root, *rel.split("/"))
        if stat.S_ISLNK(st.st_mode):
            entries.append({"path": rel, "type": "symlink", "target": os.readlink(full).replace(os.sep, "/")})
        elif stat.S_ISDIR(st.st_mode):
            if rel not in parents:
                entries.append({"path": rel, "type": "dir", "mode": stat.S_IMODE(st.st_mode)})
        elif stat.S_ISREG(st.st_mode):
            entries.append({
                "path": rel, "size": st.st_size, "sha256": _sha256(full),
                "mode": stat.S_IMODE(st.st_mode),
            })
    header["files"] = entries
    return header


def _check_mode(value, rel):
    if not isinstance(value, int) or value < 0 or value > 0o777:
        # setuid, setgid, and sticky bits never belong in an app bundle
        raise Refused(f"bad mode for {rel}: {value!r}")


def verify_tree(root, tree, *, kind="folder", windows=False, check_mode=None):
    """Refuse unless ``root`` holds exactly what ``tree`` lists, byte for byte.

    Every listed file must be a regular file with the listed size, sha256,
    and mode; every link must have the listed target and resolve inside the
    tree on disk; nothing unlisted may be present. Folders are implied by
    the entries under them, and empty ones are listed. Modes are skipped on
    Windows, where the file system does not keep them.
    """
    if check_mode is None:
        check_mode = os.name != "nt"
    entries = tree.get("files") if isinstance(tree, dict) else None
    if not isinstance(entries, list) or not entries:
        raise Refused("tree.json lists no files")

    if kind == "file":
        if len(entries) != 1 or entries[0].get("path") != ".":
            raise Refused("a one-file tree must list exactly one entry, '.'")
        _verify_file(root, entries[0], ".", check_mode)
        return

    expected = {}
    folded = set()
    implied = set()
    for e in entries:
        if not isinstance(e, dict):
            raise Refused("bad entry in tree.json")
        parts = safe_parts(e.get("path"), windows)
        rel = "/".join(parts)
        key = rel.casefold()
        if key in folded:
            # two names that are one file on Windows and macOS
            raise Refused(f"duplicate path in tree: {rel}")
        folded.add(key)
        kind_ = e.get("type", "file")
        if kind_ not in ("file", "symlink", "dir"):
            raise Refused(f"bad entry type for {rel}: {kind_!r}")
        if kind_ == "symlink":
            _link_target_parts(parts, e.get("target"))
        expected[rel] = e
        for i in range(1, len(parts)):
            implied.add("/".join(parts[:i]))

    for rel in implied:
        if rel in expected and expected[rel].get("type", "file") != "dir":
            raise Refused(f"{rel} is listed as a file and also holds other entries")

    if not os.path.isdir(root) or os.path.islink(root):
        raise Refused("the staged tree is missing")
    actual = _walk(root)
    real_root = os.path.realpath(root)

    missing = sorted(set(expected) - set(actual))
    if missing:
        raise Refused(f"staged tree is missing {missing[0]}"
                      + (f" and {len(missing) - 1} more" if len(missing) > 1 else ""))
    for rel, st in actual.items():
        if rel in expected:
            continue
        if rel in implied and stat.S_ISDIR(st.st_mode):
            continue
        raise Refused(f"staged tree has an unlisted entry: {rel}")

    for rel, e in expected.items():
        st = actual[rel]
        full = os.path.join(root, *rel.split("/"))
        kind_ = e.get("type", "file")
        if kind_ == "symlink":
            if not stat.S_ISLNK(st.st_mode):
                raise Refused(f"{rel} should be a link")
            if os.readlink(full).replace(os.sep, "/") != e["target"]:
                raise Refused(f"{rel} links somewhere else")
            # By name the target stayed inside; on disk a chain through
            # another link can still climb out, so resolve it for real.
            if not _inside(os.path.realpath(full), real_root):
                raise Refused(f"link {rel} points outside the tree")
        elif kind_ == "dir":
            if not stat.S_ISDIR(st.st_mode):
                raise Refused(f"{rel} should be a folder")
            if check_mode and "mode" in e:
                _check_mode(e["mode"], rel)
                if stat.S_IMODE(st.st_mode) != e["mode"]:
                    raise Refused(f"{rel} has the wrong mode")
        else:
            _verify_file(full, e, rel, check_mode, st)


def _verify_file(full, e, rel, check_mode, st=None):
    if st is None:
        try:
            st = os.lstat(full)
        except OSError:
            raise Refused(f"staged tree is missing {rel}")
    if not stat.S_ISREG(st.st_mode):
        raise Refused(f"{rel} should be a regular file")
    size, digest, mode = e.get("size"), e.get("sha256"), e.get("mode")
    if not isinstance(size, int) or not isinstance(digest, str) or len(digest) != 64:
        raise Refused(f"bad entry for {rel} in tree.json")
    _check_mode(mode, rel)
    if st.st_size != size:
        raise Refused(f"{rel} has the wrong size")
    if check_mode and stat.S_IMODE(st.st_mode) != mode:
        raise Refused(f"{rel} has the wrong mode")
    if _sha256(full) != digest.lower():
        raise Refused(f"{rel} does not match its checksum")


# --- The plan -------------------------------------------------------------------

def _str(plan, key, required=True):
    value = plan.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise Refused(f"plan.json: bad {key}")
    return value


def _str_list(plan, key, default):
    value = plan.get(key, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise Refused(f"plan.json: bad {key}")
    return value


def load_plan(path):
    """Read and check plan.json. Refuses anything malformed or inconsistent."""
    plan = read_json(path)
    if not isinstance(plan, dict):
        raise Refused("plan.json is missing or unreadable")
    if plan.get("format") != FORMAT:
        raise Refused(f"plan.json: unknown format {plan.get('format')!r}")
    platform = plan.get("platform")
    if platform not in ("windows", "macos", "linux"):
        raise Refused(f"plan.json: bad platform {platform!r}")
    kind = plan.get("kind", "folder")
    if kind not in ("folder", "file"):
        raise Refused(f"plan.json: bad kind {kind!r}")
    install = _str(plan, "install")
    if not os.path.isabs(install):
        raise Refused("plan.json: install must be an absolute path")
    app_name = _str(plan, "app_name")
    if any(c in app_name for c in "/\\:\x00") or app_name.startswith("."):
        raise Refused(f"plan.json: bad app_name {app_name!r}")
    flavor = plan.get("flavor")
    if flavor not in ("stable", "dev"):
        raise Refused(f"plan.json: bad flavor {flavor!r}")
    if (flavor == "dev") != app_name.endswith(" Dev"):
        raise Refused(f"plan.json: flavor {flavor} does not match app name {app_name!r}")
    bundle_id = _str(plan, "bundle_id", required=(platform == "macos"))
    if bundle_id is not None and (flavor == "dev") != bundle_id.endswith(".dev"):
        raise Refused(f"plan.json: flavor {flavor} does not match bundle id {bundle_id!r}")
    from_version = _str(plan, "from_version")
    to_version = _str(plan, "to_version")
    if from_version == to_version:
        raise Refused("plan.json: the new version is the installed version")
    pid = plan.get("pid")
    if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
        raise Refused("plan.json: bad pid")
    exe = _str(plan, "exe")
    if kind == "file":
        if exe != ".":
            raise Refused("plan.json: a one-file install launches itself; exe must be '.'")
    else:
        safe_parts(exe, platform == "windows")
    carry = _str_list(plan, "carry", [])
    for pattern in carry:
        if not pattern or any(c in pattern for c in "/\\:\x00") or ".." in pattern:
            raise Refused(f"plan.json: bad carry pattern {pattern!r}")
    if carry and kind == "file":
        raise Refused("plan.json: a one-file install has nothing to carry")
    registry_key = _str(plan, "registry_key", required=False)
    if registry_key is not None:
        if platform != "windows":
            raise Refused("plan.json: registry_key is for Windows only")
        if (not registry_key.startswith(_UNINSTALL_KEY_PREFIX)
                or not registry_key.endswith("_is1")
                or "\\" in registry_key[len(_UNINSTALL_KEY_PREFIX):]):
            raise Refused("plan.json: registry_key is not an Inno Setup uninstall key")
    return {
        "format": FORMAT, "platform": platform, "kind": kind, "install": install,
        "app_name": app_name, "flavor": flavor, "bundle_id": bundle_id,
        "from_version": from_version, "to_version": to_version, "pid": pid,
        "exe": exe, "args": _str_list(plan, "args", []),
        "selftest_args": _str_list(plan, "selftest_args", ["--selftest"]),
        "carry": carry, "registry_key": registry_key,
    }


def _read_plist(path):
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
    except Exception:
        raise Refused(f"cannot read {os.path.basename(path)}")
    if not isinstance(data, dict):
        raise Refused(f"cannot read {os.path.basename(path)}")
    return data


# --- Platform ---------------------------------------------------------------------

class Platform:
    """What differs by OS. The helper reaches processes and the registry only through here."""

    def pid_alive(self, pid):
        raise NotImplementedError

    def wait_pid(self, pid, timeout, poll=0.25):
        """True once ``pid`` has exited, False if it is still running at ``timeout``."""
        deadline = time.monotonic() + timeout
        while self.pid_alive(pid):
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll)
        return True

    def kill(self, pid, force=False):
        raise NotImplementedError

    def launch(self, argv, cwd):
        """Start a program detached from this helper and return its pid."""
        raise NotImplementedError

    def run(self, argv, timeout, cwd, log=None):
        """Run to completion: the exit code, or None if it ran past ``timeout`` and was killed.

        Output goes to the file ``log`` (or nowhere), never to a pipe. A
        pipe has to be read until every process holding it closes it, and
        a grandchild that inherited it could hold it open forever, with
        this helper waiting on it and holding helper.lock.
        """
        out = open(log, "ab") if log else open(os.devnull, "wb")
        try:
            out.write(f"{_now()} {argv}\n".encode("utf-8", "replace"))
            out.flush()
            child = subprocess.Popen(
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                env=child_env(), **self._run_flags(),
            )
            try:
                return child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.kill()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                return None
        finally:
            out.close()

    def _run_flags(self):
        return {}

    def processes_under(self, path):
        """Pids of processes whose executable is ``path`` or lives under it, this one excluded."""
        return []

    def start_time(self, pid):
        """When ``pid`` started, in any form that is stable for one process; None if unknown.

        A pid alone can be reused by an unrelated process once the first one
        exits, so a saved pid is only trusted when its start time matches.
        """
        return None

    def install_location(self, key):
        """Windows only: the uninstall entry's InstallLocation, or None."""
        return None

    def set_display_version(self, key, version):
        """Windows only: the version Settings > Apps shows."""

    def rename(self, src, dst):
        os.rename(src, dst)


class PosixPlatform(Platform):

    def __init__(self):
        self._children = {}

    def pid_alive(self, pid):
        child = self._children.get(pid)
        if child is not None:
            return child.poll() is None  # reaps it, so a dead child is not a zombie "alive"
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def kill(self, pid, force=False):
        import signal
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except OSError:
            pass

    def launch(self, argv, cwd):
        child = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True, env=child_env(),
        )
        self._children[child.pid] = child
        return child.pid

    def processes_under(self, path):
        roots = {os.path.abspath(path), os.path.realpath(path)}
        own = os.getpid()
        found = []
        if sys.platform.startswith("linux"):
            for name in os.listdir("/proc"):
                if not name.isdigit() or int(name) == own:
                    continue
                try:
                    exe = os.readlink(f"/proc/{name}/exe")
                except OSError:
                    continue
                if any(_at_or_inside(exe, r) for r in roots):
                    found.append(int(name))
            return found
        try:
            out = subprocess.run(
                ["ps", "-axww", "-o", "pid=,comm="], capture_output=True, text=True, timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        for line in out.splitlines():
            pid, _, exe = line.strip().partition(" ")
            if not pid.isdigit() or int(pid) == own:
                continue
            exe = exe.strip()
            if any(_at_or_inside(exe, r) or _at_or_inside(os.path.realpath(exe), r) for r in roots):
                found.append(int(pid))
        return found

    def start_time(self, pid):
        if sys.platform.startswith("linux"):
            try:
                with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
                    fields = f.read().rpartition(")")[2].split()
                return fields[19]  # starttime, in clock ticks since boot
            except (OSError, IndexError):
                return None
        try:
            out = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return out or None


class WindowsPlatform(Platform):

    _SYNCHRONIZE = 0x00100000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _WAIT_TIMEOUT = 0x102
    _ERROR_ACCESS_DENIED = 5

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.TerminateProcess.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.K32EnumProcesses.argtypes = [
            ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k32.K32EnumProcesses.restype = wintypes.BOOL
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        self._k32 = k32
        self._wintypes = wintypes

    def pid_alive(self, pid):
        h = self._k32.OpenProcess(self._SYNCHRONIZE | self._PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            # access denied means it exists and belongs to someone else
            return self._ctypes.get_last_error() == self._ERROR_ACCESS_DENIED
        try:
            return self._k32.WaitForSingleObject(h, 0) == self._WAIT_TIMEOUT
        finally:
            self._k32.CloseHandle(h)

    def kill(self, pid, force=False):
        # Windows has no polite signal for a GUI process from here; both are TerminateProcess.
        h = self._k32.OpenProcess(self._PROCESS_TERMINATE, False, pid)
        if h:
            try:
                self._k32.TerminateProcess(h, 1)
            finally:
                self._k32.CloseHandle(h)

    def launch(self, argv, cwd):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        child = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=child_env(),
        )
        return child.pid

    def _run_flags(self):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}

    def _image_path(self, pid):
        h = self._k32.OpenProcess(self._PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            size = self._wintypes.DWORD(32768)
            buf = self._ctypes.create_unicode_buffer(size.value)
            if not self._k32.QueryFullProcessImageNameW(h, 0, buf, self._ctypes.byref(size)):
                return None
            return buf.value
        finally:
            self._k32.CloseHandle(h)

    def processes_under(self, path):
        count = 4096
        while True:
            pids = (self._wintypes.DWORD * count)()
            needed = self._wintypes.DWORD(0)
            if not self._k32.K32EnumProcesses(pids, self._ctypes.sizeof(pids), self._ctypes.byref(needed)):
                return []
            if needed.value < self._ctypes.sizeof(pids):
                break
            count *= 2
        root = os.path.abspath(path)
        own = os.getpid()
        found = []
        for pid in pids[: needed.value // self._ctypes.sizeof(self._wintypes.DWORD)]:
            if pid in (0, own):
                continue
            image = self._image_path(pid)
            if image and _at_or_inside(image, root):
                found.append(int(pid))
        return found

    def start_time(self, pid):
        h = self._k32.OpenProcess(self._PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            ft = [self._wintypes.FILETIME() for _ in range(4)]
            if not self._k32.GetProcessTimes(h, *(self._ctypes.byref(t) for t in ft)):
                return None
            return str((ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime)
        finally:
            self._k32.CloseHandle(h)

    def install_location(self, key):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ) as k:
                value, kind = winreg.QueryValueEx(k, "InstallLocation")
        except OSError:
            return None
        return value if isinstance(value, str) else None

    def set_display_version(self, key, version):
        # Per-user installs only, so HKCU; load_plan already checked the key's
        # shape and the caller checked its InstallLocation is this install.
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)


def default_platform():
    return WindowsPlatform() if os.name == "nt" else PosixPlatform()


def take_lock(staging):
    """An exclusive lock on staging/helper.lock, or None if another helper holds it.

    The OS drops the lock when the holder exits, however it exits, so a
    crashed helper never leaves a stale one behind.
    """
    fd = os.open(os.path.join(staging, LOCK), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def release_lock(fd):
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)


# --- The swap ----------------------------------------------------------------------

class Applier:
    """One helper run over one staging folder: apply the plan, or recover an unfinished one."""

    def __init__(self, staging, platform, timings=None, *, host=None, pid=None):
        self.staging = os.path.abspath(staging)
        self.platform = platform
        self.timings = timings or default_timings(host)
        self.host = host or os_key()
        self.pid_override = pid
        self.state = None
        self.plan = None
        self.state_path = os.path.join(self.staging, STATE)
        self.new = os.path.join(self.staging, NEW)
        self.old = os.path.join(self.staging, OLD)
        self.rejected = os.path.join(self.staging, REJECTED)
        self.install = None
        self.recovering = False

    # -- bookkeeping --

    def _log(self, message):
        try:
            with open(os.path.join(self.staging, LOG), "a", encoding="utf-8") as f:
                f.write(f"{_now()} {message}\n")
        except OSError:
            pass

    def _journal(self, step, phase, **extra):
        """Record a step boundary. Everything recovery knows comes from these writes."""
        self.state.update(step=step, phase=phase, updated=_now(), **extra)
        atomic_write_json(self.state_path, self.state)

    def _finish(self, status, installed, reason=""):
        """Write result.json and close the journal. ``installed`` is what now sits at the install path."""
        plan = self.plan or {}
        to_version = plan.get("to_version")
        if installed == "old":
            self._drop_carried()
        deferrals = 0
        deferrals_path = os.path.join(self.staging, DEFERRALS)
        if status == "deferred":
            record = read_json(deferrals_path, {})
            if not isinstance(record, dict) or record.get("version") != to_version:
                record = {"version": to_version, "count": 0}
            record["count"] = int(record.get("count", 0)) + 1
            deferrals = record["count"]
            atomic_write_json(deferrals_path, record)
        elif status == "updated" and os.path.exists(deferrals_path):
            _remove(deferrals_path)
        result = {
            "format": FORMAT,
            "status": status,
            "installed": installed,
            "from_version": plan.get("from_version"),
            "to_version": to_version,
            "reason": reason,
            "deferrals": deferrals,
            "offer_installer": status in _OFFER_INSTALLER or deferrals >= MAX_DEFERRALS,
            "finished": _now(),
        }
        atomic_write_json(os.path.join(self.staging, RESULT), result)
        self._log(f"finished: {status}, {installed} version in place. {reason}".rstrip())
        if self.state is not None:
            self._journal("finish", "end", status="done", installed=installed, result=status)
        return result

    def _refuse(self, reason):
        """Close a run that stopped before touching anything."""
        self._log(f"refused: {reason}")
        if self.state is None:
            self.state = {"format": FORMAT, "status": "running", "plan": self.plan,
                          "helper_pid": os.getpid(), "started": _now(), "installed": "old"}
        return self._finish("refused", "old", reason)

    def _failed_versions(self):
        data = read_json(os.path.join(self.staging, FAILED_VERSIONS), {})
        versions = data.get("versions") if isinstance(data, dict) else None
        return list(versions) if isinstance(versions, list) else []

    def _record_failed(self):
        versions = self._failed_versions()
        if self.plan["to_version"] not in versions:
            versions.append(self.plan["to_version"])
        atomic_write_json(os.path.join(self.staging, FAILED_VERSIONS),
                          {"format": FORMAT, "versions": versions})

    def _drop_carried(self):
        """Take carried files back out of new/, so a later run finds the tree as tree.json lists it."""
        if self.state is None or not os.path.isdir(self.new):
            return
        for name in self.state.get("carried") or []:
            if "/" in name or "\\" in name or name in (".", ".."):
                continue
            try:
                _remove(os.path.join(self.new, name))
            except OSError:
                pass

    # -- entry --

    def run(self):
        """Apply plan.json, or first finish or undo a run that stopped part way."""
        try:
            lock = take_lock(self.staging)
        except OSError as e:
            return {"status": "error", "installed": None, "reason": f"no staging folder: {e}"}
        if lock is None:
            # Another helper is working here. Touch nothing, not even the log.
            return {"status": "busy", "installed": None, "reason": "another helper is running"}
        try:
            previous = read_json(self.state_path)
            if isinstance(previous, dict) and previous.get("status") == "running":
                return self.recover(previous)
            return self.apply(previous)
        finally:
            release_lock(lock)

    # -- checks --

    def _check_placement(self):
        plan = self.plan
        install, staging = self.install, self.staging
        if not os.path.lexists(install):
            raise Refused("the install is missing")
        if os.path.islink(install):
            raise Refused("the install is a link")
        if os.path.islink(staging) or not os.path.isdir(staging):
            raise Refused("the staging folder is missing or a link")
        if plan["kind"] == "folder" and not os.path.isdir(install):
            raise Refused("the install is not a folder")
        if plan["kind"] == "file" and not os.path.isfile(install):
            raise Refused("the install is not a file")
        same_parent = (os.path.normcase(os.path.realpath(os.path.dirname(install)))
                       == os.path.normcase(os.path.realpath(os.path.dirname(staging))))
        if not same_parent or os.path.basename(staging) != f".{plan['app_name']}-update":
            raise Refused("the staging folder is not next to the install")
        if os.stat(install).st_dev != os.stat(staging).st_dev:
            raise Refused("the staging folder is on another volume")
        if not os.path.lexists(self.new) or os.path.islink(self.new):
            raise Refused("nothing is staged")

    def _check_install_identity(self):
        plan, install = self.plan, self.install
        if plan["platform"] == "windows" and plan["kind"] == "folder":
            if not os.path.isfile(os.path.join(install, plan["app_name"] + ".exe")):
                raise Refused(f"the install is not {plan['app_name']}")
        elif plan["platform"] == "macos":
            if os.path.basename(install) != plan["app_name"] + ".app":
                raise Refused(f"the install is not {plan['app_name']}.app")
            info = _read_plist(os.path.join(install, "Contents", "Info.plist"))
            if info.get("CFBundleIdentifier") != plan["bundle_id"]:
                raise Refused("the install has a different bundle id")
        if plan["kind"] == "folder":
            self._check_no_foreign_files()

    def _check_no_foreign_files(self):
        """Refuse an install folder holding anything PyReconstruct did not put there.

        The swap moves the whole folder into staging and deletes it once the
        new version starts, so a series someone saved inside the install
        would go with it. The installer path leaves such files alone.
        """
        plan = self.plan
        if plan["platform"] == "macos":
            known = {"Contents"}
            fold = str
        else:
            tree = read_json(os.path.join(self.staging, TREE), {})
            entries = tree.get("files") if isinstance(tree, dict) else None
            known = {plan["app_name"] + ".exe", "_internal", "_updater"}
            if isinstance(entries, list):
                known |= {e["path"].split("/")[0] for e in entries
                          if isinstance(e, dict) and isinstance(e.get("path"), str)}
            fold = str.casefold  # Windows names match in any case
        known = {fold(n) for n in known}
        patterns = [p.lower() for p in plan["carry"]]
        for name in sorted(os.listdir(self.install)):
            if fold(name) in known or any(fnmatch.fnmatch(name.lower(), p) for p in patterns):
                continue
            raise Refused(f"the install folder holds {name!r}, which the update would remove")

    def _check_new_identity(self, tree):
        plan = self.plan
        for key in ("flavor", "app_name", "bundle_id"):
            if tree.get(key) != plan[key]:
                raise Refused(f"the staged tree's {key} is {tree.get(key)!r}, the plan's is {plan[key]!r}")
        if tree.get("version") != plan["to_version"]:
            raise Refused("the staged tree is a different version")
        if "platform" in tree and not str(tree["platform"]).startswith(plan["platform"]):
            raise Refused("the staged tree is for another platform")
        if plan["kind"] == "file":
            return
        listed = {e.get("path") for e in tree["files"] if e.get("type", "file") == "file"}
        if plan["exe"] not in listed:
            raise Refused("the staged tree has no program to launch")
        if plan["platform"] == "windows" and plan["exe"] != plan["app_name"] + ".exe":
            raise Refused("the program name does not match the app name")
        if plan["platform"] == "macos":
            if "Contents/Info.plist" not in listed:
                raise Refused("the staged bundle has no Info.plist")
            info = _read_plist(os.path.join(self.new, "Contents", "Info.plist"))
            if info.get("CFBundleIdentifier") != plan["bundle_id"]:
                raise Refused("the staged bundle has a different bundle id")
            if (info.get("CFBundleExecutable") != plan["app_name"]
                    or plan["exe"] != "Contents/MacOS/" + plan["app_name"]):
                raise Refused("the staged bundle's program does not match the app name")

    # -- apply --

    def apply(self, previous=None):
        finished = isinstance(previous, dict) and previous.get("status") == "done"
        if finished and previous.get("result") in ("updated", "rolled_back"):
            # A copy that run could not delete. Cleared first, before any
            # check below can refuse: a refusal ends with a new result, and
            # after that there would be no telling what the copy was.
            for path in (self.old, self.rejected):
                try:
                    _remove(path)
                except OSError as e:
                    self._log(f"could not clear {os.path.basename(path)}: {e}")
        if (isinstance(previous, dict) and previous.get("status") == "done"
                and not os.path.lexists(self.new)):
            # A run already finished and nothing new is staged. Its result
            # stands; a refusal here would claim the old version is in place.
            return {"status": "nothing_staged", "installed": previous.get("installed"),
                    "reason": "no update is staged"}
        try:
            self.plan = load_plan(os.path.join(self.staging, PLAN))
        except Refused as e:
            return self._refuse(str(e))
        self.install = os.path.abspath(self.plan["install"])
        self._log(f"apply {self.plan['from_version']} -> {self.plan['to_version']} at {self.install}")
        try:
            if self.plan["platform"] != self.host:
                raise Refused(f"a {self.plan['platform']} plan on {self.host}")
            self._check_placement()
            self._check_install_identity()
            if self.plan["to_version"] in self._failed_versions():
                raise Refused(f"{self.plan['to_version']} failed before and is not retried in place")
            if any(os.path.lexists(p) for p in (self.old, self.rejected)):
                # Left by a stuck run, a run with no journal, or a copy that
                # could not be cleared above. old/ may be the only copy of
                # the install, so it stays.
                raise Refused("a backup from an earlier run is still in staging")
        except Refused as e:
            return self._refuse(str(e))

        _remove(os.path.join(self.staging, HEALTH))  # only this run's launch may report in
        self.state = {
            "format": FORMAT, "status": "running", "plan": self.plan,
            "helper_pid": os.getpid(), "helper_start": self.platform.start_time(os.getpid()),
            "started": _now(), "installed": "old", "carried": [], "launched_pid": None,
        }
        return self._steps(FORWARD, 0)

    def _steps(self, steps, start):
        """Run ``steps[start:]``. A step returns a result to end the run early."""
        try:
            for name in steps[start:]:
                before = getattr(self, "_before_" + name, None)
                self._journal(name, "begin", **(before() if before else {}))
                self._log(f"{name} ...")
                result = getattr(self, "_do_" + name)()
                if result is not None:
                    return result
                self._journal(name, "end")
        except Exception:
            return self._on_error(traceback.format_exc())
        if steps is ROLLBACK:
            reason = self.state.get("rollback_reason", "")
            return self._finish("rolled_back", "old", reason)
        return self._finish("updated", "new")

    def _on_error(self, tb):
        """An unexpected error: treat it like a crash and let recovery decide from the disk."""
        self._log("error:\n" + tb)
        if self.state.get("errors", 0) >= 1:
            # Recovery hit an error too. Leave the journal open for the next run.
            self._log("second error; leaving the journal for the next run")
            return {"status": "error", "installed": None, "reason": tb.strip().splitlines()[-1]}
        self.state["errors"] = self.state.get("errors", 0) + 1
        step = self.state.get("step")
        if step in FORWARD[FORWARD.index("registry"):FORWARD.index("cleanup")]:
            return self._rollback("error after the swap: " + tb.strip().splitlines()[-1])
        return self._recover_steps()

    # -- forward steps --

    def _do_wait(self):
        pid = self.pid_override or self.plan["pid"]
        if pid and not self.platform.wait_pid(pid, self.timings.pid_exit, self.timings.poll):
            return self._finish("deferred", "old", f"PyReconstruct (pid {pid}) did not exit")
        return None

    def _do_verify(self):
        tree = read_json(os.path.join(self.staging, TREE))
        try:
            if not isinstance(tree, dict) or tree.get("format") != FORMAT:
                raise Refused("tree.json is missing or unreadable")
            if self.plan["kind"] == "file" and not os.path.isfile(self.new):
                raise Refused("the staged file is missing")
            verify_tree(self.new, tree, kind=self.plan["kind"],
                        windows=self.plan["platform"] == "windows")
            self._check_new_identity(tree)
        except Refused as e:
            return self._refuse(str(e))
        self.tree_paths = {e.get("path") for e in tree["files"]}
        return None

    def _selftest_argv(self):
        exe = self.new if self.plan["kind"] == "file" else os.path.join(self.new, *self.plan["exe"].split("/"))
        return [exe] + self.plan["selftest_args"]

    def _do_selftest(self):
        cwd = self.new if self.plan["kind"] == "folder" else self.staging
        code = self.platform.run(self._selftest_argv(), self.timings.selftest, cwd,
                                 log=os.path.join(self.staging, SELFTEST_LOG))
        if code is None:
            # A first run of new files can be slow while Defender scans them.
            # Try again at the next quit; three of these count as three deferrals.
            return self._finish("deferred", "old", "the self-test timed out")
        if code != 0:
            self._record_failed()
            return self._finish("selftest_failed", "old", f"the self-test exited {code}")
        return None

    def _before_carry(self):
        """Pick the files to carry, so the begin write records them for recovery to take back out."""
        patterns = self.plan["carry"]
        if not patterns:
            return {"carried": []}
        tree_paths = getattr(self, "tree_paths", None)
        if tree_paths is None:
            tree = read_json(os.path.join(self.staging, TREE), {})
            tree_paths = {e.get("path") for e in tree.get("files", [])}
        names = []
        for name in sorted(os.listdir(self.install)):
            full = os.path.join(self.install, name)
            if not any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns):
                continue
            if not os.path.isfile(full) or os.path.islink(full) or name in tree_paths:
                continue  # the new tree's own file wins; only plain files are carried
            names.append(name)
        return {"carried": names}

    def _do_carry(self):
        for name in self.state["carried"]:
            shutil.copy2(os.path.join(self.install, name), os.path.join(self.new, name))
        return None

    def _rename_retrying(self, src, dst, holder_root=None):
        """Rename, retrying while it is locked. False once it is still locked at the deadline.

        Windows refuses to rename a folder while any file in it is open. The
        rename is retried for ``lock_retry`` seconds in any case, then for up
        to ``lock_wait`` while processes are still running from the folder,
        and once they exit, for a fresh ``lock_retry`` window (their handles
        close a moment after they do).
        """
        if os.path.lexists(dst):
            # os.rename onto an empty folder quietly replaces it on POSIX
            raise FileExistsError(dst)
        start = window = time.monotonic()
        held = False
        while True:
            try:
                self.platform.rename(src, dst)
                _fsync_dir(os.path.dirname(dst))
                if os.path.dirname(src) != os.path.dirname(dst):
                    _fsync_dir(os.path.dirname(src))
                return True
            except (FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError):
                raise
            except OSError as e:
                self._log(f"rename {src} -> {dst} failed: {e}")
            now = time.monotonic()
            if now - window >= self.timings.lock_retry:
                holders = self.platform.processes_under(holder_root) if holder_root else []
                if holders and now - start < self.timings.lock_wait:
                    if not held:
                        self._log(f"still in use by {holders}")
                    held = True
                elif held and not holders:
                    held = False
                    window = now
                else:
                    return False
            time.sleep(self.timings.interval)

    def _rename_until_done(self, src, dst, what, before_try=None):
        """Rename ``src`` to ``dst``, retried until it works. True once it has.

        For the renames a rollback cannot do without. Nothing else would
        ever finish them (PyReconstruct is not running to start another
        helper), so this does not give up while ``src`` exists and ``dst``
        does not. Every try is logged, and the pause between tries doubles
        up to ``backoff_max``.
        """
        delay = self.timings.interval
        tries = 0
        while os.path.lexists(src) and not os.path.lexists(dst):
            tries += 1
            if before_try:
                before_try()
            try:
                self.platform.rename(src, dst)
                _fsync_dir(os.path.dirname(dst))
                _fsync_dir(os.path.dirname(src))
                self._log(f"{what}: done on try {tries}")
                break
            except OSError as e:
                self._log(f"{what}, try {tries} failed: {e}")
            time.sleep(delay)
            delay = min(delay * 2, self.timings.backoff_max)
        return not os.path.lexists(src) and os.path.lexists(dst)

    def _restore_backup(self):
        """old/ -> install, retried until it works. True once the old version is back."""
        self._rename_until_done(self.old, self.install, "putting the old version back")
        if os.path.lexists(self.install):
            self.state["installed"] = "old"
            return True
        return False

    def _wait_until_unused(self):
        """True once nothing runs from the install; False if something still does at ``lock_wait``.

        Windows would refuse the rename anyway, but macOS and Linux would
        move the folder out from under a second running copy.
        """
        start = time.monotonic()
        logged = False
        while True:
            holders = self.platform.processes_under(self.install)
            if not holders:
                return True
            if not logged:
                self._log(f"waiting for {holders} to exit")
                logged = True
            if time.monotonic() - start >= self.timings.lock_wait:
                return False
            time.sleep(self.timings.interval)

    def _do_swap_out(self):
        if not self._wait_until_unused():
            return self._finish("deferred", "old", "PyReconstruct is still running from the install")
        if not self._rename_retrying(self.install, self.old, holder_root=self.install):
            return self._finish("deferred", "old", "the install folder is in use")
        self.state["installed"] = None  # neither version is at the install path now
        return None

    def _do_swap_in(self):
        if self._rename_retrying(self.new, self.install):
            self.state["installed"] = "new"
            return None
        # Put the old version straight back and try again at the next quit.
        self._journal("swap_undo", "begin")
        if not self._restore_backup():
            return self._finish("stuck", None, "the backup vanished before it could be put back")
        return self._finish("deferred", "old", "the new version could not be moved into place")

    def _set_display_version(self, version):
        """Update the uninstall entry, but only the one that belongs to this install.

        The key comes from plan.json; its InstallLocation has to name this
        install folder, or the write is skipped. Cosmetic either way:
        Settings > Apps shows the old number until the next install.
        """
        key = self.plan["registry_key"]
        if not key:
            return
        try:
            location = self.platform.install_location(key)
        except Exception as e:
            self._log(f"DisplayVersion not set to {version}: {e!r}")
            return
        if not location or _norm_win(location) != _norm_win(self.install):
            self._log(f"DisplayVersion not set to {version}: the uninstall entry is for {location!r}")
            return
        try:
            self.platform.set_display_version(key, version)
        except Exception as e:
            self._log(f"DisplayVersion not set to {version}: {e!r}")

    def _do_registry(self):
        self._set_display_version(self.plan["to_version"])
        return None

    def _launch_argv(self):
        if self.plan["kind"] == "file":
            return [self.install] + self.plan["args"]
        return [os.path.join(self.install, *self.plan["exe"].split("/"))] + self.plan["args"]

    def _stop(self, pids):
        pids = [p for p in pids if p and self.platform.pid_alive(p)]
        for pid in pids:
            self.platform.kill(pid)
        for pid in pids:
            if not self.platform.wait_pid(pid, self.timings.kill_wait, self.timings.poll):
                self.platform.kill(pid, force=True)
                self.platform.wait_pid(pid, self.timings.kill_wait, self.timings.poll)

    def _do_launch(self):
        health = os.path.join(self.staging, HEALTH)
        if self._healthy():
            return None  # a recovered run whose new version already reported in
        if self.recovering:
            running = self.platform.processes_under(self.install)
            if running:
                # The dead run started it but did not live to record it.
                # Watch that one rather than start a second copy.
                self._log(f"adopting {running[0]}, already running from the install")
                self.state["launched_pid"] = running[0]
                return None
        _remove(health)
        cwd = os.path.dirname(self.install)
        try:
            pid = self.platform.launch(self._launch_argv(), cwd)
        except Exception as e:
            return self._rollback(f"the new version did not start: {e}")
        self.state["launched_pid"] = pid
        return None

    def _healthy(self):
        report = read_json(os.path.join(self.staging, HEALTH))
        return isinstance(report, dict) and report.get("version") == self.plan["to_version"]

    def _do_health(self):
        pid = self.state.get("launched_pid")
        deadline = time.monotonic() + self.timings.health
        while True:
            if self._healthy():
                return None
            # A pid can be reused once its process exits, so it counts as the
            # new version only while it is still running from the install.
            if pid and pid not in self.platform.processes_under(self.install):
                if self._healthy():
                    return None
                return self._rollback("the new version quit before it finished starting")
            if time.monotonic() >= deadline:
                return self._rollback("the new version did not start in time")
            time.sleep(self.timings.poll)

    def _do_cleanup(self):
        try:
            _remove(self.old)
        except OSError as e:
            # The new version is in and healthy; the next run removes the rest.
            self._log(f"backup not fully removed: {e}")
        return None

    # -- rollback --

    def _rollback(self, reason):
        self._log(f"rolling back: {reason}")
        self.state["rollback_reason"] = reason
        return self._steps(ROLLBACK, 0)

    def _do_rb_kill(self):
        # Only processes running from the install, which is the new version
        # while old/ holds the backup. A saved pid is never killed on its own
        # say-so: it may belong to someone else by now.
        if os.path.lexists(self.old) and os.path.lexists(self.install):
            self._stop(self.platform.processes_under(self.install))
        return None

    def _do_rb_aside(self):
        if os.path.lexists(self.install) and os.path.lexists(self.old):
            # Whatever still holds the new version's folder is stopped before each try.
            moved = self._rename_until_done(
                self.install, self.rejected, "moving the new version aside",
                before_try=lambda: self._stop(self.platform.processes_under(self.install)))
            if not moved:
                return {"status": "error", "installed": "new",
                        "reason": "a rejected copy is already in staging; the next run finishes the rollback"}
        self.state["installed"] = None
        return None

    def _do_rb_restore(self):
        if not os.path.lexists(self.install) and os.path.lexists(self.old):
            if not self._restore_backup():
                return self._finish("stuck", None, "the backup vanished before it could be put back")
        self.state["installed"] = "old"
        return None

    def _do_rb_registry(self):
        self._set_display_version(self.plan["from_version"])
        return None

    def _do_rb_record(self):
        self._record_failed()
        return None

    def _do_rb_launch(self):
        _remove(os.path.join(self.staging, HEALTH))
        try:
            self.platform.launch(self._launch_argv(), os.path.dirname(self.install))
        except Exception as e:
            # It is back in place; the user starts it by hand.
            self._log(f"the old version did not start: {e}")
        return None

    def _do_rb_cleanup(self):
        try:
            _remove(self.rejected)
        except OSError as e:
            self._log(f"rejected version not fully removed: {e}")
        return None

    # -- recovery --

    def recover(self, state):
        """Finish or undo a run that stopped part way, from its journal and the disk."""
        self.state = state
        self.plan = state.get("plan")
        if not isinstance(self.plan, dict):
            return {"status": "error", "installed": None, "reason": "state.json has no plan"}
        self.install = os.path.abspath(self.plan["install"])
        helper = state.get("helper_pid")
        if helper and helper != os.getpid() and self._helper_running(helper, state.get("helper_start")):
            return {"status": "busy", "installed": None, "reason": f"helper {helper} is still running"}
        if self.pid_override and not self.platform.wait_pid(
                self.pid_override, self.timings.pid_exit, self.timings.poll):
            return {"status": "busy", "installed": None, "reason": "PyReconstruct did not exit"}
        state["helper_pid"] = os.getpid()
        state["helper_start"] = self.platform.start_time(os.getpid())
        state["recoveries"] = state.get("recoveries", 0) + 1
        self.recovering = True
        state["errors"] = 0
        self._log(f"recovering from {state.get('step')} {state.get('phase')}")
        return self._recover_steps()

    def _helper_running(self, pid, started):
        """The journal's helper is alive only if that pid still has the start time it recorded."""
        if not self.platform.pid_alive(pid):
            return False
        return started is not None and self.platform.start_time(pid) == started

    def _resume_index(self, steps, step, phase):
        return steps.index(step) + (1 if phase == "end" else 0)

    def _recover_steps(self):
        step, phase = self.state.get("step"), self.state.get("phase")
        if step in ROLLBACK:
            return self._steps(ROLLBACK, self._resume_index(ROLLBACK, step, phase))
        if step in FORWARD[FORWARD.index("registry"):] or (step == "swap_in" and phase == "end"):
            # The new version is in place. Carry on: launch it and health-check it.
            return self._steps(FORWARD, self._resume_index(FORWARD, step, phase))

        # Up to the second rename, the disk decides, since the process may
        # have died between a rename and the journal write recording it.
        at_install = os.path.lexists(self.install)
        backup = os.path.lexists(self.old)
        staged = os.path.lexists(self.new)
        try:
            if at_install and not backup:
                return self._finish("interrupted", "old", f"stopped during {step}; nothing was moved")
            if not at_install and backup:
                self._journal("swap_undo", "begin", installed=None)
                if not self._restore_backup():
                    return self._finish("stuck", None, "the backup vanished before it could be put back")
                return self._finish("interrupted", "old", f"stopped during {step}; the old version was put back")
            if at_install and backup and not staged:
                self._journal("swap_in", "end", installed="new")
                return self._steps(FORWARD, FORWARD.index("registry"))
        except Exception:
            return self._on_error(traceback.format_exc())
        self._log(f"unexpected layout: install {at_install}, backup {backup}, staged {staged}")
        installed = None if not at_install else "unknown"
        return self._finish("stuck", installed, "the install and its backup are in an unexpected state")


def main(argv=None):
    """``__apply_update__ <staging> [--pid N]``: apply or recover, exit 0 when the new version is in."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == APPLY_ARG:
        argv = argv[1:]
    parser = argparse.ArgumentParser(prog=APPLY_ARG)
    parser.add_argument("staging", help="the .<AppName>-update folder next to the install")
    parser.add_argument("--pid", type=int, default=None, help="wait for this process to exit first")
    args = parser.parse_args(argv)
    # A working folder inside the install would lock it on Windows, and the
    # helper may have been started from there. Staging is never moved.
    staging = os.path.abspath(args.staging)
    os.chdir(staging)
    applier = Applier(staging, default_platform(), pid=args.pid)
    result = applier.run()
    return 0 if result.get("installed") == "new" else 1


if __name__ == "__main__":
    sys.exit(main())
