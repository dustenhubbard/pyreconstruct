"""Stage an in-place update: download the payload, check it, unpack it, write plan.json.

The app's half of an in-place update, before the hand-off at quit. The
release's payload and its tree.json are checked against the release's signed
``SHA256SUMS``, unpacked into the staging folder next to the install, checked
file by file against tree.json, and only then is ``plan.json`` written, for
``apply.py`` to act on at quit. ``backend/updater/inplace.py`` calls this and
starts the helper.

On Windows the payload is the release's update archive, unpacked into
``new/``. The installed helper, ``_updater/pyreconstruct-updater.exe``, is
copied to ``helper/`` too, since a helper run from the install would keep
the install folder from being renamed.

On macOS the payload is the release's notarized dmg itself. It is attached
read-only inside ``download/``, the app is copied out with ``ditto`` into
``new.app/`` (apply.py, ``staged_name``), and the image is detached. The copy
is then checked against tree.json and with ``codesign`` against our Team ID
and the flavor's bundle id. The helper is the installed app, so nothing is
copied for it.

Any failure (a bad or missing signature, a hash or size that does not match,
an archive entry that would land outside ``new/``, a bundle codesign refuses,
a full disk) clears what this run staged, ``plan.json`` first, and raises
:class:`StageError`. The install itself is never touched here; only the
helper changes it.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile

from PyReconstruct.modules.backend.updater import apply as A
from PyReconstruct.modules.backend.updater import updater as U

PLATFORM = "windows-x86_64"
CARRY = ["unins*.*"]  # the Inno Setup uninstaller stays with the install
DOWNLOAD = "download"
MOUNT = "mnt"  # the dmg's mount point, inside download/
HELPER = "helper"
HELPER_EXE = "pyreconstruct-updater.exe"
# The Developer ID team that signs the macOS builds (packaging/macos/sign_app.sh).
TEAM_ID = "57Z336NM5P"
# tree.json for a release build is under 1 MB (3,634 files); anything far bigger is not ours.
_MAX_TREE_BYTES = 32 << 20


class StageError(RuntimeError):
    """The update was not staged. No plan is left behind and the install is untouched."""


def payload_names(version, flavor, platform=PLATFORM):
    """(payload, tree) asset names, as the release names them.

    On Windows the payload is the archive scripts/build_update_payload.py
    writes; on macOS it is the release's dmg, the installer the app offers
    when it cannot update in place.
    """
    dev = "-Dev" if flavor == "dev" else ""
    base = f"PyReconstruct-{version}-update-{platform}{dev}"
    if platform.startswith("macos-"):
        return f"PyReconstruct-{version}-macOS-{platform.split('-', 1)[1]}{dev}.dmg", f"{base}.tree.json"
    return f"{base}.tar.xz", f"{base}.tree.json"


def code_requirement(bundle_id, team_id=TEAM_ID):
    """The codesign requirement a macOS bundle of ours meets: Developer ID, our team, this bundle id."""
    return (f'anchor apple generic and certificate leaf[subject.OU] = "{team_id}" '
            f'and identifier "{bundle_id}"')


def check_code_signature(path, requirement, deep=True):
    """Raise StageError unless ``codesign`` finds ``path`` intact and meeting ``requirement``.

    ``deep`` checks every nested framework and library too, for a bundle
    about to be put in place; the running app is checked without it.
    """
    _run(["/usr/bin/codesign", "--verify"] + (["--deep", "--strict"] if deep else [])
         + [f"-R={requirement}", path], "the app's signature is not ours")


def staging_dir(install, app_name):
    return os.path.join(os.path.dirname(os.path.abspath(install)), f".{app_name}-update")


def _is_link(path):
    """A symlink, or on Windows any reparse point such as a junction, which os.path.islink misses."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISLNK(st.st_mode)
            or bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def _clear(staging):
    """Delete what a staging run writes, plan.json first. Raises StageError if any of it stays.

    Every item is tried even when one fails (Windows refuses to delete a file
    another process holds open), because a plan.json without its tree.json or
    new/ beside it is one the helper refuses.
    """
    failed = []
    for name in (A.PLAN, A.TREE, A.NEW, A.NEW_APP, DOWNLOAD, HELPER):
        try:
            if name == DOWNLOAD:
                _remove_download(staging)
            else:
                A._remove(os.path.join(staging, name))
        except (OSError, StageError) as e:
            failed.append(f"{name} ({e})")
    if failed:
        raise StageError(f"could not clear the staging folder: {', '.join(failed)}")


