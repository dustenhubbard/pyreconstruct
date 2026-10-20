"""In-place updates from the app's side (Windows and macOS): decide, stage, and start the helper at quit.

The update dialog asks :func:`stage_for_quit` first. It checks that this
install may update in place, stages the release next to the install
(``staging.py``), and returns a :class:`Pending` the main window keeps until
the user quits. Anything that stops it raises :class:`NotEligible` or
``StageError``, and the dialog downloads the installer as before. At the
committed quit, :func:`start_helper` starts the staged helper on the plan,
with the app's process ID and the open series, and the app quits. A quit
with nothing staged calls :func:`start_recovery` instead, which finishes a
run a helper left part way. An update the helper put off is staged again
at the next launch (:func:`deferred_version`), so the quit after it puts
it in.

Eligibility: a frozen Windows x86_64 or macOS build of a flavor turned on
here; the release's ``update-manifest.json``, checked against its signed
``SHA256SUMS``, turns in-place on for this platform and flavor and names a
``min_client`` this build meets; the version has not failed in place, nor
been put off ``MAX_DEFERRALS`` times. On Windows the install is the per-user
one Setup.exe wrote (its HKCU uninstall entry names this folder, the
uninstaller and the helper are in it); an all-users install has no HKCU
entry, so it keeps the installer. On macOS the app is the bundle the user
put in place: not a translocated copy, not on a disk image or another
volume, signed with our Team ID, and in a folder this user can write to. The
installed app is its own helper there (``run.py``, ``__apply_update__``).

Only the Dev flavor is on. Stable follows once Dev has gone two weeks with
no rollback reports.

The helper is started only for the plan this process staged, for exactly
the version the dialog offered. plan.json carries a token made
fresh for each staging, and the plan on disk has to match the one staged,
token and all, when the app quits. The helper is told that version too, and
puts in nothing else: after File > Restart, the closed window's restage can
still write its plan once the check here has passed.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

from PyReconstruct.modules.backend.updater import apply as A
from PyReconstruct.modules.backend.updater import staging as S
from PyReconstruct.modules.backend.updater import updater as U

MANIFEST = "update-manifest.json"
MANIFEST_SCHEMA = 1
# Flavors that update in place. Stable waits for two weeks of Dev with no rollback reports.
FLAVORS = ("dev",)
# The Inno Setup AppId of each flavor (packaging/windows/PyReconstruct.iss), as its uninstall key.
REGISTRY_KEYS = {
    "stable": A._UNINSTALL_KEY_PREFIX + "{A1B2C3D4-E5F6-47A8-9B0C-1D2E3F4A5B6C}_is1",
    "dev": A._UNINSTALL_KEY_PREFIX + "{0C76AF3D-BB20-4EDB-99FC-2B9244E213F7}_is1",
}
# The bundle id of each flavor's macOS app (packaging/PyReconstruct.spec).
BUNDLE_IDS = {
    "stable": "edu.utexas.synapseweb.pyreconstruct",
    "dev": "edu.utexas.synapseweb.pyreconstruct.dev",
}
_MAX_MANIFEST_BYTES = 1 << 20


class NotEligible(Exception):
    """This install or this release does not update in place. Nothing was staged."""


@dataclass
class Pending:
    """An update staged by this process, waiting for the user to quit."""

    staging: str
    plan: dict
    version: str


@dataclass
class Install:
    """The running build, as the eligibility checks see it.

    ``folder`` is the install folder on Windows and the .app bundle on macOS;
    ``platform`` is the release's key for it, such as "macos-arm64".
    """

    folder: str
    app_name: str
    flavor: str
    version: str
    platform: str = S.PLATFORM
    bundle_id: str | None = None


def running_install():
    """The running build, or None when it is not a frozen Windows x86_64 or macOS build."""
    from PyReconstruct.modules.backend.updater.install_info import (
        arch_key, current_version_str, install_kind, os_key,
    )
    from PyReconstruct.modules.datatypes.series_owner import app_display_name
    if install_kind() != "frozen":
        return None
    version = current_version_str()
    if not version:
        return None
    app_name = app_display_name()
    flavor = "dev" if app_name.endswith(" Dev") else "stable"
    # the release and plan.json spell the public version, with no +local part
    version = version.split("+", 1)[0]
    exe = os.path.abspath(sys.executable)
    if os_key() == "windows" and arch_key() == "x86_64":
        if os.path.basename(exe).casefold() != f"{app_name}.exe".casefold():
            return None  # not the program Setup.exe installed
        return Install(folder=os.path.dirname(exe), app_name=app_name, flavor=flavor,
                       version=version)
    if os_key() == "macos" and arch_key() in ("arm64", "x86_64"):
        macos = os.path.dirname(exe)
        contents = os.path.dirname(macos)
        bundle = os.path.dirname(contents)
        if (os.path.basename(exe), os.path.basename(macos), os.path.basename(contents),
                os.path.basename(bundle)) != (app_name, "MacOS", "Contents", f"{app_name}.app"):
            return None  # not the program in the bundle the dmg holds
        return Install(folder=bundle, app_name=app_name, flavor=flavor, version=version,
                       platform=f"macos-{arch_key()}", bundle_id=BUNDLE_IDS[flavor])
    return None


def check_eligible(release, install, *, platform=None, trusted_keys=None):
    """Raise :class:`NotEligible` with the reason unless ``install`` may take ``release`` in place."""
    if install.flavor not in FLAVORS:
        raise NotEligible(f"in-place updates are not on for the {install.flavor} build")
    try:
        return _check_eligible(release, install, platform, trusted_keys)
    except NotEligible:
        raise
    except Exception as e:  # a network error, or a manifest value of the wrong type
        raise NotEligible(f"could not check the release: {e}") from e


def _check_eligible(release, install, platform, trusted_keys):
    version = U._tag_version(release)
    if version is None:
        raise NotEligible("the release has no version")
    entry = _manifest_entry(release, str(version), install.flavor, trusted_keys, install.platform)
    if entry.get("inplace", {}).get("enabled") is not True:
        raise NotEligible("the release does not turn in-place updates on")
    try:
        if Version(install.version) < Version(str(entry.get("min_client"))):
            raise NotEligible(f"the release needs {entry.get('min_client')} or later to update in place")
    except InvalidVersion:
        raise NotEligible("the release or this build has no version to compare")

    staging = S.staging_dir(install.folder, install.app_name)
    failed = A.read_json(os.path.join(staging, A.FAILED_VERSIONS), {})
    if isinstance(failed, dict) and str(version) in (failed.get("versions") or []):
        raise NotEligible(f"{version} failed in place before")
    deferrals = A.read_json(os.path.join(staging, A.DEFERRALS), {})
    if (isinstance(deferrals, dict) and deferrals.get("version") == str(version)
            and int(deferrals.get("count", 0)) >= A.MAX_DEFERRALS):
        raise NotEligible(f"{version} was put off {A.MAX_DEFERRALS} times")

    if _is_macos(install):
        _check_bundle(install)
    else:
        _check_per_user(install, platform or A.default_platform())
    return entry


def _is_macos(install):
    return install.platform.startswith("macos-")


def _manifest_entry(release, version, flavor, trusted_keys, platform_key=S.PLATFORM):
    """The release's signed manifest entry for this platform, checked against the release itself."""
    assets = {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)}
    if MANIFEST not in assets:
        raise NotEligible("the release has no update manifest")
    status, digest = U.fetch_signed_checksum(release, MANIFEST, trusted_keys)
    if status != "ok":
        raise NotEligible(f"the update manifest failed the signed checksum check ({status})")
    data = U._download_bytes(assets[MANIFEST]["browser_download_url"], limit=_MAX_MANIFEST_BYTES)
    if hashlib.sha256(data).hexdigest() != digest:
        raise NotEligible("the update manifest does not match the signed checksum")
    try:
        manifest = json.loads(data)
    except ValueError:
        raise NotEligible("the update manifest is not valid JSON")
    if (not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("version") != version or manifest.get("flavor") != flavor):
        raise NotEligible("the update manifest is for another release or build")
    entry = (manifest.get("platforms") or {}).get(platform_key)
    if not isinstance(entry, dict):
        raise NotEligible(f"the update manifest has no {platform_key} entry")
    return entry


