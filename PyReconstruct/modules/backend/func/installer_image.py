"""Eject the macOS installer disk image once the app runs from outside it (Qt-free).

A user drags the app from the mounted .dmg to Applications, and the image
stays mounted until they eject it by hand. The image cannot run code at drag
time, so the app does it instead: on launch it looks for the image it was
copied from and detaches it.

An image is ejected only when every one of these holds:

* this is a frozen macOS build, and its own ``Info.plist`` can be read;
* the image is read-only (the release .dmg is UDZO), so a writable image such
  as a Time Machine sparsebundle or a working image is never a candidate;
* an ``.app`` at the image's root has this app's ``CFBundleIdentifier`` and
  the same ``PyReconstructVersion``. The volume name alone is not used: a
  name is easy to share, and Stable and Dev images differ only in it. The
  version check means an older copy started while a newer image is open (the
  user is about to drag it over) leaves that image alone;
* the running app is not on that volume. A quarantined app opened straight
  from the image runs from an App Translocation path, so a translocated app
  ejects nothing.

Every failure (a busy volume, ``hdiutil`` missing or slow) is logged and
swallowed. The work runs off the GUI thread, so a slow ``hdiutil`` never
holds up the window.
"""

import plistlib
import subprocess
import sys
import threading
from pathlib import Path

from PyReconstruct.modules.constants.frozen import is_frozen
from PyReconstruct.modules.backend.func.logging_setup import log_note

_TIMEOUT = 30  # seconds; hdiutil answers in well under one


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
    """(bundle id, version) from an app's Info.plist, or None if unreadable."""
    try:
        with open(Path(app) / "Contents" / "Info.plist", "rb") as f:
            info = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    bid = info.get("CFBundleIdentifier")
    ver = info.get("PyReconstructVersion") or info.get("CFBundleVersion")
    if not isinstance(bid, str) or not isinstance(ver, str) or not bid or not ver:
        return None
    return bid, ver


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, ValueError):
        return False


def installer_mounts(info, identity, bundle):
    """Mount points in ``hdiutil info -plist`` output that hold our installer.

    ``info`` is the parsed plist; ``identity`` is this app's (bundle id,
    version); ``bundle`` is the running ``.app``. Pure apart from reading each
    candidate volume's root, so tests can drive it with temp folders.
    """
    found = []
    for image in info.get("images") or []:
        if image.get("writeable", True):
            continue
        for entity in image.get("system-entities") or []:
            mount = entity.get("mount-point")
            if not mount or _inside(bundle, mount):
                continue
            try:
                apps = [p for p in Path(mount).iterdir() if p.suffix == ".app"]
            except OSError:
                continue
            if any(_identity(app) == identity for app in apps):
                found.append(mount)
    return found


def eject_installer_image(*, platform=None, executable=None, hdiutil=_hdiutil):
    """Detach the installer image this copy came from; return the mounts ejected.

    Never raises. The keyword arguments are for tests.
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
        for mount in installer_mounts(info, identity, bundle):
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


def eject_installer_image_in_background():
    """Start :func:`eject_installer_image` on a daemon thread."""
    if sys.platform != "darwin" or not is_frozen():
        return
    threading.Thread(target=eject_installer_image, name="eject-installer-image",
                     daemon=True).start()
