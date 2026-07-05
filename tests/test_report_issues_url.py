"""Regression test for the in-app menu navigation targets.

This is a fork of PyReconstruct. All in-app menu links point at the fork, not the
upstream SynapseWeb project (upstream is credited in the README and About dialog).
The Help ▸ Report issues (GitHub) menu actions open ``gh_issues`` / ``gh_submit``
and the Help ▸ Online resources ▸ "PyReconstruct source code" action opens
``gh_repo`` (constants in ``PyReconstruct.modules.constants.websites``), so all
three must resolve to the fork. This test documents that so none of them drift
back to upstream.

Importing the constants module is Qt-free, so the test runs headless.
"""
from PyReconstruct.modules.constants import websites


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
