"""Eject the macOS installer disk image once the app runs from outside it (Qt-free).

A user drags the app from the mounted .dmg to Applications, and the image
stays mounted until they eject it by hand. The image cannot run code at drag
time, so the app does it instead: on launch it looks for a mounted installer
image of this same build and detaches it.

An image is ejected only when every one of these holds:

* this is a frozen macOS build, and its own ``Info.plist`` can be read;
* the image is read-only (the release .dmg is UDZO), so a writable image such
  as a Time Machine sparsebundle or a working image is never a candidate;
* the image has exactly one mounted volume. ``hdiutil detach`` takes every
  volume of an image, and the release image has one;
* the volume's root is the installer layout and nothing else: one ``.app``,
  the ``Applications`` link to ``/Applications``, and optionally the
  first-launch guide (see ``packaging/macos/make_dmg.sh``). Hidden files such
  as ``.DS_Store`` and ``.background.tiff`` are ignored. A backup image or a
  data volume holds other files, so it never matches;
* that ``.app`` has this app's ``CFBundleIdentifier`` and the same
  ``PyReconstructVersion``. Stable and Dev have different bundle ids. The
  version check means an older copy started while a newer image is open (the
  user is about to drag it over) leaves that image alone;
* neither the running app nor any path the caller passes in (the open series
  and its images) is on that volume. A quarantined app opened straight from
  the image runs from an App Translocation path, so a translocated app ejects
  nothing;
* no other image qualifies. With two candidates, neither is ejected.

Every failure (a busy volume, ``hdiutil`` missing or slow) is logged and
swallowed. The work runs off the GUI thread, so a slow ``hdiutil`` never
holds up the window.
"""

import os
import plistlib
import subprocess
import sys
import threading
from pathlib import Path

from PyReconstruct.modules.constants.frozen import is_frozen
from PyReconstruct.modules.backend.func.logging_setup import log_note

_TIMEOUT = 30  # seconds; hdiutil answers in well under one
GUIDE = "Read Before First Launch.html"  # make_dmg.sh adds it for unsigned apps


def _hdiutil(args):
    """Run ``hdiutil`` and return its stdout as bytes; raise on any failure."""
    return subprocess.run(
        ["hdiutil", *args], capture_output=True, check=True, timeout=_TIMEOUT,
    ).stdout


def own_bundle(executable=None):
    """The ``.app`` folder this process runs from, or None outside one."""
    exe = Path(executable or sys.executable).resolve()
    # <name>.app/Contents/MacOS/<exe>
    if len(exe.parents) < 3 or exe.parents[1].name != "Contents":
        return None
    app = exe.parents[2]
    return app if app.suffix == ".app" else None


def _identity(app):
    """(bundle id, PyReconstructVersion) from an app's Info.plist, or None."""
    try:
        with open(Path(app) / "Contents" / "Info.plist", "rb") as f:
            info = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    bid = info.get("CFBundleIdentifier")
    ver = info.get("PyReconstructVersion")
    if not isinstance(bid, str) or not isinstance(ver, str) or not bid or not ver:
        return None
    return bid, ver


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def _is_installer_volume(mount, identity):
    """Whether ``mount`` holds the installer layout for ``identity``, and nothing else."""
    root = Path(mount)
    try:
        names = {n for n in os.listdir(root) if not n.startswith(".")}
        apps = [n for n in names if n.endswith(".app")]
        if len(apps) != 1 or names - {apps[0], GUIDE} != {"Applications"}:
            return False
        if os.readlink(root / "Applications") != "/Applications":
            return False
        if GUIDE in names and not (root / GUIDE).is_file():
            return False
    except OSError:
        return False
    return _identity(root / apps[0]) == identity


def installer_mounts(info, identity, bundle, protected=()):
    """Mount points in ``hdiutil info -plist`` output that hold our installer.

    ``info`` is the parsed plist; ``identity`` is this app's (bundle id,
    version); ``bundle`` is the running ``.app``; ``protected`` are paths
    whose volume must stay mounted. Pure apart from reading each candidate
    volume's root, so tests can drive it with temp folders.
    """
    keep = [p for p in (bundle, *protected) if p]
    found = []
    for image in info.get("images") or []:
        if image.get("writeable", True):
            continue
        mounts = [e["mount-point"] for e in image.get("system-entities") or []
                  if e.get("mount-point")]
        if len(mounts) != 1:
            continue
        mount = mounts[0]
        if any(_inside(p, mount) for p in keep):
            continue
        if _is_installer_volume(mount, identity):
            found.append(mount)
    return found


def eject_installer_image(*, protected=(), platform=None, executable=None,
                          hdiutil=_hdiutil):
    """Detach the mounted installer image of this build; return the mounts ejected.

    ``protected`` are paths whose volume must stay mounted. Never raises. The
    other keyword arguments are for tests.
    """
    ejected = []
    try:
        if (platform or sys.platform) != "darwin" or not is_frozen():
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
        info = plistlib.loads(hdiutil(["info", "-plist"]))
        mounts = installer_mounts(info, identity, bundle, protected)
        if len(mounts) > 1:
            log_note(f"installer image: {len(mounts)} candidates, ejecting none: "
                     + ", ".join(mounts))
            return ejected
        for mount in mounts:
            try:
                hdiutil(["detach", mount])
                ejected.append(mount)
                log_note(f"installer image: ejected {mount}")
            except Exception as exc:
                why = (getattr(exc, "stderr", None) or b"").decode(errors="replace").strip()
                log_note(f"installer image: could not eject {mount}: {exc!r} {why}".rstrip())
    except Exception as exc:
        log_note(f"installer image: skipped: {exc!r}")
    return ejected


def eject_installer_image_in_background(protected=()):
    """Start :func:`eject_installer_image` on a daemon thread.

    ``protected`` is read by the caller on the GUI thread and passed as a
    list of strings, so the worker never touches the series.
    """
    if sys.platform != "darwin" or not is_frozen():
        return
    threading.Thread(target=eject_installer_image, name="eject-installer-image",
                     kwargs={"protected": list(protected)}, daemon=True).start()
