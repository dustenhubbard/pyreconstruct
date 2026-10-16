"""Shared setup for the tests of the copy from the old ``KHLab`` settings.

Every store here is one of the suite's redirected stores; ``empty_stores``
checks that before it empties any of them.
"""

from PySide6.QtCore import QSettings

import qsettings_isolation
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as D
from PyReconstruct.modules.datatypes.series import Series

DEV = "PyReconstruct Dev"
DAMAGED = "[broken\nentry=value\n"
# the global stores, and the per-series stores of the bare series below
_APPS = (D.SHARED_APP, DEV, f"{D.SHARED_APP}-COPYTEST", f"{DEV}-COPYTEST")


def _empty(settings):
    settings.setFallbacksEnabled(False)
    assert settings.fileName().startswith(qsettings_isolation.isolation_root)
    for key in settings.allKeys():
        settings.remove(key)
    settings.sync()


def empty_stores(*apps):
    """Empty ``apps`` under both organizations, and forget what this process
    learned about their copies."""
    getattr(D, "_copy_pending", {}).clear()
    getattr(D, "_unparsable_legacy", set()).clear()
    for org in (D.SETTINGS_ORG, D.LEGACY_SETTINGS_ORG):
        for app in apps:
            _empty(QSettings(org, app))


def bare_series_store(monkeypatch):
    """Empty global stores, and a bare series reading them through the
    QSettings store. Yields the series and the old and new shared stores; a
    test module makes it its ``setup_store`` fixture."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    empty_stores(*_APPS)
    series = Series.__new__(Series)
    series.options = {}
    series.code = "COPYTEST"
    series.jser_fp = "/new.jser"
    monkeypatch.setattr(series, "isWelcomeSeries", lambda: False)
    series.setSettingsStore(QSettingsStore())
    old = QSettings(D.LEGACY_SETTINGS_ORG, D.SHARED_APP)
    new = QSettings(D.SETTINGS_ORG, D.SHARED_APP)
    old.setFallbacksEnabled(False)
    new.setFallbacksEnabled(False)
    yield series, old, new
    empty_stores(*_APPS)


def fail_copy(monkeypatch, app=D.SHARED_APP):
    """Make ``KHLab / <app>`` report a read error until ``monkeypatch`` undoes it."""
    real = QSettings.status

    def status(self):
        if (self.organizationName(), self.applicationName()) == (
            D.LEGACY_SETTINGS_ORG, app,
        ):
            return QSettings.AccessError
        return real(self)

    monkeypatch.setattr(QSettings, "status", status)
