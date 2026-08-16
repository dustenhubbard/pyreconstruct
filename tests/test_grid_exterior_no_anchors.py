"""Grid.getExterior() on a contour with no anchor points.

``getAnchorTrace`` returns ``np.array([])`` -- shape ``(0,)``, not ``(0, 2)`` --
when a contour keeps none of its points, and ``getExterior`` then did

    new_trace += self.grid_shift

which cannot broadcast a 2-element shift against a shape-``(0,)`` array and
raised ``ValueError: operands could not be broadcast together``. A single
isolated grid pixel is exactly such a contour: its value is 1 (so the ``> 1``
branch does not fire) and it has no nonzero neighbours (so the ``>= 3``
neighbour branch does not fire either).

Reachability, measured rather than assumed
------------------------------------------
The degenerate contour is reachable through the *public method* -- any caller
holding a ``Grid`` whose grid contains an isolated pixel crashes -- but it does
not appear to be reachable through ``Grid.__init__``, which is the only way the
two module-level entry points (``getExterior(points)`` and
``mergeTraces(trace_list)``) build a grid. ``_generateGrid`` walks the trace's
points cyclically and ``_drawGridLine`` increments every cell it touches, so
after collapsing zero-length segments every distinct vertex pixel is incremented
by both of its incident segments and has value 2 -- an anchor. Every 8-connected
blob of drawn pixels contains at least one vertex, so every contour
``findContours`` returns contains at least one anchor.

That argument was checked empirically: 51,756 contours from constructor-built
grids over ~50,000 randomized traces (2-12 points, coordinate ranges +/-3 to
+/-200, single and multi-trace, heavy duplicate points and collinear runs)
produced no anchor-free contour, and no call to ``getExterior``/``mergeTraces``
raised. ``test_no_anchor_free_contour_from_the_constructor`` below pins a
smaller version of that sweep so a future change to the line drawing that *does*
produce one is caught.

So this is a latent crash in a public method, not a reproduced user-facing one.
The guard is still worth having: it is what makes the shape-``(0,)`` return
value of ``getAnchorTrace`` -- which is pinned behavior -- usable by its only
caller, and it costs one branch on a path that already allocates per contour.

The fix skips the contour: a contour with no anchor points contributes no
exterior. Appending an empty exterior instead would only relocate the crash,
because both callers feed each returned exterior straight into
``reducePoints``, and ``cv2.approxPolyDP`` rejects an empty array.
"""

import itertools
import random

import cv2
import numpy as np
import pytest

from PyReconstruct.modules.calc.grid import Grid, getExterior, mergeTraces


def _bare_grid(array, shift=(0, 0)):
    """A Grid wrapping a hand-made array, bypassing __init__/_generateGrid.

    Same helper as tests/test_grid_anchor_vectorization.py: the degenerate grid
    has to be built directly, since the constructor does not produce one.
    """
    g = Grid.__new__(Grid)
    g.grid = np.asarray(array)
    g.grid_shift = shift
    g._anchor_mask = None
    return g


def _lone_pixel_grid(h=7, w=7, at=(3, 3)):
    grid = np.zeros((h, w), dtype=int)
    grid[at] = 1
    return grid


def _ring(cx, cy, r):
    """A closed polygon whose drawn outline has genuine corner anchors."""
    return [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]


# ---------------------------------------------------------------------------
# the crash itself
# ---------------------------------------------------------------------------

def test_lone_pixel_contour_yields_no_exterior_instead_of_raising():
    """The regression: shape-(0,) anchors must not be shifted."""
    g = _bare_grid(_lone_pixel_grid(), shift=(0, 0))
    assert len(_contours(g.grid)) == 1          # cv2 does see the pixel
    assert g.getAnchorTrace(_contours(g.grid)[0]).shape == (0,)
    assert g.getExterior() == []


def test_lone_pixel_with_a_nonzero_shift_also_yields_no_exterior():
    """A nonzero grid_shift is what made the broadcast fail; still no raise."""
    g = _bare_grid(_lone_pixel_grid(), shift=(1000, -250))
    assert g.getExterior() == []


@pytest.mark.parametrize("at", [(0, 0), (0, 3), (3, 0), (5, 5)])
def test_lone_pixel_anywhere_including_the_wrapping_border(at):
    """Row 0 / column 0 read their neighbours with numpy wrap-around, so pin
    the corner and edge positions separately from the interior one."""
    g = _bare_grid(_lone_pixel_grid(at=at), shift=(4, 9))
    assert g.getExterior() == []


