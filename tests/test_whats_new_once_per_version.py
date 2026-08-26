"""The release notes are shown once, on the launch of the version they describe.

Two separate code paths used to put the same notes in front of the user around a
single update:

* ``UpdateDialog`` (reached from the background check on launch, or from
  Help -> Check for updates) rendered the *remote* release body inline, under a
  "What's new" heading, while offering the download; and
* ``maybe_show_whats_new`` (fired from ``MainWindow.showWhatsNewStartup``)
  rendered the bundled notes for the version now running, gated on the
  ``last_whatsnew_version`` setting.

So a user who took an update read the notes at the prompt and then again on the
next launch. Only the second showing describes what the reader is actually
running, so the first one no longer renders the notes: it links to them and says
when they will appear.

These tests walk the three sequences a user can be in -- take the update now,
decline and take it later, install fresh -- and assert the notes appear exactly
once in each.
"""

import pytest

from PySide6.QtWidgets import QLabel, QTextBrowser

from PyReconstruct.modules.gui.main import first_launch as F
from PyReconstruct.modules.gui.dialog import whats_new as W
from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog

pytestmark = pytest.mark.gui


# ---- fixtures / fakes -------------------------------------------------------

# Bundled highlights, as WHATS_NEW.md carries them.
WHATS_NEW = """# What's New

## [1.21.0] — 2026-07-20

- Added the shiny new thing.

## [1.20.3] — 2026-06-29

- Fixed the old thing.
"""

# What GitHub publishes on the release itself, which is what the update prompt
# used to render. Deliberately worded so it cannot be confused with the bundled
# text above.
RELEASE_BODY = "## 1.21.0\n\n- Added the shiny new thing.\n- REMOTE-ONLY-SENTINEL\n"


class FakeSettings:
    """A QSettings-shaped dict, so the gate can be driven without Qt I/O."""

    def __init__(self, data=None):
        self._d = dict(data or {})
        self.writes = []

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, val):
        self._d[key] = val
        self.writes.append((key, val))


@pytest.fixture(autouse=True)
def bundled_notes(monkeypatch, tmp_path):
    """Point the notes builder at a fixed WHATS_NEW.md, so it is offline and stable."""
    path = tmp_path / "WHATS_NEW.md"
    path.write_text(WHATS_NEW, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: path)


def _update_info(status="newer", remote="1.21.0", local="1.20.3"):
    return {
        "asset": {"name": "PyReconstruct-Installer.exe",
                  "browser_download_url": "https://example.test/asset", "size": 1024},
        "release": {"body": RELEASE_BODY},
        "status": status,
        "remote_version": remote,
        "local_version": local,
    }


def _update_prompt(qapp, **kwargs):
    """The dialog the updater puts up when it has something to offer."""
    return UpdateDialog(None, _update_info(**kwargs), "release")


def _all_text(dialog):
    """Every piece of text the dialog puts on screen, labels and browsers alike."""
    parts = [w.text() for w in dialog.findChildren(QLabel)]
    parts += [b.toPlainText() for b in dialog.findChildren(QTextBrowser)]
    return "\n".join(parts)


def _shown_once(settings, current, calls):
    """Run the startup gate for ``current`` and report whether it showed."""
    return W.maybe_show_whats_new(
        None, settings=settings, current=current,
        show=lambda parent, version, last_seen=None: calls.append((version, last_seen)),
    )


# ---- the update prompt no longer carries the notes --------------------------

@pytest.mark.parametrize("status", ["newer", "same", "older", "unknown"])
def test_update_prompt_never_renders_the_release_notes(qapp, status):
    """Whatever the updater has to offer, the prompt does not read out the notes.

    The notes belong to the version being described, and the user is not running
    it yet. Rendering them here is what produced the second showing.
    """
    dlg = _update_prompt(qapp, status=status)
    try:
        assert dlg.findChildren(QTextBrowser) == []   # no notes body at all
        assert "REMOTE-ONLY-SENTINEL" not in _all_text(dlg)
        assert "Added the shiny new thing" not in _all_text(dlg)
    finally:
        dlg.deleteLater()


def test_update_prompt_links_to_the_notes_for_the_offered_version(qapp):
    """The notes are one click away, for a user deciding whether to take it."""
    dlg = _update_prompt(qapp)
    try:
        text = _all_text(dlg)
        assert "Release notes for 1.21.0" in text
        assert F.github_release_url("1.21.0") in text
        assert F.github_release_url("1.21.0").endswith("/releases/tag/v1.21.0")
    finally:
        dlg.deleteLater()


