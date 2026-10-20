"""Staging an in-place update leaves a plan the helper accepts, or nothing at all.

``backend/updater/staging.py`` downloads a release's Windows update archive
and its tree.json, checks both against the signed SHA256SUMS, unpacks the
archive next to a fake install folder, and writes plan.json. The release is
served from memory and signed with the throwaway test key, so nothing here
touches the network or a real install. Every way staging can fail must leave
no plan.json, no staged files, and the install exactly as it was.
"""
import errno
import hashlib
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
from dataclasses import replace

import pytest

from PyReconstruct.modules.backend.updater import apply as A
from PyReconstruct.modules.backend.updater import inplace as I
from PyReconstruct.modules.backend.updater import staging as S
from PyReconstruct.modules.backend.updater import updater as U

from test_signed_checksums import TEST_PUB, make_sig
from test_updater_apply import FAST, NEW_V, OLD_V, FakePlatform, World, _write, snapshot, windows_tree

TAG = f"v{NEW_V}"
ARCHIVE, TREE = S.payload_names(NEW_V, "stable")


def _tar(entries):
    """An xz tar of (TarInfo, bytes or None) pairs."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        for info, data in entries:
            info.size = len(data) if data is not None else 0
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


class Release:
    """A fake install, a newer build packed as its payload, and a signed release serving both."""

    def __init__(self, tmp_path, monkeypatch, flavor="stable", manifest=None, version=NEW_V):
        self.flavor = flavor
        self.version, self.tag = version, f"v{version}"
        self.app_name = "PyReconstruct Dev" if flavor == "dev" else "PyReconstruct"
        self.archive_name, self.tree_name = S.payload_names(version, flavor)
        self.manifest = manifest  # update-manifest.json, published and signed when set
        self.install = str(tmp_path / "Programs" / self.app_name)
        windows_tree(self.install, OLD_V, self.app_name)
        _write(self.install, "unins000.exe", "inno uninstaller", 0o755)
        _write(self.install, "_updater/" + S.HELPER_EXE, "the installed helper", 0o755)
        self.staging = S.staging_dir(self.install, self.app_name)
        build = str(tmp_path / "build" / version / self.app_name)
        windows_tree(build, version, self.app_name)
        self.tree = A.build_tree(build, version=version, flavor=flavor, app_name=self.app_name,
                                 platform=S.PLATFORM)
        entries = []
        for e in self.tree["files"]:
            info = tarfile.TarInfo(e["path"])
            info.mode = e["mode"]
            with open(os.path.join(build, *e["path"].split("/")), "rb") as f:
                entries.append((info, f.read()))
        self.files = {}
        self.publish(_tar(entries))
        self.before = snapshot(self.install)
        self.fetched = []
        monkeypatch.setattr(U, "_open_download", self._open)

    def publish(self, archive, tree=None):
        """Put ``archive`` and tree.json on the release, listed in a SHA256SUMS signed for the tag."""
        self.files[self.archive_name] = archive
        self.files[self.tree_name] = json.dumps(tree or self.tree).encode()
        if self.manifest is not None:
            self.files[I.MANIFEST] = json.dumps(self.manifest).encode()
        sums = "".join(f"{hashlib.sha256(self.files[n]).hexdigest()}  {n}\n" for n in sorted(self.files)
                       if n not in ("SHA256SUMS", "SHA256SUMS.minisig")).encode()
        self.files["SHA256SUMS"] = sums
        self.files["SHA256SUMS.minisig"] = make_sig(sums, comment=f"tag:{self.tag} file:SHA256SUMS")
        self.sizes = {n: len(d) for n, d in self.files.items()}

    def _open(self, url, timeout):
        U._check_download_url(url)
        name = url.rsplit("/", 1)[1]
        self.fetched.append(name)
        if name not in self.files:
            raise RuntimeError("404")
        resp = io.BytesIO(self.files[name])
        resp.headers = {"Content-Length": str(len(self.files[name]))}
        return resp

    def release(self, tag=None):
        return {"tag_name": tag or self.tag, "assets": [
            {"name": n, "size": self.sizes[n],
             "browser_download_url": f"https://github.com/o/r/releases/download/{self.tag}/{n}"}
            for n in self.files]}

    def stage(self, tag=None):
        return S.stage_update(self.release(tag), install=self.install, app_name=self.app_name,
                              flavor=self.flavor, from_version=OLD_V, trusted_keys=[TEST_PUB])

    def nothing_left(self):
        assert snapshot(self.install) == self.before
        for name in (A.PLAN, A.TREE, A.NEW, S.DOWNLOAD, S.HELPER):
            assert not os.path.lexists(os.path.join(self.staging, name)), name
        assert not os.path.lexists(os.path.join(os.path.dirname(self.install), "escaped.txt"))


@pytest.fixture
def rel(tmp_path, monkeypatch):
    return Release(tmp_path, monkeypatch)


def test_staged_update_is_applied_by_the_helper(rel):
    plan = rel.stage()

    assert plan["to_version"] == NEW_V and plan["from_version"] == OLD_V
    assert A.load_plan(os.path.join(rel.staging, A.PLAN))["install"] == rel.install
    assert not os.path.lexists(os.path.join(rel.staging, S.DOWNLOAD))
    assert snapshot(rel.install) == rel.before  # staging never touches the install
    world = World()
    world.install, world.staging = rel.install, rel.staging
    result = A.Applier(rel.staging, FakePlatform(world), FAST, host="windows").run()
    assert result["status"] == "updated", result
    with open(os.path.join(rel.install, "version.txt")) as f:
        assert f.read() == NEW_V
    assert os.path.isfile(os.path.join(rel.install, "unins000.exe"))


def _bad_signature(rel):
    rel.files["SHA256SUMS"] = rel.files["SHA256SUMS"].replace(b"  ", b" *", 1)


def _no_signature(rel):
    del rel.files["SHA256SUMS.minisig"]


def _bad_hash(rel):
    data = bytearray(rel.files[ARCHIVE])
    data[len(data) // 2] ^= 0xFF
    rel.files[ARCHIVE] = bytes(data)


def _short_download(rel):
    rel.files[ARCHIVE] = rel.files[ARCHIVE][:-100]


def _zip_slip(rel):
    rel.publish(_tar([(tarfile.TarInfo("../escaped.txt"), b"outside")]))


def _link_out(rel):
    link = tarfile.TarInfo("_internal/escaped.txt")
    link.type, link.linkname = tarfile.SYMTYPE, "../../escaped.txt"
    rel.publish(_tar([(link, None)]))


def _unlisted(rel):
    rel.publish(_tar([(tarfile.TarInfo("PyReconstruct.exe"), b"not the listed size")]))


def _other_flavor(rel):
    rel.publish(rel.files[ARCHIVE], dict(rel.tree, flavor="dev"))


@pytest.mark.parametrize("break_it, reason", [
    (_bad_signature, "signed checksum check (bad_signature)"),
    (_no_signature, "signed checksum check (absent)"),
    (_bad_hash, "does not match the signed checksum"),
    (_short_download, "incomplete"),
    (_zip_slip, "unsafe path"),
    (_link_out, "which tree.json does not list"),
    (_unlisted, "which tree.json does not list"),
    (_other_flavor, "another build"),
])
def test_a_bad_release_leaves_no_plan(rel, break_it, reason):
    rel.stage()  # a plan from an earlier staging, which a failed one must not leave in place
    break_it(rel)

    with pytest.raises(S.StageError, match=reason.replace("(", r"\(").replace(")", r"\)")):
        rel.stage()
    rel.nothing_left()


def test_too_little_free_space_stops_before_the_download(rel, monkeypatch):
    monkeypatch.setattr(S.shutil, "disk_usage", lambda p: type("U", (), {"free": 1000})())

    with pytest.raises(S.StageError, match="not enough free space"):
        rel.stage()
    assert ARCHIVE not in rel.fetched
    rel.nothing_left()
    assert not os.path.lexists(rel.staging)  # a folder the uninstaller would not recognize


def test_a_disk_that_fills_while_unpacking_leaves_nothing(rel, monkeypatch):
    def full(self, path, **kw):
        _write(path, "PyReconstruct.exe", "half")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tarfile.TarFile, "extractall", full)
    with pytest.raises(S.StageError, match="No space left"):
        rel.stage()
    rel.nothing_left()


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_a_staging_folder_that_leads_into_the_install_is_refused(rel, kind):
    if kind == "junction":
        if os.name != "nt":
            pytest.skip("junctions are Windows only")
        import _winapi
        _winapi.CreateJunction(rel.install, rel.staging)
    else:
        try:
            os.symlink(rel.install, rel.staging, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this account cannot make links")
    try:
        with pytest.raises(S.StageError, match="link or a junction"):
            rel.stage()
        assert snapshot(rel.install) == rel.before  # no lock, plan, or staged file inside it
        assert rel.fetched == []
    finally:
        if kind == "junction":
            os.rmdir(rel.staging)  # the junction only, never what it leads to


def test_a_plan_that_cannot_be_deleted_is_left_unusable(rel, monkeypatch):
    rel.stage()
    remove = A._remove

    def held_open(path):
        if os.path.basename(path) == A.PLAN:
            raise PermissionError(13, "in use by another process", path)
        remove(path)

    monkeypatch.setattr(A, "_remove", held_open)
    with pytest.raises(S.StageError, match="could not clear the staging folder"):
        rel.stage()
    assert os.path.isfile(os.path.join(rel.staging, A.PLAN))
    for name in (A.TREE, A.NEW, S.DOWNLOAD):
        assert not os.path.lexists(os.path.join(rel.staging, name)), name
    world = World()
    world.install, world.staging = rel.install, rel.staging
    result = A.Applier(rel.staging, FakePlatform(world), FAST, host="windows").run()
    assert result["status"] == "refused", result
    assert snapshot(rel.install) == rel.before


def test_an_unfinished_swap_is_left_for_the_helper(rel):
    old = os.path.join(rel.staging, A.OLD)
    _write(old, "PyReconstruct.exe", "the only copy of the install")

    with pytest.raises(S.StageError, match="has not finished"):
        rel.stage()
    assert os.path.isfile(os.path.join(old, "PyReconstruct.exe"))
    assert rel.fetched == []


# --- A stale plan never outlives a refusal -----------------------------------------

def test_a_release_with_no_version_clears_the_earlier_plan_first(rel):
    rel.stage()  # a plan from an earlier staging

    with pytest.raises(S.StageError, match="no version"):
        rel.stage(tag="nightly")
    rel.nothing_left()


def test_the_installed_helper_is_staged_beside_the_plan(rel):
    rel.stage()

    with open(os.path.join(rel.staging, S.HELPER, S.HELPER_EXE)) as f:
        assert f.read() == "the installed helper"


def test_an_install_without_its_helper_is_not_staged(rel):
    os.remove(os.path.join(rel.install, "_updater", S.HELPER_EXE))
    rel.before = snapshot(rel.install)

    with pytest.raises(S.StageError, match="no update helper"):
        rel.stage()
    rel.nothing_left()


# --- inplace.py: eligibility, staging for the quit, and the helper's start ----------

DEV_KEY = I.REGISTRY_KEYS["dev"]


def _manifest(enabled=True, min_client=OLD_V, version=NEW_V, **top):
    entry = {"inplace": {"enabled": enabled}, "min_client": min_client}
    return dict({"schema": 1, "tag": f"v{version}", "version": version, "flavor": "dev",
                 "platforms": {S.PLATFORM: entry, "macos-arm64": {"inplace": {"enabled": False}}}}, **top)


class Registry:
    """The HKCU uninstall entries an install_location lookup reads."""

    def __init__(self, entries):
        self.entries = entries

    def install_location(self, key):
        return self.entries.get(key)


class Dev:
    """A per-user Dev install, a release that turns in-place on for it, and a helper start recorder."""

    def __init__(self, tmp_path, monkeypatch, version=NEW_V):
        self.rel = Release(tmp_path, monkeypatch, flavor="dev", manifest=_manifest(version=version),
                           version=version)
        self.rel.publish(self.rel.files[self.rel.archive_name])
        self.install = I.Install(folder=self.rel.install, app_name="PyReconstruct Dev",
                                 flavor="dev", version=OLD_V)
        self.registry = Registry({DEV_KEY: self.rel.install + "\\"})  # as Inno Setup writes it
        self.started = []

    def stage(self, offered=None):
        return I.stage_for_quit(self.rel.release(), offered or self.rel.version, install=self.install,
                                platform=self.registry, trusted_keys=[TEST_PUB])

    def popen(self, argv, **kw):
        self.started.append((argv, kw))

    def nothing_staged(self):
        assert self.rel.archive_name not in self.rel.fetched
        assert not os.path.lexists(os.path.join(self.rel.staging, A.PLAN))
        assert snapshot(self.rel.install) == self.rel.before


@pytest.fixture
def dev(tmp_path, monkeypatch):
    return Dev(tmp_path, monkeypatch)


def test_an_eligible_dev_install_is_staged_for_the_quit(dev, tmp_path):
    pending = dev.stage()

    assert pending.version == NEW_V and pending.staging == dev.rel.staging
    plan = A.load_plan(os.path.join(dev.rel.staging, A.PLAN))
    assert plan["registry_key"] == DEV_KEY and plan["app_name"] == "PyReconstruct Dev"
    assert plan["pid"] == os.getpid()
    assert I.still_staged(pending)

    series = tmp_path / "work.jser"
    series.write_text("{}")
    argv = I.start_helper(pending, 4321, str(series), popen=dev.popen)

    helper = os.path.join(dev.rel.staging, S.HELPER, S.HELPER_EXE)
    assert argv == [helper, dev.rel.staging, "--pid", "4321", "--expect", NEW_V, "--open", str(series)]
    (started, kw), = dev.started
    assert started == argv and kw["cwd"] == dev.rel.staging  # never inside the install
    assert kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert kw["stdin"] is subprocess.DEVNULL


def _stable(dev):
    dev.install.flavor, dev.install.app_name = "stable", "PyReconstruct"


def _switched_off(dev):
    dev.rel.manifest = _manifest(enabled=False)
    dev.rel.publish(dev.rel.files[dev.rel.archive_name])


def _no_manifest(dev):
    dev.rel.manifest = None
    del dev.rel.files[I.MANIFEST]
    dev.rel.publish(dev.rel.files[dev.rel.archive_name])


def _manifest_changed_after_signing(dev):
    dev.rel.files[I.MANIFEST] = json.dumps(_manifest(min_client="0.1.0")).encode()


def _manifest_for_stable(dev):
    dev.rel.manifest = _manifest(flavor="stable")
    dev.rel.publish(dev.rel.files[dev.rel.archive_name])


def _client_too_old(dev):
    # what release_update_files.py writes today: the release's own version
    dev.rel.manifest = _manifest(min_client=NEW_V)
    dev.rel.publish(dev.rel.files[dev.rel.archive_name])


def _failed_before(dev):
    os.makedirs(dev.rel.staging, exist_ok=True)
    A.atomic_write_json(os.path.join(dev.rel.staging, A.FAILED_VERSIONS), {"versions": [NEW_V]})


def _put_off_three_times(dev):
    os.makedirs(dev.rel.staging, exist_ok=True)
    A.atomic_write_json(os.path.join(dev.rel.staging, A.DEFERRALS),
                        {"version": NEW_V, "count": A.MAX_DEFERRALS})


def _all_users(dev):
    dev.registry.entries = {}  # an all-users install writes HKLM, not HKCU


def _entry_for_another_folder(dev):
    dev.registry.entries = {DEV_KEY: r"C:\Users\someone\AppData\Local\Programs\PyReconstruct Dev"}


def _no_uninstaller(dev):
    os.remove(os.path.join(dev.rel.install, "unins000.exe"))
    dev.rel.before = snapshot(dev.rel.install)


def _no_helper(dev):
    os.remove(os.path.join(dev.rel.install, "_updater", S.HELPER_EXE))
    dev.rel.before = snapshot(dev.rel.install)


@pytest.mark.parametrize("make_it, reason", [
    (_stable, "not on for the stable build"),
    (_switched_off, "does not turn in-place updates on"),
    (_no_manifest, "no update manifest"),
    (_manifest_changed_after_signing, "does not match the signed checksum"),
    (_manifest_for_stable, "another release or build"),
    (_client_too_old, f"needs {NEW_V} or later"),
    (_failed_before, "failed in place before"),
    (_put_off_three_times, "put off 3 times"),
    (_all_users, "not the per-user install"),
    (_entry_for_another_folder, "not the per-user install"),
    (_no_uninstaller, "no uninstaller"),
    (_no_helper, "no update helper"),
])
def test_an_ineligible_install_or_release_stages_nothing(dev, make_it, reason):
    make_it(dev)

    with pytest.raises(I.NotEligible, match=reason):
        dev.stage()
    dev.nothing_staged()


def test_a_release_that_is_not_the_version_offered_stages_nothing(dev):
    with pytest.raises(I.NotEligible, match="not 1.24.1"):
        dev.stage(offered="1.24.1")
    dev.nothing_staged()


def test_only_a_frozen_windows_build_runs_in_place(monkeypatch, tmp_path):
    import PyReconstruct.modules.backend.updater.install_info as II
    monkeypatch.setattr(II, "install_kind", lambda: "frozen")
    monkeypatch.setattr(II, "arch_key", lambda: "x86_64")
    monkeypatch.setattr(II, "current_version_str", lambda: f"{OLD_V}+g0123abc")
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    monkeypatch.setattr(I.sys, "executable", str(tmp_path / "PyReconstruct Dev" / "PyReconstruct Dev.exe"))
    monkeypatch.setattr(II, "os_key", lambda: "windows")
    assert I.running_install() == I.Install(folder=str(tmp_path / "PyReconstruct Dev"),
                                            app_name="PyReconstruct Dev", flavor="dev", version=OLD_V)
    for host in ("macos", "linux"):
        monkeypatch.setattr(II, "os_key", lambda host=host: host)
        assert I.running_install() is None
    monkeypatch.setattr(II, "os_key", lambda: "windows")
    monkeypatch.setattr(II, "install_kind", lambda: "source")
    assert I.running_install() is None


def test_the_helper_starts_only_for_this_sessions_plan(dev):
    """An earlier plan on disk, even one for the same version and install, starts nothing."""
    pending = dev.stage()
    plan_path = os.path.join(dev.rel.staging, A.PLAN)
    earlier = dict(pending.plan, session="an earlier session")
    A.atomic_write_json(plan_path, earlier)  # the plan a failed clear could leave

    assert not I.still_staged(pending)
    assert I.start_helper(pending, 4321, popen=dev.popen) is None
    assert dev.started == []


def test_the_helper_starts_only_for_the_version_offered(dev):
    pending = dev.stage()
    pending.version = "1.24.1"  # what the dialog would have shown for another release

    assert I.start_helper(pending, 4321, popen=dev.popen) is None
    assert dev.started == []


def test_staging_again_retires_the_first_pending_update(dev):
    first = dev.stage()
    second = dev.stage()

    assert not I.still_staged(first) and I.still_staged(second)
    assert first.plan["session"] != second.plan["session"]


def test_a_plan_with_no_session_never_starts_the_helper(dev):
    pending = dev.stage()
    del pending.plan["session"]
    A.atomic_write_json(os.path.join(dev.rel.staging, A.PLAN), pending.plan)

    assert I.start_helper(pending, 4321, popen=dev.popen) is None


def test_a_staged_update_the_helper_cannot_find_starts_nothing(dev):
    pending = dev.stage()
    os.remove(I.helper_path(pending))

    assert I.start_helper(pending, 4321, popen=dev.popen) is None
    assert dev.started == []


def test_the_series_is_passed_only_when_it_is_a_file(dev, tmp_path):
    pending = dev.stage()

    assert "--open" not in I.helper_argv(pending, 1, str(tmp_path / "gone.jser"))
    assert "--open" not in I.helper_argv(pending, 1, "relative.jser")
    assert "--open" not in I.helper_argv(pending, 1, None)


# --- The helper puts in only the version the quitting window offered ------------------
# File > Restart opens a new window in the same process, while the closed
# window's restage at launch may still be running. That restage can write its
# plan after the new window checked its own and before the helper starts.

NEWER_V = "1.24.1"


@pytest.fixture
def two(tmp_path, monkeypatch):
    """The Dev install, with a release of NEW_V and a newer one of NEWER_V on the feed."""
    older, newer = Dev(tmp_path, monkeypatch), Dev(tmp_path, monkeypatch, version=NEWER_V)
    releases = {older.rel.tag: older.rel, newer.rel.tag: newer.rel}
    monkeypatch.setattr(U, "_open_download",
                        lambda url, timeout: releases[url.split("/")[-2]]._open(url, timeout))
    return older, newer


def _helper_from(argv, dev, monkeypatch):
    """Run the helper from the argv the app started it with. Returns its exit code and world."""
    w = World()
    w.install, w.staging = dev.rel.install, dev.rel.staging
    w.healthy[NEWER_V] = True
    monkeypatch.setattr(A, "default_platform", lambda: FakePlatform(w))
    monkeypatch.setattr(A, "default_timings", lambda host=None: replace(FAST, health=0.2))
    monkeypatch.setattr(A, "os_key", lambda: "windows")
    monkeypatch.chdir(dev.rel.staging)  # main() moves into staging; this puts the test's folder back
    assert argv[0] == I.helper_path(I.Pending(dev.rel.staging, {}, ""))
    code = A.main(argv[1:])
    # the release build ships its own helper; this test payload has none
    _write(dev.rel.install, "_updater/" + S.HELPER_EXE, "the installed helper", 0o755)
    return code, w


def _installed(dev):
    with open(os.path.join(dev.rel.install, "version.txt")) as f:
        return f.read()


def test_a_late_plan_for_another_version_is_not_put_in(two, monkeypatch):
    older, newer = two
    plan_path = os.path.join(newer.rel.staging, A.PLAN)
    pending = newer.stage()  # the new window: the user took the newer release by hand

    def late_restage(argv, **kw):
        older.stage()  # the closed window's restage of the older release lands now
        newer.started.append(argv)

    argv = I.start_helper(pending, 4321, popen=late_restage)
    assert argv == newer.started[0] and A.read_json(plan_path)["to_version"] == NEW_V
    staged = snapshot(newer.rel.staging)

    code, w = _helper_from(argv, newer, monkeypatch)

    assert code == 1 and _installed(newer) == OLD_V and w.launches == []
    assert snapshot(newer.rel.install) == newer.rel.before
    # nothing deleted and no result, so no installer offer and no deferral; only the log grew
    after = snapshot(newer.rel.staging)
    with open(os.path.join(newer.rel.staging, A.LOG), encoding="utf-8") as f:
        log = f.read()
    assert {k: v for k, v in after.items() if k != A.LOG} == staged
    assert f"expected {NEWER_V}, but {NEW_V} is staged" in log

    # the next quit after staging it again puts the newer release in
    pending = newer.stage()
    argv = I.start_helper(pending, 4321, popen=newer.popen)
    code, w = _helper_from(argv, newer, monkeypatch)
    assert code == 0 and _installed(newer) == NEWER_V


def test_a_late_plan_for_the_same_version_is_put_in(dev, monkeypatch):
    """Another session's complete plan for the offered version, same process and install: accepted."""
    pending = dev.stage()

    argv = I.start_helper(pending, 4321, popen=lambda argv, **kw: dev.stage())
    assert not I.still_staged(pending)  # the late restage replaced the plan the window checked

    code, w = _helper_from(argv, dev, monkeypatch)
    assert code == 0 and _installed(dev) == NEW_V


