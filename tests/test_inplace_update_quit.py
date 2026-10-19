"""An update staged in place is swapped in when the user quits, and only then.

The update dialog stages a Windows Dev update next to the install
(``backend/updater/inplace.py``) and the main window keeps it until the quit.
These tests drive the real ``MainWindow.closeEvent`` and the real dialog, with
the release served from memory, the install a fake folder under ``tmp_path``,
and the helper's start recorded instead of run.

* A committed quit starts the staged helper with the plan's folder, this
  process's ID, and the series that was open, then quits.
* A canceled quit keeps the update staged and starts nothing.
* A series saved for the first time during the quit is the one reopened.
* A quit with nothing staged finishes a run a helper left part way.
* Nothing starts for a plan this window did not stage, even a valid one on
  disk, or on an in-app restart.
* The dialog says the update installs at quit, and Restart Now closes the
  window; any other build, or a copy an earlier update left, falls back to
  the installer as before.
"""
import os

import pytest

from PyReconstruct.modules.backend.updater import apply as A
from PyReconstruct.modules.backend.updater import inplace as I
from PyReconstruct.modules.backend.updater import staging as S
from PyReconstruct.modules.backend.updater.updater import UpdateCancelled

from test_update_staging import NEW_V, OLD_V, _locked, _run_helper, dev, snapshot  # noqa: F401  (fixture)

pytestmark = pytest.mark.gui


@pytest.fixture
def quit_calls(monkeypatch, dev):  # noqa: F811
    """Start the helper through a recorder, and record QApplication.quit instead of quitting."""
    from PySide6.QtWidgets import QApplication

    real, recover = I.start_helper, I.start_recovery
    monkeypatch.setattr(I, "start_helper",
                        lambda pending, pid, open_path=None: real(pending, pid, open_path, popen=dev.popen))
    monkeypatch.setattr(I, "start_recovery",
                        lambda pid: recover(pid, install=dev.install, popen=dev.popen))
    calls = []
    monkeypatch.setattr(QApplication, "quit", lambda *a: calls.append("quit"))
    return calls


def test_a_committed_quit_starts_the_helper_and_quits(main_window, dev, quit_calls):  # noqa: F811
    pending = dev.stage()
    main_window._pending_inplace = pending
    series = main_window.series.jser_fp

    assert main_window.close() is True

    (argv, kw), = dev.started
    assert argv == [I.helper_path(pending), pending.staging, "--pid", str(os.getpid()), "--open", series]
    assert kw["cwd"] == pending.staging
    assert quit_calls == ["quit"]
    assert main_window._pending_inplace is None


def test_a_canceled_quit_keeps_the_staged_update(main_window, main_window_dialogs, dev, quit_calls):  # noqa: F811
    pending = dev.stage()
    main_window._pending_inplace = pending
    main_window.series.modified = True
    main_window_dialogs.save_response = "cancel"

    assert main_window.close() is False

    assert main_window._pending_inplace is pending and I.still_staged(pending)
    assert dev.started == [] and quit_calls == []
    main_window.series.modified = False
    main_window._pending_inplace = None  # the fixture's own close starts nothing


def test_a_series_first_saved_during_the_quit_is_reopened(main_window, main_window_dialogs, dev,  # noqa: F811
                                                           quit_calls, tmp_path):
    main_window._pending_inplace = dev.stage()
    main_window.series.jser_fp = ""  # a new series, never saved
    main_window.seriesModified(True)
    target = str(tmp_path / "saved at quit.jser")
    main_window_dialogs.save_response = "yes"
    main_window_dialogs.file_responses = [target]

    assert main_window.close() is True

    (argv, kw), = dev.started
    assert os.path.isfile(target) and argv[-2:] == ["--open", target]
    assert quit_calls == ["quit"]


def test_a_quit_finishes_a_run_a_helper_left_part_way(main_window, dev, quit_calls):  # noqa: F811
    from PyReconstruct.modules.backend.updater import apply as A
    pending = dev.stage()
    A.atomic_write_json(os.path.join(pending.staging, A.STATE),
                        {"format": A.FORMAT, "status": "running", "step": "health", "phase": "begin",
                         "plan": dict(pending.plan)})

    assert main_window._pending_inplace is None
    assert main_window.close() is True

    (argv, kw), = dev.started
    assert argv == [I.helper_path(pending), pending.staging, "--pid", str(os.getpid()), "--recover"]
    assert quit_calls == ["quit"]


def test_a_plan_on_disk_that_this_window_did_not_stage_starts_nothing(main_window, dev, quit_calls):  # noqa: F811
    dev.stage()  # an update staged by an earlier run of the app, valid and verified

    assert main_window._pending_inplace is None
    assert main_window.close() is True
    assert dev.started == [] and quit_calls == []


