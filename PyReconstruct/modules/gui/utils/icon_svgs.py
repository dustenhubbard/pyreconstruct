"""Tool-button icon artwork (the v1 "Refined Familiar" line-icon set).

Pure data — no imports — so it can be loaded both as part of the package and
standalone by tooling (e.g. dev/theme_preview.py). The icons are monochrome
SVGs on a 24x24 grid, ~1.6-1.8px stroke, round joins/caps, drawn in solid black
so QSvgRenderer paints opaque pixels; gui.utils.icons tints them to the active
theme's icon color at render time (see render_svg_tinted).

Keys are the palette's stripped tool names (lower-cased, spaces/slashes removed),
matching MousePalette._stripped(): e.g. "Pan/Zoom" -> "panzoom",
"Closed Trace" -> "closedtrace". Reproduced from the v1 prototype's icon symbols;
"ztool" is a custom mark (no prototype equivalent). Flag/Host keep their glyphs.
"""

_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
_TAIL = "</svg>"


def _svg(body: str) -> bytes:
    return (_HEAD + body + _TAIL).encode("utf-8")


TOOL_SVGS = {
    # pointer / select — filled cursor (prototype i-select)
    "pointer": _svg(
        '<path d="M5 3l14 7-6 1.6L9.6 18 5 3z" fill="#000000" stroke="none"/>'
    ),
    # pan / zoom — grab hand (prototype i-hand)
    "panzoom": _svg(
        '<path d="M8 12V6.5a1.4 1.4 0 0 1 2.8 0V11m0-.5V5.4a1.4 1.4 0 0 1 2.8 0V11'
        'm0-.3V6.3a1.4 1.4 0 0 1 2.8 0V13c0 3.6-2 6-5.4 6-2 0-3.1-.7-4.4-2.4'
        'L5 13.5c-.7-1 .6-2.3 1.7-1.6L8 13" fill="none" stroke="#000000" '
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # knife / split (prototype i-knife)
    "knife": _svg(
        '<path d="M4 14L16 3l4 4-9 8-7-1z" fill="none" stroke="#000000" '
        'stroke-width="1.6" stroke-linejoin="round"/>'
        '<path d="M4 20h7" stroke="#000000" stroke-width="1.7" stroke-linecap="round"/>'
    ),
    # scissors — scalpel blade, the prototype's cut tool (i-scalpel)
    "scissors": _svg(
        '<path d="M6 18l9-9 4-4-3 8-7 7-3-2z" fill="none" stroke="#000000" '
        'stroke-width="1.6" stroke-linejoin="round"/>'
    ),
    # closed trace — closed contour with vertices (prototype i-poly)
    "closedtrace": _svg(
        '<path d="M12 4l7 5-2.6 8H7.6L5 9l7-5z" fill="none" stroke="#000000" '
        'stroke-width="1.6" stroke-linejoin="round"/>'
        '<circle cx="12" cy="4" r="1.7" fill="#000000"/>'
        '<circle cx="19" cy="9" r="1.7" fill="#000000"/>'
        '<circle cx="16.4" cy="17" r="1.7" fill="#000000"/>'
        '<circle cx="7.6" cy="17" r="1.7" fill="#000000"/>'
        '<circle cx="5" cy="9" r="1.7" fill="#000000"/>'
    ),
    # open trace — pencil / freehand (prototype i-pencil)
    "opentrace": _svg(
        '<path d="M4 20l1-4L16 5l3 3L8 19l-4 1z" fill="none" stroke="#000000" '
        'stroke-width="1.7" stroke-linejoin="round"/>'
        '<path d="M14 7l3 3" stroke="#000000" stroke-width="1.7"/>'
    ),
    # stamp (prototype i-stamp)
    "stamp": _svg(
        '<path d="M9 4h6l-1.2 6H10.2L9 4z" fill="none" stroke="#000000" '
        'stroke-width="1.6" stroke-linejoin="round"/>'
        '<rect x="5" y="12" width="14" height="3.2" rx="1.2" fill="none" '
        'stroke="#000000" stroke-width="1.6"/>'
        '<path d="M5 19h14" stroke="#000000" stroke-width="1.7" stroke-linecap="round"/>'
    ),
    # grid overlay (prototype i-grid)
    "grid": _svg(
        '<rect x="4" y="4" width="16" height="16" rx="2" fill="none" '
        'stroke="#000000" stroke-width="1.6"/>'
        '<path d="M4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16" stroke="#000000" '
        'stroke-width="1.2"/>'
    ),
    # ztool — CUSTOM (no prototype match): stacked sections + a z-trace zigzag
    "ztool": _svg(
        '<path d="M4 6h16M4 12h16M4 18h16" stroke="#000000" stroke-width="1.4" '
        'stroke-linecap="round" opacity="0.45"/>'
        '<path d="M7 6l10 6-10 6" fill="none" stroke="#000000" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
}
