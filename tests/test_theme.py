"""Tests for the application theme engine (gui.utils.theme).

The theme defaults to the OS color scheme and can be overridden to
System / Light / Dark / Studio / Atlas, persisted app-wide via QSettings.
These pin:

  * the pure mode/theme/scheme resolution (no Qt) over its full matrix,
    including the legacy "default"/"qdark" migration, the Unknown->dark
    fallback that keeps chrome and the app icon in agreement, and the named
    Studio/Atlas themes (their family, accent, and on-accent ink);
  * the qdarkstyle-base stylesheets (skipped if PySide6/qdarkstyle are
    unavailable): that the four concrete themes build distinct non-empty
    stylesheets, that the named themes carry the teal accent (and never the
    azure one, nor any leftover qdarkstyle hue), that light/dark are left
    untouched, that apply_theme installs one app-wide, and that the persisted
    choice round-trips through QSettings;
  * the Studio-layout chrome-token table (studio_tokens): its family selection,
    the single teal accent, the always-dark canvas in both shells, and the hard
    rule that no azure leaks into the Studio chrome.

The Qt fixture redirects QSettings to a temp dir so a test run never touches the
user's real theme preference.
"""
import os
import re
import pytest

from PyReconstruct.modules.gui.utils import theme as t


# the azure hues that must never appear in the Studio/Atlas chrome (the recurring
# first-attempt failure was azure #4c8dff leaking in from Refined Familiar)
AZURE_HUES = ("#4c8dff", "#3d8bd4")


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


# --- named themes ("Studio" / "Atlas"): pure logic (no Qt) -------------------
@pytest.mark.parametrize("value", ["studio", "atlas"])
def test_normalize_mode_named_themes(value):
    # the named themes are first-class selectable modes (round-trip unchanged)
    assert t.normalize_mode(value) == value


@pytest.mark.parametrize("mode,sys_light,expected", [
    ("studio", None, "studio"),   # an explicit named theme ignores the OS
    ("studio", True, "studio"),
    ("atlas", None, "atlas"),
    ("atlas", False, "atlas"),
    ("light", True, "light"),
    ("dark", False, "dark"),
    ("system", True, "light"),
    ("system", False, "dark"),
    ("system", None, "dark"),     # Unknown OS scheme -> UNKNOWN_FALLBACK
])
def test_resolve_theme(mode, sys_light, expected):
    assert t.resolve_theme(mode, sys_light) == expected


@pytest.mark.parametrize("mode,family", [
    ("studio", "dark"),   # Studio is dark-family (drives the dark app-icon glyph)
    ("atlas", "light"),   # Atlas is light-family
    ("light", "light"),
    ("dark", "dark"),
])
def test_named_theme_family(mode, family):
    # resolve_scheme stays a light/dark answer even for the named themes, so the
    # app-icon glyph and tool-icon tint keep working unchanged.
    assert t.resolve_scheme(mode, None) == family


def test_modes_themes_schemes_consistent():
    assert set(t.THEMES) <= set(t.MODES)
    assert set(t.MODES) - set(t.THEMES) == {"system"}   # system is the only non-theme mode
    assert set(t.SCHEMES) == {"light", "dark"}
    assert {"studio", "atlas"} <= set(t.THEMES)


def test_accent_and_icon_per_theme():
    # named themes share the teal accent; light/dark keep the azure one
    assert t.accent_color("studio") == t.accent_color("atlas") == t.STUDIO_ACCENT
    assert t.accent_color("light") == t.accent_color("dark") == t.ACCENT
    assert t.STUDIO_ACCENT != t.ACCENT
    # tool-icon tints differ per theme and are never the accent itself
    for theme_name in t.THEMES:
        assert t.icon_color(theme_name) not in (t.ACCENT, t.STUDIO_ACCENT)
    assert t.icon_color("studio") != t.icon_color("atlas")


def test_accent_text_per_theme():
    # white ink reads on the azure light/dark accent; the brighter Studio/Atlas
    # teal needs a dark ink instead (white on #37c0a6 is ~2.3:1, a WCAG fail).
    assert t.accent_text("light") == t.accent_text("dark") == t.ACCENT_TEXT == "#ffffff"
    for named in ("studio", "atlas"):
        assert t.accent_text(named) != t.ACCENT_TEXT, "teal needs a dark on-accent ink"
        assert t.accent_text(named) == t.STUDIO_GROUND