def test_a_plan_replaced_since_staging_starts_nothing(main_window, dev, quit_calls):  # noqa: F811
    from PyReconstruct.modules.backend.updater import apply as A
    pending = dev.stage()
    main_window._pending_inplace = pending
    A.atomic_write_json(os.path.join(pending.staging, A.PLAN), dict(pending.plan, session="another"))

    assert main_window.close() is True
    assert dev.started == [] and quit_calls == []


def test_an_in_app_restart_does_not_start_the_helper(main_window, dev, quit_calls):  # noqa: F811
    main_window._pending_inplace = dev.stage()
    main_window.restart_mainwindow = True

    assert main_window.close() is True
    assert dev.started == []
    main_window.restart_mainwindow = False


def test_a_pending_installer_still_opens_the_installer(main_window, dev, quit_calls, monkeypatch, tmp_path):  # noqa: F811
    from PyReconstruct.modules.gui.main import main_window as mw
    opened = []
    monkeypatch.setattr(mw, "launch_installer", opened.append)
    setup = tmp_path / "PyReconstruct-Setup.exe"
    main_window._pending_installer = str(setup)
    main_window._pending_inplace = dev.stage()  # not armed alongside, but the installer wins if both are

    assert main_window.close() is True
    assert opened == [str(setup)] and dev.started == [] and quit_calls == ["quit"]


# --- The dialog --------------------------------------------------------------------

def _dialog(parent, dev):  # noqa: F811
    from types import SimpleNamespace
    from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog
    info = {"asset": {"name": "PyReconstruct-1.24.0-Windows-x86_64-Dev-Setup.exe",
                      "browser_download_url": "https://github.com/x", "size": 1024},
            "release": dev.rel.release(), "status": "newer",
            "remote_version": NEW_V, "local_version": OLD_V}
    dlg = UpdateDialog(None, info, "prerelease")
    dlg._parent = parent or SimpleNamespace(_updater_pool=object(), _pending_installer=None,
                                            _pending_update_dir=None, _pending_inplace=None)
    return dlg


def test_a_staged_update_says_it_installs_at_quit(qapp, dev, tmp_path):  # noqa: F811
    dlg = _dialog(None, dev)
    dlg.show()
    old = tmp_path / "an earlier installer download"
    old.mkdir()
    dlg._parent._pending_installer, dlg._parent._pending_update_dir = str(old / "Setup.exe"), str(old)
    pending = dev.stage()

    dlg._on_downloaded(("inplace", pending))

    assert dlg._parent._pending_inplace is pending
    assert dlg._parent._pending_installer is None and not old.exists()
    assert dlg._status.text() == "The update is ready. It installs when you quit PyReconstruct."
    assert (dlg._install_btn.text(), dlg._later_btn.text()) == ("Restart Now", "Later")
    assert dlg.isVisible()  # it waits for the user's answer

    dlg._later_btn.click()
    assert dlg.result() == 1 and dlg.restart_now is False
    assert dlg._parent._pending_inplace is pending  # Later keeps it for the next quit


def test_restart_now_closes_the_window(qapp, dev):  # noqa: F811
    dlg = _dialog(None, dev)
    dlg.show()
    dlg._on_downloaded(("inplace", dev.stage()))

    dlg._install_btn.click()

    assert dlg.result() == 1 and dlg.restart_now is True


def test_a_staging_that_finishes_after_cancel_arms_nothing(qapp, dev):  # noqa: F811
    dlg = _dialog(None, dev)
    dlg.show()
    dlg._cancel.set()

    dlg._on_downloaded(("inplace", dev.stage()))

    assert dlg._parent._pending_inplace is None


def test_an_install_that_cannot_update_in_place_downloads_the_installer(qapp, dev, monkeypatch):  # noqa: F811
    dlg = _dialog(None, dev)
    monkeypatch.setattr(I, "running_install", lambda: dev.install)

    def refuse(*a, **k):
        raise I.NotEligible("the release does not turn in-place updates on")

    monkeypatch.setattr(I, "stage_for_quit", refuse)
    assert dlg._try_inplace(dev.rel.release(), NEW_V, lambda p: None) is None

    monkeypatch.setattr(I, "running_install", lambda: None)  # macOS, Linux, a source run
    monkeypatch.setattr(I, "stage_for_quit", lambda *a, **k: pytest.fail("not on this build"))
    assert dlg._try_inplace(dev.rel.release(), NEW_V, lambda p: None) is None


def test_a_cancel_during_staging_is_a_cancel_not_a_fallback(qapp, dev, monkeypatch):  # noqa: F811
    dlg = _dialog(None, dev)
    monkeypatch.setattr(I, "running_install", lambda: dev.install)

    def canceled(*a, **k):
        raise UpdateCancelled()

    monkeypatch.setattr(I, "stage_for_quit", canceled)
    with pytest.raises(UpdateCancelled):
        dlg._try_inplace(dev.rel.release(), NEW_V, lambda p: None)


