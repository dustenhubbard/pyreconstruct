"""Tests for the application theme engine (gui.utils.theme).

The theme defaults to the OS color scheme and can be overridden to
System / Light / Dark, persisted app-wide via QSettings. These pin:

  * the pure mode/scheme resolution (no Qt) over its full matrix, including the
    legacy "default"/"qdark" migration and the Unknown->dark fallback that keeps
    chrome and the app icon in agreement;
  * the Qt-backed pieces (skipped if PySide6/qdarkstyle are unavailable): that
    light and dark build distinct non-empty stylesheets carrying the accent
    token, that apply_theme installs one app-wide, and that the persisted choice
    round-trips through QSettings.

The Qt fixture redirects QSettings to a temp dir so a test run never touches the
user's real theme preference.
"""
import os
import pytest

from PyReconstruct.modules.gui.utils import theme as t


# --- pure logic (no Qt) ------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    ("system", "system"),
    ("light", "light"),
    ("dark", "dark"),
    ("default", "system"),   # legacy native default -> follow OS
    ("qdark", "dark"),        # legacy explicit dark -> dark
    (None, "system"),
    ("nonsense", "system"),
])
def test_normalize_mode(value, expected):
    assert t.normalize_mode(value) == expected


@pytest.mark.parametrize("mode,sys_light,expected", [
    ("light", None, "light"),
    ("light", True, "light"),
    ("light", False, "light"),
    ("dark", None, "dark"),
    ("dark", True, "dark"),
    ("dark", False, "dark"),
    ("system", True, "light"),
    ("system", False, "dark"),
    ("system", None, "dark"),   # Unknown OS scheme -> UNKNOWN_FALLBACK
])
def test_resolve_scheme(mode, sys_light, expected):
    assert t.resolve_scheme(mode, sys_light) == expected


def test_unknown_fallback_matches_icon_logic():
    # The shipped app-icon code treats an Unknown OS scheme as dark; the chrome
    # must agree so the two never diverge.
    assert t.UNKNOWN_FALLBACK == "dark"


# --- Qt-backed (skipped without PySide6 / qdarkstyle) ------------------------
@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    pytest.importorskip("PySide6")
    pytest.importorskip("qdarkstyle")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings
    # Redirect all Ini/UserScope settings into a temp dir for the whole module
    # so the real "KHLab/PyReconstruct" theme key is never written.
    cfg = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(cfg))
    app = QApplication.instance() or QApplication([])
    yield app


def test_build_stylesheet_light_dark_differ(qapp):
    light = t.build_stylesheet("light")
    dark = t.build_stylesheet("dark")
    assert light and dark, "stylesheets must be non-empty"
    assert light != dark, "light and dark must differ"
    assert t.ACCENT in light and t.ACCENT in dark, "accent token in both schemes"


def test_apply_theme_installs_stylesheet(qapp):
    for mode in ("light", "dark", "system"):
        scheme = t.apply_theme(qapp, mode)
        assert scheme in t.SCHEMES
        assert qapp.styleSheet(), f"mode {mode!r} left an empty app stylesheet"
        assert t.qss_active(qapp) is True


def test_toggle_changes_active_stylesheet(qapp):
    t.apply_theme(qapp, "light")
    light_ss = qapp.styleSheet()
    t.apply_theme(qapp, "dark")
    dark_ss = qapp.styleSheet()
    assert light_ss != dark_ss


def test_persist_roundtrip_and_legacy_migration(qapp):
    from PySide6.QtCore import QSettings
    for mode in ("system", "light", "dark"):
        t.write_mode(mode)
        assert t.read_mode() == mode
    # legacy stored values are migrated on read-back
    QSettings(t.QSETTINGS_ORG, t.QSETTINGS_APP).setValue(t.THEME_KEY, "qdark")
    assert t.read_mode() == "dark"
    QSettings(t.QSETTINGS_ORG, t.QSETTINGS_APP).setValue(t.THEME_KEY, "default")
    assert t.read_mode() == "system"
