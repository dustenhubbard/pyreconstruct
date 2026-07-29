"""Equivalence tests for the vectorized anchor-point selection in Grid.

Grid.getAnchorTrace() used to call the scalar Grid.isAnchorPoint() once per
contour point; it now looks the points up in a boolean mask built once per Grid
with a single 3x3 convolution. isAnchorPoint() is untouched and is used here as
the reference oracle -- every test compares the vectorized result against a
plain Python loop over it and asserts exact array equality.

Border semantics matter and are pinned below. isAnchorPoint() indexes
self.grid[y + dy, x + dx] with no bounds check, so:

  * a neighbour index of -1 wraps around to the opposite edge of the grid
    (ordinary numpy negative indexing), and contours really do contain points
    on row 0 / column 0, so this case is reachable;
  * a neighbour index of h or w would raise IndexError, but _generateGrid
    allocates (ymax-ymin+2, xmax-xmin+2) while only ever drawing at coordinates
    up to (ymax-ymin, xmax-xmin), so the last row and last column are always
    zero and cv2.findContours -- which only returns nonzero pixels -- never
    yields a point there. test_last_row_and_column_are_always_empty pins that.

The mask therefore pads the grid with mode="wrap", which reproduces the
wrap-around exactly instead of the "out of bounds reads as 0" that a plain
BORDER_CONSTANT filter would give. That makes the two implementations agree on
every point isAnchorPoint() can answer, border points included, without
relying on the zero-border property.
"""

import time

import cv2
import numpy as np
import pytest

from PyReconstruct.modules.calc.grid import Grid


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bare_grid(array, shift=(0, 0)):
    """A Grid wrapping a hand-made array, bypassing __init__/_generateGrid."""
    g = Grid.__new__(Grid)
    g.grid = np.asarray(array)
    g.grid_shift = shift
    g._anchor_mask = None
    return g


def _scalar_anchor_trace(grid_obj, trace):
    """The original getAnchorTrace body, verbatim, as the reference oracle."""
    new_trace = []
    for point in trace:
        if grid_obj.isAnchorPoint(*point):
            new_trace.append(point)
    return np.array(new_trace)


