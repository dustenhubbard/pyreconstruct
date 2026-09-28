"""Regression test for the in-app menu navigation targets.

This is a fork of PyReconstruct. All in-app menu links point at the fork, not the
upstream SynapseWeb project (upstream is credited in the README and About dialog).
The Help menu's "See unresolved issues" and "Report bug / Request feature"
actions open ``gh_issues`` / ``gh_submit`` and the Help ▸ Online resources ▸
"PyReconstruct source code" action opens ``gh_repo`` (constants in
``PyReconstruct.modules.constants.websites``), so all three must resolve to the
fork. This test documents that so none of them drift
back to upstream.

The same goes for Help ▸ "Email developers": it writes to the fork's shared
address (``PyReconstruct.modules.constants.developers``), not to the original
developers' personal addresses (fork #458).

Importing the constants modules is Qt-free, so the tests run headless.
"""
from PyReconstruct.modules.constants import developers, websites


FORK_REPO = "https://github.com/dustenhubbard/PyReconstruct"
FORK_ISSUES = FORK_REPO + "/issues"


def test_report_issues_points_at_fork():
    # "See unresolved issues" opens gh_issues directly.
    assert websites.gh_issues == FORK_ISSUES
    # "Report bug / Request feature" opens gh_submit, derived from gh_issues.
    assert websites.gh_submit == FORK_ISSUES + "/new/choose"


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