def test_update_prompt_says_when_the_notes_will_appear(qapp):
    """An upgrade promises the post-update showing, so the notes never feel lost."""
    dlg = _update_prompt(qapp, status="newer")
    try:
        assert "See what's new the first time you open 1.21.0." in _all_text(dlg)
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("status", ["same", "older", "unknown"])
def test_update_prompt_promises_nothing_it_cannot_keep(qapp, status):
    """A reinstall or a downgrade gets no post-update showing, so promise none.

    ``whats_new_due`` only fires on an upgrade, so on these paths the notes are
    reached through the link or through Help -> What's new, and the dialog says
    so by staying quiet rather than pointing at a showing that will not happen.
    """
    dlg = _update_prompt(qapp, status=status)
    try:
        text = _all_text(dlg)
        assert "first time you open" not in text
        assert "Release notes for" in text        # the link is still offered
    finally:
        dlg.deleteLater()


# ---- sequence 1: the update is taken straight away --------------------------

def test_update_accepted_immediately_shows_the_notes_once(qapp):
    """Prompt (no notes) -> install -> first launch of 1.21.0 shows them once."""
    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.3"})
    calls = []

    # 1. running 1.20.3, the updater offers 1.21.0
    dlg = _update_prompt(qapp, status="newer", remote="1.21.0", local="1.20.3")
    try:
        assert "REMOTE-ONLY-SENTINEL" not in _all_text(dlg)
    finally:
        dlg.deleteLater()
    assert settings.writes == []          # the prompt records nothing

    # 2. the update lands; first launch of the new version
    assert _shown_once(settings, "1.21.0", calls) is True
    assert calls == [("1.21.0", "1.20.3")]
    assert settings.value(F.WHATSNEW_KEY) == "1.21.0"

    content = F.whats_new_content("1.21.0", last_seen="1.20.3")
    assert content["orienter"] == "What's new since 1.20.3"
    assert "Added the shiny new thing." in content["body"]

    # 3. every later launch of 1.21.0 stays quiet
    assert _shown_once(settings, "1.21.0", calls) is False
    assert len(calls) == 1


# ---- sequence 2: the update is declined, then taken later -------------------

def test_update_declined_then_taken_later_still_shows_the_notes_once(qapp):
    """Declining must not burn the one showing the user is owed."""
    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.3"})
    calls = []

    # 1. the offer arrives and carries no notes
    dlg = _update_prompt(qapp, status="newer", remote="1.21.0", local="1.20.3")
    try:
        assert "REMOTE-ONLY-SENTINEL" not in _all_text(dlg)
        dlg.reject()                      # "Later"
    finally:
        dlg.deleteLater()
    assert settings.writes == []          # nothing marked seen

    # 2. a week of launches on the old version: still nothing to say
    assert _shown_once(settings, "1.20.3", calls) is False
    assert _shown_once(settings, "1.20.3", calls) is False
    assert calls == []

    # 3. the update is taken; the notes arrive, once, and cover the whole jump
    assert _shown_once(settings, "1.21.0", calls) is True
    assert calls == [("1.21.0", "1.20.3")]
    assert _shown_once(settings, "1.21.0", calls) is False
    assert len(calls) == 1


# ---- sequence 3: a fresh install -------------------------------------------

def test_fresh_install_gets_one_welcome_and_never_a_second(qapp):
    """A first-time user is welcomed once, not shown an update summary.

    Deliberate: with nothing stored there is no "since" to report, so the
    dialog frames the recent releases as a welcome. It still counts as the one
    showing for that version, so the next launch is silent.
    """
    settings = FakeSettings()             # nothing stored: never run before
    calls = []

    assert _shown_once(settings, "1.21.0", calls) is True
    assert calls == [("1.21.0", None)]
    assert settings.value(F.WHATSNEW_KEY) == "1.21.0"

    content = F.whats_new_content("1.21.0", last_seen=None)
    assert content["orienter"] == "Welcome to PyReconstruct"
    assert "Added the shiny new thing." in content["body"]

    assert _shown_once(settings, "1.21.0", calls) is False
    assert len(calls) == 1


# ---- "Don't show again": the popup can be switched off, and back on ---------

def _find_button(dialog, label):
    from PySide6.QtWidgets import QPushButton
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == label)


