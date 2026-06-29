"""Application theme engine.

Centralizes PyReconstruct's UI chrome. The theme **defaults to the OS color
scheme** (light/dark) and can be overridden to one of several named themes; the
choice is persisted app-wide via QSettings.

Themes (the values a user can pick and that get persisted):

  * ``system`` — follow the OS light/dark scheme (the default).
  * ``light`` / ``dark`` — qdarkstyle's clean ``LightPalette`` / established
    ``DarkPalette`` look, with a calm azure accent layered on selection chrome.
  * ``studio`` — the "Studio" concept: a cool, dark, scientific base
    (charcoal ``#0c0f14`` ground) with a calm **teal** accent (``#37c0a6``).
  * ``atlas`` — the "Atlas" concept: Studio's light sibling — a cool, neutral
    light shell for bright rooms / brightfield work, same teal accent.

``studio`` and ``atlas`` are built on qdarkstyle's Dark / Light base (for full,
consistent widget coverage) and then *remapped*: every qdarkstyle palette hex in
the generated stylesheet is substituted for its Studio / Atlas counterpart in a
single pass. The qdarkstyle palette constants are read at run time, so the remap
tracks the installed qdarkstyle version rather than hard-coding its hues.

Trace and segmentation colors are *data* (drawn in the field, not via QSS) and
are deliberately never touched here. The Studio mockup's status hues
(curated / review / flagged) are likewise data, not chrome, so they are not part
of this engine.

The persisted preference shares the global ``QSettings`` ``"theme"`` key with
``Series.getOption``/``setOption`` (that option already resolves to the global
``QSettings("KHLab", "PyReconstruct")`` store), so the two stay in sync.

Qt/qdarkstyle are imported lazily inside the functions that need them so the
pure resolution logic (:func:`normalize_mode`, :func:`resolve_theme`,
:func:`resolve_scheme`) stays importable and unit-testable without a
Qt/qdarkstyle install.
"""
import re

# --- persisted preference (shared with Series.getOption/setOption) -----------
QSETTINGS_ORG = "KHLab"
QSETTINGS_APP = "PyReconstruct"
THEME_KEY = "theme"

#: the modes a user can choose; also the persisted values
MODES = ("system", "light", "dark", "studio", "atlas")

#: the concrete themes a stylesheet can be built for (``system`` resolves to one
#: of these). ``light``/``dark`` are the qdarkstyle base looks; ``studio`` and
#: ``atlas`` are the named concept palettes.
THEMES = ("light", "dark", "studio", "atlas")

#: the two color *families*. Every concrete theme belongs to one; the family
#: drives anything that only cares about light-vs-dark (the app icon glyph, the
#: monochrome tool-icon tint, qdarkstyle's base palette).
SCHEMES = ("light", "dark")

#: which family each concrete theme belongs to
_FAMILY = {"light": "light", "dark": "dark", "studio": "dark", "atlas": "light"}

#: When the OS scheme is unknowable (Qt < 6.8 on Linux without a desktop
#: portal reports ``ColorScheme.Unknown``, and offscreen always does), fall
#: back to dark. This matches the shipped app-icon logic (Unknown -> dark
#: glyph) so chrome and icon never disagree, and preserves the long-standing
#: qdarkstyle look as the effective default.
UNKNOWN_FALLBACK = "dark"

# --- token palette -----------------------------------------------------------
# Azure accent for the qdarkstyle-based light/dark themes. (Provisional hues:
# the engine and persistence are headless-verified; the exact look is signed off
# interactively. Tune these constants, not the wiring.)
ACCENT = "#3d8bd4"        # calm azure — selection/highlight accent (light/dark)
ACCENT_TEXT = "#ffffff"   # text drawn on the accent
GROUND_DARK = "#19232d"   # qdarkstyle DarkPalette ground (informational)
GROUND_LIGHT = "#fafafa"  # qdarkstyle LightPalette ground (informational)

# Tool-button icon color (the monochrome line icons tint to this per theme).
# Provisional — from the v1 prototype's resting tool color (its --txt-dim).
ICON_DARK = "#9aa7bb"     # icons on dark (qdarkstyle) chrome
ICON_LIGHT = "#54627a"    # icons on light (qdarkstyle) chrome

