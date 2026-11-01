"""Help submenus retain their commands and open the public reference pages."""

import pytest

from PyReconstruct.modules.gui.main.menu_search import collect_menu_commands

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