def _check_per_user(install, platform):
    """The install is the one Setup.exe wrote for this user, with what the swap needs beside it."""
    location = platform.install_location(REGISTRY_KEYS[install.flavor])
    if not location or A._norm_win(location) != A._norm_win(install.folder):
        raise NotEligible("this is not the per-user install")
    if not os.path.isfile(os.path.join(install.folder, "unins000.exe")):
        raise NotEligible("the install has no uninstaller")
    if not os.path.isfile(os.path.join(install.folder, "_updater", S.HELPER_EXE)):
        raise NotEligible("the install has no update helper")
    if not os.access(os.path.dirname(install.folder), os.W_OK):
        raise NotEligible("the folder that holds the install is not writable")


def _check_bundle(install):
    """The bundle is one the user put in place, signed by us, in a folder the swap can write.

    A copy macOS translocated, or one run from the dmg or another volume, is
    not where the user keeps the app, so the installer is the way to update it.
    """
    bundle = install.folder
    real = os.path.realpath(bundle)
    if os.path.islink(bundle):
        raise NotEligible("the app is a link")
    if "/AppTranslocation/" in real:
        raise NotEligible("macOS runs this app from a translocated copy")
    if real.startswith("/Volumes/"):
        raise NotEligible("the app runs from a disk image or another volume")
    try:
        info = A._read_plist(os.path.join(bundle, "Contents", "Info.plist"))
    except A.Refused as e:
        raise NotEligible(str(e))
    if info.get("CFBundleIdentifier") != install.bundle_id:
        raise NotEligible("the app has another bundle id")
    if not os.access(os.path.dirname(bundle), os.W_OK):
        raise NotEligible("the folder that holds the app is not writable")
    try:
        S.check_code_signature(bundle, S.code_requirement(install.bundle_id), deep=False)
    except S.StageError as e:
        raise NotEligible(str(e))


