"""The launch check shows a quiet status bar notice, not a dialog (#430).

A newer build found at launch used to raise "PyReconstruct X is available.
View the update now?". Now it puts "Update available: X" on the right of the
status bar, and the notice stays until it is clicked, across launches too:
the version is kept per app, so on the days the 24h throttle skips the check
the notice still comes back. Clicking it runs Help > Check for updates.

Driven through the real window and the real handlers. The feed is faked at
``_runUpdateCheck``, so nothing here reaches the network, and the settings
the notice keeps land in the suite's redirected store.
"""

import pytest

from packaging.version import Version
from PySide6.QtCore import QSettings

from PyReconstruct.modules.backend.updater import install_info as II
from PyReconstruct.modules.backend.updater import updater as U
from PyReconstruct.modules.constants.settings_domain import domain_for

KEY = "update_notice_version"
STAMP = "last_update_check_epoch"


def _settings(key):
    return QSettings(*domain_for(key))


@pytest.fixture
def launch(main_window, monkeypatch):
    """Run the real launch check on ``main_window`` as an installed build.

    ``launch(info)`` feeds the check ``info``; ``launch(None)`` is a launch
    the 24h throttle holds back. Any launch-time dialog or download fails the
    test.
    """
    from PyReconstruct.modules.gui.dialog import update_dialog as UD
    from PyReconstruct.modules.gui.main import main_window as MW

    def boom(*a, **k):
        raise AssertionError("no dialog may open at launch")

    monkeypatch.setattr(MW, "notifyConfirm", boom)
    monkeypatch.setattr(MW, "notify", boom)
    monkeypatch.setattr(UD, "UpdateDialog", boom)
    monkeypatch.setattr(UD, "ReinstallDialog", boom)
    monkeypatch.setattr(MW, "install_kind", lambda: "frozen")
    monkeypatch.setattr(II, "current_version", lambda: Version("1.23.0"))
    main_window.series.setOption("update_check_on_startup", True)
    checks = []

    def fake_check(self, channel, on_result, on_error, kind=None):
        # Only this test's window counts. Every MainWindow schedules
        # checkForUpdatesStartup 2.5 s after it is built, and a window from an
        # earlier test is only deleteLater()ed, so its timer can still be
        # pending. pytest-qt runs processEvents right after fixture setup, and
        # a timer that comes due then reaches this class-wide patch with
        # install_kind already faked, which put an extra "release" in checks.
        if self is not main_window:
            return
        checks.append(channel)
        if fake_check.during is not None:
            fake_check.during()  # what the user does while the worker runs
        if isinstance(fake_check.info, Exception):
            on_error(fake_check.info)
        else:
            on_result(fake_check.info)

    monkeypatch.setattr(MW.MainWindow, "_runUpdateCheck", fake_check)

    def run(info, during=None):
        import time
        fake_check.during = during
        if info is None:
            _settings(STAMP).setValue(STAMP, time.time())
        else:
            _settings(STAMP).remove(STAMP)
        fake_check.info = info
        main_window.checkForUpdatesStartup()
        return main_window.update_notice

    run.checks = checks
    _settings(KEY).remove(KEY)
    _settings(STAMP).remove(STAMP)
    yield run
    _settings(KEY).remove(KEY)
    _settings(STAMP).remove(STAMP)


def _newer(version="1.24.0"):
    return {"asset": {"name": "x"}, "status": "newer",
            "remote_version": version, "local_version": "1.23.0"}


pytestmark = pytest.mark.gui


def test_a_newer_build_shows_the_notice_and_no_dialog(launch):
    notice = launch(_newer())

    assert not notice.isHidden()
    assert notice.text() == "Update available: 1.24.0"
    assert _settings(KEY).value(KEY) == "1.24.0"


def test_the_notice_sits_in_the_status_bar_beside_the_readout(main_window, launch):
    notice = launch(_newer())

    assert notice.parent() is not None
    assert main_window.statusbar.isAncestorOf(notice)
    # a transient message does not hide it (it is a permanent widget)
    main_window.statusbar.showMessage("something else", 5000)
    assert not notice.isHidden()


def test_the_notice_comes_back_at_the_next_launch_without_a_check(launch):
    launch(_newer())
    notice = launch(None)  # throttled: no check this launch

    assert launch.checks == ["release"]
    assert not notice.isHidden()
    assert notice.text() == "Update available: 1.24.0"


def test_a_stored_version_this_build_already_has_is_dropped(launch, main_window):
    _settings(KEY).setValue(KEY, "1.23.0")

    notice = launch(None)

    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_an_unreadable_stored_version_is_dropped(launch):
    _settings(KEY).setValue(KEY, "not a version")

    notice = launch(None)

    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_a_check_that_finds_nothing_newer_clears_the_notice(launch):
    launch(_newer())
    notice = launch({"asset": {"name": "x"}, "status": "same",
                     "remote_version": "1.23.0", "local_version": "1.23.0"})

    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_clicking_the_notice_runs_the_manual_check_and_hides_it(
    launch, main_window, monkeypatch, qtbot
):
    from PySide6.QtCore import Qt
    from PyReconstruct.modules.gui.main import main_window as MW

    manual = []
    monkeypatch.setattr(MW.MainWindow, "checkForUpdates", lambda self: manual.append(self))
    notice = launch(_newer())
    main_window.show()
    qtbot.waitExposed(main_window)

    qtbot.mouseClick(notice, Qt.LeftButton)

    assert manual == [main_window]
    assert notice.isHidden()