def test_the_dialog_stages_through_the_real_checks(qapp, dev, monkeypatch):  # noqa: F811
    """The worker's path end to end: eligible, staged, and the plan is the one offered."""
    dlg = _dialog(None, dev)
    monkeypatch.setattr(I, "running_install", lambda: dev.install)
    real = I.stage_for_quit
    monkeypatch.setattr(I, "stage_for_quit", lambda release, offered, **kw: real(
        release, offered, platform=dev.registry, trusted_keys=dev_keys(), **kw))

    pending = dlg._try_inplace(dev.rel.release(), NEW_V, lambda p: None)

    assert pending is not None and pending.version == NEW_V and I.still_staged(pending)


def test_a_copy_a_finished_update_left_downloads_the_installer(qapp, dev, monkeypatch):  # noqa: F811
    """Staging refuses while that copy is there; the dialog takes the installer and keeps it."""
    dev.stage()
    old = os.path.join(dev.rel.staging, A.OLD)
    unlock = _locked(monkeypatch, old)
    assert _run_helper(dev)["status"] == "updated"
    unlock()
    kept, installed = snapshot(old), snapshot(dev.rel.install)
    dlg = _dialog(None, dev)
    monkeypatch.setattr(I, "running_install", lambda: dev.install)
    real, raised = I.stage_for_quit, []

    def stage(release, offered, **kw):
        try:
            return real(release, offered, platform=dev.registry, trusted_keys=dev_keys(), **kw)
        except Exception as e:
            raised.append(e)
            raise

    monkeypatch.setattr(I, "stage_for_quit", stage)
    assert dlg._try_inplace(dev.rel.release(), NEW_V, lambda p: None) is None  # the installer next

    (e,), = [raised]
    assert isinstance(e, S.StageError) and "earlier update has not finished" in str(e)
    assert snapshot(old) == kept and snapshot(dev.rel.install) == installed


def dev_keys():
    from test_signed_checksums import TEST_PUB
    return [TEST_PUB]


class InlinePool:
    """A thread pool that runs its one job on the test's thread, so the job's result is there at once."""

    def createWorker(self, fn):
        from types import SimpleNamespace
        self.fn, self.slots = fn, {"result": [], "error": []}

        def signal(name):
            return SimpleNamespace(connect=self.slots[name].append, emit=lambda *a: None)

        progress = SimpleNamespace(connect=lambda f: None, emit=lambda p: None)
        return SimpleNamespace(signals=SimpleNamespace(
            progress=progress, result=signal("result"), error=signal("error")))

    def start(self, worker):
        import sys
        try:
            value = self.fn()
        except Exception:
            for slot in self.slots["error"]:
                slot(sys.exc_info())
            return
        for slot in self.slots["result"]:
            slot(value)


def test_the_download_worker_stages_in_place_and_skips_the_installer(qapp, dev, monkeypatch):  # noqa: F811
    from PyReconstruct.modules.gui.dialog import update_dialog
    monkeypatch.setattr(update_dialog, "ThreadPool", InlinePool)
    dlg = _dialog(None, dev)
    dlg.show()
    monkeypatch.setattr(I, "running_install", lambda: dev.install)
    real = I.stage_for_quit
    monkeypatch.setattr(I, "stage_for_quit", lambda release, offered, **kw: real(
        release, offered, platform=dev.registry, trusted_keys=dev_keys(), **kw))

    dlg._start_download()

    assert dlg._parent._pending_inplace is not None

    assert I.still_staged(dlg._parent._pending_inplace)
    assert not any(n.endswith("Setup.exe") for n in dev.rel.fetched)  # the installer was never fetched
    assert dlg._install_btn.text() == "Restart Now"


@pytest.mark.parametrize("restart", [True, False])
def test_restart_now_closes_the_window_and_later_does_not(main_window, monkeypatch, restart):
    from PyReconstruct.modules.gui.dialog import update_dialog

    class Answered:
        def __init__(self, parent, info, channel):
            self.restart_now = restart

        def exec(self):
            return 1

    monkeypatch.setattr(update_dialog, "UpdateDialog", Answered)
    closed = []
    main_window.close = lambda: closed.append(True)
    info = {"asset": {"name": "x"}, "release": {}, "status": "newer",
            "remote_version": NEW_V, "local_version": OLD_V}
    try:
        main_window._onCheckResult(info, "prerelease", manual=True)
    finally:
        del main_window.close  # the fixture's teardown closes the window for real

    assert closed == ([True] if restart else [])
