"""Dev update prompts show the missed nightly lists before Stable notes."""

import pytest
from packaging.version import Version
from PySide6.QtWidgets import QLabel, QTextBrowser

from PyReconstruct.modules.backend.updater import install_info as II
from PyReconstruct.modules.backend.updater import updater as U
from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog, ReinstallDialog
from PyReconstruct.modules.gui.main import first_launch as F

LOCAL = "1.26.0.dev202610300800"
SKIPPED = "1.26.0.dev202610310800"
OFFERED = "1.26.0.dev202611010800"
NOTES = """## [Unreleased]
- Unreleased work.
## [1.26.0] - 2026-11-02
- Future Stable notes.
## [1.25.0] - 2026-10-20
- Latest Stable notes.
## [1.24.0] - 2026-10-10
- Earlier Stable notes.
"""


def release(version, label, *, prerelease=True, draft=False):
    flavor = "-Dev" if prerelease else ""
    return {
        "tag_name": f"v{version}", "prerelease": prerelease, "draft": draft,
        "body": (
            "Nightly build from main.\n\n## Changes since Stable\n"
            "- Cumulative highlights.\n\n---\n\n## What's Changed\n"
            f"* {label} in https://github.com/dustenhubbard/pyreconstruct/pull/123\n\n"
            f"**Full Changelog**: https://github.com/dustenhubbard/pyreconstruct/compare/base...v{version}\n"
        ),
        "assets": [{"name": f"PyReconstruct-{version}-Windows-x86_64{flavor}-Setup.exe"},
                   {"name": f"PyReconstruct-{version}-linux-x86_64{flavor}.AppImage"}],
    }


@pytest.fixture
def update_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(II, "current_version", lambda: Version(LOCAL))
    monkeypatch.setattr(II, "platform_asset_tag", lambda: "Windows-x86_64")
    notes = tmp_path / "WHATS_NEW.md"
    notes.write_text(NOTES)
    monkeypatch.setattr(F, "find_whats_new_path", lambda: notes)
    feed = [release(SKIPPED, "Skipped PR"), release(LOCAL, "Installed PR"),
            release(OFFERED, "Offered PR"),
            release("1.27.0.dev202611020800", "Draft PR", draft=True),
            release("1.25.0", "Stable PR", prerelease=False)]
    monkeypatch.setattr(U, "fetch_releases", lambda: feed)
    return feed


def dialog_for(kind, channel):
    if kind == "frozen":
        return UpdateDialog(None, U.check_for_update(channel), channel)
    return ReinstallDialog(None, U.check_for_reinstall(channel, kind),
                           "PyReconstruct Dev" if channel == "prerelease" else "PyReconstruct")


@pytest.mark.gui
@pytest.mark.parametrize("kind", ["frozen", "appimage", "linux-installer"])
def test_two_nightlies_ahead_shows_each_list_then_stable(qtbot, update_feed, kind):
    dialog = dialog_for(kind, "prerelease")
    qtbot.addWidget(dialog)
    browsers = dialog.findChildren(QTextBrowser)
    assert len(browsers) == 1
    text = browsers[0].toPlainText()
    expected = [f"Changes in {OFFERED}", "Offered PR", "Full Changelog",
                f"Changes in {SKIPPED}", "Skipped PR", "Full Changelog",
                "1.25.0", "Latest Stable notes.", "1.24.0", "Earlier Stable notes."]
    cursor = 0
    for part in expected:
        cursor = text.index(part, cursor) + len(part)
    for absent in (LOCAL, "Installed PR", "Draft PR", "Cumulative highlights",
                   "Future Stable notes", "Unreleased work", "Stable PR"):
        assert absent not in text
    html = browsers[0].toHtml()
    for version in (OFFERED, SKIPPED):
        assert f"https://github.com/dustenhubbard/pyreconstruct/compare/base...v{version}" in html
    assert "https://github.com/dustenhubbard/pyreconstruct/pull/123" in html
    assert browsers[0].openExternalLinks()
    labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert "View release on GitHub" in labels
    assert F.github_release_url(OFFERED) in labels


@pytest.mark.gui
@pytest.mark.parametrize("kind", ["frozen", "appimage", "linux-installer"])
def test_stable_update_stays_link_only(qtbot, update_feed, monkeypatch, kind):
    monkeypatch.setattr(II, "current_version", lambda: Version("1.24.0"))
    dialog = dialog_for(kind, "release")
    qtbot.addWidget(dialog)
    assert dialog.findChildren(QTextBrowser) == []
    labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Release notes for 1.25.0" in labels
    assert "View release on GitHub" not in labels
    assert ("See what's new" in labels) == (kind == "frozen")


