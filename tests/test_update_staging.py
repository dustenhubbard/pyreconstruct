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
import tarfile

import pytest

from PyReconstruct.modules.backend.updater import apply as A
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

    def __init__(self, tmp_path, monkeypatch):
        self.install = str(tmp_path / "Programs" / "PyReconstruct")
        windows_tree(self.install, OLD_V)
        _write(self.install, "unins000.exe", "inno uninstaller", 0o755)
        self.staging = S.staging_dir(self.install, "PyReconstruct")
        build = str(tmp_path / "build" / "PyReconstruct")
        windows_tree(build, NEW_V)
        self.tree = A.build_tree(build, version=NEW_V, flavor="stable", app_name="PyReconstruct",
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
        self.files[ARCHIVE] = archive
        self.files[TREE] = json.dumps(tree or self.tree).encode()
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

    def stage(self):
        release = {"tag_name": TAG, "assets": [
            {"name": n, "size": self.sizes[n],
             "browser_download_url": f"https://github.com/o/r/releases/download/{TAG}/{n}"}
            for n in self.files]}
        return S.stage_update(release, install=self.install, app_name="PyReconstruct",
                              flavor="stable", from_version=OLD_V, trusted_keys=[TEST_PUB])

    def nothing_left(self):
        assert snapshot(self.install) == self.before
        for name in (A.PLAN, A.TREE, A.NEW, S.DOWNLOAD):
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