def stage_update(release, *, install, app_name, flavor, from_version, pid=None,
                 registry_key=None, trusted_keys=None, progress_cb=None, cancel_cb=None,
                 session=None, platform=PLATFORM, bundle_id=None, requirement=None):
    """Stage ``release``'s payload for the install at ``install``. Returns the plan written.

    ``install`` is the install folder (on macOS the .app bundle), ``app_name``
    its name ("PyReconstruct" or "PyReconstruct Dev"), and ``from_version``
    the running version. ``platform`` is the release's platform key, such as
    "windows-x86_64" or "macos-arm64"; a macOS one needs the bundle's
    ``bundle_id``, and the staged copy has to meet ``requirement``
    (:func:`code_requirement` for it by default).
    ``session`` is written into plan.json as it is, so the app can tell the
    plan it staged from one an earlier run left. Raises :class:`StageError`
    when the update cannot be staged, and :class:`UpdateCancelled` when
    ``cancel_cb`` stops the download; either way nothing this run staged is
    left, and neither is a plan an earlier run staged.
    """
    version = U._tag_version(release)
    staging = staging_dir(install, app_name)
    created = not os.path.lexists(staging)
    if _is_link(staging):
        # a junction to the install would put the lock and every staged file inside it
        raise StageError("the staging folder is a link or a junction")
    os.makedirs(staging, exist_ok=True)
    lock = A.take_lock(staging)
    if lock is None:
        raise StageError("an update helper is running")
    ok = False
    try:
        state = A.read_json(os.path.join(staging, A.STATE))
        if ((isinstance(state, dict) and state.get("status") == "running")
                or any(os.path.lexists(os.path.join(staging, n)) for n in (A.OLD, A.REJECTED))):
            # old/ may be the only copy of the install; the helper finishes or undoes that run
            raise StageError("an earlier update has not finished")
        try:
            _clear(staging)  # first, so an earlier plan never outlives a refusal below
            if version is None:
                raise StageError("the release has no version")
            if platform.startswith("macos-") and not bundle_id:
                raise StageError("a macOS install needs its bundle id")
            plan = _stage(release, str(version), staging, install, app_name, flavor,
                          from_version, pid, registry_key, trusted_keys, progress_cb, cancel_cb,
                          session, platform, bundle_id, requirement)
        except BaseException as e:
            try:
                _clear(staging)
            except StageError:
                pass  # the first error is the one to report
            if isinstance(e, (StageError, U.UpdateCancelled)) or not isinstance(e, Exception):
                raise
            raise StageError(f"could not stage the update: {e}") from e
        ok = True
        return plan
    finally:
        A.release_lock(lock)
        if created and not ok:
            # an empty folder holds no file the uninstaller looks for, so it would stay behind
            try:
                os.remove(os.path.join(staging, A.LOCK))
                os.rmdir(staging)
            except OSError:
                pass