def stage_for_quit(release, offered, *, install=None, platform=None, trusted_keys=None,
                   progress_cb=None, cancel_cb=None):
    """Stage ``release`` to go in at quit. Returns a :class:`Pending`.

    ``offered`` is the version the dialog showed the user; the staged plan
    has to be that version. Raises :class:`NotEligible` or ``StageError``
    when the installer should be used instead, and ``UpdateCancelled`` when
    the user stops the download.
    """
    install = install or running_install()
    if install is None:
        raise NotEligible("only a frozen Windows or macOS build updates in place")
    try:
        same = Version(str(U._tag_version(release))) == Version(str(offered))
    except InvalidVersion:
        same = False
    if not same:
        raise NotEligible(f"the release is not {offered}, the version offered")
    check_eligible(release, install, platform=platform, trusted_keys=trusted_keys)
    session = secrets.token_hex(16)
    plan = S.stage_update(
        release, install=install.folder, app_name=install.app_name, flavor=install.flavor,
        from_version=install.version, pid=os.getpid(),
        registry_key=None if _is_macos(install) else REGISTRY_KEYS[install.flavor],
        trusted_keys=trusted_keys, progress_cb=progress_cb, cancel_cb=cancel_cb,
        session=session, platform=install.platform, bundle_id=install.bundle_id,
    )
    return Pending(staging=S.staging_dir(install.folder, install.app_name), plan=plan,
                   version=plan["to_version"])


def still_staged(pending):
    """True if the staging folder still holds exactly what ``pending`` staged, helper included."""
    if not isinstance(pending, Pending) or pending.plan.get("session") is None:
        return False
    if pending.plan.get("to_version") != pending.version:
        return False
    if A.read_json(os.path.join(pending.staging, A.PLAN)) != pending.plan:
        return False
    staged = A.staged_name(pending.plan.get("platform"))
    return all(os.path.lexists(os.path.join(pending.staging, n)) for n in (A.TREE, staged)) \
        and os.path.isfile(helper_path(pending))


def _helper(platform, staging, install, app_name):
    """The helper's program and the arguments before the staging folder.

    Windows runs the helper staging copied from the install. macOS runs the
    installed app itself, whose ``run.py`` turns into the helper on its first
    argument before it loads anything from Qt.
    """
    if platform == "macos":
        return [os.path.join(install, "Contents", "MacOS", app_name), A.APPLY_ARG]
    return [os.path.join(staging, S.HELPER, S.HELPER_EXE)]


