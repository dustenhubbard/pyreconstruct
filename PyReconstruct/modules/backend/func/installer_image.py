"""Eject the macOS installer disk image once the app runs from outside it (Qt-free).

After an install from the .dmg, the image stays mounted until the user ejects
it. The image cannot run code, so the installed app does it instead: at
launch, before the main window exists, it looks for a mounted installer image
of this same build and detaches it.

Doing it before the window means no series is open and no path can change
while ``hdiutil`` runs. A launch that opens a file ejects nothing (see
:func:`eject_installer_image`). ``runPyReconstruct`` calls this once, before
its window loop, so an in-app restart does not run it again.

An image is ejected only when every one of these holds:

* this is a frozen macOS build, and its own ``Info.plist`` can be read;
* the launch opens no file;
* the image is read-only (the release .dmg is UDZO), so a writable image such
  as a Time Machine sparsebundle or a working image is never a candidate;
* the image has exactly one mounted volume. ``hdiutil detach`` takes every
  volume of an image, and the release image has one;
* the volume's root is the installer layout and nothing else: one ``.app``,
  the ``Applications`` link to ``/Applications``, optionally the first-launch
  guide (see ``packaging/macos/make_dmg.sh``), and only the hidden entries in
  :data:`HIDDEN`. A backup image or a data volume holds other files, so it
  never matches;
* that ``.app`` has this app's ``CFBundleIdentifier`` and the same
  ``PyReconstructVersion``. Stable and Dev have different bundle ids. The
  version check means an older copy started while a newer image is open
  leaves that image alone. Its ``Info.plist`` is read only when it is a
  small regular file (:func:`_read_small`), so a FIFO, device or symlink
  planted there cannot block startup;
* no other image qualifies. With two candidates, neither is ejected;
* the running app is not on that volume. Paths are compared by device
  number, not by text, so a path that names the volume in other letter case
  still counts. A quarantined app opened straight from the image runs from an
  App Translocation path, so a translocated app ejects nothing.

Every failure (a busy volume, ``hdiutil`` missing or slow) is logged and
swallowed. All ``hdiutil`` calls share a budget of :data:`_BUDGET` seconds; a
call still running when it runs out is killed and the window opens. Killing
``hdiutil`` only ends the wait: an unmount macOS has already accepted may
still finish.
"""

import os
import plistlib
import stat
import subprocess
import sys
import time
from pathlib import Path

from PyReconstruct.modules.constants.frozen import is_frozen
from PyReconstruct.modules.backend.func.logging_setup import log_note

_BUDGET = 5  # seconds for every hdiutil call together; each takes well under one
_MAX_PLIST = 1 << 20  # bytes; a real Info.plist is a few kilobytes
GUIDE = "Read Before First Launch.html"  # make_dmg.sh adds it for unsigned apps
# Hidden root entries an installer image may hold. dmgbuild writes .DS_Store,
# .background.tiff (or .background.png for a single image) and, with an icon,
# .VolumeIcon.icns; macOS can add .fseventsd, .Trashes and .Spotlight-V100
# while dmgbuild has the image mounted read-write.
HIDDEN = {".DS_Store", ".background.tiff", ".background.png", ".VolumeIcon.icns",
          ".fseventsd", ".Trashes", ".Spotlight-V100"}


def _hdiutil(args, timeout):
    """Run ``hdiutil`` and return its stdout as bytes; raise on any failure.

    On timeout ``subprocess.run`` kills the child it started and waits for it.
    """
    return subprocess.run(
        ["hdiutil", *args], capture_output=True, check=True, timeout=timeout,
    ).stdout


def own_bundle(executable=None):
    """The ``.app`` folder this process runs from, or None outside one."""
    exe = Path(executable or sys.executable).resolve()
    # <name>.app/Contents/MacOS/<exe>
    if len(exe.parents) < 3 or exe.parents[1].name != "Contents":
        return None
    app = exe.parents[2]
    return app if app.suffix == ".app" else None


def _is_kind(path, kind):
    """Whether ``path`` itself (not a symlink's target) is of ``kind``.

    ``kind`` is ``stat.S_ISREG`` or ``stat.S_ISDIR``. ``lstat`` opens nothing,
    so it cannot block on a FIFO or a device.
    """
    try:
        return kind(os.lstat(path).st_mode)
    except OSError:
        return False