def test_dont_show_again_suppresses_the_popup_across_restarts(qapp):
    """The button closes the dialog, and no later launch shows the popup.

    Asserted through the persisted preference rather than any dialog state:
    the dialog writes the same store ``maybe_show_whats_new`` reads, so each
    fresh gate run below is a "restart" of the startup logic against the
    settings the button left behind. The suppression must also beat a pending
    version bump: a stored last-seen older than the running version is exactly
    the state ``whats_new_due`` fires on, and the button has to win that
    argument, or the very next update would undo the user's choice.
    """
    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.3"})
    calls = []

    dlg = W.WhatsNewDialog(None, "1.21.0", last_seen="1.20.3", settings=settings)
    try:
        dlg.show()
        _find_button(dlg, "Don't show again").click()
        assert not dlg.isVisible()                    # closed, like "Got it"
        assert F.whats_new_suppressed(settings.value(F.WHATSNEW_SUPPRESS_KEY))
    finally:
        dlg.deleteLater()

    # relaunches of the same version stay quiet, as they would have anyway...
    assert _shown_once(settings, "1.21.0", calls) is False
    # ...and so does the launch after the NEXT update: the button wins
    assert _shown_once(settings, "1.21.1", calls) is False
    assert calls == []
    # the last-seen record did not advance while suppressed, which is what
    # keeps the once-per-version rules intact for a later re-enable
    assert settings.value(F.WHATSNEW_KEY) == "1.20.3"


def test_reenabling_restores_the_once_per_version_rules(qapp):
    """Switching the popup back on hands back the ordinary rules, intact.

    The stored preference is the same one the Help-menu toggle writes (the
    toggle handler stores ``not checked``); this drives the pure layer with
    that exact write. A version bump missed while the popup was off shows on
    the first launch after re-enabling -- the suppressed path never advanced
    the last-seen record, so nothing was skipped -- and it still shows only
    once.
    """
    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.3",
                             F.WHATSNEW_SUPPRESS_KEY: True})
    calls = []

    assert _shown_once(settings, "1.21.0", calls) is False      # off: quiet

    settings.setValue(F.WHATSNEW_SUPPRESS_KEY, False)           # Help toggle

    assert _shown_once(settings, "1.21.0", calls) is True       # catch-up
    assert calls == [("1.21.0", "1.20.3")]
    assert _shown_once(settings, "1.21.0", calls) is False      # once only
    assert len(calls) == 1


def test_suppression_survives_the_string_spelling_qsettings_stores(qapp):
    """A suppression written as the string "true" still suppresses.

    The suite's redirected store is INI-format, and INI (like other QSettings
    backends) hands a stored Python bool back as the strings "true"/"false".
    A gate that only respected real booleans would suppress until the app
    restarted and then start popping up again, which is the kind of failure
    a test that keeps one FakeSettings dict alive can never see.
    """
    for stored, suppressed in [
        (True, True), ("true", True), ("True", True),
        (False, False), ("false", False), (None, False), ("", False),
    ]:
        assert F.whats_new_suppressed(stored) is suppressed, repr(stored)

    settings = FakeSettings({F.WHATSNEW_KEY: "1.20.3",
                             F.WHATSNEW_SUPPRESS_KEY: "true"})
    calls = []
    assert _shown_once(settings, "1.21.0", calls) is False
    assert calls == []


def test_help_menu_reopen_ignores_the_suppression(qapp):
    """Help > What's new still opens while the popup is suppressed.

    "Don't show again" is about the unasked startup popup; a menu click is an
    explicit request, and honoring the preference there would make the toggle
    the only way to ever see the notes again. ``show_whats_new`` consults no
    settings at all, and this pins that staying true.
    """
    shown = []
    W.show_whats_new(
        None, current="1.21.0",
        show=lambda parent, version, last_seen=None, content=None:
            shown.append(version),
    )
    assert shown == ["1.21.0"]


# ---- the real window, real settings store ----------------------------------

