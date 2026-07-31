"""The update-checks note, through the real window and the real dialog.

`tests/test_first_launch.py` covers which framing gets the note by calling the
content builder directly. These tests cover the part a string comparison cannot:
that the note actually reaches the screen. The dialog renders markdown into a
`QTextBrowser`, and the note carries a `▸` and sits behind a `---` rule, so
"the builder returned it" and "the reader can read it" are two different claims.

Driven through `MainWindow` rather than by constructing the dialog, because the
stored last-seen version is what selects the framing and the startup handler is
what reads it. All three framings are walked here from the same window API a
user reaches: a first launch with nothing stored, an update, and the Help-menu
re-open with nothing stored -- the last being the combination most likely to
leak the note, since only the on-demand flag separates it from a first launch.
The first launch is walked twice, once as the installed app and once as the
source checkout that never runs the update check the note describes.

The settings store is the suite's redirected one (see tests/conftest.py and
tests/qsettings_isolation.py); nothing here touches real user preferences.
"""

import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel

from PyReconstruct.modules.gui.main import first_launch as F
from PyReconstruct.modules.gui.dialog import whats_new as W

pytestmark = pytest.mark.gui


# Stand-in for the bundled WHATS_NEW.md, so the rendering assertions do not
# depend on what the real notes happen to say this release.
WHATS_NEW = """# What's New

## [1.21.0] — 2026-07-20

- Added the shiny new thing.

## [1.20.3] — 2026-06-29

- Fixed the old thing.
"""


@pytest.fixture(autouse=True)
def bundled_notes(monkeypatch, tmp_path):
    """Point the notes builder at fixed highlights, so it is offline and stable."""
    path = tmp_path / "WHATS_NEW.md"
    path.write_text(WHATS_NEW, encoding="utf-8")
    monkeypatch.setattr(F, "find_whats_new_path", lambda: path)


@pytest.fixture
def running_version(monkeypatch):
    """Pin the version the startup handler thinks it is running."""
    monkeypatch.setattr(W, "current_version_str", lambda: "1.21.0")


@pytest.fixture
def installed_app(monkeypatch):
    """Answer the install-kind question the way the installed app would.

    The note only applies where the startup update check actually runs, and the
    suite runs from a source checkout, so without this the dialog is right to
    stay quiet and there would be nothing to assert on.
    """
    monkeypatch.setattr(F, "install_kind", lambda: "frozen")


def _stored(value=None):
    """Set (or clear) the last-seen record in the redirected settings store."""
    settings = QSettings(W.ORG, W.APP)
    if value is None:
        settings.remove(F.WHATSNEW_KEY)
    else:
        settings.setValue(F.WHATSNEW_KEY, value)
    return settings


def _opened(window, open_it):
    """Run ``open_it`` on the window and return (orienter labels, notes text).

    Both startup handlers swallow exceptions so a first-launch convenience can
    never disrupt the app, so a dialog that failed to build shows up here as a
    missing dialog rather than as a traceback.
    """
    window._whatsnew_dialog = None
    open_it(window)
    dialog = window._whatsnew_dialog
    assert dialog is not None, "the What's-new dialog did not open"
    assert dialog.isVisible()
    return (
        [label.text() for label in dialog.findChildren(QLabel)],
        dialog._notes.toPlainText(),
    )


def test_first_launch_dialog_renders_the_update_checks_note(
    main_window, running_version, installed_app
):
    """Nothing stored: the newcomer is told the app checks, and where to change it."""
    _stored(None)
    labels, notes = _opened(main_window, lambda w: w.showWhatsNewStartup())

    assert "Welcome to PyReconstruct" in labels          # the welcome framing
    assert "Added the shiny new thing." in notes         # release notes still there
    assert "checks once a day" in notes                  # the app checks on its own
    assert "turn this off" in notes                      # and it can be turned off
    assert "Beta channel" in notes                       # and there is a second channel
    # the menu path survives markdown rendering into the browser, arrow and all
    assert "Series ▸ Options" in notes
    # the note is an aside under the release history, not another release bullet
    assert notes.index("Added the shiny new thing.") < notes.index("checks once a day")

    main_window._whatsnew_dialog.close()


def test_running_from_source_first_launch_is_welcomed_without_the_note(
    main_window, running_version
):
    """A source checkout never runs the startup check, so it is never promised one.

    No `installed_app` fixture here: this is the install the developer and every
    user running from source actually has. The welcome and the release notes are
    unaffected; only the claim about update checking is withheld.
    """
    _stored(None)
    labels, notes = _opened(main_window, lambda w: w.showWhatsNewStartup())

    assert "Welcome to PyReconstruct" in labels          # still welcomed
    assert "Added the shiny new thing." in notes         # still shown the notes
    assert "checks once a day" not in notes
    assert "Beta channel" not in notes

    main_window._whatsnew_dialog.close()


def test_update_dialog_does_not_render_the_note(
    main_window, running_version, installed_app
):
    """Someone arriving from an update has just used the check; do not explain it."""
    _stored("1.20.3")
    labels, notes = _opened(main_window, lambda w: w.showWhatsNewStartup())

    assert "What's new since 1.20.3" in labels
    assert "Added the shiny new thing." in notes
    assert "checks once a day" not in notes
    assert "Beta channel" not in notes

    main_window._whatsnew_dialog.close()


def test_help_menu_reopen_does_not_render_the_note(
    main_window, running_version, installed_app
):
    """The leak case: the Help-menu re-open with no stored version.

    Nothing is stored, so the only thing telling this apart from a first launch
    is that the reader asked for it. They went looking for the notes; they do
    not need orienting.
    """
    _stored(None)
    labels, notes = _opened(main_window, lambda w: w.showWhatsNew())

    assert "Recent releases" in labels
    assert "Welcome to PyReconstruct" not in labels
    assert "Added the shiny new thing." in notes
    assert "checks once a day" not in notes
    assert "Beta channel" not in notes

    main_window._whatsnew_dialog.close()
