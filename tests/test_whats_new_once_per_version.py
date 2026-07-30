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
    assert "Added the shiny new thing." in dialog._notes.toPlainText()
    assert settings.value(F.WHATSNEW_KEY) == "1.21.0"     # recorded as seen

    dialog.close()
    assert main_window._whatsnew_dialog is None

    # relaunching the same version: the gate holds, nothing opens
    main_window.showWhatsNewStartup()
    assert main_window._whatsnew_dialog is None
