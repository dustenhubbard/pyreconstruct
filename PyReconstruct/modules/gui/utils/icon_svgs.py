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
    # knife — 1:1 vector trace of the IconExperience "plain" chef's-knife icon:
    # contours auto-traced from the 256px PNG (OpenCV), scaled to the 24 grid and
    # even-odd filled so the line-art interiors stay open. Tip lower-left, outline
    # blade + outline handle with the looped end, exactly as the reference.
    "knife": _svg(
        '<path fill-rule="evenodd" fill="#000000" d="'
        'M21.09 2.81L20.62 2.53L19.69 2.34L19.59 2.44L18.84 2.53L18.19 2.91'
        'L12.47 8.62L12.28 9.00L12.28 9.47L11.25 10.50L7.59 14.72L5.25 17.81'
        'L3.84 20.06L3.19 21.38L2.72 22.69L3.56 22.69L3.66 22.59L4.22 22.59'
        'L4.31 22.50L5.44 22.31L6.75 21.84L7.22 21.56L7.41 21.56L9.28 20.53'
        'L11.81 18.75L13.59 17.25L17.44 13.50L17.53 13.22L17.44 12.75'
        'L16.12 11.44L16.12 11.25L16.31 10.97L16.31 10.31L16.22 10.12'
        'L19.31 7.03L19.41 7.12L19.78 7.12L19.88 7.03L20.53 6.94L21.00 6.66'
        'L21.56 6.09L21.94 5.25L21.94 4.12L21.56 3.28Z'
        'M16.69 13.12L16.69 13.22L13.50 16.31L11.53 18.00L10.03 19.12'
        'L7.97 20.44L6.84 21.00L4.69 21.75L4.31 21.75L4.22 21.84L3.94 21.84'
        'L3.84 21.75L5.34 19.03L7.22 16.41L10.12 12.94L12.75 10.03'
        'L14.53 11.72L14.72 11.81L15.38 11.81Z'
        'M20.44 3.28L21.00 3.84L21.19 4.22L21.19 5.16L20.91 5.72L20.16 6.28'
        'L19.88 6.28L19.78 6.38L19.22 6.28L18.75 6.47L15.56 9.66L15.47 9.84'
        'L15.56 10.78L15.28 11.06L14.91 11.06L13.03 9.19L18.84 3.38L19.59 3.09Z'
        '"/>'
    ),
    # scissors — literal scissors (two finger loops + crossed blades)
    "scissors": _svg(
        '<circle cx="6" cy="6" r="3" fill="none" stroke="#000000" stroke-width="1.6"/>'
        '<circle cx="6" cy="18" r="3" fill="none" stroke="#000000" stroke-width="1.6"/>'
        '<path d="M20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12" fill="none" '
        'stroke="#000000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
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
