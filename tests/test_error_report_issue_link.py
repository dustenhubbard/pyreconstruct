"""The report dialogs' buttons open the bug form and a mail with the report in them.

``ErrorReportDialog`` is every copyable report window: the crash hook, the
handled save failure, and Help > Copy diagnostic report. Filing the report is
the main thing to do there, so "Report a bug on GitHub" is a button and the
default one, next to "Email developers", "Copy report to clipboard" and "Close"
(#470). The bug form gets the report in its error field and the setup lines in
"About your setup"; the diagnostic report, which has no error, fills the setup
field alone. The mail goes to the Help menu's address with the report as the
body.

The buttons are clicked for real; only the hand-off to the OS is replaced, so
nothing opens a browser or a mail client during the run.
"""
from urllib.parse import parse_qs, urlsplit

import pytest

from PySide6.QtCore import Qt

from PyReconstruct.modules.backend.func import error_report
from PyReconstruct.modules.gui.utils import errors

pytestmark = pytest.mark.gui

REPORT = "PyReconstruct error report\nVersion:  1.24.0\n\nValueError: boom"


@pytest.fixture(autouse=True)
def fixed_context(monkeypatch):
    monkeypatch.setattr(error_report, "_context_lines", lambda: ["Version:  1.24.0"])


@pytest.fixture
def opened(monkeypatch):
    urls = []
    def fake_open(url):
        urls.append(url)
        return True
    monkeypatch.setattr(errors, "_open_url", fake_open)
    return urls


def _dialog(qtbot, *args, **kwargs):
    dialog = errors.ErrorReportDialog(*args, **kwargs)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _buttons(dialog):
    from PySide6.QtWidgets import QPushButton
    return {b.text(): b for b in dialog.findChildren(QPushButton)}


def test_the_window_has_the_four_buttons_and_reporting_is_the_default(qtbot):
    dialog = _dialog(qtbot, "<b>An error occurred</b>", REPORT)
    buttons = _buttons(dialog)
    assert set(buttons) == {
        "Report a bug on GitHub",
        "Email developers",
        "Copy report to clipboard",
        "Close",
    }
    assert buttons["Report a bug on GitHub"].isDefault()
    assert not buttons["Close"].isDefault()


def test_report_button_opens_the_bug_form_with_the_report(qtbot, opened):
    dialog = _dialog(qtbot, "<b>An error occurred</b>", REPORT)
    qtbot.mouseClick(_buttons(dialog)["Report a bug on GitHub"], Qt.LeftButton)
    assert len(opened) == 1
    parts = urlsplit(opened[0])
    assert parts.netloc + parts.path == "github.com/dustenhubbard/PyReconstruct/issues/new"
    query = parse_qs(parts.query, strict_parsing=True)
    assert query["template"] == ["bug.yml"]
    assert query["setup"] == ["Version:  1.24.0"]
    assert query["error"] == [REPORT]


def test_email_button_opens_a_mail_with_the_report(qtbot, opened):
    dialog = _dialog(qtbot, "<b>An error occurred</b>", REPORT)
    qtbot.mouseClick(_buttons(dialog)["Email developers"], Qt.LeftButton)
    assert len(opened) == 1
    parts = urlsplit(opened[0])
    assert (parts.scheme, parts.path) == ("mailto", "issues@pyreconstruct.org")
    query = parse_qs(parts.query, strict_parsing=True)
    assert query["subject"] == ["PyReconstruct error report"]
    assert query["body"] == [REPORT.replace("\n", "\r\n")]


def test_diagnostic_window_fills_the_setup_field_only(qtbot, opened, monkeypatch):
    # show_diagnostic_report hands its setup-only link through show_error_report;
    # exec is replaced by a click on the report button.
    def click_report(dialog):
        qtbot.addWidget(dialog)
        qtbot.mouseClick(_buttons(dialog)["Report a bug on GitHub"], Qt.LeftButton)
        return 0
    monkeypatch.setattr(errors.ErrorReportDialog, "exec", click_report)
    errors.show_diagnostic_report()
    query = parse_qs(urlsplit(opened[0]).query, strict_parsing=True)
    assert query["template"] == ["bug.yml"]
    assert query["setup"] == ["Version:  1.24.0"]
    assert "error" not in query


def test_summary_says_it_once_with_no_text_link():
    # The button replaces the old "open a bug report on GitHub" link, so the
    # window names the report path once (#470).
    crash = errors._standard_summary("<b>An error occurred</b>", REPORT)
    diagnostic = errors._standard_summary("<b>Diagnostic report</b>")
    for summary in (crash, diagnostic):
        assert "<a " not in summary and "href" not in summary
        assert "<b>Report a bug on GitHub</b>" in summary
        assert "<b>Email developers</b>" in summary
    assert "with this report already filled in" in crash
    assert "with your version and OS already filled in" in diagnostic


def test_open_url_hands_qt_the_link_unchanged(monkeypatch):
    # The links arrive percent-encoded; Qt must get them as they are, not
    # encoded a second time (a "%0D%0A" turned into "%250D%250A" would put the
    # escape codes in the mail instead of line breaks).
    from PySide6.QtCore import QUrl
    got = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url):
            got.append(url)
            return True

    monkeypatch.setattr(errors, "QDesktopServices", FakeDesktop)
    for url in (
        error_report.mailto_for_report("issues@pyreconstruct.org", REPORT),
        error_report.issue_url_for_report("https://github.com/o/r/issues/new?template=bug.yml", REPORT),
    ):
        errors._open_url(url)
        assert got[-1].toString(QUrl.FullyEncoded) == url


@pytest.mark.parametrize(
    "label, program",
    [("Email developers", "email program"), ("Report a bug on GitHub", "web browser")],
)
def test_a_link_the_os_cannot_open_says_so_and_names_the_address(
    qtbot, monkeypatch, label, program
):
    # With no mail program set up, openUrl returns False. The click must not
    # do nothing: a message names the copy button and the address (#470).
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: False))
    shown = []
    monkeypatch.setattr(
        errors.QMessageBox, "information", staticmethod(lambda *args: shown.append(args))
    )
    dialog = _dialog(qtbot, "<b>An error occurred</b>", REPORT)
    qtbot.mouseClick(_buttons(dialog)[label], Qt.LeftButton)
    assert len(shown) == 1
    title, text = shown[0][1], shown[0][2]
    assert title == "Could not open link"
    assert f"could not open your {program}" in text
    assert "Copy report to clipboard" in text
    assert "issues@pyreconstruct.org" in text