# --- A run a helper left part way is finished at the next quit ------------------------

def _left_part_way(dev, **changes):
    """Stage, then leave the journal a helper killed part way through its run would leave."""
    pending = dev.stage()
    state = {"format": A.FORMAT, "status": "running", "step": "health", "phase": "begin",
             "plan": dict(pending.plan), "launched_pid": 999999}
    state.update(changes)
    A.atomic_write_json(os.path.join(dev.rel.staging, A.STATE), state)
    return pending


def test_a_quit_starts_the_helper_to_finish_a_run_left_part_way(dev):
    """The next quit finishes or undoes it, so the journal never blocks later updates."""
    pending = _left_part_way(dev)
    with pytest.raises(S.StageError, match="not finished"):
        dev.stage()

    argv = I.start_recovery(4321, install=dev.install, popen=dev.popen)

    assert argv == [I.helper_path(pending), dev.rel.staging, "--pid", "4321", "--recover"]
    (started, kw), = dev.started
    assert started == argv and kw["cwd"] == dev.rel.staging
    # the app that quits ran from the install: what it reports decides whether the update stays
    report = A.read_json(os.path.join(dev.rel.staging, A.HEALTH))
    assert report["version"] == OLD_V and report["pid"] == os.getpid()


def _finished(dev):
    pending = dev.stage()
    A.atomic_write_json(os.path.join(dev.rel.staging, A.STATE),
                        {"format": A.FORMAT, "status": "done", "plan": dict(pending.plan)})