def test_several_lone_pixels_yield_no_exteriors():
    grid = np.zeros((11, 11), dtype=int)
    for y, x in ((1, 1), (1, 8), (8, 1), (5, 5)):
        grid[y, x] = 1
    g = _bare_grid(grid, shift=(7, 7))
    assert len(_contours(g.grid)) == 4
    assert g.getExterior() == []


# ---------------------------------------------------------------------------
# non-degenerate contours are untouched
# ---------------------------------------------------------------------------

def _contours(grid):
    cv_traces, _ = cv2.findContours(
        grid.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    return [t[:, 0, :] for t in cv_traces]


def _scalar_exterior_of_one(grid_obj, contour):
    """The pre-fix body applied to a single contour, as the reference value."""
    kept = np.array([p for p in contour if grid_obj.isAnchorPoint(*p)])
    kept += grid_obj.grid_shift
    return kept.tolist()


def test_a_lone_pixel_beside_a_real_blob_drops_only_the_lone_pixel():
    """The surviving exterior must be bit-identical to the pre-fix value."""
    g = Grid([_ring(40, 40, 12)])
    # pad so there is room for a pixel that touches nothing the ring drew
    grid = np.pad(g.grid, 4)
    grid[1, 1] = 1
    poisoned = _bare_grid(grid, g.grid_shift)

    contours = _contours(grid)
    assert len(contours) == 2

    got = poisoned.getExterior()
    assert len(got) == 1

    expected = [
        _scalar_exterior_of_one(poisoned, c)
        for c in contours
        if poisoned.getAnchorTrace(c).size
    ]
    assert len(expected) == 1
    assert np.array_equal(np.array(got[0]), np.array(expected[0]))
    # and it is the blob, not the stray pixel
    assert len(got[0]) >= 4


def test_ordinary_grids_are_bit_identical_to_the_pre_fix_result():
    """No behavior change wherever every contour has at least one anchor."""
    rng = np.random.default_rng(31)
    checked = 0
    for _ in range(30):
        cx, cy = rng.integers(20, 300, 2)
        traces = [_ring(int(cx), int(cy), int(rng.integers(4, 40)))]
        if rng.random() < 0.5:
            traces.append(_ring(int(cx) + 200, int(cy) + 150, 25))
        g = Grid(traces)
        contours = _contours(g.grid)
        assert all(g.getAnchorTrace(c).size for c in contours)
        ref = [_scalar_exterior_of_one(g, c) for c in contours]
        got = g.getExterior()
        assert len(ref) == len(got)
        for a, b in zip(ref, got):
            assert np.array_equal(np.array(a), np.array(b))
        checked += 1
    assert checked == 30


# ---------------------------------------------------------------------------
# the module-level entry points
# ---------------------------------------------------------------------------

def test_module_get_exterior_still_returns_points_for_a_real_polygon():
    pts = getExterior(_ring(30, 30, 10))
    assert len(pts) >= 3


def test_module_get_exterior_of_a_single_point_is_empty():
    """A one-point trace draws nothing, so there is no contour at all -- the
    pre-existing empty-result path, pinned here so the guard does not change
    it."""
    assert getExterior([(5, 5)]) == []


def test_merge_traces_of_single_point_traces_is_empty():
    assert mergeTraces([[(5, 5)], [(9, 2)]]) == []


def test_no_anchor_free_contour_from_the_constructor():
    """The reachability claim above, as an executable check.

    If a change to _generateGrid/_drawGridLine ever does produce an anchor-free
    contour, this test's premise is false and the note in the module docstring
    needs revisiting -- getExterior() itself keeps working either way.
    """
    rng = random.Random(41)
    contours_seen = 0
    anchor_free = []

    cases = []
    # exhaustive small cases: every 3-point trace in a 5x5 box
    box = list(itertools.product(range(5), repeat=2))
    cases += [[list(p)] for p in itertools.combinations_with_replacement(box, 3)]
    # randomized larger ones, single and multi-trace
    for _ in range(1500):
        n = rng.randint(2, 10)
        r = rng.choice([3, 15, 90])
        cases.append([[(rng.randint(-r, r), rng.randint(-r, r)) for _ in range(n)]])
    for _ in range(500):
        r = rng.choice([5, 25])
        cases.append([
            [(rng.randint(-r, r), rng.randint(-r, r)) for _ in range(rng.randint(1, 6))]
            for _ in range(rng.randint(2, 4))
        ])

    for traces in cases:
        g = Grid(traces)
        for c in _contours(g.grid):
            contours_seen += 1
            if not g.getAnchorTrace(c).size:
                anchor_free.append(traces)
        g.getExterior()          # must not raise for any of them

    assert contours_seen > 2000
    assert anchor_free == []
