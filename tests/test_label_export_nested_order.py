"""Label export draws an object's traces by nesting, like the 3D volume.

``_drawHoledLabel`` filled every positive trace and then cleared every
negative one, so a positive inside one of the object's own holes (an island)
was filled and then erased. It now draws in the order ``nestedFillOrder``
gives. These check the island case and that every layout without an island
comes out pixel for pixel the way the old two passes drew it.
"""
import types

import numpy as np
import pytest

from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.calc.nesting import nestedFillOrder
from PyReconstruct.modules.datatypes import Trace, Transform

SIZE = 100


def _square(name, lo, hi, negative=False, x=0):
    trace = Trace(name, (255, 0, 0), closed=True)
    trace.points = [(lo + x, lo), (hi + x, lo), (hi + x, hi), (lo + x, hi)]
    trace.negative = negative
    return trace


def _layer():
    section = types.SimpleNamespace(mag=1.0, tform=Transform([1, 0, 0, 0, 1, 0]))
    series = types.SimpleNamespace(window=None)
    return TraceLayer(section, series)


def _labels(traces, draw=None):
    """Labels for a 100 by 100 window at 1 px per unit."""
    layer = _layer()
    if draw is not None:
        layer._drawHoledLabel = types.MethodType(draw, layer)
    arr, ids = layer.generateLabelsArray(
        (SIZE, SIZE), [0, 0, SIZE, SIZE], traces
    )
    return arr, ids


def _at(arr, x, y):
    """The label at series point (x, y); rows run top down."""
    return int(arr[arr.shape[0] - 1 - y, x])


def _twoPassDraw(self, arr, traces, label, tform=None):
    """The old drawing: every positive fills, then every negative clears."""
    from skimage.draw import polygon

    pix = [(self.traceToPixArray(trace, tform), trace.negative) for trace in traces]
    positive = [pts for pts, negative in pix if not negative and len(pts)]
    if not positive:
        return
    h, w = arr.shape
    pts = np.concatenate(positive)
    x0, y0 = np.maximum(pts.min(axis=0), 0)
    x1 = min(int(pts[:, 0].max()) + 1, w)
    y1 = min(int(pts[:, 1].max()) + 1, h)
    if x0 >= x1 or y0 >= y1:
        return
    mask = np.zeros((y1 - y0, x1 - x0), dtype=bool)
    for fill in (True, False):
        for pts, negative in pix:
            if negative == fill or not len(pts):
                continue
            yy, xx = polygon(pts[:, 1] - y0, pts[:, 0] - x0, mask.shape)
            mask[yy, xx] = fill
    arr[y0:y1, x0:x1][mask] = label


PLAIN_LAYOUTS = {
    "one ring": [_square("a", 10, 90)],
    "ring with hole": [_square("a", 10, 90), _square("a", 30, 70, negative=True)],
    "hole listed first": [
        _square("a", 30, 70, negative=True),
        _square("a", 10, 90),
    ],
    "two separate rings": [_square("a", 5, 40), _square("a", 55, 95)],
    "two rings, one with a hole": [
        _square("a", 5, 40),
        _square("a", 55, 95),
        _square("a", 65, 85, negative=True),
    ],
    "hole across the edge": [
        _square("a", 10, 60),
        _square("a", 40, 90, negative=True),
    ],
    "hole off the edge": [
        _square("a", -20, 60),
        _square("a", 10, 30, negative=True),
    ],
    "positive across the hole edge by less than a pixel": [
        _square("a", 10, 90),
        _square("a", 30, 70, negative=True),
        _square("a", 40, 70.4),
    ],
    "another object in the hole": [
        _square("a", 10, 90),
        _square("a", 30, 70, negative=True),
        _square("b", 45, 55),
    ],
}


@pytest.mark.parametrize("layout", list(PLAIN_LAYOUTS))
def test_layouts_without_an_island_draw_as_before(layout):
    traces = PLAIN_LAYOUTS[layout]

    arr, ids = _labels(traces)
    old, old_ids = _labels(traces, draw=_twoPassDraw)

    assert ids == old_ids
    assert arr.any()
    np.testing.assert_array_equal(arr, old)


