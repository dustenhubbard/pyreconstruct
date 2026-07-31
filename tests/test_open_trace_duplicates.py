"""Duplicate detection for open traces (reported by Lyndsey Kirk).

Her lab's cfa traces are about 98% open lines, and the duplicate scan was
missing pairs that are obvious by eye: one reported pair measured 0.2581 and
0.25894 in length, 0.33% apart, and was not flagged at a 95% overlap threshold.

The cause is that `Trace.getOverlapRatio` rasterized both traces with
`skimage.draw.polygon`, which implicitly closes the point list. For an open
trace the filled region is therefore the sliver between the polyline and the
straight chord from its last point back to its first, and the shape of that
sliver is governed by the trace's own wiggle rather than by where the curve
lies. Two independent tracings of one structure have independent wiggle, so
their slivers disagree even when the curves sit on top of each other. Measured
on the constructions below, a pair of near-straight profiles 0.08% apart in
length scored 0.1887.

Lowering the threshold is not a fix: 0.1887 would need a threshold near 15%,
which would call everything a duplicate. The metric was measuring the wrong
quantity, so open traces are now compared curve-to-curve instead
(`Trace._openCurveRatio`).

What is pinned here:

  * each of the five constructions that measured below threshold on the area
    metric is now detected at a 95% threshold, through the public
    `Trace.overlaps` and not just through the ratio
  * the same five hold when the two tracings have *different point counts*,
    which is the realistic case and the one that matters: `pointsMatch` has an
    absolute 1e-2 tolerance, so at her 0.25 um scale it rescues a pair whose
    point counts happen to agree, and independent tracings' counts do not
  * genuinely different open traces are still not flagged -- a metric that says
    yes to everything would satisfy every assertion above
  * a trace covering only half of another is not called a duplicate of it
  * closed traces still go through the area comparison, unchanged
  * `Series.findDifferentlyNamedDuplicates` finds an open pair end to end, which
    the ratio fix alone does not achieve: that scan's area-based ratio ceiling
    dropped the near-straight pair at 0.63 before any ratio was measured
"""
import os
import shutil

import numpy as np
import pytest

from PyReconstruct.modules.datatypes.trace import Trace

THRESHOLD = 0.95

## Her scale: a cfa profile about 0.25 um long.
SCALE = 0.25

## The magnification every ratio here is measured at, in um per image pixel. The
## open-trace tolerance is bounded in image pixels, so a ratio for an open pair is
## only defined relative to one (see Trace.getOverlapRatio). 0.00254 is the
## checker fixture's own mag, so the unit cases and the end-to-end cases below are
## measured on the same scale. At this mag the bounds are 0.00254 and 0.0127 um,
## which bracket 2% of a 0.25 um profile (0.005) -- the fraction is what decides
## for a trace this size, and the constructions keep the ratios they had.
MAG = 0.00254


def mk(points, closed=False):
    trace = Trace("cfa", (255, 0, 0), closed=closed)
    trace.points = list(points)
    return trace


def arc_length(points):
    p = np.asarray(points, dtype=float)
    return float(np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1])).sum())


def curve(t):
    """The gently curving profile the constructions are built from."""
    t = np.asarray(t, dtype=float)
    return list(zip((SCALE * t).tolist(), (0.02 * np.sin(3 * t)).tolist()))


def noisy_line_pair(n_a, n_b, seed=3, sigma=0.0005):
    """Two near-straight profiles with independent hand noise, as a cfa often is.

    Both noise realizations come from one stream, drawn in order, which is how
    the pair that measured 0.1887 on the area metric was generated. Keeping the
    construction identical is what lets that number stay quoted here.
    """
    rng = np.random.default_rng(seed)
    out = []
    for n in (n_a, n_b):
        t = np.linspace(0, 1, n)
        y = sigma * rng.normal(size=n)
        out.append(list(zip((SCALE * t).tolist(), y.tolist())))
    return out


def noisy_curve(n, seed, sigma=0.0006):
    """The curving profile with independent hand noise on top."""
    t = np.linspace(0, 1, n)
    y = 0.02 * np.sin(3 * t) + sigma * np.random.default_rng(seed).normal(size=n)
    return list(zip((SCALE * t).tolist(), y.tolist()))


