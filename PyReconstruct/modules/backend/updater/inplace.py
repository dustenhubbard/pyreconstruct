"""Windows in-place updates from the app's side: decide, stage, and start the helper at quit.

The update dialog asks :func:`stage_for_quit` first. It checks that this
install may update in place, stages the release next to the install
(``staging.py``), and returns a :class:`Pending` the main window keeps until
the user quits. Anything that stops it raises :class:`NotEligible` or
``StageError``, and the dialog downloads the installer as before. At the
committed quit, :func:`start_helper` starts the staged helper on the plan,
with the app's process ID and the open series, and the app quits.

Eligibility: a frozen Windows x86_64 build of a flavor turned on here; the
release's ``update-manifest.json``, checked against its signed
``SHA256SUMS``, turns in-place on for this platform and flavor and names a
``min_client`` this build meets; the version has not failed in place, nor
been put off ``MAX_DEFERRALS`` times; and the install is the per-user one
Setup.exe wrote (its HKCU uninstall entry names this folder, the uninstaller
and the helper are in it). An all-users install has no HKCU entry, so it
keeps the installer.

Only the Dev flavor is on. Stable follows once Dev has gone two weeks with
no rollback reports.

The helper is started only for the plan this process staged, for exactly
the version the dialog offered. plan.json carries a token made
fresh for each staging, and the plan on disk has to match the one staged,
token and all, when the app quits.
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
    """The running build, as the eligibility checks see it."""

    folder: str
    app_name: str
    flavor: str
    version: str


def running_install():
    """The running build, or None when it is not a frozen Windows x86_64 build."""
    from PyReconstruct.modules.backend.updater.install_info import (
        arch_key, current_version_str, install_kind, os_key,
    )
    from PyReconstruct.modules.datatypes.series_owner import app_display_name
    if install_kind() != "frozen" or os_key() != "windows" or arch_key() != "x86_64":
        return None
    version = current_version_str()
    if not version:
        return None
    app_name = app_display_name()
    exe = os.path.abspath(sys.executable)
    if os.path.basename(exe).casefold() != f"{app_name}.exe".casefold():
        return None  # not the program Setup.exe installed
    return Install(
        folder=os.path.dirname(exe),
        app_name=app_name,
        flavor="dev" if app_name.endswith(" Dev") else "stable",
        # the release and plan.json spell the public version, with no +local part
        version=version.split("+", 1)[0],
    )


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
    entry = _manifest_entry(release, str(version), install.flavor, trusted_keys)
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

    _check_per_user(install, platform or A.default_platform())
    return entry


def _manifest_entry(release, version, flavor, trusted_keys):
    """The release's signed manifest entry for Windows, checked against the release itself."""
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
    entry = (manifest.get("platforms") or {}).get(S.PLATFORM)
    if not isinstance(entry, dict):
        raise NotEligible("the update manifest has no Windows entry")
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
        raise NotEligible("only a frozen Windows build updates in place")
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
        registry_key=REGISTRY_KEYS[install.flavor], trusted_keys=trusted_keys,
        progress_cb=progress_cb, cancel_cb=cancel_cb, session=session,
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
    return all(os.path.lexists(os.path.join(pending.staging, n)) for n in (A.TREE, A.NEW)) \
        and os.path.isfile(helper_path(pending))


def helper_path(pending):
    return os.path.join(pending.staging, S.HELPER, S.HELPER_EXE)


def helper_argv(pending, pid, open_path=None):
    argv = [helper_path(pending), pending.staging, "--pid", str(int(pid))]
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
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    (popen or subprocess.Popen)(
        argv, cwd=pending.staging, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=A.child_env(),
    )
    return argv