def _islandInHole():
    return [
        _square("a", 10, 90),
        _square("a", 30, 70, negative=True),
        _square("a", 45, 55),
    ]


def test_island_inside_its_own_hole_keeps_the_label():
    arr, ids = _labels(_islandInHole())

    assert _at(arr, 50, 50) == ids["a"]  # the island
    assert _at(arr, 35, 35) == 0  # the hole around it
    assert _at(arr, 20, 20) == ids["a"]  # the ring


def test_two_passes_lost_the_island():
    ## the case above, drawn the old way, to show what it fixes
    arr, ids = _labels(_islandInHole(), draw=_twoPassDraw)

    assert _at(arr, 50, 50) == 0


def test_hole_inside_the_island_clears_again():
    traces = _islandInHole() + [_square("a", 48, 52, negative=True)]

    arr, ids = _labels(traces)

    assert _at(arr, 50, 50) == 0  # the hole in the island
    assert _at(arr, 46, 46) == ids["a"]  # the island around it
    assert _at(arr, 35, 35) == 0
    assert _at(arr, 20, 20) == ids["a"]


def test_island_order_does_not_matter():
    traces = list(reversed(_islandInHole()))

    arr, ids = _labels(traces)

    assert _at(arr, 50, 50) == ids["a"]
    assert _at(arr, 35, 35) == 0
    assert _at(arr, 20, 20) == ids["a"]


def test_order_comes_from_the_unrounded_traces():
    ## 40 to 70.4 rounds to 40 to 70, inside the hole, but the trace itself
    ## crosses the hole's edge, so it is no island and the hole clears it
    traces = PLAIN_LAYOUTS["positive across the hole edge by less than a pixel"]

    arr, ids = _labels(traces)

    assert _at(arr, 50, 50) == 0
    assert _at(arr, 20, 20) == ids["a"]


def test_island_smaller_than_a_pixel_draws_one_pixel():
    ## the 3D order counts it as an island, so it fills again after the hole,
    ## and its outline rounds to one pixel
    outer, hole, island = (
        _square("a", 10, 90),
        _square("a", 30, 70, negative=True),
        _square("a", 49.9, 50.1),
    )
    pos, neg = [outer.points, island.points], [hole.points]
    assert nestedFillOrder(pos, neg)[-1] == (island.points, True)

    arr, ids = _labels([outer, hole, island])

    ## inside the hole, only the pixel that series point (50, 50) rounds to
    ## (row 100 - 50) carries the label
    hole_px = arr[35:66, 35:66]
    assert np.argwhere(hole_px == ids["a"]).tolist() == [[50 - 35, 50 - 35]]
    assert int(np.count_nonzero(hole_px)) == 1


def _rect(name, x0, y0, x1, y1, negative=False):
    trace = Trace(name, (255, 0, 0), closed=True)
    trace.points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    trace.negative = negative
    return trace


@pytest.mark.parametrize("name, touch", [
    ("sharing an edge", (60, 45, 66, 55)),
    ("touching a corner", (60, 60, 66, 66)),
])
def test_negative_touching_the_island_clears_its_edge(name, touch):
    ## a negative that only touches the island clears the island's edge
    ## pixels again after the island refills, as it does with no hole
    outer, island = _square("a", 10, 90), _square("a", 40, 60)
    hole = _square("a", 30, 70, negative=True)
    cut = _rect("a", *touch, negative=True)

    arr, ids = _labels([outer, hole, island, cut])
    no_hole, _ = _labels([outer, island, cut], draw=_twoPassDraw)

    ## the island's pixels: series y 40 to 60 rounds to rows 60 down to 40
    rows, cols = slice(SIZE - 60, SIZE - 40 + 1), slice(40, 61)
    assert (no_hole[rows, cols] == 0).any(), name
    np.testing.assert_array_equal(arr[rows, cols], no_hole[rows, cols])
    assert arr[SIZE - touch[1], touch[0]] == 0  # a shared edge pixel