# ---------------------------------------------------------------------------
# The five constructions, at equal point counts (the ratio each measured on the
# area metric is named in the id) and at unequal counts (the realistic case).
#
# Equal counts matter because they isolate the *metric*: four of these five
# pairs were already answered True by pointsMatch, so only the ratio is at
# fault. Unequal counts matter because they are what real independent tracings
# have, and they are the pairs that actually reached the broken ratio and were
# dropped.
# ---------------------------------------------------------------------------

STRAIGHT_EQUAL = noisy_line_pair(30, 30)
STRAIGHT_UNEQUAL = noisy_line_pair(30, 25)

EQUAL_COUNT_CASES = [
    # (id, a, b, ratio the area metric measured)
    ("near-straight, independent noise", *STRAIGHT_EQUAL, 0.1887),
    ("same curve, 30 pts vs 9 pts", curve(np.linspace(0, 1, 30)),
     curve(np.linspace(0, 1, 9)), 0.9746),
    ("same curve, small uniform offset", curve(np.linspace(0, 1, 30)),
     [(x + 0.0008, y + 0.0008) for x, y in curve(np.linspace(0, 1, 30))], 0.8818),
    ("one overshoots the end by 3%", curve(np.linspace(0, 1, 30)),
     curve(np.linspace(0, 1.03, 31)), 0.9052),
    ("wiggly, independent noise", noisy_curve(30, 1), noisy_curve(30, 2), 0.9329),
]

UNEQUAL_COUNT_CASES = [
    ("near-straight, independent noise", *STRAIGHT_UNEQUAL),
    ("same curve, 30 pts vs 9 pts", curve(np.linspace(0, 1, 30)),
     curve(np.linspace(0, 1, 9))),
    ("same curve, small uniform offset", curve(np.linspace(0, 1, 30)),
     [(x + 0.0008, y + 0.0008) for x, y in curve(np.linspace(0, 1, 25))]),
    ("one overshoots the end by 3%", curve(np.linspace(0, 1, 30)),
     curve(np.linspace(0, 1.03, 31))),
    ("wiggly, independent noise", noisy_curve(30, 1), noisy_curve(25, 2)),
]


@pytest.mark.parametrize(
    "a,b", [pytest.param(a, b, id=i) for i, a, b, _ in EQUAL_COUNT_CASES]
)
def test_open_duplicate_detected(a, b):
    """Each construction is a duplicate at a 95% threshold."""
    A, B = mk(a), mk(b)
    ratio = A.getOverlapRatio(B, MAG)
    assert ratio > THRESHOLD, f"ratio {ratio:.4f} does not clear {THRESHOLD}"
    assert A.overlaps(B, THRESHOLD, MAG) is True
    ## symmetric: which trace the scan happens to ask from must not matter
    assert B.overlaps(A, THRESHOLD, MAG) is True


@pytest.mark.parametrize(
    "a,b", [pytest.param(a, b, id=i) for i, a, b in UNEQUAL_COUNT_CASES]
)
def test_open_duplicate_detected_unequal_point_counts(a, b):
    """The same five with point counts that differ, so pointsMatch cannot mask it.

    This is the set that fails on the area metric end to end. With equal counts
    the 1e-2 absolute pointsMatch tolerance is 4% of a 0.25 um trace and answers
    True on its own for several of these; with unequal counts pointsMatch is
    False by construction and the ratio is the only thing deciding.
    """
    A, B = mk(a), mk(b)
    if len(a) != len(b):
        assert A.pointsMatch(B) is False, "premise: pointsMatch cannot settle this"
    assert A.overlaps(B, THRESHOLD, MAG) is True
    assert B.overlaps(A, THRESHOLD, MAG) is True