def _read_small(path, limit):
    """The bytes of ``path`` when it is a regular file of at most ``limit`` bytes.

    Raise OSError otherwise. A symlink is refused (``O_NOFOLLOW``), and a
    FIFO or device is never waited on (``O_NONBLOCK``) and then refused by the
    ``fstat`` of what was opened, so reading cannot block startup.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise OSError(f"not a regular file under {limit} bytes: {path}")
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise OSError(f"over {limit} bytes: {path}")
    return data


def _identity(app):
    """(bundle id, PyReconstructVersion) from an app's Info.plist, or None.

    The ``.app`` and its ``Contents`` must be real folders, not symlinks, and
    the plist a small regular file.
    """
    contents = Path(app) / "Contents"
    if not (_is_kind(app, stat.S_ISDIR) and _is_kind(contents, stat.S_ISDIR)):
        return None
    try:
        info = plistlib.loads(_read_small(contents / "Info.plist", _MAX_PLIST))
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    bid = info.get("CFBundleIdentifier")
    ver = info.get("PyReconstructVersion")
    if not isinstance(bid, str) or not isinstance(ver, str) or not bid or not ver:
        return None
    return bid, ver


def _st_dev(path):
    """Device number of ``path``, or of its nearest existing parent."""
    path = os.path.abspath(path)
    while True:
        try:
            return os.stat(path).st_dev
        except (FileNotFoundError, NotADirectoryError):
            parent = os.path.dirname(path)
            if parent == path:
                raise
            path = parent


def _on_volume(paths, mount):
    """Whether any of ``paths`` is on the volume mounted at ``mount``.

    True when a device number cannot be read, so the volume stays mounted.
    """
    try:
        dev = _st_dev(mount)
        return any(_st_dev(p) == dev for p in paths if p)
    except OSError:
        return True


def _is_installer_volume(mount, identity):
    """Whether ``mount`` holds the installer layout for ``identity``, and nothing else."""
    root = Path(mount)
    try:
        entries = set(os.listdir(root))
        if {n for n in entries if n.startswith(".")} - HIDDEN:
            return False
        names = {n for n in entries if not n.startswith(".")}
        apps = [n for n in names if n.endswith(".app")]
        if len(apps) != 1 or names - {apps[0], GUIDE} != {"Applications"}:
            return False
        if os.readlink(root / "Applications") != "/Applications":
            return False
        if GUIDE in names and not _is_kind(root / GUIDE, stat.S_ISREG):
            return False
    except OSError:
        return False
    return _identity(root / apps[0]) == identity


def installer_mounts(info, identity, bundle):
    """Mount points in ``hdiutil info -plist`` output that hold our installer.

    ``info`` is the parsed plist; ``identity`` is this app's (bundle id,
    version); ``bundle`` is the running ``.app``. Pure apart from reading each
    candidate volume, so tests can drive it with temp folders.
    """
    found = []
    for image in info.get("images") or []:
        if image.get("writeable", True):
            continue
        mounts = [e["mount-point"] for e in image.get("system-entities") or []
                  if e.get("mount-point")]
        if len(mounts) != 1:
            continue
        mount = mounts[0]
        if _on_volume([bundle], mount):
            continue
        if _is_installer_volume(mount, identity):
            found.append(mount)
    return found


def eject_installer_image(*, open_file=None, platform=None, executable=None,
                          hdiutil=None, budget=None, clock=time.monotonic):
    """Detach the mounted installer image of this build; return the mounts ejected.

    Call it before the main window exists. ``open_file`` is the file the
    first window will open, if any. Never raises. The other keyword arguments
    are for tests.
    """
    ejected = []
    try:
        if (platform or sys.platform) != "darwin" or not is_frozen():
            return ejected
        # A launch that opens a file (a double-click, a command-line argument
        # or a FileOpen event) ejects nothing. The series can keep its images
        # anywhere, the installer image included, and they are not known until
        # it loads. The next launch with no file ejects the image.
        if open_file:
            log_note("installer image: this launch opens a file; ejecting nothing")
            return ejected
        bundle = own_bundle(executable)
        if bundle is None:
            return ejected
        if "/AppTranslocation/" in str(bundle):
            log_note("installer image: app is translocated, so it may be running "
                     "from the image; ejecting nothing")
            return ejected
        identity = _identity(bundle)
        if identity is None:
            return ejected
        hdiutil = hdiutil or _hdiutil
        budget = _BUDGET if budget is None else budget
        deadline = clock() + budget

        def remaining():
            left = deadline - clock()
            if left <= 0:
                raise TimeoutError(f"hdiutil took over {budget} s")
            return left

        info = plistlib.loads(hdiutil(["info", "-plist"], remaining()))
        mounts = installer_mounts(info, identity, bundle)
        if len(mounts) > 1:
            log_note(f"installer image: {len(mounts)} candidates, ejecting none: "
                     + ", ".join(mounts))
            return ejected
        if not mounts:
            return ejected
        mount = mounts[0]
        try:
            hdiutil(["detach", mount], remaining())
            ejected.append(mount)
            log_note(f"installer image: ejected {mount}")
        except Exception as exc:
            why = (getattr(exc, "stderr", None) or b"").decode(errors="replace").strip()
            log_note(f"installer image: could not eject {mount}: {exc!r} {why}".rstrip())
    except Exception as exc:
        log_note(f"installer image: skipped: {exc!r}")
    return ejected