# --- named-theme palettes (the "Studio" / "Atlas" concepts) ------------------
# Studio's palette is lifted verbatim from the UI-direction mockup
# (artifact a386d6e8 — "Direction A: Studio"). Atlas is that mockup's described
# light sibling ("Direction B: Atlas — light precision, same teal accent"); the
# mockup names it but gives no hex, so its neutral cool-light shell is derived
# here to mirror Studio while keeping the identical teal/cyan accent.
STUDIO_ACCENT = "#37c0a6"   # teal — Studio/Atlas selection/highlight accent
STUDIO_GROUND = "#0c0f14"   # cool charcoal ground (informational)
ATLAS_GROUND = "#f4f6fa"    # cool near-white ground (informational)

#: Studio: remap qdarkstyle ``DarkPalette`` -> Studio hues. Keys are qdarkstyle
#: palette-constant *names* (resolved to their hexes at run time); values are the
#: Studio targets. Background ramp runs darkest (BACKGROUND_1, the ground) to
#: lightest (BACKGROUND_6, handles); the accent ramp lands the true teal on
#: ACCENT_3 (qdarkstyle's focus/hover accent).
_STUDIO_MAP = {
    "COLOR_BACKGROUND_1": "#0c0f14",  # ground
    "COLOR_BACKGROUND_2": "#141921",  # panel
    "COLOR_BACKGROUND_3": "#1b212b",  # panel-2 / low raise
    "COLOR_BACKGROUND_4": "#2a323e",  # hairline / border (dominant)
    "COLOR_BACKGROUND_5": "#3a4452",  # hover / handle
    "COLOR_BACKGROUND_6": "#4a5666",  # lightest handle / scrollbar
    "COLOR_TEXT_1": "#e8edf3",        # ink
    "COLOR_TEXT_2": "#aab4c0",
    "COLOR_TEXT_3": "#9aa7b5",        # muted
    "COLOR_TEXT_4": "#6a7686",        # faint (mockup --faint)
    "COLOR_DISABLED": "#4f5a6b",
    "COLOR_ACCENT_1": "#16332d",      # darkest teal (pressed/selected base)
    "COLOR_ACCENT_2": "#2b8675",      # mid teal
    "COLOR_ACCENT_3": "#37c0a6",      # the teal accent (focus/hover)
    "COLOR_ACCENT_4": "#45cdb2",
    "COLOR_ACCENT_5": "#5ad8c0",      # brightest teal
}

#: Atlas: remap qdarkstyle ``LightPalette`` -> Atlas hues. Background ramp runs
#: lightest (BACKGROUND_1, the ground) to darkest (BACKGROUND_6, borders); the
#: teal accent lands on ACCENT_4 (qdarkstyle light's focus accent).
_ATLAS_MAP = {
    "COLOR_BACKGROUND_1": "#f4f6fa",  # cool light ground / surface
    "COLOR_BACKGROUND_2": "#e9edf3",  # alt rows / headers
    "COLOR_BACKGROUND_3": "#dde3ec",
    "COLOR_BACKGROUND_4": "#ccd4df",  # hairline / border (dominant)
    "COLOR_BACKGROUND_5": "#bcc5d2",
    "COLOR_BACKGROUND_6": "#aab4c2",
    "COLOR_TEXT_1": "#1a2230",        # cool near-black ink
    "COLOR_TEXT_2": "#33405a",
    "COLOR_TEXT_3": "#586478",        # muted
    "COLOR_TEXT_4": "#8893a6",        # faint
    "COLOR_DISABLED": "#aab3bf",
    "COLOR_ACCENT_1": "#d9f1ea",      # light teal tint (hover/selection wash)
    "COLOR_ACCENT_2": "#88dccc",
    "COLOR_ACCENT_3": "#4cccb5",
    "COLOR_ACCENT_4": "#37c0a6",      # the teal accent
    "COLOR_ACCENT_5": "#2ba892",      # deeper teal (pressed)
}

_THEME_REMAP = {"studio": _STUDIO_MAP, "atlas": _ATLAS_MAP}

#: accent each concrete theme paints onto selection chrome / the active tool
_THEME_ACCENT = {
    "light": ACCENT, "dark": ACCENT,
    "studio": STUDIO_ACCENT, "atlas": STUDIO_ACCENT,
}

#: color drawn *on* the accent (selected-row text, highlighted menu items, the
#: active-tool glyph). White reads on the azure light/dark accent, but the
#: brighter Studio/Atlas teal needs a dark ink — white on ``#37c0a6`` is only
#: ~2.3:1 (below WCAG's 3:1 floor), whereas the charcoal ground clears 8:1.
_THEME_ON_ACCENT = {
    "light": ACCENT_TEXT, "dark": ACCENT_TEXT,
    "studio": STUDIO_GROUND, "atlas": STUDIO_GROUND,
}