def test_area_metric_measured_these_below_threshold():
    """Premise, pinned: the area comparison is what failed on these pairs.

    Rasterizes each pair the way getOverlapRatio used to, so the numbers the
    module docstring quotes cannot drift out of the code silently. If this
    starts failing, the constructions changed and the ratios above are stale.
    """
    from skimage.draw import polygon

    def area_ratio(pts1, pts2):
        a = np.asarray(pts1, dtype=float)
        b = np.asarray(pts2, dtype=float)
        xmin = min(a[:, 0].min(), b[:, 0].min())
        xmax = max(a[:, 0].max(), b[:, 0].max())
        ymin = min(a[:, 1].min(), b[:, 1].min())
        ymax = max(a[:, 1].max(), b[:, 1].max())
        scale = (1e4 / ((xmax - xmin) * (ymax - ymin))) ** 0.5
        a = np.round(a * scale).astype(int)
        b = np.round(b * scale).astype(int)
        x0, x1 = round(xmin * scale), round(xmax * scale)
        y0, y1 = round(ymin * scale), round(ymax * scale)
        shape = (y1 - y0 + 1, x1 - x0 + 1)
        m1 = np.zeros(shape, dtype=bool)
        m2 = np.zeros(shape, dtype=bool)
        r1, c1 = polygon(a[:, 1] - y0, a[:, 0] - x0)
        r2, c2 = polygon(b[:, 1] - y0, b[:, 0] - x0)
        m1[r1, c1] = True
        m2[r2, c2] = True
        return np.sum(m1 & m2) / np.sum(m1 | m2)

    for name, a, b, expected in EQUAL_COUNT_CASES:
        measured = area_ratio(a, b)
        assert measured == pytest.approx(expected, abs=5e-4), (
            f"{name}: area metric now measures {measured:.4f}, not {expected}"
        )

    ## and four of the five fell below the threshold, which is the bug
    below = [n for n, a, b, r in EQUAL_COUNT_CASES if r <= THRESHOLD]
    assert len(below) == 4, below


# ---------------------------------------------------------------------------
# Negative cases. Without these, a metric that returned 1.0 unconditionally
# would satisfy everything above.
# ---------------------------------------------------------------------------

def test_genuinely_different_open_traces_not_flagged():
    """Two different open traces near each other are not duplicates."""
    t = np.linspace(0, 1, 26)
    other = list(zip(
        (SCALE * t).tolist(),
        (0.05 + 0.02 * np.cos(5 * t)).tolist(),
    ))
    A, B = mk(curve(np.linspace(0, 1, 30))), mk(other)
    assert A.getOverlapRatio(B, MAG) < THRESHOLD
    assert A.overlaps(B, THRESHOLD, MAG) is False
    assert B.overlaps(A, THRESHOLD, MAG) is False


def test_partial_overlap_is_not_a_duplicate():
    """A trace running along half of another is not a duplicate of it.

    The hardest negative, because every point of the short trace *is* on the
    long one. Taking the min of the two directions is what answers it: the long
    trace has only half its length near the short one.
    """
    A = mk(curve(np.linspace(0, 1, 30)))
    B = mk(curve(np.linspace(0, 0.5, 15)))
    ratio = A.getOverlapRatio(B, MAG)
    assert 0.4 < ratio < 0.6, f"expected about the length ratio, got {ratio:.4f}"
    assert A.overlaps(B, THRESHOLD, MAG) is False


def test_crossing_open_traces_not_flagged():
    """Two traces that merely cross are not duplicates."""
    t = np.linspace(-0.1, 0.1, 20)
    crossing = list(zip([SCALE / 2] * 20, t.tolist()))
    A, B = mk(curve(np.linspace(0, 1, 30))), mk(crossing)
    assert A.getOverlapRatio(B, MAG) < 0.2
    assert A.overlaps(B, THRESHOLD, MAG) is False


def test_open_traces_far_apart_score_zero():
    """No shared geometry at all."""
    A = mk(curve(np.linspace(0, 1, 30)))
    B = mk([(x + 100, y + 100) for x, y in curve(np.linspace(0, 1, 30))])
    assert A.getOverlapRatio(B, MAG) == 0
    assert A.overlaps(B, THRESHOLD, MAG) is False


# ---------------------------------------------------------------------------
# Properties of the metric
# ---------------------------------------------------------------------------

