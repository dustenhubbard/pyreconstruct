"""The intermittent 1px black line at the field's edge, pinned for good.

His report (2026-08-26): a thin vertical line at the field's left edge,
white on the default theme, blue on qdark, per-section, oscillating on
scroll. Parked, then root-caused by the review fleet: adjustBounds rounds
the crop to whole image pixels, the scaled crop truncates besides, so the
scaled image came up short of the pixmap; the centered rip then started at
a NEGATIVE origin, and QImage.copy paints out-of-source columns black. The
theme showed through wherever the black layer was composited. 3029 of 4000
random views reproduced it.

These tests run the REAL ImageLayer against a real white image on disk, so
the whole pipeline (crop, scale, fill, transform, rip) is what is measured.
"""

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

pytestmark = pytest.mark.gui


@pytest.fixture
def white_layer(qapp, real_series, tmp_path):
    """A real ImageLayer over a solid-white 2000x2000 image."""
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    img = QImage(2000, 2000, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)
    src = tmp_path / "white.png"
    img.save(str(src))

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(tmp_path)
    section.src = "white.png"
    # pinned so the test's windows sit fully inside the 20x20-unit image
    # with no transform in play: any black then IS the bug, never real fill
    section.mag = 0.01
    from PyReconstruct.modules.datatypes import Transform
    section.tforms[real_series.alignment] = Transform([1, 0, 0, 0, 1, 0])

    layer = ImageLayer(section, real_series)
    assert layer.image_found, "the synthetic image failed to load"
    return layer


def _edge_black_fraction(image, edge):
    """How much of one edge column/row is pure black."""
    w, h = image.width(), image.height()
    if edge in ("left", "right"):
        x = 0 if edge == "left" else w - 1
        samples = [image.pixelColor(x, y) for y in range(h)]
    else:
        y = 0 if edge == "top" else h - 1
        samples = [image.pixelColor(x, y) for x in range(w)]
    black = sum(
        1 for c in samples if (c.red(), c.green(), c.blue()) == (0, 0, 0)
    )
    return black / len(samples)


# The exact shape from the fleet's sweep: mag 0.01, pixmap 977, window
# widths chosen so the rounded crop scales to just under the pixmap.
VIEWS = [
    (3.0, 4.0, 3.7467),
    (2.113, 5.87, 3.7467),
    (7.31, 2.02, 2.9153),
    (4.44, 4.44, 1.2371),
    (0.77, 9.13, 6.5449),
    (5.05, 0.33, 0.7433),
]


@pytest.mark.parametrize("wx, wy, ww", VIEWS)
def test_no_edge_of_the_view_is_a_black_line(white_layer, wx, wy, ww):
    """A window fully inside a white image must render with no black edge."""
    pmw, pmh = 977, 700
    wh = ww * pmh / pmw                      # the aspect the field keeps
    image = white_layer._generateImage((pmw, pmh), [wx, wy, ww, wh])

    assert (image.width(), image.height()) == (pmw, pmh)
    for edge in ("left", "right", "top", "bottom"):
        fraction = _edge_black_fraction(image, edge)
        assert fraction < 0.5, (
            f"the {edge} edge is {fraction:.0%} black at window "
            f"({wx}, {wy}, {ww:.4f}): the edge line is back"
        )


def test_the_sweep_finds_no_black_lines(white_layer):
    """The fleet's brute-force sweep, shrunk to stay fast: many random-ish
    view positions, every edge checked. Before the fix most positions failed."""
    import itertools

    pmw, pmh = 977, 700
    failures = []
    xs = [0.13, 1.77, 3.001, 5.55, 8.4]
    widths = [0.7433, 1.2371, 2.9153, 3.7467, 6.5449]
    for wx, ww in itertools.product(xs, widths):
        wh = ww * pmh / pmw
        image = white_layer._generateImage((pmw, pmh), [wx, wx / 2 + 0.3, ww, wh])
        for edge in ("left", "right", "top", "bottom"):
            if _edge_black_fraction(image, edge) >= 0.5:
                failures.append((wx, ww, edge))

    assert failures == [], f"{len(failures)} black-edged views: {failures[:5]}"
