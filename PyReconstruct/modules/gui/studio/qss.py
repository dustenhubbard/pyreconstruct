"""Chrome stylesheet for the Studio layout widgets.

One source of styling truth for the bespoke widgets, driven entirely by
:func:`PyReconstruct.modules.gui.utils.theme.studio_tokens`. The same template
renders both shells — the Studio (dark) and Atlas (light) tokens differ, the
selectors do not — so a theme toggle is just "re-build and re-apply".

Set on :class:`~.shell.StudioShell`, it cascades to every child by objectName.
It styles container chrome, labels and buttons (resting + active); the data-ish
bits (object-row swatches, palette swatches, the brand mark, slider tracks,
status dots) are custom-painted in the widgets from the same tokens.

The template uses ``string.Template`` ``${token}`` placeholders so QSS's literal
``{ }`` braces need no escaping. Active button states use the dynamic ``active``
property (``QToolButton[active="true"]``); widgets repolish on toggle.
"""
from string import Template

from ..utils import theme


# rem→px uses the mockup's 14px root. Kept inline as literals for legibility.
_TEMPLATE = Template("""
/* ---- shell ground -------------------------------------------------------- */
#studioShell, #studioBody, #studioMainColumn, #studioWorkRow { background: ${bg}; }

/* qdarkstyle paints every QLabel with the theme ground (light in Atlas), which
   would show through our dark glass floats; make labels transparent by default
   so they take their parent's surface. Labels that need a fill (chip, kbd,
   status dots) override this with an id selector or their own stylesheet. */
QLabel { background: transparent; padding: 0px; margin: 0px; }

/* ---- title strip --------------------------------------------------------- */
#studioTitleStrip {
    background: ${panel_2};
    border-bottom: 1px solid ${line};
}
#studioBrand { color: ${ink}; font-weight: 800; font-size: 14px; }
QLabel#studioMenuItem { color: ${muted}; font-size: 12px; padding: 3px 7px; border-radius: 6px; }
QLabel#studioMenuItem:hover { color: ${ink}; background: ${raised}; }
#studioChip {
    color: ${chip_ink};
    background: ${chip_bg};
    border: 1px solid ${chip_border};
    border-radius: 10px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}
#studioCmdk {
    color: ${faint};
    background: ${bg};
    border: 1px solid ${line};
    border-radius: 7px;
    padding: 4px 9px;
    font-size: 11px;
}
#studioCmdkKbd {
    color: ${muted};
    background: ${raised};
    border: 1px solid ${line};
    border-radius: 4px;
    padding: 0px 5px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
    font-size: 10px;
}

/* ---- activity rail ------------------------------------------------------- */
#studioActivityRail {
    background: ${panel_2};
    border-right: 1px solid ${line};
}
QToolButton#studioRailButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
}
QToolButton#studioRailButton:hover { background: ${raised}; }
QToolButton#studioRailButton[active="true"] {
    background: ${rail_active_bg};
    border: 1px solid ${rail_active_ring};
}

/* ---- objects panel ------------------------------------------------------- */
#studioObjectsPanel {
    background: ${panel};
    border-right: 1px solid ${line};
}
#studioPanelHeader { border-bottom: 1px solid ${line_soft}; }
#studioPanelTitle {
    color: ${muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
#studioPanelCount {
    color: ${faint};
    font-size: 10px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
}
QLineEdit#studioFilter {
    color: ${ink};
    background: ${bg};
    border: 1px solid ${line};
    border-radius: 8px;
    padding: 5px 8px;
    font-size: 11px;
    selection-background-color: ${accent};
    selection-color: ${on_accent};
}
QLineEdit#studioFilter:focus { border: 1px solid ${accent}; }
QListView#studioObjectList {
    background: ${panel};
    border: none;
    outline: none;
}
#studioLegend { border-top: 1px solid ${line_soft}; }
#studioLegendLabel { color: ${faint}; font-size: 10px; }

/* ---- canvas + glassy floats ---------------------------------------------- */
#studioCanvas { background: ${canvas_bg}; }
QFrame#studioFloat {
    background: ${float_bg};
    border: 1px solid ${float_line};
    border-radius: 10px;
}
#studioFloatText { color: ${float_ink}; font-size: 10px; }
#studioFloatLabel { color: ${float_faint}; font-size: 10px; }
#studioScaleText {
    color: ${scale_ink};
    font-size: 10px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
}
#studioSecnavLabel {
    color: ${float_ink};
    font-size: 11px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
}
#studioSecnavTotal { color: ${float_faint}; }
QToolButton#studioSecnavButton {
    color: ${float_muted};
    background: ${raised_dark};
    border: none;
    border-radius: 7px;
}
QToolButton#studioSecnavButton:hover { color: ${float_ink}; }

/* ---- tool rail (flush; no card, no blur, no shadow, no glow) -------------- */
#studioToolRail {
    background: ${panel_2};
    border-left: 1px solid ${line};
}
QToolButton#studioToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}
QToolButton#studioToolButton:hover { background: ${raised}; }
QToolButton#studioToolButton[active="true"] {
    background: ${tool_active_bg};
    border: 1px solid ${tool_active_border};
}

/* ---- palette strip ------------------------------------------------------- */
#studioPaletteStrip {
    background: ${panel};
    border-top: 1px solid ${line};
}
#studioPaletteLabel {
    color: ${muted};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.6px;
}
QToolButton#studioAddSwatch {
    color: ${faint};
    background: ${raised};
    border: 1px dashed ${line};
    border-radius: 8px;
    font-size: 15px;
}
QToolButton#studioAddSwatch:hover { color: ${ink}; border: 1px dashed ${accent}; }
#studioPaletteReadout {
    color: ${faint};
    font-size: 11px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
}

/* ---- status bar ---------------------------------------------------------- */
#studioStatusBar {
    background: ${panel_2};
    border-top: 1px solid ${line};
}
#studioStatusText {
    color: ${muted};
    font-size: 10px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
}
#studioStatusValue {
    color: ${accent};
    font-size: 10px;
    font-family: "DejaVu Sans Mono", "Cascadia Code", Menlo, Consolas, monospace;
}
""")


def chrome_qss(theme_name=None, app=None) -> str:
    """Build the Studio chrome stylesheet for a theme (or the active one)."""
    tokens = theme.studio_tokens(theme_name, app)
    return _TEMPLATE.substitute(tokens)
