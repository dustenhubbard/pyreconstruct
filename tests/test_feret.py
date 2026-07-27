"""Correctness tests for min/max Feret diameters (modules/calc/feret.py).

The minimum Feret diameter of a point set is its *minimum width*: the smallest
distance between two parallel supporting lines. By the standard rotating-calipers
result, that minimum is attained when one of the two lines is flush with an edge
of the convex hull, so the answer is

    min over hull edges e of (extent of the point set along the normal of e)

which is emphatically *not* the same thing as the smallest distance between a
pair of antipodal hull vertices. For a thin triangle the two disagree by a factor
of five. These tests pin the width definition, using two independent oracles:

  * ``_exact_min_width`` -- every candidate direction is the normal of some pair
    of input points, and every hull edge is such a pair, so sweeping all O(n^2)
    pairs is exact (no sampling error) for the small sets used here.
  * ``_brute_min_width`` -- a dense sweep of directions, as a cross-check that
    the pair-based oracle is not itself missing the optimum.

The maximum Feret diameter is the ordinary set diameter and is checked against a
brute-force all-pairs maximum.

Invariance is the sharpest available oracle for this measurement: a rigid motion
cannot change either diameter, and a uniform scale must scale both linearly.
Traces reach ``feret()`` after an alignment transform is applied, so rotational
invariance is not a theoretical nicety -- it is the property that decides whether
two views of the same trace report the same width.
"""
import math

import pytest

from PyReconstruct.modules.calc.feret import feret


# ---------------------------------------------------------------------------
# helpers: shapes, rigid motions, and independent oracles
# ---------------------------------------------------------------------------

