"""The report dialogs link to the GitHub bug form with their report filled in.

``_standard_summary`` is the heading every copyable report dialog shows (the
crash hook, the handled save failure, and Help > Copy diagnostic report). Its
link used to be the bare issues page; now it is the bug form, with the setup
field prefilled always and the error field prefilled when the dialog carries a
report. Pure string work, so no QApplication is needed.
"""
import html
from urllib.parse import parse_qs, urlsplit

import pytest

from PyReconstruct.modules.backend.func import error_report
from PyReconstruct.modules.constants import websites
from PyReconstruct.modules.gui.utils import errors


@pytest.fixture(autouse=True)
def fixed_context(monkeypatch):
    monkeypatch.setattr(error_report, "_context_lines", lambda: ["Version:  1.24.0"])


def _href(summary_html: str) -> str:
    start = summary_html.index('href="') + len('href="')
    end = summary_html.index('"', start)
    return html.unescape(summary_html[start:end])


def test_crash_summary_links_the_bug_form_with_the_report():
    report = "PyReconstruct error report\nVersion:  1.24.0\n\nValueError: boom"
    summary = errors._standard_summary("<b>An error occurred</b>", report)
    url = _href(summary)
    parts = urlsplit(url)
    assert parts.netloc + parts.path == "github.com/dustenhubbard/PyReconstruct/issues/new"
    query = parse_qs(parts.query, strict_parsing=True)
    assert query["template"] == ["bug.yml"]
    assert query["setup"] == ["Version:  1.24.0"]
    assert query["error"] == [report]
    assert "with this report already filled in" in summary
    # the bare issues page is no longer the link
    assert websites.gh_issues + '"' not in summary


def test_diagnostic_summary_links_the_bug_form_with_setup_only():
    summary = errors._standard_summary("<b>Diagnostic report</b>")
    query = parse_qs(urlsplit(_href(summary)).query, strict_parsing=True)
    assert query["template"] == ["bug.yml"]
    assert query["setup"] == ["Version:  1.24.0"]
    assert "error" not in query
    assert "with your version and OS already filled in" in summary


def test_summary_href_is_escaped_for_rich_text():
    # Qt's rich text is HTML: the query string's ampersands must arrive as
    # entities so the label does not try to read them as entity starts.
    summary = errors._standard_summary("lead", "ValueError: x")
    href_attr = summary[summary.index('href="') + 6 : summary.index('">open a bug report')]
    assert "&amp;" in href_attr
    assert "&setup" not in href_attr and "&error" not in href_attr