def _stage(release, version, staging, install, app_name, flavor, from_version, pid,
           registry_key, trusted_keys, progress_cb, cancel_cb, session, platform, bundle_id,
           requirement):
    macos = platform.startswith("macos-")
    archive_name, tree_name = payload_names(version, flavor, platform)
    assets = {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)}
    if archive_name not in assets or tree_name not in assets:
        raise StageError("the release has no update payload for this build")
    signed = {}
    for name in (tree_name, archive_name):
        status, digest = U.fetch_signed_checksum(release, name, trusted_keys)
        if status != "ok":
            raise StageError(f"{name} failed the signed checksum check ({status})")
        signed[name] = digest

    tree_bytes = U._download_bytes(assets[tree_name]["browser_download_url"], limit=_MAX_TREE_BYTES)
    if hashlib.sha256(tree_bytes).hexdigest() != signed[tree_name]:
        raise StageError("tree.json does not match the signed checksum")
    tree = json.loads(tree_bytes)
    identity = {"format": A.FORMAT, "version": version, "flavor": flavor,
                "app_name": app_name, "platform": platform}
    if macos:
        identity["bundle_id"] = bundle_id
    if not isinstance(tree, dict) or any(tree.get(k) != v for k, v in identity.items()):
        raise StageError("tree.json is for another build")
    listed = {e.get("path"): e for e in tree.get("files") or [] if isinstance(e, dict)}
    installed = sum(e["size"] for e in listed.values()
                    if e.get("type", "file") == "file" and isinstance(e.get("size"), int))

    size = assets[archive_name].get("size")
    if not isinstance(size, int) or size <= 0:
        raise StageError("the release does not give the payload's size")
    free = shutil.disk_usage(staging).free
    if free < size + 2 * installed:
        raise StageError(f"not enough free space: {size + 2 * installed} bytes needed, {free} free")

    os.mkdir(os.path.join(staging, DOWNLOAD))
    archive = os.path.join(staging, DOWNLOAD, archive_name)
    digest = U.download_asset(assets[archive_name]["browser_download_url"], archive,
                              progress_cb=progress_cb, cancel_cb=cancel_cb)
    if os.path.getsize(archive) != size:
        raise StageError("the download is incomplete")
    if digest != signed[archive_name]:
        raise StageError("the payload does not match the signed checksum")

    if macos:
        return _stage_bundle(archive, tree, staging, install, app_name, flavor, bundle_id,
                             from_version, version, pid, session, requirement)
    new = os.path.join(staging, A.NEW)
    os.mkdir(new)
    with tarfile.open(archive, "r:xz") as tar:
        for m in tar.getmembers():
            # Every entry checked before anything is written: only listed files at
            # their listed sizes, and folders, at paths that stay inside new/.
            try:
                A.safe_parts(m.name, windows=True)
            except A.Refused as e:
                raise StageError(f"the payload holds an unsafe path: {e}")
            entry = listed.get(m.name)
            if m.isfile() and entry is not None and entry.get("size") == m.size:
                continue
            if not m.isdir():
                raise StageError(f"the payload holds {m.name!r}, which tree.json does not list")
        tar.extractall(new, filter="data")
    A._remove(os.path.join(staging, DOWNLOAD))
    try:
        A.verify_tree(new, tree, windows=True)
    except A.Refused as e:
        raise StageError(f"the unpacked payload does not match tree.json: {e}")

    # Kept unsigned, for the helper to check new/ against at quit. Anyone who can
    # write here can also write the per-user install itself, so signing it again
    # would not keep out anyone the install folder lets in.
    A.atomic_write_json(os.path.join(staging, A.TREE), tree)
    helper = os.path.join(install, "_updater", HELPER_EXE)
    if not os.path.isfile(helper):
        raise StageError("the install has no update helper")
    os.mkdir(os.path.join(staging, HELPER))
    shutil.copy2(helper, os.path.join(staging, HELPER, HELPER_EXE))
    return _write_plan(staging, session, {
        "format": A.FORMAT, "platform": "windows", "kind": "folder",
        "install": os.path.abspath(install), "app_name": app_name, "flavor": flavor,
        "bundle_id": None, "from_version": from_version, "to_version": version, "pid": pid,
        "exe": f"{app_name}.exe", "args": [], "selftest_args": ["--selftest"],
        "carry": list(CARRY), "registry_key": registry_key,
    })