def _another_version(dev):
    _left_part_way(dev)
    dev.install.version = "1.25.0"  # the installer put another version in since


def _another_install(dev):
    pending = _left_part_way(dev)
    plan = dict(pending.plan, install=os.path.join(os.path.dirname(dev.rel.install), "Other"))
    A.atomic_write_json(os.path.join(dev.rel.staging, A.STATE),
                        {"format": A.FORMAT, "status": "running", "plan": plan})


def _stable_flavor(dev):
    _left_part_way(dev)
    dev.install.flavor = "stable"


def _no_staged_helper(dev):
    pending = _left_part_way(dev)
    os.remove(I.helper_path(pending))


@pytest.mark.parametrize("make_it", [
    lambda dev: dev.stage(), _finished, _another_version, _another_install, _stable_flavor,
    _no_staged_helper,
], ids=["staged-only", "finished", "another-version", "another-install", "stable", "no-helper"])
def test_a_quit_with_nothing_left_part_way_starts_no_helper(dev, make_it):
    make_it(dev)

    assert I.start_recovery(4321, install=dev.install, popen=dev.popen) is None
    assert dev.started == []
    assert not os.path.exists(os.path.join(dev.rel.staging, A.HEALTH))


def test_a_quit_while_a_helper_runs_leaves_it_alone(dev):
    _left_part_way(dev)
    held = A.take_lock(dev.rel.staging)
    try:
        assert I.start_recovery(4321, install=dev.install, popen=dev.popen) is None
    finally:
        A.release_lock(held)
    assert dev.started == []
    assert not os.path.exists(os.path.join(dev.rel.staging, A.HEALTH))


