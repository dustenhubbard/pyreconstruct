"""The Dev flavor is one environment variable wide.

Packaging stamps PYRECON_APP_NAME (packaging/rthook_flavor.py, bundled only
when packaging/FLAVOR says "dev"), and everything that distinguishes the two
side-by-side apps reads it at call time: the window title, the global
QSettings domain, the per-series settings store, the pinned update channel,
and the series ownership marker. These pin that seam.
"""
import pytest

from PyReconstruct.modules.constants.settings_domain import settings_app, settings_domain
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.backend.updater.updater import pinned_channel
from PyReconstruct.modules.datatypes.series_owner import app_display_name


def test_stable_defaults(monkeypatch):
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    assert settings_domain() == ("KHLab", "PyReconstruct")
    assert QSettingsStore().APP == "PyReconstruct"
    assert pinned_channel() == "release"
    assert app_display_name() == "PyReconstruct"


def test_dev_flavor_is_fully_isolated(monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    assert settings_app() == "PyReconstruct Dev"
    assert QSettingsStore().APP == "PyReconstruct Dev"
    assert pinned_channel() == "prerelease"
    assert app_display_name() == "PyReconstruct Dev"


def test_flavor_file_marks_this_branch_dev():
    """main carries packaging/FLAVOR=dev; the release line carries none."""
    import os
    here = os.path.join(os.path.dirname(__file__), "..", "packaging", "FLAVOR")
    assert open(here).read().strip() == "dev"


def test_rthook_stamps_but_never_overrides(monkeypatch):
    import runpy, os
    hook = os.path.join(os.path.dirname(__file__), "..", "packaging", "rthook_flavor.py")
    # setenv-then-delenv leaves a restore record, so the hook's own write is
    # rolled back at teardown (a bare delenv on an unset name records nothing,
    # and the hook's setdefault would leak into the rest of the suite)
    monkeypatch.setenv("PYRECON_APP_NAME", "placeholder")
    monkeypatch.delenv("PYRECON_APP_NAME")
    runpy.run_path(hook)
    assert os.environ["PYRECON_APP_NAME"] == "PyReconstruct Dev"
    monkeypatch.setenv("PYRECON_APP_NAME", "elsewhere")
    runpy.run_path(hook)
    assert os.environ["PYRECON_APP_NAME"] == "elsewhere"
