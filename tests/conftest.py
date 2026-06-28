"""Shared test fixtures.

The autouse ``_isolate_qsettings`` fixture redirects every per-user config location
(env + Qt's QSettings paths) to a session temp dir BEFORE any QSettings or QApplication
is constructed, so a test run can never read or clobber the user's real preferences.
It asserts the isolation actually took effect and aborts the run otherwise — important
for unattended runs that exercise setOption/getOption round-trips.
"""

import os

import pytest

# Project-wide QSettings identity (mirrors PyReconstruct.modules.gui.utils.theme).
QSETTINGS_ORG = "KHLab"
QSETTINGS_APP = "PyReconstruct"


@pytest.fixture(scope="session", autouse=True)
def _isolate_qsettings(tmp_path_factory):
    cfg = tmp_path_factory.mktemp("qsettings_home")

    # Belt: redirect the env vars Qt / the OS use to locate per-user config + data.
    for var in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        os.environ[var] = str(cfg)

    # Suspenders: pin QSettings to the temp dir explicitly (works even if env is ignored).
    try:
        from PySide6.QtCore import QSettings
    except Exception:
        # No Qt available — env redirect still stands; pure-logic tests run fine.
        yield cfg
        return

    QSettings.setDefaultFormat(QSettings.IniFormat)
    for scope in (QSettings.UserScope, QSettings.SystemScope):
        QSettings.setPath(QSettings.IniFormat, scope, str(cfg))

    resolved = QSettings(QSETTINGS_ORG, QSETTINGS_APP).fileName()
    assert str(cfg) in resolved, (
        f"QSettings is NOT isolated to the temp dir (resolved to {resolved!r}); "
        "aborting so the run cannot touch real user preferences."
    )

    yield cfg


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for widget tests (offscreen). Reuses the singleton so it
    coexists with any module-local qapp fixtures."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