# --- A copy a finished run could not delete ----------------------------------------
# Windows can hold a file for a moment at cleanup, so a run that ended well can
# leave old/ or rejected/ behind. Staging never deletes either: it refuses, and
# the dialog downloads the installer.

def _locked(monkeypatch, *names):
    """Make ``_remove`` fail on these staging entries, as Windows does while a scanner holds a file."""
    real = A._remove
    held = {os.path.normcase(os.path.abspath(n)) for n in names}

    def remove(path):
        if os.path.normcase(os.path.abspath(path)) in held:
            raise PermissionError(errno.EACCES, "The process cannot access the file", path)
        real(path)
    monkeypatch.setattr(A, "_remove", remove)
    return lambda: monkeypatch.setattr(A, "_remove", real)


def _run_helper(dev, healthy=True):
    w = World()
    w.install, w.staging = dev.rel.install, dev.rel.staging
    w.healthy[NEW_V] = healthy
    result = A.Applier(dev.rel.staging, FakePlatform(w), replace(FAST, health=0.2), host="windows").run()
    # the release build ships its own helper; this test payload has none
    _write(dev.rel.install, "_updater/" + S.HELPER_EXE, "the installed helper", 0o755)
    return result


def _journal(dev):
    return A.read_json(os.path.join(dev.rel.staging, A.STATE))