def _rotate(points, degrees, tx=0.0, ty=0.0):
    """Rigid motion: rotate about the origin by ``degrees``, then translate."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [(c * x - s * y + tx, s * x + c * y + ty) for x, y in points]


def _rect_with_collinear_edges(pts_per_edge, w=10.0, h=4.0):
    """A w x h rectangle carrying ``pts_per_edge`` evenly spaced points on each
    edge, i.e. exactly collinear runs on the hull boundary -- the shape of
    pixel-derived, grid-snapped, and interpolated traces."""
    n = pts_per_edge
    xs = [w * i / (n - 1) for i in range(n)]
    ys = [h * i / (n - 1) for i in range(n)]
    return ([(x, 0.0) for x in xs] + [(w, y) for y in ys]
            + [(x, h) for x in reversed(xs)] + [(0.0, y) for y in reversed(ys)])


def _exact_min_width(points):
    """Exact minimum width: sweep the normal of every pair of distinct points.

    The optimal supporting direction is the normal of a convex-hull edge, and
    every hull edge joins two input points, so this candidate set provably
    contains the optimum. For a fixed direction the extent (max - min
    projection) is computed exactly, so the result is exact, not approximate.
    """
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    best = math.inf
    for i, (ax, ay) in enumerate(pts):
        for bx, by in pts[i + 1:]:
            ex, ey = bx - ax, by - ay
            length = math.hypot(ex, ey)
            if length == 0.0:
                continue
            nx, ny = -ey / length, ex / length
            projections = [x * nx + y * ny for x, y in pts]
            extent = max(projections) - min(projections)
            if extent < best:
                best = extent
    return 0.0 if best is math.inf else best


def _brute_min_width(points, samples=4001):
    """Cross-check oracle: dense sweep of supporting-line directions."""
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    best = math.inf
    for k in range(samples):
        a = math.pi * k / samples
        nx, ny = math.cos(a), math.sin(a)
        projections = [x * nx + y * ny for x, y in pts]
        best = min(best, max(projections) - min(projections))
    return best


def _brute_max_diameter(points):
    """Exact maximum Feret: the greatest pairwise distance."""
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    return max(math.dist(p, q)
               for i, p in enumerate(pts) for q in pts[i + 1:])


# A gallery of shapes with no collinear runs and no rotation applied, i.e. the
# plainest possible inputs. Feret is a property of the convex hull, so the
# non-convex members are scored against the width of their hull, which the
# oracles compute for free.
SHAPES = {
    "thin_triangle": [(0.0, 0.0), (10.0, 0.0), (5.0, 1.0)],
    "equilateral": [(0.0, 0.0), (10.0, 0.0), (5.0, 8.6602540378443865)],
    "convex_pentagon": [(0.0, 0.0), (6.0, -1.0), (9.0, 4.0), (4.0, 7.0), (-1.0, 4.0)],
    "square": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
    "rectangle": [(0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)],
    "needle": [(0.0, 0.0), (100.0, 0.0), (100.0, 0.5), (0.0, 0.5)],
    "l_shape": [(0.0, 0.0), (10.0, 0.0), (10.0, 2.0),
                (2.0, 2.0), (2.0, 10.0), (0.0, 10.0)],
    "scattered": [(0.0, 0.0), (10.0, 1.0), (3.0, 9.0), (-2.0, 4.0), (7.0, -3.0)],
}


# ---------------------------------------------------------------------------
# the definition: min Feret is the minimum width, not a vertex-pair distance
# ---------------------------------------------------------------------------

def test_min_feret_of_thin_triangle_is_its_smallest_altitude():
    """A triangle's minimum width is its shortest altitude.

    For (0,0), (10,0), (5,1) the area is 5, so the altitude onto the length-10
    base is 2*5/10 = 1.0. Every pairwise vertex distance is at least 5.0999,
    so any implementation that reports the smallest distance between a pair of
    antipodal hull vertices overstates this width by a factor of five.
    """
    triangle = SHAPES["thin_triangle"]
    min_feret, _ = feret(list(triangle))
    assert min_feret == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_min_feret_matches_exact_minimum_width(name):
    """min Feret equals the exact minimum width for every gallery shape."""
    points = SHAPES[name]
    min_feret, _ = feret(list(points))
    assert min_feret == pytest.approx(_exact_min_width(points), rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_exact_and_brute_force_width_oracles_agree(name):
    """Guard on the oracles themselves: the exact pair-normal sweep must not be
    beaten by a dense direction sweep (it would mean the candidate set is
    incomplete and every assertion above is measuring the wrong thing)."""
    points = SHAPES[name]
    exact = _exact_min_width(points)
    assert exact <= _brute_min_width(points) + 1e-9


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_max_feret_is_the_farthest_pair(name):
    points = SHAPES[name]
    _, max_feret = feret(list(points))
    assert max_feret == pytest.approx(_brute_max_diameter(points), rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_min_feret_never_exceeds_max_feret(name):
    min_feret, max_feret = feret(list(SHAPES[name]))
    assert min_feret <= max_feret + 1e-12


# ---------------------------------------------------------------------------
# rigid-motion invariance -- the reported failure
# ---------------------------------------------------------------------------

# Angles chosen to include ones where the naive orientation determinant
# mis-decides collinear hull runs; 63.43494882292201 deg is atan(2), which maps
# the rectangle's collinear runs onto near-degenerate determinants.
ANGLES = [0.0, 0.3, 1.0, 5.0, 17.5, 30.0, 45.0, 63.4, 63.43494882292201, 89.9]
PTS_PER_EDGE = [3, 5, 10, 20, 40]


@pytest.mark.parametrize("degrees", ANGLES)
@pytest.mark.parametrize("pts_per_edge", PTS_PER_EDGE)
def test_rotated_rectangle_min_feret_is_its_width(degrees, pts_per_edge):
    """A rigid rotation preserves distance, so a rotated 10x4 rectangle still
    has minimum Feret exactly 4.0 no matter how many collinear points sit on
    its edges or what angle the alignment transform applies."""
    points = _rotate(_rect_with_collinear_edges(pts_per_edge), degrees, 3.7, -2.1)
    min_feret, _ = feret(list(points))
    assert min_feret == pytest.approx(4.0, abs=1e-9)


@pytest.mark.parametrize("degrees", ANGLES)
@pytest.mark.parametrize("pts_per_edge", PTS_PER_EDGE)
def test_rotated_rectangle_max_feret_is_its_diagonal(degrees, pts_per_edge):
    """The same rotation leaves the max Feret at the diagonal sqrt(116)."""
    points = _rotate(_rect_with_collinear_edges(pts_per_edge), degrees, 3.7, -2.1)
    _, max_feret = feret(list(points))
    assert max_feret == pytest.approx(math.hypot(10.0, 4.0), abs=1e-9)


@pytest.mark.parametrize("name", sorted(SHAPES))
@pytest.mark.parametrize("degrees", [0.0, 7.0, 33.0, 45.0, 63.4, 90.0, 180.0, 271.5])
def test_feret_is_invariant_under_rigid_motion(name, degrees):
    """Rotation plus translation cannot change either diameter."""
    points = SHAPES[name]
    base_min, base_max = feret(list(points))
    moved = _rotate(points, degrees, -1234.5, 987.25)
    moved_min, moved_max = feret(list(moved))
    assert moved_min == pytest.approx(base_min, rel=1e-9, abs=1e-9)
    assert moved_max == pytest.approx(base_max, rel=1e-9, abs=1e-9)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_feret_is_invariant_under_translation(name):
    points = SHAPES[name]
    base_min, base_max = feret(list(points))
    shifted = [(x + 1000.0, y - 500.0) for x, y in points]
    shifted_min, shifted_max = feret(list(shifted))
    assert shifted_min == pytest.approx(base_min, rel=1e-9, abs=1e-9)
    assert shifted_max == pytest.approx(base_max, rel=1e-9, abs=1e-9)


@pytest.mark.parametrize("name", sorted(SHAPES))
@pytest.mark.parametrize("scale", [0.001, 0.5, 2.0, 1000.0])
def test_feret_scales_linearly(name, scale):
    """A uniform scale multiplies both diameters by the same factor."""
    points = SHAPES[name]
    base_min, base_max = feret(list(points))
    scaled = [(x * scale, y * scale) for x, y in points]
    scaled_min, scaled_max = feret(list(scaled))
    assert scaled_min == pytest.approx(base_min * scale, rel=1e-9)
    assert scaled_max == pytest.approx(base_max * scale, rel=1e-9)


def test_feret_is_invariant_under_reflection():
    """Mirroring is also an isometry."""
    points = SHAPES["convex_pentagon"]
    base = feret(list(points))
    mirrored = feret([(-x, y) for x, y in points])
    assert mirrored[0] == pytest.approx(base[0], rel=1e-12)
    assert mirrored[1] == pytest.approx(base[1], rel=1e-12)


def test_feret_is_invariant_under_point_order():
    """The answer depends on the point set, not the order it arrives in."""
    points = SHAPES["scattered"]
    base = feret(list(points))
    for rotation in range(1, len(points)):
        rolled = points[rotation:] + points[:rotation]
        assert feret(list(rolled))[0] == pytest.approx(base[0], rel=1e-12)
        assert feret(list(rolled))[1] == pytest.approx(base[1], rel=1e-12)
    assert feret(list(reversed(points)))[0] == pytest.approx(base[0], rel=1e-12)


def test_duplicated_points_do_not_change_feret():
    """Repeated vertices (a common artifact of interpolation and imports) are
    geometrically inert."""
    points = SHAPES["convex_pentagon"]
    base = feret(list(points))
    doubled = [p for p in points for _ in range(3)]
    assert feret(list(doubled))[0] == pytest.approx(base[0], rel=1e-12)
    assert feret(list(doubled))[1] == pytest.approx(base[1], rel=1e-12)


# ---------------------------------------------------------------------------
# degenerate inputs and purity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "points",
    [
        [],                                             # empty
        [(1.0, 1.0)],                                   # single point
        [(2.0, 2.0), (2.0, 2.0), (2.0, 2.0)],           # all coincident
    ],
)
def test_degenerate_point_sets_are_zero(points):
    assert feret(list(points)) == (0.0, 0.0)


@pytest.mark.parametrize(
    "points",
    [
        [(0.0, 0.0), (5.0, 0.0)],                                   # two points
        [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)],           # collinear
        [(0.0, 0.0), (0.0, 5.0), (0.0, 2.0)],                       # vertical
        [(0.0, 0.0), (5.0, 0.0), (2.0, 0.0)],                       # horizontal
    ],
)
def test_zero_area_point_sets_have_zero_min_and_correct_max(points):
    """A segment has no width, but it does have a length."""
    min_feret, max_feret = feret(list(points))
    assert min_feret == pytest.approx(0.0, abs=1e-12)
    assert max_feret == pytest.approx(_brute_max_diameter(points), rel=1e-12)


def test_feret_does_not_mutate_its_argument():
    """feret() is a measurement, not a transformation: callers hand it their own
    point list (TraceData does) and must get it back unchanged."""
    points = [(10.0, 10.0), (0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]
    original = list(points)
    feret(points)
    assert points == original