def _contours(grid):
    """The contours getExterior() works from."""
    cv_traces, _ = cv2.findContours(
        grid.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    return [t[:, 0, :] for t in cv_traces]


def _scalar_exterior(grid_obj):
    """The original getExterior body, using the scalar oracle."""
    traces = []
    for trace in _contours(grid_obj.grid):
        new_trace = _scalar_anchor_trace(grid_obj, trace)
        new_trace += grid_obj.grid_shift
        traces.append(new_trace.tolist())
    return traces


def _random_grid(rng, h, w):
    """Sprinkle counts the way _drawGridLine does: mostly 1s, some overlaps."""
    grid = np.zeros(h * w, dtype=int)
    idx = rng.integers(0, h * w, size=max(1, (h * w) // 4))
    for i in idx:
        grid[i] += 1
    return grid.reshape(h, w)


def _blob(rng, n_pts=None, center=None, radius=None):
    """A closed, wobbly, roughly convex polygon of integer points."""
    n_pts = int(rng.integers(5, 40)) if n_pts is None else n_pts
    cx, cy = rng.integers(0, 400, 2) if center is None else center
    radius = int(rng.integers(8, 200)) if radius is None else radius
    angles = np.sort(rng.random(n_pts)) * 2 * np.pi
    radii = radius * (0.4 + 0.6 * rng.random(n_pts))
    pts = np.stack([cx + radii * np.cos(angles), cy + radii * np.sin(angles)], 1)
    return pts.astype(int).tolist()


# ---------------------------------------------------------------------------
# bit-identity on randomized grids
# ---------------------------------------------------------------------------

def test_bit_identical_on_randomized_grids():
    """Vectorized getAnchorTrace == scalar loop, exactly, over many trials."""
    rng = np.random.default_rng(11)
    mismatches = []
    trials = 0
    for _ in range(60):
        h, w = int(rng.integers(4, 220)), int(rng.integers(4, 220))
        grid = _random_grid(rng, h, w)
        g = _bare_grid(grid)

        # every in-range point the scalar version can answer without raising
        ys, xs = np.mgrid[0:h - 1, 0:w - 1]
        pts = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.int32)

        ref = _scalar_anchor_trace(g, pts)
        got = g.getAnchorTrace(pts)
        trials += 1
        if not (ref.shape == got.shape and np.array_equal(ref, got)):
            mismatches.append((h, w))

    assert trials == 60
    assert mismatches == []


def test_bit_identical_on_sparse_and_saturated_grids():
    """Values 0/1/>1 and near-empty or fully-filled grids all agree."""
    rng = np.random.default_rng(12)
    for fill in (0.0, 0.01, 0.05, 0.5, 0.95, 1.0):
        for _ in range(6):
            h, w = int(rng.integers(4, 90)), int(rng.integers(4, 90))
            grid = (rng.random((h, w)) < fill).astype(int)
            # push some cells above 1 so the "> 1" branch is exercised
            grid += (rng.random((h, w)) < fill / 2).astype(int)
            g = _bare_grid(grid)
            ys, xs = np.mgrid[0:h - 1, 0:w - 1]
            pts = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.int32)
            ref = _scalar_anchor_trace(g, pts)
            got = g.getAnchorTrace(pts)
            assert ref.shape == got.shape
            assert np.array_equal(ref, got)


def test_isanchorpoint_still_matches_the_mask_pointwise():
    """The kept public scalar method agrees with the cached mask everywhere."""
    rng = np.random.default_rng(13)
    grid = _random_grid(rng, 60, 75)
    g = _bare_grid(grid)
    mask = g._anchorMask()
    h, w = grid.shape
    for y in range(h - 1):
        for x in range(w - 1):
            assert bool(mask[y, x]) == g.isAnchorPoint(x, y)


# ---------------------------------------------------------------------------
# the real code path: Grid built from traces, compared through getExterior
# ---------------------------------------------------------------------------

def test_get_exterior_matches_scalar_reference_on_realistic_traces():
    rng = np.random.default_rng(21)
    for _ in range(40):
        trace = _blob(rng)
        g = Grid([trace])
        ref = _scalar_exterior(_bare_grid(g.grid, g.grid_shift))
        got = g.getExterior()
        assert len(ref) == len(got)
        for a, b in zip(ref, got):
            assert np.array_equal(np.array(a), np.array(b))


def test_get_exterior_matches_scalar_reference_on_multiple_traces():
    """getExterior loops over several contours -- the cached mask must hold."""
    rng = np.random.default_rng(22)
    for _ in range(20):
        traces = [
            _blob(rng, center=(60, 60), radius=40),
            _blob(rng, center=(300, 90), radius=50),
            _blob(rng, center=(180, 320), radius=60),
        ]
        g = Grid(traces)
        assert len(_contours(g.grid)) >= 2
        ref = _scalar_exterior(_bare_grid(g.grid, g.grid_shift))
        got = g.getExterior()
        assert len(ref) == len(got)
        for a, b in zip(ref, got):
            assert np.array_equal(np.array(a), np.array(b))


def test_get_anchor_trace_preserves_order_and_dtype():
    rng = np.random.default_rng(23)
    g = Grid([_blob(rng, center=(100, 100), radius=60)])
    contour = _contours(g.grid)[0]
    got = g.getAnchorTrace(contour)
    ref = _scalar_anchor_trace(_bare_grid(g.grid, g.grid_shift), contour)
    assert got.dtype == ref.dtype
    assert got.shape == ref.shape
    assert np.array_equal(got, ref)
    # the kept points appear in contour order
    order = [tuple(p) for p in contour]
    kept = [tuple(p) for p in got]
    assert kept == [p for p in order if p in set(kept)][:len(kept)]


def test_get_anchor_trace_does_not_mutate_its_input():
    """getExterior does an in-place += on the result, so it must be a copy."""
    rng = np.random.default_rng(24)
    g = Grid([_blob(rng, center=(100, 100), radius=60)])
    contour = _contours(g.grid)[0]
    before = contour.copy()
    g.getExterior()
    assert np.array_equal(contour, before)


# ---------------------------------------------------------------------------
# border semantics
# ---------------------------------------------------------------------------

def test_last_row_and_column_are_always_empty_for_generated_grids():
    """Why the IndexError branch of isAnchorPoint is unreachable in practice."""
    rng = np.random.default_rng(31)
    for _ in range(60):
        g = Grid([_blob(rng)])
        assert not g.grid[-1].any()
        assert not g.grid[:, -1].any()
        h, w = g.grid.shape
        for contour in _contours(g.grid):
            assert contour[:, 0].max() <= w - 2
            assert contour[:, 1].max() <= h - 2


def test_contours_do_reach_row_zero_and_column_zero():
    """The negative-index wrap-around case is reachable, so it must match."""
    rng = np.random.default_rng(32)
    seen = 0
    for _ in range(60):
        g = Grid([_blob(rng)])
        for contour in _contours(g.grid):
            seen += int(((contour[:, 0] == 0) | (contour[:, 1] == 0)).sum())
    assert seen > 0


def test_border_points_match_scalar_including_negative_wraparound():
    """Explicit border check on grids whose opposite edge is NOT zero.

    Generated grids always have a zero last row/column, which would make
    wrap-around and zero-padding indistinguishable. These grids deliberately
    put nonzero values on the far edges, so only the wrap semantics can match.
    """
    rng = np.random.default_rng(33)
    for _ in range(30):
        h, w = int(rng.integers(4, 60)), int(rng.integers(4, 60))
        grid = _random_grid(rng, h, w)
        # guarantee a populated last row/column
        grid[-1, :] += 1
        grid[:, -1] += 1
        g = _bare_grid(grid)

        border = [(x, 0) for x in range(w - 1)]
        border += [(0, y) for y in range(h - 1)]
        border += [(x, h - 2) for x in range(w - 1)]
        border += [(w - 2, y) for y in range(h - 1)]
        pts = np.array(border, dtype=np.int32)

        ref = _scalar_anchor_trace(g, pts)
        got = g.getAnchorTrace(pts)
        assert ref.shape == got.shape
        assert np.array_equal(ref, got)


def test_isanchorpoint_still_raises_past_the_last_row_or_column():
    """isAnchorPoint kept its exact behaviour, IndexError included."""
    g = _bare_grid(np.ones((5, 5), dtype=int))
    with pytest.raises(IndexError):
        g.isAnchorPoint(4, 2)
    with pytest.raises(IndexError):
        g.isAnchorPoint(2, 4)


# ---------------------------------------------------------------------------
# empty / degenerate cases
# ---------------------------------------------------------------------------

def test_no_anchor_points_returns_the_same_empty_array_as_before():
    """Zero anchors still yields np.array([]) -- shape (0,), float64."""
    g = _bare_grid(np.zeros((5, 5), dtype=int), shift=(10, 20))
    out = g.getAnchorTrace(np.array([[1, 1], [2, 2]], dtype=np.int32))
    ref = _scalar_anchor_trace(g, np.array([[1, 1], [2, 2]], dtype=np.int32))
    assert out.shape == ref.shape == (0,)
    assert out.dtype == ref.dtype == np.float64


def test_empty_input_trace_returns_the_same_empty_array_as_before():
    g = _bare_grid(np.zeros((5, 5), dtype=int), shift=(10, 20))
    empty = np.zeros((0, 2), dtype=np.int32)
    out = g.getAnchorTrace(empty)
    ref = _scalar_anchor_trace(g, empty)
    assert out.shape == ref.shape == (0,)
    assert out.dtype == ref.dtype == np.float64


def test_get_exterior_skips_a_contour_with_no_anchors():
    """A contour that keeps no anchor points now yields no exterior.

    The old body did ``new_trace += self.grid_shift`` unconditionally, and a
    shape-(0,) array cannot be broadcast against a 2-tuple; ``_scalar_exterior``
    is that body verbatim and still shows the raise. A lone pixel is such a
    case. See tests/test_grid_exterior_no_anchors.py for the full treatment,
    including how far the degenerate contour is reachable.
    """
    grid = np.zeros((7, 7), dtype=int)
    grid[3, 3] = 1
    g = _bare_grid(grid, shift=(0, 0))
    with pytest.raises(ValueError):
        _scalar_exterior(g)
    assert _bare_grid(grid, shift=(0, 0)).getExterior() == []


def test_single_point_trace_draws_nothing_and_yields_no_contours():
    g = Grid([[(5, 5)]])
    assert not g.grid.any()
    assert g.getExterior() == []


def test_two_point_trace_matches_scalar_reference():
    g = Grid([[(2, 2), (12, 7)]])
    ref = _scalar_exterior(_bare_grid(g.grid, g.grid_shift))
    got = g.getExterior()
    assert len(ref) == len(got)
    for a, b in zip(ref, got):
        assert np.array_equal(np.array(a), np.array(b))


def test_tiny_grids_do_not_break_the_mask():
    """Grids smaller than the 3x3 kernel still pad and filter cleanly."""
    for shape in ((1, 1), (1, 5), (5, 1), (2, 2), (3, 3)):
        g = _bare_grid(np.ones(shape, dtype=int))
        mask = g._anchorMask()
        assert mask.shape == shape
        assert mask.dtype == bool


# ---------------------------------------------------------------------------
# caching
# ---------------------------------------------------------------------------

def test_mask_is_computed_once_and_cached():
    rng = np.random.default_rng(41)
    g = Grid([_blob(rng, center=(100, 100), radius=60)])
    first = g._anchorMask()
    assert g._anchorMask() is first
    g.getExterior()
    assert g._anchorMask() is first


def test_regenerating_the_grid_invalidates_the_cache():
    rng = np.random.default_rng(42)
    g = Grid([_blob(rng, center=(100, 100), radius=60)])
    stale = g._anchorMask()
    g.traces = [np.array(_blob(rng, center=(40, 40), radius=15))]
    g._generateGrid()
    fresh = g._anchorMask()
    assert fresh is not stale
    assert fresh.shape == g.grid.shape


def test_vectorized_path_is_faster_than_the_scalar_loop():
    """Sanity check on the point of the change, with generous headroom."""
    grid = np.zeros((700, 700), dtype=np.uint8)
    cv2.circle(grid, (350, 350), 300, 1, 2)
    g = _bare_grid(grid.astype(int), shift=(0, 0))
    contour = _contours(g.grid)[0]
    assert len(contour) > 1000

    g._anchorMask()  # warm the cache; getExterior pays this once per Grid
    t0 = time.perf_counter()
    for _ in range(3):
        g.getAnchorTrace(contour)
    t_vec = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(3):
        _scalar_anchor_trace(g, contour)
    t_scalar = time.perf_counter() - t0

    assert t_vec < t_scalar
