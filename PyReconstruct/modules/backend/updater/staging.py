"""Stage an in-place update on Windows: download the payload, check it, unpack it, write plan.json.

The app's half of an in-place update, before the hand-off at quit. The
release's update archive and its tree.json are checked against the release's
signed ``SHA256SUMS``, unpacked into ``new/`` in the staging folder next to
the install, checked file by file against tree.json, and only then is
``plan.json`` written, for ``apply.py`` to act on at quit. The installed
helper, ``_updater/pyreconstruct-updater.exe``, is copied to ``helper/`` in
the staging folder too, since a helper run from the install would keep the
install folder from being renamed. ``backend/updater/inplace.py`` calls this
and starts the helper.

Any failure (a bad or missing signature, a hash or size that does not match,
an archive entry that would land outside ``new/``, a full disk) clears what
this run staged, ``plan.json`` first, and raises :class:`StageError`. The
install itself is never touched here; only the helper changes it.
"""

import hashlib
import json
import os
import shutil
import stat
import tarfile

from PyReconstruct.modules.backend.updater import apply as A
from PyReconstruct.modules.backend.updater import updater as U

PLATFORM = "windows-x86_64"
CARRY = ["unins*.*"]  # the Inno Setup uninstaller stays with the install
DOWNLOAD = "download"
HELPER = "helper"
HELPER_EXE = "pyreconstruct-updater.exe"
# The copy each finished result leaves spare, and what that result put at the install path.
_SPARE_COPY = {"updated": (A.OLD, "new"), "rolled_back": (A.REJECTED, "old")}
# tree.json for a release build is under 1 MB (3,634 files); anything far bigger is not ours.
_MAX_TREE_BYTES = 32 << 20


class StageError(RuntimeError):
    """The update was not staged. No plan is left behind and the install is untouched."""


def payload_names(version, flavor):
    """(archive, tree) asset names, as scripts/build_update_payload.py writes them."""
    base = f"PyReconstruct-{version}-update-{PLATFORM}{'-Dev' if flavor == 'dev' else ''}"
    return f"{base}.tar.xz", f"{base}.tree.json"


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
    for name in (A.PLAN, A.TREE, A.NEW, DOWNLOAD, HELPER):
        try:
            A._remove(os.path.join(staging, name))
        except OSError as e:
            failed.append(f"{name} ({e})")
    if failed:
        raise StageError(f"could not clear the staging folder: {', '.join(failed)}")


def _spare_copy(staging, state, install):
    """The copy a finished run could not delete, when the install is back in place; else None.

    Windows refuses to delete a file a scanner or the indexer holds for a
    moment, so a run that ended well can leave old/ (after a healthy update,
    the version before it) or rejected/ (after a rollback, the version that
    failed) behind. Either is a spare once the install is back. Anything else
    is not: a run that ended stuck, a journal for another install, no journal,
    or a link, since old/ may be the only copy of the install.
    """
    if not isinstance(state, dict) or state.get("status") != "done":
        return None
    spare, installed = _SPARE_COPY.get(state.get("result"), (None, None))
    plan = state.get("plan")
    if spare is None or state.get("installed") != installed or not isinstance(plan, dict):
        return None
    if not isinstance(plan.get("install"), str) or A._norm_win(plan["install"]) != A._norm_win(install):
        return None
    path = os.path.join(staging, spare)
    if not os.path.lexists(path) or _is_link(path) or not os.path.isdir(install) or _is_link(install):
        return None
    if A._at_or_inside(os.path.realpath(install), os.path.realpath(path)) or \
            A._at_or_inside(os.path.realpath(path), os.path.realpath(install)):
        return None
    return path


def stage_update(release, *, install, app_name, flavor, from_version, pid=None,
                 registry_key=None, trusted_keys=None, progress_cb=None, cancel_cb=None,
                 session=None):
    """Stage ``release``'s Windows payload for the install at ``install``. Returns the plan written.

    ``install`` is the install folder, ``app_name`` its name ("PyReconstruct"
    or "PyReconstruct Dev"), and ``from_version`` the running version.
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
        if isinstance(state, dict) and state.get("status") == "running":
            raise StageError("an earlier update has not finished")  # the helper finishes or undoes it
        spare = _spare_copy(staging, state, install)
        if any(os.path.lexists(p) and p != spare
               for p in (os.path.join(staging, n) for n in (A.OLD, A.REJECTED))):
            # old/ may be the only copy of the install
            raise StageError("an earlier update has not finished")
        try:
            _clear(staging)  # first, so an earlier plan never outlives a refusal below
            if version is None:
                raise StageError("the release has no version")
            plan = _stage(release, str(version), staging, install, app_name, flavor,
                          from_version, pid, registry_key, trusted_keys, progress_cb, cancel_cb,
                          session)
            if spare is not None:
                # Last, once the update is staged and checked: the install may
                # have been damaged since, and until then this copy is the good one.
                if _spare_copy(staging, state, install) != spare:
                    raise StageError("an earlier update has not finished")
                try:
                    A._remove(spare)
                except OSError as e:
                    # Kept, and tried again at the next staging; the journal still says what it is.
                    raise StageError(f"could not remove what an earlier update left: {e}") from e
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
           registry_key, trusted_keys, progress_cb, cancel_cb, session):
    archive_name, tree_name = payload_names(version, flavor)
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
                "app_name": app_name, "platform": PLATFORM}
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
    plan = {
        "format": A.FORMAT, "platform": "windows", "kind": "folder",
        "install": os.path.abspath(install), "app_name": app_name, "flavor": flavor,
        "bundle_id": None, "from_version": from_version, "to_version": version, "pid": pid,
        "exe": f"{app_name}.exe", "args": [], "selftest_args": ["--selftest"],
        "carry": list(CARRY), "registry_key": registry_key,
    }
    if session is not None:
        plan["session"] = session
    plan_path = os.path.join(staging, A.PLAN)
    A.atomic_write_json(plan_path, plan)
    try:
        A.load_plan(plan_path)  # the helper's own check, so a plan it would refuse is not left
    except A.Refused as e:
        raise StageError(str(e))
    return plan
