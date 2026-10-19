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
import subprocess
import tarfile

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

    def __init__(self, tmp_path, monkeypatch, flavor="stable", manifest=None):
        self.flavor = flavor
        self.app_name = "PyReconstruct Dev" if flavor == "dev" else "PyReconstruct"
        self.archive_name, self.tree_name = S.payload_names(NEW_V, flavor)
        self.manifest = manifest  # update-manifest.json, published and signed when set
        self.install = str(tmp_path / "Programs" / self.app_name)
        windows_tree(self.install, OLD_V, self.app_name)
        _write(self.install, "unins000.exe", "inno uninstaller", 0o755)
        _write(self.install, "_updater/" + S.HELPER_EXE, "the installed helper", 0o755)
        self.staging = S.staging_dir(self.install, self.app_name)
        build = str(tmp_path / "build" / self.app_name)
        windows_tree(build, NEW_V, self.app_name)
        self.tree = A.build_tree(build, version=NEW_V, flavor=flavor, app_name=self.app_name,
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
        self.files["SHA256SUMS.minisig"] = make_sig(sums, comment=f"tag:{TAG} file:SHA256SUMS")
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

    def release(self, tag=TAG):
        return {"tag_name": tag, "assets": [
            {"name": n, "size": self.sizes[n],
             "browser_download_url": f"https://github.com/o/r/releases/download/{TAG}/{n}"}
            for n in self.files]}

    def stage(self, tag=TAG):
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


def _manifest(enabled=True, min_client=OLD_V, **top):
    entry = {"inplace": {"enabled": enabled}, "min_client": min_client}
    return dict({"schema": 1, "tag": TAG, "version": NEW_V, "flavor": "dev",
                 "platforms": {S.PLATFORM: entry, "macos-arm64": {"inplace": {"enabled": False}}}}, **top)


class Registry:
    """The HKCU uninstall entries an install_location lookup reads."""

    def __init__(self, entries):
        self.entries = entries

    def install_location(self, key):
        return self.entries.get(key)


class Dev:
    """A per-user Dev install, a release that turns in-place on for it, and a helper start recorder."""

    def __init__(self, tmp_path, monkeypatch):
        self.rel = Release(tmp_path, monkeypatch, flavor="dev", manifest=_manifest())
        self.rel.publish(self.rel.files[self.rel.archive_name])
        self.install = I.Install(folder=self.rel.install, app_name="PyReconstruct Dev",
                                 flavor="dev", version=OLD_V)
        self.registry = Registry({DEV_KEY: self.rel.install + "\\"})  # as Inno Setup writes it
        self.started = []

    def stage(self, offered=NEW_V):
        return I.stage_for_quit(self.rel.release(), offered, install=self.install,
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
    assert argv == [helper, dev.rel.staging, "--pid", "4321", "--open", str(series)]
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
