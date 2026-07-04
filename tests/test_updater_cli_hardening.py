"""Hardening tests for the updater/CLI self-update surface.

Pins the fixes for:
- H7: dismissing UpdateDialog (Esc/X) mid-download defers the reject until the
  worker unwinds and never arms the pending-installer hand-off.
- H9: cli.update() targets the fork, uses this interpreter's pip, never
  uninstalls first, and redirects .sh-installer venv installs to the installer.
- M7: frozen builds hard-refuse an unverifiable (checksum-less) download.
- M10: repo_info reads the normalized dist-info; cli.update treats the
  'PyReconstruct' fallback branch as main and validates before touching pip.
- L9: download URLs (and redirects) must be https on github-owned hosts.
"""
import json
import subprocess
import sys
import urllib.request
from types import SimpleNamespace

import pytest

from PyReconstruct import cli
from PyReconstruct.modules.backend.updater import updater as U


# ---- L9: download URL allowlist ----------------------------------------------

@pytest.mark.parametrize("url", [
    "https://github.com/dustenhubbard/PyReconstruct/releases/download/v1/x.exe",
    "https://objects.githubusercontent.com/some/asset",
    "https://api.github.com/repos/x/y/releases",
])
def test_check_download_url_accepts_github_https(url):
    U._check_download_url(url)  # must not raise

@pytest.mark.parametrize("url", [
    "http://github.com/x",                      # https downgrade
    "https://evil.com/x",                       # off-host
    "https://github.com.evil.com/x",            # suffix spoof
    "ftp://github.com/x",
    "",
    None,
])
def test_check_download_url_rejects_offlist(url):
    with pytest.raises(RuntimeError):
        U._check_download_url(url)

def test_redirect_handler_rejects_offlist_redirect():
    handler = U._AllowlistedRedirectHandler()
    req = urllib.request.Request("https://github.com/x")
    with pytest.raises(RuntimeError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://evil.com/payload")

def test_redirect_handler_allows_github_redirect():
    handler = U._AllowlistedRedirectHandler()
    req = urllib.request.Request("https://github.com/x")
    new = handler.redirect_request(
        req, None, 302, "Found", {}, "https://objects.githubusercontent.com/asset")
    assert new is not None and "githubusercontent.com" in new.full_url

def test_download_asset_refuses_bad_url_without_network(tmp_path):
    dest = tmp_path / "x.exe"
    with pytest.raises(RuntimeError):
        U.download_asset("http://evil.com/x.exe", dest)
    assert not dest.exists()


# ---- H9/M10: cli.update ------------------------------------------------------

@pytest.fixture
def no_marker_prefix(tmp_path, monkeypatch):
    """Point sys.prefix at a venv-like dir with NO installer marker."""
    venv = tmp_path / "app" / "venv"
    venv.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(venv))
    return tmp_path / "app"

def _forbid_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"subprocess.run must not be called: {a}")
    monkeypatch.setattr(cli.subprocess, "run", boom)

def test_update_redirects_sh_installer_venv(no_marker_prefix, monkeypatch):
    (no_marker_prefix / ".pyreconstruct-install").touch()
    _forbid_subprocess(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cli.update()
    assert "install.sh" in str(e.value)

def test_update_targets_fork_with_this_pythons_pip_and_no_uninstall(no_marker_prefix, monkeypatch):
    monkeypatch.setattr(cli, "_repo_info", lambda: {"branch": "PyReconstruct", "commit": "1.20.0"})
    validated = []
    monkeypatch.setattr(cli, "validate_branch", lambda b: validated.append(b) or True)
    calls = []
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=0))

    cli.update()

    assert validated == ["main"]  # 'PyReconstruct' fallback treated like unknown
    assert len(calls) == 1        # a single install call, no pre-uninstall
    cmd = calls[0]
    assert cmd[:6] == [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall"]
    assert cmd[-1] == f"git+https://github.com/{U.GITHUB_REPO}@main"
    assert not any("uninstall" in str(part) for part in cmd)

def test_update_validates_branch_before_touching_pip(no_marker_prefix, monkeypatch):
    monkeypatch.setattr(cli, "validate_branch", lambda b: False)
    _forbid_subprocess(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cli.update("no-such-branch")
    assert "nothing was changed" in str(e.value)

def test_update_pip_failure_raises_and_never_uninstalled(no_marker_prefix, monkeypatch):
    monkeypatch.setattr(cli, "validate_branch", lambda b: True)
    calls = []
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError):
        cli.update("main")
    assert len(calls) == 1 and "uninstall" not in " ".join(map(str, calls[0]))

def test_validate_branch_queries_the_fork(monkeypatch):
    seen = {}
    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout="abc\trefs/heads/main\n", returncode=0)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.validate_branch("main") is True
    assert seen["cmd"][0:2] == ["git", "ls-remote"]
    assert f"https://github.com/{U.GITHUB_REPO}" in seen["cmd"]


