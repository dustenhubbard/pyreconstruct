"""Theme-tinted SVG tool icons (the v1 "Refined Familiar" line-icon set).

The palette's mode buttons used static PNGs; v1 switches the standard tools to
monochrome SVGs (see icon_svgs.TOOL_SVGS) rendered and tinted to the active
theme's icon color, so they follow light/dark. The artwork is solid black, so
QSvgRenderer paints opaque pixels; a CompositionMode_SourceIn pass recolors
every opaque pixel to the target color while preserving the anti-aliased alpha.

Trace/segmentation colors are data and are never touched here. Tools without a
modern SVG (Flag/Host glyphs, anything not in TOOL_SVGS) fall back to the
caller's existing PNG/glyph path via has_icon().
"""
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from PySide6.QtCore import Qt

from . import theme
from .icon_svgs import TOOL_SVGS


def has_icon(name: str) -> bool:
    """True if a modern SVG exists for this stripped tool name."""
    return name in TOOL_SVGS


def render_svg_tinted(svg: bytes, size_px: int, color_hex: str) -> QPixmap:
    """Render an SVG to a square pixmap and tint every opaque pixel to color."""
    renderer = QSvgRenderer(bytes(svg))
    pm = QPixmap(size_px, size_px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    p = QPainter(pm)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(pm.rect(), QColor(color_hex))
    p.end()
    return pm


def tool_icon(name: str, size_px: int, color_hex: str = None) -> QIcon:
    """QIcon for a tool, tinted to the theme icon color (or an explicit color).

    Returns an empty QIcon if the tool has no modern SVG (callers should check
    has_icon() first to fall back to the legacy PNG/glyph).
    """
    svg = TOOL_SVGS.get(name)
    if svg is None:
        return QIcon()
    if color_hex is None:
        color_hex = theme.icon_color()
    return QIcon(render_svg_tinted(svg, size_px, color_hex))