def test_reversed_open_trace_is_a_duplicate():
    """A trace redrawn end-to-start is the same curve.

    Falls out of comparing point sets rather than paired-up points. Worth
    pinning because a point-wise metric would answer 0 here.
    """
    A = mk(curve(np.linspace(0, 1, 30)))
    B = mk(curve(np.linspace(1, 0, 25)))
    assert A.getOverlapRatio(B, MAG) == pytest.approx(1.0)
    assert A.overlaps(B, THRESHOLD, MAG) is True


def test_ratio_stays_in_unit_interval_and_keeps_threshold_semantics():
    """The open ratio is a 0-to-1 overlap ratio, so the user threshold is unchanged.

    ratioIsOverlap is shared with the closed path and must need no special case:
    a plain bool out, and a threshold of exactly 1 demanding a ratio of exactly 1.
    """
    A = mk(curve(np.linspace(0, 1, 30)))
    identical = mk(curve(np.linspace(0, 1, 30)))
    different = mk(list(zip(
        (SCALE * np.linspace(0, 1, 26)).tolist(),
        (0.05 + 0.02 * np.cos(5 * np.linspace(0, 1, 26))).tolist(),
    )))

    for other in (identical, different):
        r = A.getOverlapRatio(other, MAG)
        assert 0 <= r <= 1
        assert Trace.ratioIsOverlap(r, 0.5) is (r > 0.5)

    assert Trace.ratioIsOverlap(A.getOverlapRatio(identical, MAG), 1) is True
    assert Trace.ratioIsOverlap(A.getOverlapRatio(different, MAG), 1) is False


def test_scale_invariance():
    """The same shapes at 100x the size, on a series whose pixels are 100x bigger.

    What has to be scale-free is the *physical* judgment: the same structures,
    traced on the same images, must get the same verdict whatever units the series
    records them in -- and a series in units 100x larger has a mag 100x larger
    too, which is exactly the pair of quantities Trace.magScale converts between.
    Both parts of the tolerance are then scaled: the fraction of arc length by the
    geometry, the pixel bounds by the mag.

    Not tested here, because it is deliberately false: scaling the coordinates
    while holding the mag fixed. That is a different physical claim -- structures
    100x larger on the same images -- and the bounds are there precisely so that
    the tolerance does not grow with it without limit. test_tolerance_is_bounded
    _above_at_five_pixels covers that direction.
    """
    a = noisy_curve(30, 1)
    b = noisy_curve(25, 2)
    small = mk(a).getOverlapRatio(mk(b), MAG)
    big = mk([(x * 100, y * 100) for x, y in a]).getOverlapRatio(
        mk([(x * 100, y * 100) for x, y in b]), MAG * 100
    )
    assert small == pytest.approx(big)


def test_point_density_does_not_change_the_answer():
    """Resampling one trace more finely along the same path changes nothing.

    Distances are measured to the other trace's segments, not to its points, so
    how densely it was clicked must not matter.
    """
    A = mk(curve(np.linspace(0, 1, 30)))
    coarse = mk(noisy_curve(12, 5))
    fine_pts = noisy_curve(12, 5)
    ## same path, extra points interpolated onto the existing segments
    dense = []
    for (x1, y1), (x2, y2) in zip(fine_pts, fine_pts[1:]):
        dense.append((x1, y1))
        dense.append(((x1 + x2) / 2, (y1 + y2) / 2))
    dense.append(fine_pts[-1])
    assert arc_length(dense) == pytest.approx(arc_length(fine_pts))
    assert A.getOverlapRatio(dense_trace := mk(dense), MAG) == pytest.approx(
        A.getOverlapRatio(coarse, MAG), abs=0.02
    )
    assert dense_trace.closed is False


# ---------------------------------------------------------------------------
# The tolerance, and its two bounds.
#
# d = clamp(OPEN_TRACE_MATCH_FRACTION * min(arc length),
#           OPEN_TRACE_MATCH_MIN_PIXELS * mag,
#           OPEN_TRACE_MATCH_MAX_PIXELS * mag)
#
# The two cases below are the two real traces from her series that the fraction
# alone gets wrong, one at each end. Both are quoted in image pixels at her own
# magnification, which is the only unit in which they mean anything.
# ---------------------------------------------------------------------------

LK_MAG = 0.00204508     # um/px, the reporting user's series