# ---- M10: repo_info reads the normalized dist-info ----------------------------

def test_repo_info_reads_dist_info_via_importlib_metadata(monkeypatch):
    # the constants package shadows the module name with the repo_info dict,
    # so fetch the module itself via importlib
    from importlib import import_module
    RI = import_module("PyReconstruct.modules.constants.repo_info")
    import importlib.metadata as md

    # defeat the git-checkout path (tests run inside a git worktree)
    try:
        import git
        monkeypatch.setattr(git, "Repo",
                            lambda *a, **k: (_ for _ in ()).throw(Exception("not a repo")))
    except ImportError:
        pass

    class FakeDist:
        def read_text(self, name):
            assert name == "direct_url.json"
            return json.dumps({
                "url": "https://github.com/dustenhubbard/PyReconstruct",
                "vcs_info": {"vcs": "git", "commit_id": "a" * 40,
                             "requested_revision": "feature-x"},
            })

    def fake_distribution(name):
        assert name.lower() == "pyreconstruct"  # normalized lookup, no case-glob
        return FakeDist()

    monkeypatch.setattr(md, "distribution", fake_distribution)
    info = RI.returnRepoInfo()
    assert info == {"branch": "feature-x", "commit": "a" * 7}


# ---- H7/M7: UpdateDialog lifecycle --------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])

def _make_dialog(qapp):
    from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog
    info = {
        "asset": {"name": "PyReconstruct-9.9-Linux-x86_64.AppImage",
                  "browser_download_url": "https://github.com/x", "size": 1024},
        "release": {"body": "notes"},
        "status": "newer",
        "remote_version": "9.9",
        "local_version": "1.0",
    }
    dlg = UpdateDialog(None, info, "release")
    dlg._parent = SimpleNamespace(_updater_pool=object(), _pending_installer=None,
                                  _pending_update_dir=None)
    return dlg

def test_reject_mid_download_defers_until_cancelled(qapp):
    from PyReconstruct.modules.backend.updater.updater import UpdateCancelled
    dlg = _make_dialog(qapp)
    rejected = []
    dlg.rejected.connect(lambda: rejected.append(True))

    dlg._pool = object()  # download in flight
    dlg.reject()          # Esc / X / Cancel
    assert dlg._cancel.is_set()
    assert not rejected   # not dismissed yet -- waiting for the worker

    # worker unwinds with UpdateCancelled -> now the reject really happens
    dlg._on_error((UpdateCancelled, UpdateCancelled(), None))
    assert rejected
    assert dlg._parent._updater_pool is None
    assert dlg._parent._pending_installer is None

def test_downloaded_after_cancel_never_arms_installer(qapp, tmp_path):
    dlg = _make_dialog(qapp)
    dlg._pool = object()
    dlg._cancel.set()  # user backed out; download won the race anyway
    tmpdir = tmp_path / "dl"
    tmpdir.mkdir()
    dest = tmpdir / "installer.AppImage"
    dest.write_bytes(b"x")
    dlg._tmpdir = str(tmpdir)

    dlg._on_downloaded(("sha", "ok", "sha", str(dest)))

    assert dlg._parent._pending_installer is None
    assert not tmpdir.exists()  # download discarded

def test_frozen_build_hard_refuses_missing_checksum(qapp, tmp_path, monkeypatch):
    import PyReconstruct.modules.backend.updater.install_info as II
    import PyReconstruct.modules.gui.utils as gui_utils
    monkeypatch.setattr(II, "install_kind", lambda: "frozen")
    notified = []
    monkeypatch.setattr(gui_utils, "notify", lambda msg: notified.append(msg))
    monkeypatch.setattr(gui_utils, "notifyConfirm",
                        lambda *a, **k: pytest.fail("must not offer 'install anyway'"))

    dlg = _make_dialog(qapp)
    dlg.show()  # visible, not cancelled -- the real 'missing checksum' path
    dlg._pool = object()
    tmpdir = tmp_path / "dl2"
    tmpdir.mkdir()
    dest = tmpdir / "installer.AppImage"
    dest.write_bytes(b"x")
    dlg._tmpdir = str(tmpdir)

    dlg._on_downloaded(("sha", "missing", None, str(dest)))

    assert notified and "verified" in notified[0]
    assert dlg._parent._pending_installer is None
    assert not tmpdir.exists()