def test_startup_shows_the_notes_once_per_version_in_the_real_window(
    main_window, monkeypatch
):
    """End to end through `MainWindow`, against the suite's redirected settings.

    The sequence tests above inject the store and the dialog; this one lets the
    real startup handler read and write the real key and build the real dialog,
    so the wiring between them is covered too.
    """
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)    # redirected away from the real store
    settings.setValue(F.WHATSNEW_KEY, "1.20.3")
    monkeypatch.setattr(W, "current_version_str", lambda: "1.21.0")

    main_window._whatsnew_dialog = None
    main_window.showWhatsNewStartup()
    dialog = main_window._whatsnew_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.isModal() is False                      # never blocks startup
    rendered = dialog._notes.toPlainText()
    assert "Added the shiny new thing." in rendered
    # the maintainer byline is its own always-visible label below the notes --
    # not inside the scrollable browser -- exactly once, all the way through the
    # real startup handler and dialog
    assert F.MAINTAINER_BYLINE not in rendered
    # the byline label carries link markup, so compare what it *renders*: the
    # approved sentence on its two display lines, broken at the comma (the
    # explicit break the dialog adds; the constant itself is one string)
    two_line_byline = F.MAINTAINER_BYLINE.replace(", ", ",\n", 1)
    from PySide6.QtGui import QTextDocumentFragment
    def shows_byline(lab):
        return two_line_byline in (
            QTextDocumentFragment.fromHtml(lab.text()).toPlainText()
        )

    shown = QTextDocumentFragment.fromHtml(dialog._byline.text()).toPlainText()
    assert shown == two_line_byline
    bylines = [lab for lab in dialog.findChildren(QLabel) if shows_byline(lab)]
    assert bylines == [dialog._byline]
    # placement, on the dialog the real startup handler built: the byline sits
    # in the footer row below the notes, left of the "All release notes" link
    dialog.layout().activate()
    link = next(lab for lab in dialog.findChildren(QLabel)
                if "All release notes on GitHub" in lab.text())
    assert dialog._byline.geometry().top() >= dialog._notes.geometry().bottom()
    assert dialog._byline.geometry().right() < link.geometry().left()
    assert settings.value(F.WHATSNEW_KEY) == "1.21.0"     # recorded as seen

    dialog.close()
    assert main_window._whatsnew_dialog is None

    # relaunching the same version: the gate holds, nothing opens
    main_window.showWhatsNewStartup()
    assert main_window._whatsnew_dialog is None


def test_the_main_window_fixture_closes_the_gate_before_the_startup_timer(
    main_window
):
    """No test gets this dialog by accident, whatever the 750 ms timer does.

    `MainWindow.__init__` schedules `showWhatsNewStartup` on a 750 ms timer, and
    the session's redirected settings store starts empty, so on an unprepared
    window that handler is due. Teardown only calls `deleteLater()`, so the
    timer outlives the test that built the window often enough to matter, and
    the modeless dialog it opens then becomes `QApplication.activeWindow()` in
    the middle of some later test: `Qt::WindowShortcut` stops resolving to the
    `MainWindow` and any popup showing at that moment is dismissed. That cost
    `tests/test_menu_stays_open_on_toggle.py` 15 of 30 full-file runs, in three
    different tests, none of which reproduced in isolation.

    The fixture records the running version as already seen, so this asserts on
    the gate rather than on the timer: due-ness is deterministic, the timer is
    not.
    """
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)

    assert settings.value(F.WHATSNEW_KEY) == W.current_version_str()
    assert W.whats_new_due(settings.value(F.WHATSNEW_KEY), W.current_version_str()) is False

    main_window._whatsnew_dialog = None
    main_window.showWhatsNewStartup()
    assert main_window._whatsnew_dialog is None


def test_help_toggle_reflects_the_stored_state_when_the_menu_opens(main_window):
    """The Help toggle never lies about whether the popup is on.

    The preference can change behind the menu's back -- the dialog's "Don't
    show again" button writes it without going anywhere near the menubar -- so
    the toggle resyncs from the store on every Help open instead of trusting
    its build-time seed. ``aboutToShow`` is emitted here directly; it is the
    same signal a real open fires, without needing a visible menu on an
    offscreen platform.
    """
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)    # the suite's redirected store

    # The row reads "Turn off What's new pop-up", so a TICK is the disabled
    # state (his call, 2026-08-26): the checkmark and the stored suppression
    # flag are the same thing.
    #
    # freshly built with nothing stored: the popup is on, so the row is clear
    assert main_window.togglewhatsnew_act.isCheckable() is True
    assert main_window.togglewhatsnew_act.isChecked() is False

    # the dialog's button flips the preference behind the menu's back...
    settings.setValue(F.WHATSNEW_SUPPRESS_KEY, True)
    # ...and opening Help brings the toggle back to the truth: off means ticked
    main_window.helpmenu.aboutToShow.emit()
    assert main_window.togglewhatsnew_act.isChecked() is True

    settings.setValue(F.WHATSNEW_SUPPRESS_KEY, False)
    main_window.helpmenu.aboutToShow.emit()
    assert main_window.togglewhatsnew_act.isChecked() is False


