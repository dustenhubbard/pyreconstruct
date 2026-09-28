"""Regression test for the in-app menu navigation targets.

This is a fork of PyReconstruct. All in-app menu links point at the fork, not the
upstream SynapseWeb project (upstream is credited in the README and About dialog).
The Help menu's "See unresolved issues" row opens ``gh_issues``, its "Report a
bug..." / "Request a feature..." rows open the two issue forms ``gh_bug_form`` /
``gh_feature_form``, and the Help ▸ Online
resources ▸ "PyReconstruct source code" action opens ``gh_repo`` (constants in
``PyReconstruct.modules.constants.websites``), so all of them must resolve to
the fork. This test documents that so none of them drift back to upstream.

The two form rows open the form directly, not GitHub's chooser page, because
only a direct form link can carry a prefilled field: ``prefilled_issue_url``
appends the diagnostic report's version/OS/Python lines as the ``setup`` query
parameter, which is the id of the "About your setup" textarea in both forms.

The same goes for Help ▸ "Email developers": it writes to the fork's shared
address (``PyReconstruct.modules.constants.developers``), not to the original
developers' personal addresses (fork #458).

Importing the constants modules is Qt-free, so the tests run headless.
"""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PyReconstruct.modules.backend.func import error_report
from PyReconstruct.modules.constants import developers, websites

_FORMS_DIR = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE"


FORK_REPO = "https://github.com/dustenhubbard/PyReconstruct"
FORK_ISSUES = FORK_REPO + "/issues"


def test_report_issues_points_at_fork():
    # "See unresolved issues" opens gh_issues directly.
    assert websites.gh_issues == FORK_ISSUES
    # "Report a bug..." / "Request a feature..." open their forms directly,
    # each derived from gh_issues and naming its .yml under ISSUE_TEMPLATE.
    assert websites.gh_bug_form == FORK_ISSUES + "/new?template=bug.yml"
    assert websites.gh_feature_form == FORK_ISSUES + "/new?template=feature.yml"
    # ...and those two files exist; a renamed form would silently send the
    # filer to the chooser page with nothing prefilled.
    assert (_FORMS_DIR / "bug.yml").is_file()
    assert (_FORMS_DIR / "feature.yml").is_file()


def test_prefilled_issue_url_carries_the_diagnostic_lines(monkeypatch):
    monkeypatch.setattr(
        error_report, "_context_lines",
        lambda: ["Version:  1.24.0", "Platform: macOS-15.0-arm64", "Python:   3.11.9"],
    )
    url = error_report.prefilled_issue_url(websites.gh_bug_form)
    parts = urlsplit(url)
    assert parts.scheme + "://" + parts.netloc + parts.path == FORK_ISSUES + "/new"
    query = parse_qs(parts.query, strict_parsing=True)
    # template= survives untouched; setup= is the report's lines, newline-joined.
    assert query["template"] == ["bug.yml"]
    assert query["setup"] == ["Version:  1.24.0\nPlatform: macOS-15.0-arm64\nPython:   3.11.9"]
    # ...and "setup" is the id the forms declare for the "About your setup"
    # textarea, in both forms (GitHub prefills a field from a same-named param).
    for form in ("bug.yml", "feature.yml"):
        assert "id: setup" in (_FORMS_DIR / form).read_text(encoding="utf-8")


def test_prefilled_issue_url_falls_back_to_the_plain_form(monkeypatch):
    # No context (every lookup failed): the plain form URL, nothing appended.
    monkeypatch.setattr(error_report, "_context_lines", lambda: [])
    assert error_report.prefilled_issue_url(websites.gh_bug_form) == websites.gh_bug_form
    # A builder that raises must not take the menu action down with it.
    def boom():
        raise RuntimeError("no platform")
    monkeypatch.setattr(error_report, "_context_lines", boom)
    assert error_report.prefilled_issue_url(websites.gh_feature_form) == websites.gh_feature_form


def test_source_code_link_points_at_fork():
    # The "PyReconstruct source code" menu link opens the fork, like every other
    # in-app menu link; upstream provenance is credited in the README/About.
    assert websites.gh_repo == FORK_REPO


def test_email_developers_writes_to_the_fork_address():
    # "Email developers" opens developers_mailto_str; one shared fork address,
    # no personal addresses (fork #458).
    assert developers.developers_email == "issues@pyreconstruct.org"
    assert developers.developers_mailto_str == "mailto:issues@pyreconstruct.org"
    assert "utexas.edu" not in developers.developers_mailto_str


def test_issue_url_for_report_fills_both_fields(monkeypatch):
    monkeypatch.setattr(error_report, "_context_lines", lambda: ["Version:  1.24.0"])
    report = "PyReconstruct error report\nVersion:  1.24.0\n\nTraceback...\nValueError: boom"
    url = error_report.issue_url_for_report(websites.gh_bug_form, report)
    query = parse_qs(urlsplit(url).query, strict_parsing=True)
    assert query["template"] == ["bug.yml"]
    assert query["setup"] == ["Version:  1.24.0"]
    # the whole report, untrimmed, in the form's error field
    assert query["error"] == [report]
    assert "id: error" in (_FORMS_DIR / "bug.yml").read_text(encoding="utf-8")


def test_issue_url_for_report_trims_a_long_report_to_fit(monkeypatch):
    monkeypatch.setattr(error_report, "_context_lines", lambda: ["Version:  1.24.0"])
    head = "PyReconstruct error report\nVersion:  1.24.0\n\nTraceback (most recent call last):\n"
    frames = "".join(f'  File "deep/module_{i}.py", line {i}, in step\n    do_thing({i})\n' for i in range(600))
    tail = "ValueError: the raise site names the bug"
    report = head + frames + tail
    url = error_report.issue_url_for_report(websites.gh_bug_form, report)
    assert len(url) <= error_report.ISSUE_URL_MAX_CHARS
    error = parse_qs(urlsplit(url).query, strict_parsing=True)["error"][0]
    # the head (version lines, start of the traceback) and the tail (the raise
    # site and message) both survive; the cut is marked in the middle
    assert error.startswith(head)
    assert error.endswith(tail)
    assert error_report.REPORT_TRIM_MARKER in error


def test_issue_url_for_report_without_a_report_is_the_setup_link(monkeypatch):
    monkeypatch.setattr(error_report, "_context_lines", lambda: ["Version:  1.24.0"])
    assert (error_report.issue_url_for_report(websites.gh_bug_form, "")
            == error_report.prefilled_issue_url(websites.gh_bug_form))


def test_issue_url_for_report_survives_a_broken_context(monkeypatch):
    def boom():
        raise RuntimeError("no platform")
    monkeypatch.setattr(error_report, "_context_lines", boom)
    url = error_report.issue_url_for_report(websites.gh_bug_form, "ValueError: x")
    query = parse_qs(urlsplit(url).query, strict_parsing=True)
    assert query["template"] == ["bug.yml"]
    assert "setup" not in query
    assert query["error"] == ["ValueError: x"]