def line_px(length_px, y_px, n, mag=LK_MAG):
    """A straight open trace `length_px` long at height `y_px`, in series units."""
    return [(i * length_px * mag / (n - 1), y_px * mag) for i in range(n)]


def test_tolerance_is_the_fraction_between_the_two_bounds():
    """Where the fraction lies inside the bounds, nothing has changed.

    A 123 px trace is the median open trace in her series: 2% of it is 2.5 px,
    comfortably between 1 and 5, so the clamp is inert and the fraction decides.
    """
    d = Trace.openCurveTolerance(LK_MAG, 123 * LK_MAG, 130 * LK_MAG)
    assert d / LK_MAG == pytest.approx(2.46, abs=0.01)
    assert Trace.OPEN_TRACE_MATCH_MIN_PIXELS < d / LK_MAG < Trace.OPEN_TRACE_MATCH_MAX_PIXELS


def test_tolerance_is_bounded_below_at_one_pixel():
    """Her shortest genuine duplicate pair, which the fraction alone missed.

    ``s195 d000cfa052axi011`` traces #0 and #1: a 29 px arc traced twice, the two
    tracings 0.72 px apart at worst. 2% of 29 px is 0.58 px, so an unbounded
    fraction scored the pair 0 and the duplicate scan did not report it. One image
    pixel is the floor, and it is what catches this.
    """
    A, B = mk(line_px(29, 0.0, 3)), mk(line_px(29, 0.6, 4))
    assert A.pointsMatch(B) is False, "premise: unequal point counts"

    d = Trace.openCurveTolerance(LK_MAG, arc_length(A.points), arc_length(B.points))
    assert d / LK_MAG == pytest.approx(1.0, abs=0.01), "the floor is binding here"
    assert 0.02 * 29 == pytest.approx(0.58, abs=0.01), "what the fraction alone gives"

    assert A.getOverlapRatio(B, LK_MAG) == pytest.approx(1.0)
    assert A.overlaps(B, THRESHOLD, LK_MAG) is True


def test_the_floor_is_load_bearing_for_that_pair(monkeypatch):
    """Premise, pinned: without the floor the same pair scores 0."""
    monkeypatch.setattr(Trace, "OPEN_TRACE_MATCH_MIN_PIXELS", 0.0)
    A, B = mk(line_px(29, 0.0, 3)), mk(line_px(29, 0.6, 4))
    assert A.getOverlapRatio(B, LK_MAG) == 0
    assert A.overlaps(B, THRESHOLD, LK_MAG) is False


def test_tolerance_is_bounded_above_at_five_pixels():
    """Two DIFFERENT structures 10 px apart along a 6,846 px trace.

    6,846 px is the 95th percentile open trace in her series, so 2% of it is
    137 px: at an unbounded fraction two unrelated profiles running 10 px apart
    lie within tolerance of each other everywhere, and the ratio is exactly 1.0.
    The ceiling of 5 px is what refuses them.
    """
    A, B = mk(line_px(6846, 0.0, 3)), mk(line_px(6846, 10.0, 4))

    d = Trace.openCurveTolerance(LK_MAG, arc_length(A.points), arc_length(B.points))
    assert d / LK_MAG == pytest.approx(5.0, abs=0.01), "the ceiling is binding here"
    assert 0.02 * 6846 == pytest.approx(136.92, abs=0.01), "what the fraction gives"

    assert A.getOverlapRatio(B, LK_MAG) == 0
    for threshold in (0.9, 0.92, THRESHOLD, 0.99, 0.999, 1.0):
        assert A.overlaps(B, threshold, LK_MAG) is False, threshold


def test_the_ceiling_is_load_bearing_for_that_pair(monkeypatch):
    """Premise, pinned: without the ceiling the pair saturates at exactly 1.0.

    Exactly 1.0 matters, and not merely "above 0.95": ratioIsOverlap reads a
    threshold of 1 as "demand an exact match", so a saturated ratio is collapsed
    at every setting the import dialog can produce, the strictest one included.
    """
    monkeypatch.setattr(Trace, "OPEN_TRACE_MATCH_MAX_PIXELS", 1e9)
    A, B = mk(line_px(6846, 0.0, 3)), mk(line_px(6846, 10.0, 4))
    assert A.getOverlapRatio(B, LK_MAG) == 1.0
    assert A.overlaps(B, 1.0, LK_MAG) is True


