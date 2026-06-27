"""Application theme engine.

Centralizes PyReconstruct's UI chrome. The theme **defaults to the OS color
scheme** (light/dark) and can be overridden to System / Light / Dark; the choice
is persisted app-wide via QSettings. Dark keeps the established ``qdarkstyle``
look (its ``DarkPalette``); light is ``qdarkstyle``'s clean ``LightPalette``
counterpart. A small token palette (charcoal ground, calm azure accent) is
layered on top of both.

Trace and segmentation colors are *data* (drawn in the field, not via QSS) and
are deliberately never touched here.

The persisted preference shares the global ``QSettings`` ``"theme"`` key with
``Series.getOption``/``setOption`` (that option already resolves to the global
``QSettings("KHLab", "PyReconstruct")`` store), so the two stay in sync.

Qt/qdarkstyle are imported lazily inside the functions that need them so the
pure mode-resolution logic (:func:`normalize_mode`, :func:`resolve_scheme`)
stays importable and unit-testable without a Qt/qdarkstyle install.
"""

# --- persisted preference (shared with Series.getOption/setOption) -----------
QSETTINGS_ORG = "KHLab"
QSETTINGS_APP = "PyReconstruct"
THEME_KEY = "theme"

#: the modes a user can choose; also the persisted values
MODES = ("system", "light", "dark")

#: the two concrete schemes the chrome can resolve to
SCHEMES = ("light", "dark")

#: When the OS scheme is unknowable (Qt < 6.8 on Linux without a desktop
#: portal reports ``ColorScheme.Unknown``, and offscreen always does), fall
#: back to dark. This matches the shipped app-icon logic (Unknown -> dark
#: glyph) so chrome and icon never disagree, and preserves the long-standing
#: qdarkstyle look as the effective default.
UNKNOWN_FALLBACK = "dark"

# --- token palette -----------------------------------------------------------
# Provisional hues: the engine and persistence are headless-verified, but the
# exact look (and the accent's specificity vs qdarkstyle's own selection color)
# is signed off interactively. Tune these constants, not the wiring.
ACCENT = "#3d8bd4"        # calm azure — selection/highlight accent
ACCENT_TEXT = "#ffffff"   # text drawn on the accent
GROUND_DARK = "#19232d"   # qdarkstyle DarkPalette ground (informational)
GROUND_LIGHT = "#fafafa"  # qdarkstyle LightPalette ground (informational)


# --- pure mode/scheme logic (no Qt) ------------------------------------------
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


def resolve_scheme(mode, system_is_light) -> str:
    """Resolve a mode to a concrete scheme (``"light"`` / ``"dark"``).

    Pure and Qt-free so the full matrix is unit-testable.

        Params:
            mode: one of :data:`MODES` (normalize first).
            system_is_light: ``True`` if the OS scheme is light, ``False`` if
                dark, ``None`` if unknown.
    """
    if mode == "light":
        return "light"
    if mode == "dark":
        return "dark"
    # system
    if system_is_light is True:
        return "light"
    if system_is_light is False:
        return "dark"
    return UNKNOWN_FALLBACK


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


def current_scheme(app=None, mode=None) -> str:
    """The concrete scheme currently in effect (respects the manual override)."""
    if mode is None:
        mode = read_mode()
    return resolve_scheme(normalize_mode(mode), system_is_light(app))


# --- stylesheet construction -------------------------------------------------
# Applies to both schemes. The first two rules are the long-standing qdarkstyle
# fix-ups (transparent QPushButton border; QComboBox dropdown padding), now
# shared by light too. The rest applies the azure accent to selection chrome.
def _addon_qss() -> str:
    return f"""
QPushButton {{ border: 1px solid transparent; }}
QComboBox {{ padding-right: 40px; }}

QListView, QTreeView, QTableView,
QListWidget, QTreeWidget, QTableWidget {{
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QMenu::item:selected {{ background-color: {ACCENT}; color: {ACCENT_TEXT}; }}
"""


def build_stylesheet(scheme: str) -> str:
    """Build the full app stylesheet for a scheme (qdarkstyle base + tokens).

    Raises ``ImportError`` if qdarkstyle is unavailable; callers decide whether
    to fall back to native styling.
    """
    import qdarkstyle
    from qdarkstyle import DarkPalette, LightPalette
    palette = DarkPalette if scheme == "dark" else LightPalette
    base = qdarkstyle.load_stylesheet(qt_api="pyside6", palette=palette)
    return base + _addon_qss()


def apply_theme(app=None, mode=None) -> str:
    """Resolve ``mode`` and apply the matching stylesheet app-wide.

    Returns the concrete scheme applied. If qdarkstyle can't be imported, falls
    back to native styling (empty stylesheet + standard palette) rather than
    raising, so startup never breaks on a missing optional dependency.
    """
    app = _app(app)
    scheme = current_scheme(app, mode)
    try:
        qss = build_stylesheet(scheme)
    except Exception:
        qss = ""
    app.setStyleSheet(qss)
    if not qss:
        app.setPalette(app.style().standardPalette())
    return scheme


def qss_active(app=None) -> bool:
    """True when a (qdarkstyle-based) app stylesheet is in effect.

    Used by widgets that need to compensate qdarkstyle's metrics (e.g. table
    column widths), which now applies to both light and dark schemes.
    """
    try:
        return bool(_app(app).styleSheet())
    except Exception:
        return False