def test_remap_leaves_longer_hex_intact():
    # The remap targets only whole 6-digit tokens: a longer (8-digit alpha) hex
    # must be left untouched, not partially rewritten.
    class _P:
        COLOR_X = "#19232d"
    src = "a{color:#19232d}b{color:#19232dff}"
    out = t._remap_palette(src, _P, {"COLOR_X": "#0c0f14"})
    assert "a{color:#0c0f14}" in out   # standalone 6-digit token was remapped
    assert "#19232dff" in out          # 8-digit token left intact (not corrupted)


# --- Studio-layout chrome tokens (studio_tokens): pure logic (no Qt) ---------
def test_studio_tokens_family_selection():
    # Studio and bare "dark" share the dark shell; Atlas and "light" the light.
    assert t.studio_tokens("studio") == t.studio_tokens("dark")
    assert t.studio_tokens("atlas") == t.studio_tokens("light")
    assert t.studio_tokens("studio")["family"] == "dark"
    assert t.studio_tokens("atlas")["family"] == "light"
    # the shells differ on the neutral ground but never on the accent
    assert t.studio_tokens("studio")["bg"] == "#0c0f14"
    assert t.studio_tokens("atlas")["bg"] == "#f4f6fa"


def test_studio_tokens_one_teal_accent_dark_ink():
    for shell in ("studio", "atlas"):
        tok = t.studio_tokens(shell)
        assert tok["accent"] == t.STUDIO_ACCENT == "#37c0a6"
        assert tok["on_accent"] == "#0c0f14", "dark ink on solid teal fills"
        # curation status hues are the fixed data palette, identical in both
        assert (tok["ok"], tok["warn"], tok["bad"]) == ("#3ecf8e", "#f4bd4f", "#f07a72")


def test_studio_tokens_canvas_dark_in_both_shells():
    # The EM canvas — and the glassy controls floating on it — stay dark in both
    # Studio and Atlas, so every canvas/float token is shell-independent.
    dark, light = t.studio_tokens("studio"), t.studio_tokens("atlas")
    for key in ("canvas_bg", "float_bg", "float_line", "float_ink", "scale_ink",
                "raised_dark", "accent", "on_accent", "ok", "warn", "bad"):
        assert dark[key] == light[key], f"{key} must match across shells"
    assert dark["canvas_bg"] == "#0c0f14"
    assert dark["float_bg"].startswith("rgba("), "alpha float bg needs Qt rgba(), not #rrggbbaa"


def test_studio_tokens_no_azure():
    # The hard rule: no azure anywhere in the Studio/Atlas chrome tokens.
    for shell in ("studio", "atlas"):
        blob = " ".join(str(v) for v in t.studio_tokens(shell).values()).lower()
        for azure in AZURE_HUES:
            assert azure not in blob, f"azure {azure} leaked into {shell} chrome tokens"


def test_studio_tokens_returns_fresh_copy():
    a = t.studio_tokens("studio")
    a["bg"] = "#ffffff"
    assert t.studio_tokens("studio")["bg"] == "#0c0f14", "caller mutation must not stick"


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
    for mode in ("light", "dark", "studio", "atlas", "system"):
        theme_applied = t.apply_theme(qapp, mode)
        assert theme_applied in t.THEMES
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
    for mode in ("system", "light", "dark", "studio", "atlas"):
        t.write_mode(mode)
        assert t.read_mode() == mode
    # legacy stored values are migrated on read-back
    QSettings(t.QSETTINGS_ORG, t.QSETTINGS_APP).setValue(t.THEME_KEY, "qdark")
    assert t.read_mode() == "dark"
    QSettings(t.QSETTINGS_ORG, t.QSETTINGS_APP).setValue(t.THEME_KEY, "default")
    assert t.read_mode() == "system"


# --- named themes: Qt-backed (skipped without PySide6 / qdarkstyle) ----------
def _hexes(qss):
    return {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}", qss)}