@pytest.mark.parametrize("result, leftover, healthy", [
    ("updated", A.OLD, True),
    ("rolled_back", A.REJECTED, False),
], ids=["backup-after-update", "rejected-after-rollback"])
def test_a_copy_a_finished_run_left_keeps_later_updates_on_the_installer(
        dev, monkeypatch, result, leftover, healthy):
    """The install may be damaged since, and that copy may be the good one: staging keeps it."""
    dev.stage()
    copy = os.path.join(dev.rel.staging, leftover)
    unlock = _locked(monkeypatch, copy)
    assert _run_helper(dev, healthy)["status"] == result
    unlock()
    assert _journal(dev)["status"] == "done" and _journal(dev)["result"] == result
    os.remove(os.path.join(dev.rel.install, "_internal", "base_library.zip"))
    journal, kept, installed = _journal(dev), snapshot(copy), snapshot(dev.rel.install)
    dev.rel.fetched.clear()

    # staged straight, as for a later release: a rollback keeps this version off in-place
    for _ in range(2):
        with pytest.raises(S.StageError, match="earlier update has not finished"):
            dev.rel.stage()  # the dialog downloads the installer instead
        assert snapshot(copy) == kept and snapshot(dev.rel.install) == installed
        assert _journal(dev) == journal
        assert dev.rel.fetched == []
    assert dev.started == []


def _done(dev, result, installed, **plan):
    pending = dev.stage()
    A.atomic_write_json(os.path.join(dev.rel.staging, A.STATE), {
        "format": A.FORMAT, "status": "done", "result": result, "installed": installed,
        "plan": dict(pending.plan, **plan)})