@pytest.mark.gui
@pytest.mark.parametrize("local", [OFFERED, "1.27.0.dev202611020800", None])
def test_reinstall_downgrade_and_unknown_version_show_only_the_offer(
    qtbot, update_feed, monkeypatch, local
):
    monkeypatch.setattr(II, "current_version", lambda: Version(local) if local else None)
    dialog = dialog_for("frozen", "prerelease")
    qtbot.addWidget(dialog)
    text = dialog.findChild(QTextBrowser).toPlainText()
    assert f"Changes in {OFFERED}" in text
    assert "Offered PR" in text
    assert "Skipped PR" not in text
    assert "Installed PR" not in text
    assert "Latest Stable notes." in text


@pytest.mark.gui
@pytest.mark.parametrize("body", [None, "", "Nightly build without a generated list."])
def test_missing_nightly_list_keeps_other_notes_and_release_link(
    qtbot, update_feed, body
):
    update_feed[2]["body"] = body
    dialog = dialog_for("frozen", "prerelease")
    qtbot.addWidget(dialog)
    text = dialog.findChild(QTextBrowser).toPlainText()
    assert f"Changes in {OFFERED}" in text
    assert "No nightly change list was published." in text
    assert "Skipped PR" in text
    assert "Latest Stable notes." in text
    assert any("View release on GitHub" in label.text() for label in dialog.findChildren(QLabel))


@pytest.mark.gui
def test_appimage_notes_stop_at_the_offered_build(qtbot, update_feed):
    # A newer nightly has no AppImage and cannot be installed by this build.
    update_feed.append(release("1.26.0.dev202611011200", "Unavailable PR"))
    update_feed[-1]["assets"] = []
    dialog = dialog_for("appimage", "prerelease")
    qtbot.addWidget(dialog)
    text = dialog.findChild(QTextBrowser).toPlainText()
    assert "Offered PR" in text
    assert "Unavailable PR" not in text


@pytest.mark.gui
def test_dialog_uses_the_checked_feed_without_another_request(qtbot, update_feed, monkeypatch):
    info = U.check_for_update("prerelease")

    def unexpected_request(*args, **kwargs):
        pytest.fail("The dialog must not request releases on the UI thread")

    monkeypatch.setattr(U, "fetch_releases", unexpected_request)
    dialog = UpdateDialog(None, info, "prerelease")
    qtbot.addWidget(dialog)
    dialog.show()
    assert "Offered PR" in dialog.findChild(QTextBrowser).toPlainText()


def test_missing_bundled_stable_notes_keeps_the_nightly_list():
    text = F.dev_update_notes([release(OFFERED, "Offered PR")], OFFERED, text="")
    assert "Offered PR" in text
    assert "Earlier Stable notes" not in text


@pytest.mark.gui
def test_nightly_links_are_visible_and_open_their_targets(qtbot, update_feed):
    from PySide6.QtCore import QObject, Slot, QUrl, Qt
    from PySide6.QtGui import QDesktopServices, QPalette

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.urls = []

        @Slot(QUrl)
        def opened(self, url):
            self.urls.append(url.toString())

    receiver = Receiver()
    QDesktopServices.setUrlHandler("https", receiver, "opened")
    try:
        dialog = dialog_for("frozen", "prerelease")
        qtbot.addWidget(dialog)
        dialog.show()
        browser = dialog.findChild(QTextBrowser)
        for label, target in [
            ("#123", "https://github.com/dustenhubbard/pyreconstruct/pull/123"),
            ("Full Changelog", f"https://github.com/dustenhubbard/pyreconstruct/compare/base...v{OFFERED}"),
        ]:
            cursor = browser.document().find(label)
            assert cursor.charFormat().isAnchor()
            assert cursor.charFormat().fontUnderline()
            assert cursor.charFormat().foreground().color() == browser.palette().color(QPalette.Link)
            cursor.setPosition(cursor.selectionStart() + 1)
            browser.setTextCursor(cursor)
            browser.ensureCursorVisible()
            qtbot.mouseClick(browser.viewport(), Qt.LeftButton, pos=browser.cursorRect(cursor).center())
            assert receiver.urls[-1] == target
        palette = browser.palette()
        palette.setColor(QPalette.Link, Qt.darkGreen)
        browser.setPalette(palette)
        cursor = browser.document().find("Full Changelog")
        assert cursor.charFormat().foreground().color() == palette.color(QPalette.Link)
    finally:
        QDesktopServices.unsetUrlHandler("https")


@pytest.mark.gui
def test_release_without_prs_still_shows_its_full_changelog(qtbot, update_feed):
    url = f"https://github.com/dustenhubbard/pyreconstruct/compare/base...v{OFFERED}"
    update_feed[2]["body"] = f"Nightly build from main.\n\n**Full Changelog**: {url}\n"
    dialog = dialog_for("frozen", "prerelease")
    qtbot.addWidget(dialog)
    browser = dialog.findChild(QTextBrowser)
    cursor = browser.document().find("Full Changelog")
    assert cursor.charFormat().anchorHref() == url