def _click_through(main_window, monkeypatch, info=None, error=None):
    """Click the notice with the manual check's feed faked; returns what
    ``notify`` showed. ``info`` is what the check finds, ``error`` a failure."""
    from PyReconstruct.modules.gui.main import main_window as MW

    shown = []
    monkeypatch.setattr(MW, "notify", lambda msg, *a, **k: shown.append(msg))
    monkeypatch.setattr(MW, "install_kind", lambda: "frozen")

    def manual_check(self, channel, on_result, on_error, kind=None):
        if error is not None:
            on_error(error)
        else:
            on_result(info)

    monkeypatch.setattr(MW.MainWindow, "_runUpdateCheck", manual_check)
    main_window.openUpdateNotice()
    return shown


def test_a_click_while_an_update_is_in_progress_keeps_the_saved_notice(
    launch, main_window, monkeypatch
):
    notice = launch(_newer())
    main_window._updater_pool = object()
    try:
        shown = _click_through(main_window, monkeypatch, info=_newer())
    finally:
        main_window._updater_pool = None

    assert shown == ["An update is already in progress."]
    assert notice.isHidden()
    assert _settings(KEY).value(KEY) == "1.24.0"
    assert not launch(None).isHidden()  # back at the next launch


def test_a_click_whose_check_fails_keeps_the_saved_notice(
    launch, main_window, monkeypatch
):
    notice = launch(_newer())

    shown = _click_through(main_window, monkeypatch, error=OSError("no network"))

    assert len(shown) == 1 and shown[0].startswith("Could not check for updates")
    assert notice.isHidden()
    assert _settings(KEY).value(KEY) == "1.24.0"
    assert not launch(None).isHidden()


def test_a_click_that_opens_the_update_forgets_the_notice(
    launch, main_window, monkeypatch
):
    from PyReconstruct.modules.gui.dialog import update_dialog as UD

    opened = []

    class FakeDialog:
        def __init__(self, *a, **k):
            opened.append(a)

        def exec(self):
            return 0  # closed without installing

    monkeypatch.setattr(UD, "UpdateDialog", FakeDialog)
    notice = launch(_newer())

    _click_through(main_window, monkeypatch, info=_newer())

    assert len(opened) == 1
    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)
    assert launch(None).isHidden()


def test_turning_off_the_automatic_check_clears_the_notice(launch, main_window):
    notice = launch(_newer())

    main_window.toggleupdatecheck_act.setChecked(False)
    main_window.toggleUpdateCheckOnStartup()

    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_a_startup_check_from_an_earlier_window_is_not_counted(launch, main_window):
    """What an earlier test's window does when its startup timer comes due
    during this test's setup: it runs the real launch check on itself."""
    import types

    from PyReconstruct.modules.gui.main import main_window as MW

    earlier = types.SimpleNamespace(series=main_window.series,
                                    restoreUpdateNotice=lambda: None)
    earlier._runUpdateCheck = types.MethodType(MW.MainWindow._runUpdateCheck, earlier)
    MW.MainWindow.checkForUpdatesStartup(earlier)

    launch(_newer())
    launch(None)

    assert launch.checks == ["release"]


def test_the_notice_is_kept_per_app(monkeypatch):
    """The stable and Dev apps follow different feeds, so each keeps its own."""
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    assert domain_for(KEY) == ("PyReconstruct", "PyReconstruct Dev")


@pytest.mark.parametrize("text,newer", [
    ("1.24.0", True),
    ("1.24.0.dev20261001", True),
    ("1.23.0", False),
    ("1.22.9", False),
    ("not a version", False),
    ("", False),
])
def test_is_newer_than(text, newer):
    assert U.is_newer_than(text, Version("1.23.0")) is newer


def test_is_newer_than_an_unknown_local_version_is_false():
    assert U.is_newer_than("9.9.9", None) is False


def test_a_check_with_nothing_to_offer_clears_the_notice(launch):
    """A pulled release, or one with no installer for this build: a saved
    notice would open nothing, so it goes."""
    launch(_newer())
    notice = launch({"asset": None, "status": "unknown", "release": None,
                     "remote_version": None, "local_version": "1.23.0"})

    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_a_failed_check_keeps_the_notice(launch):
    launch(_newer())
    notice = launch(OSError("no network"))

    assert not notice.isHidden()
    assert _settings(KEY).value(KEY) == "1.24.0"


def _reinstall_info(remote):
    return {"release": None, "asset": None, "remote_version": remote,
            "local_version": "1.23.0",
            "status": "newer" if remote else "unknown", "command": "x"}


def test_a_reinstall_check_with_nothing_to_offer_clears_the_notice(
    launch, main_window
):
    launch(_newer())

    main_window._onReinstallCheck(_reinstall_info(None), "release", manual=False)

    assert main_window.update_notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_turning_the_check_off_while_it_runs_shows_no_notice(launch, main_window):
    def turn_off():
        main_window.series.setOption("update_check_on_startup", False)

    notice = launch(_newer(), during=turn_off)

    assert notice.isHidden()
    assert not _settings(KEY).contains(KEY)


def test_a_reinstall_result_after_the_check_is_off_shows_no_notice(
    launch, main_window
):
    main_window.series.setOption("update_check_on_startup", False)

    main_window._onReinstallCheck(_reinstall_info("1.24.0"), "release", manual=False)

    assert main_window.update_notice.isHidden()
    assert not _settings(KEY).contains(KEY)


@pytest.mark.parametrize("text,local,newer", [
    ("1.24.0.dev20261002", "1.24.0.dev20261001", True),
    ("1.24.0.dev20261001", "1.24.0.dev20261001", False),
    ("1.24.0.dev20260930", "1.24.0.dev20261001", False),
    ("1.24.0", "1.24.0.dev20261001", True),
    ("1.24.0.dev20261001", "1.24.0", False),
])
def test_is_newer_than_with_dev_versions(text, local, newer):
    assert U.is_newer_than(text, Version(local)) is newer