def _backup_is_a_link_to_the_install(dev):
    _done(dev, "updated", "new")
    old = os.path.join(dev.rel.staging, A.OLD)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(dev.rel.install, old)
        return
    try:
        os.symlink(dev.rel.install, old, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot make links")


def _backup_after_a_stuck_run(dev):
    _done(dev, "stuck", None)
    _write(os.path.join(dev.rel.staging, A.OLD), "PyReconstruct Dev.exe", "the only copy")


def _backup_after_a_rollback(dev):
    _done(dev, "rolled_back", "old")
    _write(os.path.join(dev.rel.staging, A.OLD), "PyReconstruct Dev.exe", "the only copy")


def _backup_for_another_install(dev):
    _done(dev, "updated", "new", install=os.path.join(os.path.dirname(dev.rel.install), "Other"))
    _write(os.path.join(dev.rel.staging, A.OLD), "PyReconstruct Dev.exe", "the only copy")


def _backup_with_no_journal(dev):
    dev.stage()
    _write(os.path.join(dev.rel.staging, A.OLD), "PyReconstruct Dev.exe", "the only copy")


def _backup_after_an_update(dev):
    _done(dev, "updated", "new")
    _write(os.path.join(dev.rel.staging, A.OLD), "PyReconstruct Dev.exe", "the version before")


def _rejected_after_a_rollback(dev):
    _done(dev, "rolled_back", "old")
    _write(os.path.join(dev.rel.staging, A.REJECTED), "PyReconstruct Dev.exe", "the version that failed")
    return A.REJECTED


@pytest.mark.parametrize("make_it", [
    _backup_is_a_link_to_the_install, _backup_after_a_stuck_run, _backup_after_a_rollback,
    _backup_for_another_install, _backup_with_no_journal, _backup_after_an_update,
    _rejected_after_a_rollback,
], ids=["link-to-install", "stuck", "old-after-rollback", "another-install", "no-journal",
        "old-after-update", "rejected-after-rollback"])
def test_staging_never_clears_a_copy_that_may_be_the_only_one(dev, make_it):
    old = os.path.join(dev.rel.staging, make_it(dev) or A.OLD)
    kept = snapshot(old)
    try:
        with pytest.raises(S.StageError, match="earlier update"):
            dev.stage()
        assert snapshot(dev.rel.install) == dev.rel.before
        assert os.path.lexists(old) and snapshot(old) == kept
        assert dev.started == []
    finally:
        if os.name == "nt" and make_it is _backup_is_a_link_to_the_install:
            os.rmdir(old)  # the junction only, never what it leads to


# --- macOS: the notarized dmg is the payload, and the installed app is the helper ----

MAC = "macos-arm64"
DEV_ID = I.BUNDLE_IDS["dev"]
MAC_APP = "PyReconstruct Dev"


def _tar_folder(root):
    """An xz tar of ``root``'s contents: the stand-in for a dmg off macOS."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        for name in os.listdir(root):
            tar.add(os.path.join(root, name), arcname=name)
    return buf.getvalue()


def _mac_manifest(enabled=True):
    return {"schema": 1, "tag": f"v{NEW_V}", "version": NEW_V, "flavor": "dev",
            "platforms": {S.PLATFORM: {"inplace": {"enabled": False}},
                          MAC: {"inplace": {"enabled": enabled}, "min_client": OLD_V}}}


class MacDev:
    """A Dev bundle in a fake Applications folder, a release whose dmg holds a newer one, and recorders.

    Off macOS the dmg is a tar the fake attach unpacks; ``codesign`` is a
    recorder unless ``real`` is set, when the dmg, hdiutil, ditto, and
    codesign are all real (macOS only).
    """

    def __init__(self, tmp_path, monkeypatch, parent=None, real=False):
        from test_updater_apply import macos_tree
        self.tmp_path = tmp_path
        self.folder = str(parent or tmp_path / "Applications")
        self.install = os.path.join(self.folder, f"{MAC_APP}.app")
        macos_tree(self.install, OLD_V, links=os.name != "nt", app_name=MAC_APP, bundle_id=DEV_ID)
        self.staging = S.staging_dir(self.install, MAC_APP)
        self.dmg_name, self.tree_name = S.payload_names(NEW_V, "dev", MAC)
        build = tmp_path / "build"
        self.build = str(build / f"{MAC_APP}.app")
        macos_tree(self.build, NEW_V, links=os.name != "nt", app_name=MAC_APP, bundle_id=DEV_ID)
        if real:
            _sign_ad_hoc(self.build)
            # what the release dmg carries: Finder flags on the bundle, which codesign's
            # strict check refuses, and quarantine, as a downloaded dmg passes it on
            subprocess.run(["xattr", "-wx", "com.apple.FinderInfo", "00" * 8 + "0400" + "00" * 22,
                            self.build], check=True, timeout=60)
            subprocess.run(["xattr", "-w", "com.apple.quarantine", "0081;00000000;Safari;",
                            os.path.join(self.build, "Contents", "Info.plist")], check=True, timeout=60)
            dmg = tmp_path / "release.dmg"
            subprocess.run(["hdiutil", "create", "-quiet", "-srcfolder", str(build), "-volname", "Update",
                            "-fs", "HFS+", "-format", "UDZO", str(dmg)], check=True, timeout=300)
            payload = dmg.read_bytes()
        else:
            payload = _tar_folder(build)
        self.tree = A.build_tree(self.build, version=NEW_V, flavor="dev", app_name=MAC_APP,
                                 bundle_id=DEV_ID, platform=MAC)
        self.manifest = _mac_manifest()
        self.files = {self.dmg_name: payload}
        self.publish()
        self.before = snapshot(self.install)
        self.fetched, self.attached, self.signatures = [], [], []
        self.signature_error = {}
        self.started = []
        self.install_info = I.Install(folder=self.install, app_name=MAC_APP, flavor="dev",
                                      version=OLD_V, platform=MAC, bundle_id=DEV_ID)
        monkeypatch.setattr(U, "_open_download", self._open)
        if not real:
            monkeypatch.setattr(S, "_copy_from_dmg", self._copy_from_dmg)
            monkeypatch.setattr(S, "check_code_signature", self._codesign)

    def publish(self, tree=None):
        self.files[self.tree_name] = json.dumps(tree or self.tree).encode()
        self.files[I.MANIFEST] = json.dumps(self.manifest).encode()
        sums = "".join(f"{hashlib.sha256(self.files[n]).hexdigest()}  {n}\n" for n in sorted(self.files)
                       if n not in ("SHA256SUMS", "SHA256SUMS.minisig")).encode()
        self.files["SHA256SUMS"] = sums
        self.files["SHA256SUMS.minisig"] = make_sig(sums, comment=f"tag:v{NEW_V} file:SHA256SUMS")

    def _open(self, url, timeout):
        U._check_download_url(url)
        name = url.rsplit("/", 1)[1]
        self.fetched.append(name)
        resp = io.BytesIO(self.files[name])
        resp.headers = {"Content-Length": str(len(self.files[name]))}
        return resp

    def release(self):
        return {"tag_name": f"v{NEW_V}", "assets": [
            {"name": n, "size": len(d), "browser_download_url": f"https://github.com/o/r/releases/download/v{NEW_V}/{n}"}
            for n, d in self.files.items()]}

    def _copy_from_dmg(self, dmg, mount, bundle, dest):
        self.attached.append((dmg, mount, bundle))
        with tarfile.open(dmg, "r:xz") as tar:
            tar.extractall(self.tmp_path / "attached", filter="fully_trusted")
        shutil.copytree(self.tmp_path / "attached" / bundle, dest, symlinks=True)

    def _codesign(self, path, requirement, deep=True):
        self.signatures.append((path, requirement, deep))
        if path in self.signature_error:
            raise S.StageError(self.signature_error[path])

    def stage(self, **kw):
        return I.stage_for_quit(self.release(), NEW_V, install=self.install_info,
                                trusted_keys=[TEST_PUB], **kw)

    def popen(self, argv, **kw):
        self.started.append((argv, kw))

    def nothing_staged(self):
        assert self.dmg_name not in self.fetched
        assert not os.path.lexists(os.path.join(self.staging, A.PLAN))
        assert snapshot(self.install) == self.before

    def nothing_left(self):
        assert snapshot(self.install) == self.before
        for name in (A.PLAN, A.TREE, A.NEW, A.NEW_APP, S.DOWNLOAD):
            assert not os.path.lexists(os.path.join(self.staging, name)), name


def _sign_ad_hoc(bundle):
    """Give a fake bundle a real program and an ad-hoc signature with the Dev bundle id.

    The fake framework goes first: codesign signs a framework only in a real one's layout.
    """
    shutil.rmtree(os.path.join(bundle, "Contents", "Frameworks"))
    exe = os.path.join(bundle, "Contents", "MacOS", MAC_APP)
    shutil.copyfile("/usr/bin/true", exe)  # not copy2: the system file's flags do not copy
    os.chmod(exe, 0o755)
    subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", DEV_ID, bundle],
                   check=True, capture_output=True, timeout=120)


@pytest.fixture
def mac(tmp_path, monkeypatch):
    return MacDev(tmp_path, monkeypatch)


def test_a_macos_dev_bundle_is_staged_as_new_app_and_the_app_is_its_own_helper(mac, tmp_path):
    pending = mac.stage()

    plan = A.load_plan(os.path.join(mac.staging, A.PLAN))
    assert (plan["platform"], plan["install"], plan["bundle_id"], plan["exe"]) == (
        "macos", mac.install, DEV_ID, f"Contents/MacOS/{MAC_APP}")
    assert plan["carry"] == [] and plan["registry_key"] is None and plan["pid"] == os.getpid()
    new = os.path.join(mac.staging, A.NEW_APP)
    assert snapshot(new) == snapshot(mac.build)
    assert not os.path.lexists(os.path.join(mac.staging, S.DOWNLOAD))
    assert not os.path.lexists(os.path.join(mac.staging, S.HELPER))  # nothing is copied for it
    requirement = S.code_requirement(DEV_ID)
    assert 'leaf[subject.OU] = "57Z336NM5P"' in requirement and f'identifier "{DEV_ID}"' in requirement
    assert mac.signatures == [(mac.install, requirement, False), (new, requirement, True)]
    assert I.still_staged(pending)

    series = tmp_path / "work.jser"
    series.write_text("{}")
    argv = I.start_helper(pending, 4321, str(series), popen=mac.popen)

    program = os.path.join(mac.install, "Contents", "MacOS", MAC_APP)
    assert argv == [program, A.APPLY_ARG, mac.staging, "--pid", "4321", "--expect", NEW_V,
                    "--open", str(series)]
    (started, kw), = mac.started
    assert started == argv and kw["cwd"] == mac.staging and kw["start_new_session"] is True
    assert kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"

    w = World()
    w.install, w.staging = mac.install, mac.staging
    assert A.Applier(mac.staging, FakePlatform(w), FAST, host="macos").run()["status"] == "updated"
    assert snapshot(mac.install) == snapshot(mac.build)


def _translocated(mac, monkeypatch, tmp_path):
    return MacDev(tmp_path / "t", monkeypatch,
                  parent=tmp_path / "t" / "private" / "var" / "folders" / "AppTranslocation" / "1A2B" / "d")


def _on_a_volume(mac, monkeypatch, tmp_path):
    real = os.path.realpath
    monkeypatch.setattr(os.path, "realpath",
                        lambda p, **kw: "/Volumes/PyReconstruct Dev/" + os.path.basename(p)
                        if p == mac.install else real(p, **kw))


def _not_ours(mac, monkeypatch, tmp_path):
    mac.signature_error[mac.install] = "the app's signature is not ours: test-requirement failed"


def _other_bundle_id(mac, monkeypatch, tmp_path):
    with open(os.path.join(mac.install, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleIdentifier": I.BUNDLE_IDS["stable"], "CFBundleExecutable": MAC_APP}, f)
    mac.before = snapshot(mac.install)


def _a_link(mac, monkeypatch, tmp_path):
    elsewhere = os.path.join(str(tmp_path), "Elsewhere.app")
    os.rename(mac.install, elsewhere)
    os.symlink(elsewhere, mac.install)
    mac.before = snapshot(mac.install)


def _read_only_folder(mac, monkeypatch, tmp_path):
    os.chmod(mac.folder, 0o555)


def _stable(mac, monkeypatch, tmp_path):
    mac.install_info.flavor = "stable"


def _switched_off(mac, monkeypatch, tmp_path):
    mac.manifest = _mac_manifest(enabled=False)
    mac.publish()


@pytest.mark.parametrize("make_it", [
    _translocated, _on_a_volume, _not_ours, _other_bundle_id, _a_link, _read_only_folder, _stable,
    _switched_off,
], ids=["translocated", "on-a-volume", "not-our-team", "other-bundle-id", "link", "read-only-folder",
        "stable", "switched-off"])
def test_an_ineligible_macos_app_downloads_the_installer_instead(mac, monkeypatch, tmp_path, make_it):
    if make_it in (_a_link, _read_only_folder) and os.name == "nt":
        pytest.skip("POSIX links and modes")
    if make_it is _read_only_folder and hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root writes anywhere")
    mac = make_it(mac, monkeypatch, tmp_path) or mac
    try:
        with pytest.raises(I.NotEligible):
            mac.stage()
        mac.nothing_staged()
    finally:
        os.chmod(mac.folder, 0o755)


@pytest.mark.parametrize("problem", ["codesign", "tree"])
def test_a_staged_bundle_that_fails_a_check_leaves_nothing(mac, problem):
    if problem == "codesign":
        mac.signature_error[os.path.join(mac.staging, A.NEW_APP)] = "the app's signature is not ours: x"
    else:
        files = [dict(e, sha256="0" * 64) if e["path"] == "Contents/Info.plist" else e
                 for e in mac.tree["files"]]
        mac.publish(dict(mac.tree, files=files))
    with pytest.raises(S.StageError, match="not ours" if problem == "codesign" else "does not match tree.json"):
        mac.stage()
    mac.nothing_left()


def test_a_tree_for_another_bundle_id_is_not_staged(mac):
    mac.publish(dict(mac.tree, bundle_id=I.BUNDLE_IDS["stable"]))
    with pytest.raises(S.StageError, match="another build"):
        mac.stage()
    assert mac.dmg_name not in mac.fetched
    mac.nothing_left()


def test_a_macos_quit_with_nothing_staged_recovers_with_the_installed_app(mac):
    pending = mac.stage()
    A.atomic_write_json(os.path.join(mac.staging, A.STATE),
                        {"format": A.FORMAT, "status": "running", "step": "health", "phase": "begin",
                         "plan": dict(pending.plan)})

    argv = I.start_recovery(4321, install=mac.install_info, popen=mac.popen)

    assert argv == [os.path.join(mac.install, "Contents", "MacOS", MAC_APP), A.APPLY_ARG, mac.staging,
                    "--pid", "4321", "--recover"]
    assert A.read_json(os.path.join(mac.staging, A.HEALTH))["version"] == OLD_V


def test_a_macos_plan_whose_bundle_is_gone_starts_nothing(mac):
    pending = mac.stage()
    shutil.rmtree(os.path.join(mac.staging, A.NEW_APP))

    assert I.still_staged(pending) is False
    assert I.start_helper(pending, 4321, popen=mac.popen) is None and mac.started == []


@pytest.mark.parametrize("exe, expected", [
    ("Applications/PyReconstruct Dev.app/Contents/MacOS/PyReconstruct Dev", "Applications/PyReconstruct Dev.app"),
    ("Applications/PyReconstruct Dev/PyReconstruct Dev", None),
    ("Applications/Other.app/Contents/MacOS/PyReconstruct Dev", None),
])
def test_the_running_macos_install_is_the_bundle_that_holds_the_program(tmp_path, monkeypatch, exe, expected):
    from PyReconstruct.modules.backend.updater import install_info
    monkeypatch.setattr(install_info, "install_kind", lambda: "frozen")
    monkeypatch.setattr(install_info, "os_key", lambda: "macos")
    monkeypatch.setattr(install_info, "arch_key", lambda: "arm64")
    monkeypatch.setattr(install_info, "current_version_str", lambda: OLD_V + "+g1a2b3c4")
    monkeypatch.setattr(sys, "executable", str(tmp_path / exe))
    monkeypatch.setenv("PYRECON_APP_NAME", MAC_APP)

    found = I.running_install()

    if expected is None:
        assert found is None
    else:
        assert found == I.Install(folder=str(tmp_path / expected), app_name=MAC_APP, flavor="dev",
                                  version=OLD_V, platform=MAC, bundle_id=DEV_ID)


needs_macos = pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil, ditto, and codesign")


@needs_macos
def test_a_real_dmg_is_attached_copied_checked_and_detached(tmp_path, monkeypatch):
    mac = MacDev(tmp_path, monkeypatch, real=True)
    plan = S.stage_update(mac.release(), install=mac.install, app_name=MAC_APP, flavor="dev",
                          from_version=OLD_V, trusted_keys=[TEST_PUB], platform=MAC, bundle_id=DEV_ID,
                          requirement=f'identifier "{DEV_ID}"')

    new = os.path.join(mac.staging, A.NEW_APP)
    A.verify_tree(new, mac.tree)
    assert plan["exe"] == f"Contents/MacOS/{MAC_APP}"
    assert not os.path.lexists(os.path.join(mac.staging, S.DOWNLOAD))
    assert not os.path.ismount(os.path.join(mac.staging, S.DOWNLOAD, S.MOUNT))
    xattrs = subprocess.run(["xattr", "-r", new], capture_output=True, text=True).stdout
    assert "com.apple.FinderInfo" not in xattrs and "com.apple.quarantine" not in xattrs


@needs_macos
def test_a_real_bundle_not_signed_by_our_team_is_refused(tmp_path, monkeypatch):
    mac = MacDev(tmp_path, monkeypatch, real=True)
    with pytest.raises(S.StageError, match="not ours"):
        S.stage_update(mac.release(), install=mac.install, app_name=MAC_APP, flavor="dev",
                       from_version=OLD_V, trusted_keys=[TEST_PUB], platform=MAC, bundle_id=DEV_ID)
    mac.nothing_left()
    mounts = subprocess.run(["mount"], capture_output=True, text=True).stdout
    assert mac.staging not in mounts
