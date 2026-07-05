"""Regression test for the in-app 'Report issues' target.

This is a fork of PyReconstruct. Bug reports and feature requests belong on the
fork's own issue tracker, not the upstream SynapseWeb project. The Help ▸ Report
issues (GitHub) menu actions open ``gh_issues`` / ``gh_submit`` (constants in
``PyReconstruct.modules.constants.websites``), so those must resolve to the fork.

The source-code provenance link (Help ▸ Online resources ▸ "PyReconstruct source
code") uses ``gh_repo`` and intentionally stays pointed at upstream. This test
documents that split so neither side drifts back.

Importing the constants module is Qt-free, so the test runs headless.
"""
from PyReconstruct.modules.constants import websites


FORK_ISSUES = "https://github.com/dustenhubbard/PyReconstruct/issues"
UPSTREAM_REPO = "https://github.com/SynapseWeb/PyReconstruct"


def test_report_issues_points_at_fork():
    # "See unresolved issues" opens gh_issues directly.
    assert websites.gh_issues == FORK_ISSUES
    # "Report bug / Request feature" opens gh_submit, derived from gh_issues.
    assert websites.gh_submit == FORK_ISSUES + "/new/choose"


def test_source_code_link_stays_upstream():
    # The provenance link is intentionally left on the upstream project.
    assert websites.gh_repo == UPSTREAM_REPO