def helper_path(pending):
    plan = pending.plan
    return _helper(plan.get("platform"), pending.staging, plan.get("install"), plan.get("app_name"))[0]


def helper_argv(pending, pid, open_path=None):
    plan = pending.plan
    argv = _helper(plan.get("platform"), pending.staging, plan.get("install"), plan.get("app_name")) \
        + [pending.staging, "--pid", str(int(pid)), "--expect", pending.version]
    if open_path and os.path.isabs(open_path) and os.path.isfile(open_path):
        argv += ["--open", open_path]
    return argv


def start_helper(pending, pid, open_path=None, popen=None):
    """Start the staged helper detached, to swap the update in once ``pid`` exits.

    Returns the helper's argv, or None when the staging folder no longer
    holds what this process staged, in which case nothing is started.
    """
    if not still_staged(pending):
        return None
    argv = helper_argv(pending, pid, open_path)
    _start(argv, pending.staging, popen)
    return argv


def deferred_version(install=None):
    """The version the helper put off at the last quit, for this session to stage again, or None.

    A run the helper defers (Windows held the install folder) is closed, so
    nothing goes in at the next quit unless that session stages the update
    again: the helper starts only for a plan the running app staged. None
    once the version has been put off ``MAX_DEFERRALS`` times; the dialog
    offers the installer for it then.
    """
    install = install or running_install()
    if install is None or install.flavor not in FLAVORS:
        return None
    result = A.read_json(os.path.join(S.staging_dir(install.folder, install.app_name), A.RESULT))
    if not isinstance(result, dict) or result.get("status") != "deferred" or result.get("offer_installer"):
        return None
    if result.get("from_version") != install.version:
        return None  # another version went in since
    version = result.get("to_version")
    return version if isinstance(version, str) else None


def start_recovery(pid, install=None, popen=None):
    """At a quit with nothing staged, start the staged helper on a run a helper left part way.

    A helper killed part way (a shutdown, a crash) leaves its journal open,
    and staging refuses to start another update over it. A running app holds
    its own install folder, so the next quit is the first moment a helper can
    finish or undo that run: it waits for ``pid`` to exit, then does, and
    starts nothing (``--recover``). This app ran from the install and is
    quitting cleanly, so it writes the health report first; it counts only if
    the journal expects this version. Returns the helper's argv, or None when
    nothing was left part way, a helper is still running, or the journal is
    not this install's or this version's.
    """
    install = install or running_install()
    if install is None or install.flavor not in FLAVORS:
        return None
    staging = S.staging_dir(install.folder, install.app_name)
    state = A.read_json(os.path.join(staging, A.STATE))
    plan = state.get("plan") if isinstance(state, dict) else None
    if not isinstance(plan, dict) or state.get("status") != "running":
        return None
    if not isinstance(plan.get("install"), str) or not _same_path(plan["install"], install):
        return None
    if install.version not in (plan.get("from_version"), plan.get("to_version")):
        return None  # the installer put another version in since; this journal is not about it
    helper = _helper("macos" if _is_macos(install) else "windows", staging, install.folder,
                     install.app_name)
    if not os.path.isfile(helper[0]):
        return None
    lock = A.take_lock(staging)
    if lock is None:
        return None  # a helper is still at work, and may be waiting on a report of its own
    A.release_lock(lock)
    A.write_health(staging, install.version)
    argv = helper + [staging, "--pid", str(int(pid)), "--recover"]
    _start(argv, staging, popen)
    return argv


def _same_path(path, install):
    """True if ``path`` names ``install``'s folder, compared as its platform compares paths."""
    if _is_macos(install):
        return os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(install.folder))
    return A._norm_win(path) == A._norm_win(install.folder)


def _start(argv, cwd, popen=None):
    """Start the helper detached, from the staging folder, never inside the install."""
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    (popen or subprocess.Popen)(
        argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=A.child_env(),
        start_new_session=os.name != "nt",
    )