def test_help_toggle_reenables_the_popup(main_window):
    """Clicking the Help toggle turns the popup off and back on, persistently.

    Driven through ``trigger()``, which is what a real menu click does: it
    flips the checked state and then runs the handler, so this covers the
    polarity in ``toggleWhatsNewPopup`` -- the handler reads the state the
    click just produced, and getting that backwards would persist the
    opposite of every click. Checked means OFF here (his call, 2026-08-26),
    matching the row's wording. The re-enabled preference is then read back
    through the pure gate to show the popup is eligible again.
    """
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)

    # off: the click TICKS the row ("turn off") and persists the suppression
    assert main_window.togglewhatsnew_act.isChecked() is False
    main_window.togglewhatsnew_act.trigger()
    assert main_window.togglewhatsnew_act.isChecked() is True
    assert F.whats_new_suppressed(settings.value(F.WHATSNEW_SUPPRESS_KEY))
    assert W.maybe_show_whats_new(
        None, settings=settings, current="1.21.0",
        show=lambda *a, **k: pytest.fail("suppressed popup was shown"),
    ) is False

    # back on: unticking the row makes the popup eligible again
    main_window.togglewhatsnew_act.trigger()
    assert main_window.togglewhatsnew_act.isChecked() is False
    assert not F.whats_new_suppressed(settings.value(F.WHATSNEW_SUPPRESS_KEY))
    settings.setValue(F.WHATSNEW_KEY, "1.20.3")     # a pending bump
    calls = []
    assert _shown_once(settings, "1.21.0", calls) is True
    assert calls == [("1.21.0", "1.20.3")]


# ---- the log line that makes an absence readable -----------------------------
#
# The startup hook swallows its own failures on purpose, so nothing must be able
# to escape it. That is exactly what made a real 1.21.0-beta-7 launch
# undiagnosable: the dialog did not reach the user, and the only trace left
# anywhere was the stored version having moved. Nothing raised, so an
# exception-only log would still have said nothing -- hence a line on every
# branch, not just the failing one. `capsys` reads it because the helpers write
# through `sys.stderr`, which is what `install_file_logging` tees.

def test_startup_logs_that_it_showed_the_dialog(main_window, monkeypatch, capsys):
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)              # redirected by the suite
    settings.setValue(F.WHATSNEW_KEY, "1.20.3")
    monkeypatch.setattr(W, "current_version_str", lambda: "1.21.0")

    main_window._whatsnew_dialog = None
    main_window.showWhatsNewStartup()
    err = capsys.readouterr().err
    assert "What's new (startup): dialog shown" in err
    main_window._whatsnew_dialog.close()


def test_startup_logs_that_the_gate_declined(main_window, monkeypatch, capsys):
    """The branch that leaves no dialog behind is the one worth naming: without
    this line, "not due" and "it crashed" look identical from the outside."""
    from PySide6.QtCore import QSettings

    settings = QSettings(W.ORG, W.APP)
    settings.setValue(F.WHATSNEW_KEY, "1.21.0")     # already seen
    monkeypatch.setattr(W, "current_version_str", lambda: "1.21.0")

    main_window._whatsnew_dialog = None
    main_window.showWhatsNewStartup()
    err = capsys.readouterr().err
    assert "What's new (startup): not due for this version" in err
    assert main_window._whatsnew_dialog is None


def test_startup_logs_a_failure_and_still_swallows_it(main_window, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("the injected cause")

    monkeypatch.setattr(W, "maybe_show_whats_new", boom)
    main_window._whatsnew_dialog = None
    main_window.showWhatsNewStartup()               # must not raise: startup goes on
    err = capsys.readouterr().err
    assert "What's new (startup) failed; continuing without it" in err
    assert "RuntimeError: the injected cause" in err
    assert "Traceback (most recent call last)" in err
    assert main_window._whatsnew_dialog is None


def test_help_menu_reopen_logs_a_failure_and_still_swallows_it(
        main_window, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("the injected cause")

    monkeypatch.setattr(W, "show_whats_new", boom)
    main_window.showWhatsNew()                      # a menu click must not raise
    err = capsys.readouterr().err
    assert "What's new (Help menu) failed" in err
    assert "RuntimeError: the injected cause" in err


def test_startup_never_writes_the_developers_own_log(main_window, monkeypatch, tmp_path):
    """The breadcrumbs go through `sys.stderr`, so a suite run cannot append to
    `~/Library/Logs/PyReconstruct`. Pinned because routing them through
    `log_file_path()` instead would pass every test above and quietly grow the
    real log by one line per test."""
    import PyReconstruct.modules.backend.func.logging_setup as ls

    called = []
    monkeypatch.setattr(ls, "log_file_path", lambda: called.append(1) or tmp_path / "x")
    main_window._whatsnew_dialog = None
    main_window.showWhatsNewStartup()
    if main_window._whatsnew_dialog is not None:
        main_window._whatsnew_dialog.close()
    assert called == []