def test_studio_atlas_stylesheets_distinct_and_teal(qapp):
    light = t.build_stylesheet("light")
    dark = t.build_stylesheet("dark")
    studio = t.build_stylesheet("studio")
    atlas = t.build_stylesheet("atlas")
    for ss in (studio, atlas):
        assert ss, "named-theme stylesheet must be non-empty"
        assert t.STUDIO_ACCENT in ss, "named themes paint the teal accent"
    assert len({light, dark, studio, atlas}) == 4, "all four themes are distinct"
    # named themes carry teal (not azure); light/dark carry azure (not teal)
    assert t.ACCENT not in studio and t.ACCENT not in atlas
    assert t.STUDIO_ACCENT not in light and t.STUDIO_ACCENT not in dark


def test_studio_atlas_stylesheets_have_no_azure(qapp):
    # zero azure anywhere in the named-theme stylesheets
    for theme_name in ("studio", "atlas"):
        ss = t.build_stylesheet(theme_name).lower()
        for azure in AZURE_HUES:
            assert azure not in ss, f"azure {azure} leaked into the {theme_name} stylesheet"


def test_light_dark_not_remapped(qapp):
    # The named-theme remap must leave the historical light/dark look untouched:
    # *every* hue qdarkstyle emits survives (the base is not remapped at all),
    # and only the azure add-on is appended.
    import qdarkstyle
    from qdarkstyle import DarkPalette, LightPalette
    for palette, theme_name in ((DarkPalette, "dark"), (LightPalette, "light")):
        base = qdarkstyle.load_stylesheet(qt_api="pyside6", palette=palette)
        built = t.build_stylesheet(theme_name)
        assert _hexes(base) <= _hexes(built), "a qdarkstyle hue was altered"
        assert t.ACCENT in built          # azure accent add-on present
        assert t.STUDIO_ACCENT not in built  # no teal leaked into light/dark


def test_studio_remaps_dark_ground(qapp):
    from qdarkstyle import DarkPalette
    studio = t.build_stylesheet("studio")
    # qdarkstyle's dark ground is gone; Studio's charcoal ground is in
    assert DarkPalette.COLOR_BACKGROUND_1.lower() not in studio.lower()
    assert t.STUDIO_GROUND in studio


def test_atlas_remaps_light_ground(qapp):
    from qdarkstyle import LightPalette
    atlas = t.build_stylesheet("atlas")
    assert LightPalette.COLOR_BACKGROUND_1.lower() not in atlas.lower()
    assert t.ATLAS_GROUND in atlas


def test_remap_is_complete_no_qdarkstyle_hue_survives(qapp):
    # Every hue in a remapped stylesheet is a declared target (plus the ink drawn
    # on the accent) — proof the single-pass remap covered the whole base QSS and
    # no original qdarkstyle palette color leaked through.
    studio = t.build_stylesheet("studio")
    allowed = {v.lower() for v in t._STUDIO_MAP.values()} | {t.accent_text("studio").lower()}
    assert _hexes(studio) <= allowed
    atlas = t.build_stylesheet("atlas")
    allowed = {v.lower() for v in t._ATLAS_MAP.values()} | {t.accent_text("atlas").lower()}
    assert _hexes(atlas) <= allowed


def test_studio_remap_applies_to_every_used_slot(qapp):
    # Self-adjusting fidelity check: for each Studio remap whose qdarkstyle source
    # slot is actually used in the base QSS, the Studio target must appear. (Some
    # qdarkstyle slots — e.g. BACKGROUND_2 — are defined but unused, so their
    # targets legitimately don't render; this asserts the ones that should, do.)
    import qdarkstyle
    from qdarkstyle import DarkPalette
    base = qdarkstyle.load_stylesheet(qt_api="pyside6", palette=DarkPalette).lower()
    studio = t.build_stylesheet("studio").lower()
    for cname, target in t._STUDIO_MAP.items():
        if getattr(DarkPalette, cname).lower() in base:
            assert target.lower() in studio, f"{cname} -> {target} was not applied"
    # the Studio identity anchors (ground, hairline, ink, teal) all map to used
    # slots, so they are guaranteed present
    for hexv in ("#0c0f14", "#2a323e", "#e8edf3", "#37c0a6"):
        assert hexv in studio, f"Studio anchor {hexv} missing"
