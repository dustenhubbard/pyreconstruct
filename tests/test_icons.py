"""Tests for the theme-tinted tool-icon set (gui.utils.icons / icon_svgs).

Pins: every palette mode tool that should have a modern icon has one; the SVGs
render to non-empty pixmaps; the SourceIn tint recolors every *fully opaque*
pixel to the requested color (anti-aliased edges are partially transparent and
excluded); tool_icon returns a real QIcon for known tools and an empty one for
unknown; and icon_color tracks the scheme.

Qt-backed parts skip if PySide6/QtSvg are unavailable.
"""
import os
import pytest

from PyReconstruct.modules.gui.utils import icon_svgs
from PyReconstruct.modules.gui.utils import theme


# tools whose palette buttons load a PNG today and should get a modern SVG
# (Flag/Host historically fell back to glyphs; they now have Studio-set icons
# too — see STUDIO_ICONS below)
EXPECTED_TOOLS = {
    "pointer", "panzoom", "knife", "scissors", "closedtrace",
    "opentrace", "stamp", "grid", "ztool",
}


def test_expected_tools_present():
    assert EXPECTED_TOOLS <= set(icon_svgs.TOOL_SVGS), \
        "every standard mode tool must have a modern SVG"


# Studio-layout chrome icons (activity rail panels + the tool rail's Flag/Host
# tiles); these replace the mockup's placeholder unicode glyphs.
STUDIO_ICONS = {"objects", "traces", "sections", "scene3d", "settings", "flag", "host"}


def test_studio_chrome_icons_present():
    assert STUDIO_ICONS <= set(icon_svgs.TOOL_SVGS), \
        "the Studio activity/tool rails must have stroked vector icons (no unicode glyphs)"


def test_svgs_are_wellformed_bytes():
    for name, svg in icon_svgs.TOOL_SVGS.items():
        assert isinstance(svg, bytes), f"{name} svg must be bytes"
        assert svg.startswith(b"<svg") and svg.rstrip().endswith(b"</svg>"), name
        assert b'viewBox="0 0 24 24"' in svg, f"{name} should use the 24x24 grid"


@pytest.mark.parametrize("scheme,expected", [
    ("dark", theme.ICON_DARK),
    ("light", theme.ICON_LIGHT),
])
def test_icon_color_per_scheme(scheme, expected):
    assert theme.icon_color(scheme) == expected


# --- Qt-backed -------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    pytest.importorskip("PySide6.QtSvg")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def test_render_tints_opaque_pixels(qapp):
    from PyReconstruct.modules.gui.utils import icons
    from PySide6.QtGui import QColor
    color = "#e84d8a"  # any vivid non-grayscale tint exercises the exactness check
    target = QColor(color)
    # use a solid-filled icon (pointer) so there are plenty of fully-opaque
    # pixels to assert exactness on; thin line-art icons are mostly anti-aliased
    pm = icons.render_svg_tinted(icon_svgs.TOOL_SVGS["pointer"], 40, color)
    assert not pm.isNull() and pm.size().width() == 40
    img = pm.toImage()
    opaque = exact = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 255:
                opaque += 1
                if (c.red(), c.green(), c.blue()) == (target.red(), target.green(), target.blue()):
                    exact += 1
    assert opaque > 20, "icon should have a meaningful number of solid pixels"
    assert exact == opaque, "every fully-opaque pixel must be tinted to the color"


def test_tool_icon_known_and_unknown(qapp):
    from PyReconstruct.modules.gui.utils import icons
    # known tools (incl. the now-present Flag/Host) resolve; an unknown name does not
    assert icons.has_icon("knife") and icons.has_icon("flag") and icons.has_icon("host")
    assert not icons.has_icon("no_such_tool")
    icon = icons.tool_icon("knife", 32, "#ffffff")
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()
    # unknown tool -> empty icon (caller falls back to PNG/glyph)
    assert icons.tool_icon("no_such_tool", 32).isNull()


def test_tool_icon_defaults_to_theme_color(qapp):
    from PyReconstruct.modules.gui.utils import icons
    # should not raise when no explicit color is given (uses theme.icon_color())
    icon = icons.tool_icon("grid", 32)
    assert not icon.isNull()