def test_open_ratio_refuses_to_guess_a_magnification():
    """A caller that omits mag is refused rather than quietly given a tolerance.

    The alternative -- falling back to the unbounded fraction -- is the behavior
    the two tests above show to be wrong, and a call site that forgot would get it
    silently. Loud instead. Closed pairs never need it.
    """
    A, B = mk(line_px(6846, 0.0, 3)), mk(line_px(6846, 10.0, 4))
    with pytest.raises(ValueError, match="mag"):
        A.getOverlapRatio(B)
    with pytest.raises(ValueError, match="mag"):
        A.overlaps(B, THRESHOLD)

    closed_a, closed_b = mk(line_px(6846, 0.0, 3), closed=True), mk(
        line_px(6846, 10.0, 4), closed=True)
    assert 0 <= closed_a.getOverlapRatio(closed_b) <= 1, "no mag needed when closed"


# ---------------------------------------------------------------------------
# Degenerate traces: the zero-area guard's open-trace counterpart (fork PR #167
# fixed a crash here and it must not come back).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("points", [
    pytest.param([], id="no points"),
    pytest.param([(1.0, 1.0)], id="one point"),
    pytest.param([(1.0, 1.0), (1.0, 1.0)], id="two identical points"),
    pytest.param([(1.0, 1.0)] * 5, id="five identical points"),
])
def test_degenerate_open_traces_do_not_crash(points):
    """Zero length means no tolerance to measure against; answer 0, never raise."""
    A = mk(points)
    B = mk(curve(np.linspace(0, 1, 30)))
    assert A.getOverlapRatio(B, MAG) == 0
    assert B.getOverlapRatio(A, MAG) == 0
    assert A.getOverlapRatio(mk(list(points)), MAG) == 0


def test_identical_degenerate_open_traces_still_match_on_points():
    """A zero-length trace is still a duplicate of an identical copy.

    The ratio cannot say so, and does not have to: overlaps() settles identical
    point sequences before it ever asks for one. Same reasoning as the zero-area
    case for closed traces.
    """
    A = mk([(1.0, 1.0), (1.0, 1.0)])
    B = mk([(1.0, 1.0), (1.0, 1.0)])
    assert A.getOverlapRatio(B, MAG) == 0
    assert A.pointsMatch(B) is True
    assert A.overlaps(B, THRESHOLD, MAG) is True