#: resting tool-icon tint per theme (active tool uses :func:`accent_text`)
_THEME_ICON = {
    "light": ICON_LIGHT, "dark": ICON_DARK,
    "studio": "#9aa7b5", "atlas": "#586478",
}


# --- pure mode/theme/scheme logic (no Qt) ------------------------------------
def normalize_mode(value) -> str:
    """Coerce any stored/legacy theme value to one of :data:`MODES`.

    Legacy values map forward: ``"default"`` (old native/light default) ->
    ``"system"`` so existing installs adopt the new system-following default;
    ``"qdark"`` -> ``"dark"`` to preserve an explicit dark choice. Anything
    unrecognized (or ``None``) falls back to ``"system"``.
    """
    if value in MODES:
        return value
    if value == "qdark":
        return "dark"
    # "default", None, or anything unexpected
    return "system"


def resolve_theme(mode, system_is_light) -> str:
    """Resolve a mode to a concrete theme (one of :data:`THEMES`).

    Pure and Qt-free so the full matrix is unit-testable.

        Params:
            mode: one of :data:`MODES` (normalize first).
            system_is_light: ``True`` if the OS scheme is light, ``False`` if
                dark, ``None`` if unknown.
    """
    if mode in THEMES:           # light, dark, studio, atlas
        return mode
    # system: follow the OS
    if system_is_light is True:
        return "light"
    if system_is_light is False:
        return "dark"
    return UNKNOWN_FALLBACK


def resolve_scheme(mode, system_is_light) -> str:
    """Resolve a mode to a concrete color *family* (``"light"`` / ``"dark"``).

    Studio resolves to the dark family, Atlas to light. Used by anything that
    only distinguishes light vs dark (the app-icon glyph, the tool-icon tint).
    """
    return _FAMILY[resolve_theme(mode, system_is_light)]


# --- Qt-facing helpers (lazy imports) ----------------------------------------
def _app(app=None):
    if app is not None:
        return app
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


def system_is_light(app=None):
    """``True``/``False`` for the OS light/dark scheme, ``None`` if unknown."""
    try:
        from PySide6.QtCore import Qt
        app = _app(app)
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return True
        if scheme == Qt.ColorScheme.Dark:
            return False
    except Exception:  # pragma: no cover - older Qt without colorScheme()
        pass
    return None


def read_mode() -> str:
    """Read the persisted mode from the global QSettings (normalized)."""
    from PySide6.QtCore import QSettings
    settings = QSettings(QSETTINGS_ORG, QSETTINGS_APP)
    return normalize_mode(settings.value(THEME_KEY, "system", type=str))


def write_mode(mode) -> str:
    """Persist a (normalized) mode to the global QSettings; returns it."""
    from PySide6.QtCore import QSettings
    mode = normalize_mode(mode)
    QSettings(QSETTINGS_ORG, QSETTINGS_APP).setValue(THEME_KEY, mode)
    return mode


def current_theme(app=None, mode=None) -> str:
    """The concrete theme currently in effect (respects the manual override)."""
    if mode is None:
        mode = read_mode()
    return resolve_theme(normalize_mode(mode), system_is_light(app))


def current_scheme(app=None, mode=None) -> str:
    """The concrete color family (light/dark) currently in effect."""
    return _FAMILY[current_theme(app, mode)]


def accent_color(theme=None, app=None) -> str:
    """Accent hex the active theme paints onto selection chrome / active tool.

    Azure for the qdarkstyle light/dark themes, teal for Studio/Atlas. Defaults
    to the theme currently in effect.
    """
    if theme is None:
        theme = current_theme(app)
    return _THEME_ACCENT.get(theme, ACCENT)


def accent_text(theme=None, app=None) -> str:
    """Hex for text/icons drawn on the accent.

    White on the azure (light/dark) accent; a dark ink on the brighter
    Studio/Atlas teal so a selected row's text and the active-tool glyph stay
    legible. Defaults to the theme currently in effect.
    """
    if theme is None:
        theme = current_theme(app)
    return _THEME_ON_ACCENT.get(theme, ACCENT_TEXT)


