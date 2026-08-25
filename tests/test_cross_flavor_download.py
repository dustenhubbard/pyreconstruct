"""The Help-menu cross-flavor download row.

The two builds install side by side, but nothing pointed a user of one at the
other: legacy Beta-channel users in particular hold a lone beta install and no
stable. Each build's Help menu now carries a download row for the OTHER build,
resolved at click time so it always lands on the latest of that flavor:

* Dev build -> GitHub's ``releases/latest`` redirect (always the newest
  stable, no API call to go wrong).
* stable build -> the newest curated beta, looked up through the same release
  list the updater reads, with the same exclusions (drafts, the rolling tag).
  Any failure falls back to the releases index.
"""

import pytest

from PyReconstruct.modules.backend.updater import updater as U

pytestmark = pytest.mark.gui

BASE = f"https://github.com/{U.GITHUB_REPO}/releases"


def _releases():
    return [
        {"tag_name": "v1.24.0-beta-9", "prerelease": True, "draft": True,
         "html_url": f"{BASE}/tag/v1.24.0-beta-9"},          # draft: never offered
        {"tag_name": U.ROLLING_TAG, "prerelease": True, "draft": False,
         "html_url": f"{BASE}/tag/{U.ROLLING_TAG}"},          # rolling: excluded
        {"tag_name": "v1.23.0-beta-2", "prerelease": True, "draft": False,
         "html_url": f"{BASE}/tag/v1.23.0-beta-2"},           # the answer
        {"tag_name": "v1.22.1", "prerelease": False, "draft": False,
         "html_url": f"{BASE}/tag/v1.22.1"},
    ]


def test_stable_build_gets_the_newest_beta(monkeypatch):
    monkeypatch.setattr(U, "pinned_channel", lambda: "release")
    monkeypatch.setattr(U, "fetch_releases", lambda timeout=6: _releases())
    assert U.other_flavor_url() == f"{BASE}/tag/v1.23.0-beta-2"


def test_dev_build_gets_the_latest_stable_without_the_api(monkeypatch):
    def boom(timeout=6):
        raise AssertionError("the Dev side must not call the API")
    monkeypatch.setattr(U, "pinned_channel", lambda: "prerelease")
    monkeypatch.setattr(U, "fetch_releases", boom)
    assert U.other_flavor_url() == f"{BASE}/latest"


def test_offline_falls_back_to_the_releases_index(monkeypatch):
    def offline(timeout=6):
        raise RuntimeError("Could not reach GitHub")
    monkeypatch.setattr(U, "pinned_channel", lambda: "release")
    monkeypatch.setattr(U, "fetch_releases", offline)
    assert U.other_flavor_url() == BASE


def test_no_beta_after_a_final_falls_back_to_the_index(monkeypatch):
    """Right after a final ships, prune-betas may leave no beta at all."""
    stables_only = [r for r in _releases() if not r.get("prerelease")]
    monkeypatch.setattr(U, "pinned_channel", lambda: "release")
    monkeypatch.setattr(U, "fetch_releases", lambda timeout=6: stables_only)
    assert U.other_flavor_url() == BASE


def test_help_menu_carries_the_row_and_labels_it_by_flavor(monkeypatch):
    from types import SimpleNamespace
    import PyReconstruct.modules.datatypes.series_owner as owner
    from PyReconstruct.modules.gui.main import menubar

    self = SimpleNamespace(
        series=None,
        copyCommit=None, checkForUpdates=None, toggleUpdateCheckOnStartup=None,
        showWhatsNew=None, toggleWhatsNewPopup=None, openMenuSearch=None,
        displayShortcuts=None, openWebsite=None, downloadExample=None,
        copyDiagnosticReport=None, viewLogFile=None, openLogFolder=None,
        openOtherFlavorPage="HANDLER",
    )

    monkeypatch.setattr(owner, "app_display_name", lambda: "PyReconstruct")
    opts = menubar.return_help_menu(self)["opts"]
    row = next(o for o in opts if isinstance(o, tuple) and o[0] == "getotherflavor_act")
    assert row[1] == "Download PyReconstruct Dev (beta)..."
    assert row[3] == "HANDLER"

    monkeypatch.setattr(owner, "app_display_name", lambda: "PyReconstruct Dev")
    opts = menubar.return_help_menu(self)["opts"]
    row = next(o for o in opts if isinstance(o, tuple) and o[0] == "getotherflavor_act")
    assert row[1] == "Download PyReconstruct (stable)..."