def _stage_bundle(dmg, tree, staging, install, app_name, flavor, bundle_id, from_version,
                  version, pid, session, requirement):
    """macOS: copy the app out of the verified dmg into new.app, check it, write the plan."""
    new = os.path.join(staging, A.NEW_APP)
    _copy_from_dmg(dmg, os.path.join(staging, DOWNLOAD, MOUNT), f"{app_name}.app", new)
    _remove_download(staging)
    _clear_attributes(new)
    try:
        A.verify_tree(new, tree)
    except A.Refused as e:
        raise StageError(f"the app in the disk image does not match tree.json: {e}")
    check_code_signature(new, requirement or code_requirement(bundle_id))
    A.atomic_write_json(os.path.join(staging, A.TREE), tree)
    return _write_plan(staging, session, {
        "format": A.FORMAT, "platform": "macos", "kind": "folder",
        "install": os.path.abspath(install), "app_name": app_name, "flavor": flavor,
        "bundle_id": bundle_id, "from_version": from_version, "to_version": version, "pid": pid,
        "exe": f"Contents/MacOS/{app_name}", "args": [], "selftest_args": ["--selftest"],
        "carry": [], "registry_key": None,
    })


def _run(argv, what):
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        raise StageError(f"{what}: {e}") from e
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise StageError(f"{what}: {detail[-1] if detail else done.returncode}")


def _detach(mount):
    """Detach the dmg at ``mount``, forcing it if a plain detach fails. Never raises.

    Returns whether ``mount`` is free of it.
    """
    for extra in ([], ["-force"]):
        try:
            if subprocess.run(["/usr/bin/hdiutil", "detach", mount] + extra,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=120).returncode == 0:
                break
        except (OSError, subprocess.SubprocessError):
            pass
    return not os.path.ismount(mount)


def _remove_download(staging):
    """Delete download/, detaching a dmg still attached inside it first.

    A dmg left by a staging run that was killed, or one neither detach
    could close, raises StageError and is left as it is: deleting into it
    would go through its links, such as Applications -> /Applications.
    """
    mount = os.path.join(staging, DOWNLOAD, MOUNT)
    if os.path.ismount(mount) and not _detach(mount):
        raise StageError("the disk image in the staging folder could not be detached")
    A._remove(os.path.join(staging, DOWNLOAD))


def _copy_from_dmg(dmg, mount, bundle, dest):
    """Attach ``dmg`` read-only at ``mount``, ``ditto`` its ``bundle`` to ``dest``, and detach it."""
    os.mkdir(mount)
    _run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen",
          "-mountpoint", mount, dmg], "could not open the disk image")
    try:
        src = os.path.join(mount, bundle)
        if os.path.islink(src) or not os.path.isdir(src):
            raise StageError(f"the disk image holds no {bundle}")
        _run(["/usr/bin/ditto", src, dest], "could not copy the app from the disk image")
    finally:
        _detach(mount)


def _clear_attributes(bundle):
    """Clear the Finder flags on the bundle folder and any quarantine inside it.

    The dmg sets Finder information on the app's folder, which codesign's
    strict check refuses, and a dmg the system quarantined passes quarantine
    to every file copied out of it. Neither is part of the signed app.
    Failures are left to the checks after this.
    """
    for argv in (["/usr/bin/xattr", "-c", bundle],
                 ["/usr/bin/xattr", "-r", "-d", "com.apple.quarantine", bundle]):
        try:
            subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            pass


def _write_plan(staging, session, plan):
    if session is not None:
        plan["session"] = session
    plan_path = os.path.join(staging, A.PLAN)
    A.atomic_write_json(plan_path, plan)
    try:
        A.load_plan(plan_path)  # the helper's own check, so a plan it would refuse is not left
    except A.Refused as e:
        raise StageError(str(e))
    return plan