def test_collinear_open_traces_do_not_crash():
    """A straight line has no area at all, which is what broke before PR #167."""
    A = mk([(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)])
    B = mk([(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (0.0, 3.0)])
    ratio = A.getOverlapRatio(B, MAG)
    assert 0 <= ratio <= 1
    ## A is two thirds of B and lies exactly on it, so the min direction caps it
    assert ratio < THRESHOLD


@pytest.mark.parametrize("label,a_pts,b_pts", [
    ("overlapping halves", [(0, 0), (1, 0)], [(0.5, 0), (1.5, 0)]),
    ("one inside the other", [(0, 0), (2, 0)], [(0.5, 0), (1.5, 0)]),
    ("vertical, offset along the line", [(0, 0), (0, 1)], [(0, 0.2), (0, 1.2)]),
])
def test_degenerate_open_pairs_are_compared_not_exempted(label, a_pts, b_pts):
    """The decision on pixel dust, pinned deliberately in both directions.

    Fork PR #167 gave a pair of traces with no area between them a ratio of 0 at
    every threshold, because the area comparison could not say anything else about
    them. That guarantee does NOT carry over to open pairs, and it is not restored
    here. Two reasons:

      * A two-point open trace is not pixel dust in this data. 695 of the 3,974
        open traces in the reporting user's series have exactly two points --
        short straight profiles -- and Section.__init__ forces every two-point
        trace open. Refusing to compare them would re-break the case reported.
      * "No enclosed area" is a fact about the area metric, not about the curves.
        Two collinear segments lying on top of each other are the same annotation
        by any reading; scoring them 0 was the area metric's limitation showing.

    So a degenerate open pair is measured like any other, and what the bounds buy
    is that the number means something: the tolerance is a few image pixels rather
    than a few percent of an arbitrary length. A partial overlap still scores about
    the shared fraction, which is below anything the import dialog can ask for; it
    is above zero, so a caller passing threshold=0 reads it as an overlap. Both
    halves of that are asserted, because both are consequences worth noticing if
    they change.
    """
    A, B = mk(a_pts), mk(b_pts)
    ratio = A.getOverlapRatio(B, MAG)
    assert 0 < ratio < THRESHOLD, f"{label}: measured, and not a duplicate"
    assert A.overlaps(B, THRESHOLD, MAG) is False, f"{label}: not at the import range"
    assert A.overlaps(B, 0.9, MAG) is False, f"{label}: nor at the lowest setting"
    assert A.overlaps(B, 0, MAG) is True, (
        f"{label}: but threshold=0 asks only whether they meet at all, and they do"
    )


# ---------------------------------------------------------------------------
# Closed traces are untouched
# ---------------------------------------------------------------------------

def test_closed_traces_still_use_the_area_metric():
    """The same constructions, closed, keep the ratios the area metric gives.

    The area comparison is correct for closed traces and this change must not
    reach it.
    """
    for name, a, b, expected in EQUAL_COUNT_CASES:
        A, B = mk(a, closed=True), mk(b, closed=True)
        measured = A.getOverlapRatio(B, MAG)
        assert measured == pytest.approx(expected, abs=5e-4), (
            f"{name}: closed ratio changed to {measured:.4f}, expected {expected}"
        )


def test_mixed_open_and_closed_never_overlap():
    """overlaps() refuses a mixed pair before any ratio is measured."""
    A = mk(curve(np.linspace(0, 1, 30)), closed=False)
    B = mk(curve(np.linspace(0, 1, 30)), closed=True)
    assert A.overlaps(B, THRESHOLD, MAG) is False
    assert B.overlaps(A, THRESHOLD, MAG) is False


# ---------------------------------------------------------------------------
# End to end, through the two scans a user actually runs.
#
# The ratio fix alone is not enough for the cross-name scan: it prefilters pairs
# with a ceiling derived from enclosed area, and for an open pair that area is
# the meaningless sliver. The near-straight pair ceilings at 0.63 and never
# reaches any ratio, so these tests are the ones that pin the second half of the
# fix.
# ---------------------------------------------------------------------------

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    series.setProgressReporter(NullProgressReporter)
    return series


def _template_trace(section):
    for cname in section.contours:
        for trace in section.contours[cname]:
            if len(trace.points) >= 3:
                return trace
    pytest.skip("no usable trace in fixture section")


def _first_snum(series):
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        if any(section.contours[c] for c in section.contours):
            return snum
    pytest.skip("no traces anywhere in fixture")


def _make(section, name, points, closed=False):
    t = _template_trace(section).copy()
    t.name = name
    t.points = list(points)
    t.closed = closed
    section.addTrace(t, log_event=False)
    return t


def _pairs(records):
    return {frozenset((r["name"], r["other_name"])) for r in records}


def test_cross_name_scan_finds_open_duplicate(tmp_path):
    """Her case, end to end: a near-straight open pair under two names."""
    series = _load_series(tmp_path)
    snum = _first_snum(series)
    section = series.loadSection(snum)
    a, b = STRAIGHT_UNEQUAL
    _make(section, "CFA_A", a)
    _make(section, "CFA_B", b)
    section.save()

    records = series.findDifferentlyNamedDuplicates(THRESHOLD)
    assert frozenset(("CFA_A", "CFA_B")) in _pairs(records)


def test_cross_name_scan_still_ignores_different_open_traces(tmp_path):
    """The negative, end to end: two different open traces are not reported."""
    series = _load_series(tmp_path)
    snum = _first_snum(series)
    section = series.loadSection(snum)
    t = np.linspace(0, 1, 26)
    _make(section, "CFA_A", curve(np.linspace(0, 1, 30)))
    _make(section, "CFA_B", list(zip(
        (SCALE * t).tolist(), (0.05 + 0.02 * np.cos(5 * t)).tolist(),
    )))
    section.save()

    records = series.findDifferentlyNamedDuplicates(THRESHOLD)
    assert frozenset(("CFA_A", "CFA_B")) not in _pairs(records)


def test_delete_duplicates_removes_open_duplicate(tmp_path):
    """Same-name open duplicates are deleted, where before they were kept."""
    series = _load_series(tmp_path)
    snum = _first_snum(series)
    section = series.loadSection(snum)
    a, b = STRAIGHT_UNEQUAL
    _make(section, "CFA_DUP", a)
    _make(section, "CFA_DUP", b)
    section.save()
    assert len(series.loadSection(snum).contours["CFA_DUP"]) == 2

    series.deleteDuplicateTraces(THRESHOLD, log_event=False)
    assert len(series.loadSection(snum).contours["CFA_DUP"]) == 1


def test_delete_duplicates_keeps_different_open_traces(tmp_path):
    """Two genuinely different open traces under one name both survive."""
    series = _load_series(tmp_path)
    snum = _first_snum(series)
    section = series.loadSection(snum)
    t = np.linspace(0, 1, 26)
    _make(section, "CFA_KEEP", curve(np.linspace(0, 1, 30)))
    _make(section, "CFA_KEEP", list(zip(
        (SCALE * t).tolist(), (0.05 + 0.02 * np.cos(5 * t)).tolist(),
    )))
    section.save()

    series.deleteDuplicateTraces(THRESHOLD, log_event=False)
    assert len(series.loadSection(snum).contours["CFA_KEEP"]) == 2


def test_area_ceiling_would_have_dropped_the_open_pair():
    """Premise for the ceiling exemption, pinned.

    Reproduces the ceiling _duplicatePairs computes for the reported pair and
    shows it falls below the floor, so the pair was skipped before any ratio was
    measured. If this stops holding, the exemption in _duplicatePairs is no
    longer load-bearing and the reason for it has changed.
    """
    from PyReconstruct.modules.calc import traceGeometry
    from PyReconstruct.modules.datatypes.series import Series

    a, b = STRAIGHT_UNEQUAL
    A, B = mk(a), mk(b)
    assert A.pointsMatch(B) is False, "premise: pointsMatch cannot settle it"

    axmin, aymin, axmax, aymax = A.getBounds()
    bxmin, bymin, bxmax, bymax = B.getBounds()
    _, aarea, _, _ = traceGeometry(a, True)
    _, barea, _, _ = traceGeometry(b, True)
    aarea, barea = abs(aarea), abs(barea)
    box = (
        max(0.0, min(axmax, bxmax) - max(axmin, bxmin))
        * max(0.0, min(aymax, bymax) - max(aymin, bymin))
    )
    ceiling = min(box, aarea, barea) / max(aarea, barea)
    floor = THRESHOLD - Series._OVERLAP_CEILING_MARGIN
    assert ceiling <= floor, (
        f"ceiling {ceiling:.4f} no longer falls below the floor {floor:.4f}"
    )


def test_overlap_ceiling_margin_is_pinned():
    """The margin is a measured quantity, not a free parameter.

    0.05 exists because the rasterized ratio can read slightly higher than the
    ceiling bounds the true geometry at, and it was sized at six times the
    largest excess measured on real data. Pinned because nothing else pins it,
    and because the exemption added for open traces sits right beside it: a
    change to either should be a deliberate edit to this line.
    """
    from PyReconstruct.modules.datatypes.series import Series

    assert Series._OVERLAP_CEILING_MARGIN == 0.05


def test_open_trace_tolerance_constants_are_pinned():
    """The three numbers that decide how far apart two curves may be.

    Pinned for the same reason as the margin above: each was measured, none is a
    free parameter, and none should drift without a deliberate edit here. The two
    pixel bounds are load-bearing in both directions and each has its own
    revert-and-fail test above.
    """
    assert Trace.OPEN_TRACE_MATCH_FRACTION == 0.02
    assert Trace.OPEN_TRACE_MATCH_MIN_PIXELS == 1.0
    assert Trace.OPEN_TRACE_MATCH_MAX_PIXELS == 5.0
