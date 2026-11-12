"""Help submenus retain their commands and open the public reference pages."""

import sys

import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel

from PyReconstruct.modules.backend.func import logging_setup
from PyReconstruct.modules.gui.main.menu_search import collect_menu_commands
from PyReconstruct.modules.gui.utils import errors

pytestmark = pytest.mark.gui


def test_diagnostics_commands_and_search_paths(main_window, monkeypatch):
    calls = []
    for name in (
        "copyDiagnosticReport", "openWebsite", "openIssueForm",
        "viewLogFile", "openLogFolder",
    ):
        monkeypatch.setattr(
            main_window, name,
            lambda *args, method=name: calls.append((method, args)),
        )
    main_window.createMenuBar()

    diagnostics = main_window.diagnosticsmenu
    assert diagnostics.title() == "Diagnostics"
    expected = [
        "Copy diagnostic report...", "Email developers", "Report a bug...",
        "Request a feature...", "See unresolved issues", "View log file...",
        "Open log folder",
    ]
    assert [action.text() for action in diagnostics.actions()] == expected
    assert main_window.helpmenu.actions().index(diagnostics.menuAction()) < (
        main_window.helpmenu.actions().index(main_window.onlinemenu.menuAction())
    )
    assert all(
        action not in main_window.helpmenu.actions()
        for action in diagnostics.actions()
    )

    paths = [path for path, *_ in collect_menu_commands(main_window.menubar)]
    assert [path for path in paths if path.startswith("Help > Diagnostics > ")] == [
        "Help > Diagnostics > " + label.removesuffix("...") for label in expected
    ]
    for action in diagnostics.actions():
        action.trigger()
    assert calls == [
        ("copyDiagnosticReport", ()),
        ("openWebsite", ("mailto:issues@pyreconstruct.org",)),
        ("openIssueForm", ("https://github.com/dustenhubbard/PyReconstruct/issues/new?template=bug.yml",)),
        ("openIssueForm", ("https://github.com/dustenhubbard/PyReconstruct/issues/new?template=feature.yml",)),
        ("openWebsite", ("https://github.com/dustenhubbard/PyReconstruct/issues",)),
        ("viewLogFile", ()),
        ("openLogFolder", ()),
    ]


def test_exception_dialog_log_path_matches_live_menu(
    main_window, qtbot, monkeypatch, tmp_path,
):
    summaries = []

    def capture_dialog(dialog):
        qtbot.addWidget(dialog)
        for label in dialog.findChildren(QLabel):
            document = QTextDocument()
            document.setHtml(label.text())
            summaries.append(document.toPlainText())
        return 0

    monkeypatch.setattr(errors.ErrorReportDialog, "exec", capture_dialog)
    monkeypatch.setattr(errors, "_reported_signatures", set())
    monkeypatch.setattr(errors, "_showing_report", False)
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: None)
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: tmp_path / "error.log")

    try:
        raise RuntimeError("Log breadcrumb regression")
    except RuntimeError:
        errors.customExcepthook(*sys.exc_info())

    paths = [
        path for path, _, _, action in collect_menu_commands(main_window.menubar)
        if action == main_window.viewlog_act
    ]
    assert paths == ["Help > Diagnostics > View log file"]
    assert len(summaries) == 1
    assert f"({paths[0]}) instead of opening another window." in summaries[0]


@pytest.mark.parametrize("label,url", [
    ("PyReconstruct user guide", "https://pyreconstruct.org/USER_GUIDE/"),
    ("Harris lab wiki", "https://pyreconstruct.org/harrislabwiki/"),
    ("PyReconstruct lab wiki guide",
     "https://cloud.wikis.utexas.edu/wiki/spaces/khlab/pages/53543200/PyReconstruct+user+guide"),
])
def test_online_resources_open_the_public_guides(main_window, monkeypatch, label, url):
    opened = []
    monkeypatch.setattr(main_window, "openWebsite", opened.append)
    main_window.createMenuBar()
    action = next(
        action for action in main_window.onlinemenu.actions()
        if action.text() == label
    )
    action.trigger()
    assert opened == [url]