def icon_color(theme=None, app=None) -> str:
    """Hex the monochrome tool icons should tint to for a theme.

    Accepts a concrete theme or a family (``"light"``/``"dark"``); defaults to
    the theme currently in effect.
    """
    if theme is None:
        theme = current_theme(app)
    if theme in _THEME_ICON:
        return _THEME_ICON[theme]
    # tolerate a family string that isn't a concrete theme
    return ICON_DARK if _FAMILY.get(theme, "dark") == "dark" else ICON_LIGHT


# --- stylesheet construction -------------------------------------------------
# The accent add-on applies to every theme. The first two rules are the
# long-standing qdarkstyle fix-ups (transparent QPushButton border; QComboBox
# dropdown padding); the rest paints the theme accent onto selection chrome.
def _accent_addon_qss(accent: str, on_accent: str) -> str:
    return f"""
QPushButton {{ border: 1px solid transparent; }}
QComboBox {{ padding-right: 40px; }}

QListView, QTreeView, QTableView,
QListWidget, QTreeWidget, QTableWidget {{
    selection-background-color: {accent};
    selection-color: {on_accent};
}}
QMenu::item:selected {{ background-color: {accent}; color: {on_accent}; }}
"""


def _addon_qss() -> str:
    """The azure add-on for the light/dark themes (unchanged historical look)."""
    return _accent_addon_qss(ACCENT, ACCENT_TEXT)


def _remap_palette(qss: str, base_palette, name_to_target: dict) -> str:
    """Substitute a qdarkstyle base stylesheet's palette hexes for new ones.

    ``name_to_target`` maps qdarkstyle palette-constant *names* (e.g.
    ``COLOR_BACKGROUND_1``) to target hexes. The source hex is read from
    ``base_palette`` at run time, so the remap follows the installed qdarkstyle
    version. Replacement is a single case-insensitive pass over 6-digit hex
    tokens (the generated QSS uses no ``rgba()``), so a target that happens to
    equal another source is never re-substituted. The trailing boundary keeps a
    longer token (a hypothetical 8-digit ``#rrggbbaa``) from being partially
    matched and corrupted.
    """
    mapping = {}
    for cname, target in name_to_target.items():
        src = getattr(base_palette, cname, None)
        if src:
            mapping[src.lower()] = target
    if not mapping:
        return qss
    return re.sub(
        r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])",
        lambda m: mapping.get(m.group(0).lower(), m.group(0)),
        qss,
    )


def build_stylesheet(theme: str) -> str:
    """Build the full app stylesheet for a concrete theme.

    ``light``/``dark`` are qdarkstyle's base look + the azure add-on (unchanged).
    ``studio``/``atlas`` take the matching qdarkstyle base (Dark / Light), remap
    its palette to the Studio / Atlas hues, then add the teal accent. Accepts a
    family string (``"light"``/``"dark"``) as a tolerant alias.

    Raises ``ImportError`` if qdarkstyle is unavailable; callers decide whether
    to fall back to native styling.
    """
    import qdarkstyle
    from qdarkstyle import DarkPalette, LightPalette

    if theme not in THEMES:
        theme = resolve_scheme(theme, None)  # tolerate a family/legacy string
    base_palette = DarkPalette if _FAMILY[theme] == "dark" else LightPalette
    base = qdarkstyle.load_stylesheet(qt_api="pyside6", palette=base_palette)

    remap = _THEME_REMAP.get(theme)
    if remap is not None:
        base = _remap_palette(base, base_palette, remap)
        return base + _accent_addon_qss(_THEME_ACCENT[theme], _THEME_ON_ACCENT[theme])
    return base + _addon_qss()


def apply_theme(app=None, mode=None) -> str:
    """Resolve ``mode`` and apply the matching stylesheet app-wide.

    Returns the concrete theme applied. If qdarkstyle can't be imported, falls
    back to native styling (empty stylesheet + standard palette) rather than
    raising, so startup never breaks on a missing optional dependency.
    """
    app = _app(app)
    theme = current_theme(app, mode)
    try:
        qss = build_stylesheet(theme)
    except Exception:
        qss = ""
    app.setStyleSheet(qss)
    if not qss:
        app.setPalette(app.style().standardPalette())
    return theme


def qss_active(app=None) -> bool:
    """True when a (qdarkstyle-based) app stylesheet is in effect.

    Used by widgets that need to compensate qdarkstyle's metrics (e.g. table
    column widths), which applies to every theme (all are qdarkstyle-based).
    """
    try:
        return bool(_app(app).styleSheet())
    except Exception:
        return False
