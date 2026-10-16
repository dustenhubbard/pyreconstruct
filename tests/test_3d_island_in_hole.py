"""The 3D surface keeps an island that sits inside one of the object's own holes.

``Surface.generateVolume`` filled every positive trace of a section and then
cleared every negative trace, so a positive trace drawn inside a negative one
(an island in a hole) was cleared along with the hole. The mesh, and the volume
``3D ▸ Export quantitative data`` measures from it, lost the island.

The fill now draws the same way and then fills each island back in, less the
voxels of the negatives ``islandCuts`` lists for it. A section with no island
draws exactly as the two passes do, which the reference loop below (every
positive, then every negative, each through ``traceVoxels``) pins voxel for
voxel.
"""
import math
import os
import shutil

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.backend.volume.objects_3D import (  # noqa: E402
    Surface,
    _covers,
    _traceLine,
    _tracePolygon,
    islandCuts,
    traceVoxels,
)

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)


class _StubSeries:
    """The only series attributes the surface path reads."""

    avg_mag = 0.01
    avg_thickness = 0.05

    def getOption(self, name):
        return {"3D_xy_res": 50, "3D_smoothing": "none",
                "smoothing_iterations": 0}[name]

    def getAttr(self, name, attr):
        return 1.0


class _StubTrace:
    def __init__(self, points, negative=False, color=(255, 0, 0)):
        self.points = points
        self.negative = negative
        self.color = color


def _square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


OUTER = _square(0, 0, 3, 3)
HOLE = _square(1, 1, 2, 2)
ISLAND = _square(1.3, 1.3, 1.7, 1.7)
INNER_HOLE = _square(1.4, 1.4, 1.6, 1.6)
INNER_ISLAND = _square(1.47, 1.47, 1.53, 1.53)
# positives with no area, drawn inside the hole
COLLINEAR = [(1.2, 1.2), (1.5, 1.5), (1.8, 1.8)]
ONE_POINT = [(1.5, 1.5), (1.5, 1.5), (1.5, 1.5)]
# a negative that cuts across the island's edge, and one with no area that
# runs over the island
CROSS = _square(1.5, 1.5, 1.9, 1.9)
LINE = [(1.5, 1.35), (1.5, 1.65)]
# negatives beside the island: one sharing part of its right edge, one
# touching its corner, and two that miss it by a fraction of a voxel (the
# voxels here are 0.03 wide), so both reach into its edge voxels
TOUCH = _square(1.7, 1.4, 1.9, 1.6)
CORNER = _square(1.7, 1.7, 1.9, 1.9)
NEAR = _square(1.705, 1.4, 1.9, 1.6)
NEAR_CORNER = _square(1.705, 1.705, 1.9, 1.9)
# one too far to reach a voxel of the island at all
FAR = _square(1.76, 1.4, 1.9, 1.6)
VOXEL = 0.03
REACH = math.hypot(VOXEL, VOXEL)


def _surface(sections, nsec=3):
    """A Surface with the same traces on ``nsec`` sections."""
    surf = Surface("obj", _StubSeries(), None, None, None)
    for snum in range(nsec):
        for points, negative in sections:
            surf.addTrace(_StubTrace(points, negative=negative), snum)
    return surf


def _vres(surf):
    series = surf.series
    vres_min = min(series.avg_mag, series.avg_thickness)
    vres_max = max(series.avg_mag, series.avg_thickness)
    return vres_min + (1 - series.getOption("3D_xy_res") / 100) * (vres_max - vres_min)


def _shape(surf):
    """The volume's shape in x, y and sections."""
    vres = _vres(surf)
    xmin, xmax, ymin, ymax, smin, smax = tuple(surf.extremes)
    return (round((xmax - xmin) / vres) + 1, round((ymax - ymin) / vres) + 1, smax - smin + 1)


def _voxels(points, surf):
    """The voxels a trace covers on the volume's grid, as x and y arrays."""
    xmin, _, ymin, _, _, _ = tuple(surf.extremes)
    return traceVoxels(points, xmin, ymin, _vres(surf), _shape(surf)[:2])


def _order_volume(surf, order):
    """The volume drawn in the order ``order(pos, neg)`` gives."""
    smin = surf.extremes[4]
    volume = np.zeros(_shape(surf), dtype=bool)
    for snum, trace_lists in surf.traces.items():
        for trace, fill in order(trace_lists["pos"], trace_lists["neg"]):
            xx, yy = _voxels(trace, surf)
            volume[xx, yy, snum - smin] = fill
    return volume


def _two_pass_order(pos, neg):
    return [(p, True) for p in pos] + [(n, False) for n in neg]


def _reference_volume(surf):
    """The fill as it shipped: every positive, then every negative."""
    return _order_volume(surf, _two_pass_order)


def _count(volume, points, surf):
    """Voxels of ``volume`` the trace ``points`` covers, on every section."""
    xx, yy = _voxels(points, surf)
    return int(volume[xx, yy, :].sum())


# ------------------------------------------------------------------ islands
def test_island_in_hole_fills():
    surf = _surface([(OUTER, False), (HOLE, True), (ISLAND, False)])
    volume, _ = surf.generateVolume()
    island_voxels = _count(volume, ISLAND, surf)
    assert island_voxels > 0
    # the island fills completely, and the hole around it stays clear
    assert island_voxels == _count(np.ones_like(volume), ISLAND, surf)
    assert _count(volume, HOLE, surf) == island_voxels


def test_island_adds_to_the_mesh_and_its_volume():
    ring = _surface([(OUTER, False), (HOLE, True)]).generateTrimesh()
    with_island = _surface(
        [(OUTER, False), (HOLE, True), (ISLAND, False)]
    ).generateTrimesh()
    assert with_island.body_count == ring.body_count + 1
    assert with_island.volume > ring.volume
    # the mesh gains about the island's own volume (0.4 x 0.4 x 3 sections)
    gained = with_island.volume - ring.volume
    assert 0.4 * 0.4 * 3 * 0.05 * 0.5 < gained < 0.4 * 0.4 * 3 * 0.05 * 1.5


def test_hole_inside_an_island_clears():
    surf = _surface([
        (OUTER, False), (HOLE, True), (ISLAND, False), (INNER_HOLE, True),
    ])
    volume, _ = surf.generateVolume()
    assert _count(volume, INNER_HOLE, surf) == 0
    assert _count(volume, ISLAND, surf) == (
        _count(np.ones_like(volume), ISLAND, surf)
        - _count(np.ones_like(volume), INNER_HOLE, surf)
    )


def test_island_three_levels_deep_fills():
    """An island inside a hole inside an island: the inner hole clears the
    inner island after the first refill, so a later level must fill it again."""
    surf = _surface([
        (OUTER, False), (HOLE, True), (ISLAND, False),
        (INNER_HOLE, True), (INNER_ISLAND, False),
    ])
    volume, _ = surf.generateVolume()
    full = np.ones_like(volume)
    inner_island = _count(full, INNER_ISLAND, surf)
    assert inner_island > 0
    assert _count(volume, INNER_ISLAND, surf) == inner_island
    assert _count(volume, INNER_HOLE, surf) == inner_island
    assert _count(volume, ISLAND, surf) == (
        _count(full, ISLAND, surf) - _count(full, INNER_HOLE, surf) + inner_island
    )


def test_island_cuts_three_levels():
    # the inner island is in the outer hole and in the inner hole, so both
    # are around it and neither cuts it; the inner hole cuts the island
    assert islandCuts([OUTER, ISLAND, INNER_ISLAND], [HOLE, INNER_HOLE]) == [
        (ISLAND, [INNER_HOLE]), (INNER_ISLAND, []),
    ]


def test_island_only_on_some_sections():
    """The islands are found per section, so an island on one section does
    not change the sections without one."""
    surf = Surface("obj", _StubSeries(), None, None, None)
    for snum in range(3):
        surf.addTrace(_StubTrace(OUTER), snum)
        surf.addTrace(_StubTrace(HOLE, negative=True), snum)
    surf.addTrace(_StubTrace(ISLAND), 1)
    volume, _ = surf.generateVolume()
    reference = _reference_volume(surf)
    assert (volume[:, :, 0] == reference[:, :, 0]).all()
    assert (volume[:, :, 2] == reference[:, :, 2]).all()
    assert volume[:, :, 1].sum() > reference[:, :, 1].sum()


def test_island_cuts_hole_inside_the_island():
    assert islandCuts([OUTER, ISLAND], [HOLE, INNER_HOLE]) == [
        (ISLAND, [INNER_HOLE]),
    ]


def test_identical_outlines_are_not_an_island():
    assert islandCuts([HOLE], [HOLE]) == []


def test_coincident_negative_cancels_the_island():
    """A negative with the island's own outline cuts all of it, so the pair
    cancels as it did in the old fill."""
    traces = [(OUTER, False), (HOLE, True), (ISLAND, False), (ISLAND, True)]
    surf = _surface(traces)
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all()
    assert islandCuts([OUTER, ISLAND], [HOLE, ISLAND]) == [(ISLAND, [ISLAND])]


@pytest.mark.parametrize("hole", [True, False])
def test_negative_across_the_island_edge_still_cuts_it(hole):
    """A negative that crosses the island's edge cuts it. With no hole around
    the island the old fill already cut it, and the island inside a hole
    must end up cut the same way."""
    cut = _surface([(OUTER, False), (ISLAND, False), (CROSS, True)])
    cut_ref = _reference_volume(cut)
    full = np.ones_like(cut_ref)
    assert 0 < _count(cut_ref, ISLAND, cut) < _count(full, ISLAND, cut)

    traces = [(OUTER, False), (ISLAND, False), (CROSS, True)]
    if hole:
        traces.insert(1, (HOLE, True))
    volume, _ = _surface(traces).generateVolume()
    assert _count(volume, ISLAND, cut) == _count(cut_ref, ISLAND, cut)
    assert _count(volume, CROSS, cut) == 0
    if not hole:
        assert (volume == cut_ref).all()


def test_zero_area_negative_over_the_island_still_cuts_it():
    cut = _surface([(OUTER, False), (ISLAND, False), (LINE, True)])
    cut_ref = _reference_volume(cut)
    full = np.ones_like(cut_ref)
    assert 0 < _count(cut_ref, ISLAND, cut) < _count(full, ISLAND, cut)

    volume, _ = _surface(
        [(OUTER, False), (HOLE, True), (ISLAND, False), (LINE, True)]
    ).generateVolume()
    assert _count(volume, ISLAND, cut) == _count(cut_ref, ISLAND, cut)


def test_island_cuts_lists_negatives_across_it():
    assert islandCuts([OUTER, ISLAND], [HOLE, CROSS, LINE]) == [
        (ISLAND, [CROSS, LINE]),
    ]


@pytest.mark.parametrize("name, near", [
    ("sharing an edge", TOUCH),
    ("touching a corner", CORNER),
    ("less than a voxel away", NEAR),
    ("less than a voxel's diagonal from a corner", NEAR_CORNER),
])
def test_negative_beside_the_island_still_cuts_it(name, near):
    """A negative that touches the island, or sits close enough that both
    reach into the same voxels, cuts it: the island ends up with the voxels
    it has with no hole around it, and the negative's own voxels stay clear
    as they did before."""
    cut = _surface([(OUTER, False), (ISLAND, False), (near, True)])
    cut_ref = _reference_volume(cut)
    full = np.ones_like(cut_ref)
    assert 0 < _count(cut_ref, ISLAND, cut) < _count(full, ISLAND, cut), name

    surf = _surface([(OUTER, False), (HOLE, True), (ISLAND, False), (near, True)])
    volume, vres = surf.generateVolume()
    assert vres == pytest.approx(VOXEL)
    assert _count(volume, ISLAND, cut) == _count(cut_ref, ISLAND, cut), name
    assert _count(volume, near, cut) == 0, name


def test_island_cuts_lists_negatives_beside_the_island():
    pos, neg = [OUTER, ISLAND], [HOLE, TOUCH, CORNER, NEAR, NEAR_CORNER, FAR]
    # touching counts with no reach; the ones a fraction of a voxel away need
    # it, and a negative too far to reach the island's voxels is left out
    assert islandCuts(pos, neg) == [(ISLAND, [TOUCH, CORNER])]
    assert islandCuts(pos, neg, REACH) == [
        (ISLAND, [TOUCH, CORNER, NEAR, NEAR_CORNER]),
    ]


def test_hole_the_island_touches_does_not_cut_it():
    """An island against the inside of its hole's edge touches the hole, but
    the hole is around it, so it does not cut the island."""
    against = _square(1, 1.3, 1.4, 1.7)
    assert islandCuts([OUTER, against], [HOLE], REACH) == [(against, [])]
    surf = _surface([(OUTER, False), (HOLE, True), (against, False)])
    volume, _ = surf.generateVolume()
    assert _count(volume, against, surf) == _count(np.ones_like(volume), against, surf)


def _outside(surf, island, negatives):
    """Voxels of ``island`` outside every one of ``negatives``, all sections."""
    full = np.ones_like(surf.generateVolume()[0])
    cleared = full.copy()
    for negative in negatives:
        xx, yy = _voxels(negative, surf)
        cleared[xx, yy, :] = False
    return _count(cleared, island, surf)


# two holes side by side with a thin wall between them, each with an island
# against that wall, closer to the other hole than a voxel
H_LEFT, H_RIGHT = _square(0.3, 0.3, 1.49, 2.7), _square(1.51, 0.3, 2.7, 2.7)
I_LEFT, I_RIGHT = _square(0.6, 0.9, 1.47, 2.1), _square(1.53, 0.9, 2.4, 2.1)


def test_islands_in_holes_side_by_side_both_fill():
    """Each hole comes within a voxel of the other hole's island, so it cuts
    that island's edge, but neither hole clears its own island."""
    surf = _surface([
        (OUTER, False), (H_LEFT, True), (H_RIGHT, True),
        (I_LEFT, False), (I_RIGHT, False),
    ])
    volume, _ = surf.generateVolume()
    for island, other in ((I_LEFT, H_RIGHT), (I_RIGHT, H_LEFT)):
        kept = _count(volume, island, surf)
        assert kept == _outside(surf, island, [other]) > 0
    assert islandCuts([OUTER, I_LEFT, I_RIGHT], [H_LEFT, H_RIGHT], REACH) == [
        (I_LEFT, [H_RIGHT]), (I_RIGHT, [H_LEFT]),
    ]


# island A in hole HA and island B in hole HB, where HA cuts into B and HB
# touches A, comes within a voxel of A, or cuts into A as well
A_NEAR = _square(1.4, 1.5, 1.776, 1.9)
A_TOUCH = _square(1.4, 1.5, 1.8, 1.9)
B = _square(2.3, 1.8, 2.6, 2.1)
HA = _square(1.3, 1.4, 2.4, 2.1)
HB_BESIDE = _square(1.8, 1.3, 3, 3)
HB_ACROSS = _square(1.7, 1.3, 3, 3)


@pytest.mark.parametrize("name, a, hb", [
    ("HB near A", A_NEAR, HB_BESIDE),
    ("HB touching A", A_TOUCH, HB_BESIDE),
    ("each hole cutting the other's island", A_TOUCH, HB_ACROSS),
])
def test_islands_whose_holes_cut_each_other_both_fill(name, a, hb):
    """Each island keeps every voxel outside the other island's hole."""
    traces = [(OUTER, False), (a, False), (B, False), (HA, True), (hb, True)]
    surf = _surface(traces, nsec=1)
    volume, _ = surf.generateVolume()
    assert _count(volume, a, surf) == _outside(surf, a, [hb]) > 0, name
    assert _count(volume, B, surf) == _outside(surf, B, [HA]) > 0, name
    main = _order_volume(surf, _main_order)
    assert _count(volume, B, surf) >= _count(main, B, surf), name


def _main_order(pos, neg):
    """The fill order as it shipped before islands were filled back in one
    by one: fill the islands again after the holes, clear again the
    negatives inside them, across their edge or with no area over them, and
    so on down, stopping when a set of islands comes back."""
    order = [(pts, True) for pts in pos] + [(pts, False) for pts in neg]
    if not pos or not neg:
        return order
    pos_polys = [_tracePolygon(pts) for pts in pos]
    neg_polys = [_tracePolygon(pts) for pts in neg]
    neg_lines = [None if poly is not None else _traceLine(pts)
                 for poly, pts in zip(neg_polys, neg)]

    def inside_or_across(island, n):
        if island is None or n is None:
            return False
        try:
            return island.covers(n) or island.overlaps(n)
        except Exception:
            return False

    def along(island, line):
        if island is None or line is None:
            return False
        try:
            return island.intersects(line)
        except Exception:
            return False

    holes = range(len(neg))
    seen = set()
    for _ in range(len(pos) + len(neg)):
        islands = [
            i for i, p in enumerate(pos_polys)
            if any(_covers(neg_polys[j], p) for j in holes)
        ]
        if not islands or tuple(islands) in seen:
            break
        seen.add(tuple(islands))
        order.extend((pos[i], True) for i in islands)
        holes = [
            j for j in range(len(neg))
            if any(inside_or_across(pos_polys[i], neg_polys[j])
                   or along(pos_polys[i], neg_lines[j]) for i in islands)
        ]
        if not holes:
            break
        order.extend((neg[j], False) for j in holes)
    return order


@pytest.mark.parametrize("seed", range(40))
def test_no_island_loses_more_than_its_cuts_against_the_old_order(seed):
    """Random holes, islands and negatives, snapped to a grid so traces
    touch and share edges. Against the order as it shipped before, an
    island may lose only voxels of the negatives that cut it, and it keeps
    every voxel outside them."""
    rng = np.random.default_rng(seed)

    def rect(lo, hi, size_lo, size_hi):
        x, y = rng.uniform(lo, hi, 2)
        w, h = rng.uniform(size_lo, size_hi, 2)
        return _square(*(round(v / 0.05) * 0.05 for v in (x, y, x + w, y + h)))

    holes = [rect(0.2, 2.0, 0.4, 1.0) for _ in range(rng.integers(2, 5))]
    islands = []
    for _ in range(rng.integers(2, 6)):
        x0, y0 = holes[rng.integers(len(holes))][0]
        x, y = x0 + rng.uniform(0, 0.4), y0 + rng.uniform(0, 0.4)
        side = rng.uniform(0.1, 0.4)
        islands.append(_square(*(round(v / 0.05) * 0.05 for v in (x, y, x + side, y + side))))
    extra = [rect(0.2, 2.6, 0.05, 0.4) for _ in range(rng.integers(0, 4))]
    pos, neg = [OUTER] + islands, holes + extra

    surf = _surface([(p, False) for p in pos] + [(n, True) for n in neg], nsec=1)
    volume, _ = surf.generateVolume()
    main = _order_volume(surf, _main_order)
    shape = volume.shape[:2]

    for island, cuts in islandCuts(pos, neg, REACH):
        xx, yy = _voxels(island, surf)
        cut = np.zeros(shape, dtype=bool)
        for n in cuts:
            cut[_voxels(n, surf)] = True
        here, before = volume[xx, yy, 0], main[xx, yy, 0]
        lost = before & ~here
        assert not (lost & ~cut[xx, yy]).any(), seed
        assert here[~cut[xx, yy]].all(), seed


def _pairwise_cuts(pos, neg, reach=0.0):
    """The islands and their cuts with every negative looked at for every
    positive, no index; the shipped search must give the same answer."""
    from PyReconstruct.modules.calc.nesting import _holeAround, _reaches

    pos_polys = [_tracePolygon(pts) for pts in pos]
    neg_polys = [_tracePolygon(pts) for pts in neg]
    neg_shapes = [poly if poly is not None else _traceLine(pts)
                  for poly, pts in zip(neg_polys, neg)]
    if not pos or not neg:
        return []
    found = []
    for i, island in enumerate(pos_polys):
        hole = set(_holeAround(island, neg_polys, reach))
        if not hole:
            continue
        found.append((pos[i], [
            neg[j] for j in range(len(neg))
            if j not in hole and _reaches(island, neg_shapes[j], reach)
        ]))
    return found


@pytest.mark.parametrize("reach", [0.0, 0.05])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_indexed_search_matches_the_pairwise_search(seed, reach):
    """Random squares, many of them nested, a few duplicated, some with no
    area: the tree only narrows the pairs, it must not change the answer."""
    rng = np.random.default_rng(seed)

    def random_square():
        x, y = rng.uniform(0, 10, 2)
        side = float(rng.choice([0.0, 0.1, 0.4, 1.0, 2.5, 6.0]))
        return _square(float(x), float(y), float(x) + side, float(y) + side)

    pos = [random_square() for _ in range(80)]
    neg = [random_square() for _ in range(80)]
    # nested chains with alternating sign, duplicates on both sides
    for k in range(5):
        base = k * 2.0
        pos.append(_square(base, base, base + 1.6, base + 1.6))
        neg.append(_square(base + 0.2, base + 0.2, base + 1.4, base + 1.4))
        pos.append(_square(base + 0.4, base + 0.4, base + 1.2, base + 1.2))
        neg.append(_square(base + 0.6, base + 0.6, base + 1.0, base + 1.0))
        pos.append(_square(base + 0.7, base + 0.7, base + 0.9, base + 0.9))
    neg.append(pos[-1])
    pos.append(neg[0])
    neg.append(COLLINEAR)
    pos.append(ONE_POINT)
    # negatives with no area laid over the nested chains
    for k in range(5):
        neg.append([(k * 2.0 + 0.8, k * 2.0 + 0.1), (k * 2.0 + 0.8, k * 2.0 + 1.5)])
        neg.append([(k * 2.0 + 0.8, k * 2.0 + 0.8)] * 3)
    # holes drawn as two abutting traces, each around an island, one with a
    # negative inside the island and one with a piece drawn twice
    for k in range(3):
        base = 11.0 + k * 3.0
        neg.append(_square(base, base, base + 1.0, base + 2.0))
        neg.append(_square(base + 1.0, base, base + 2.0, base + 2.0))
        pos.append(_square(base + 0.3, base + 0.3, base + 1.7, base + 1.7))
    neg.append(_square(11.8, 11.8, 12.2, 12.2))
    neg.append(_square(14.0, 14.0, 15.0, 16.0))

    got = islandCuts(pos, neg, reach)
    assert got == _pairwise_cuts(pos, neg, reach)
    assert got, "the case has islands"


@pytest.mark.parametrize("points", [COLLINEAR, ONE_POINT])
def test_zero_area_positive_in_a_hole_is_not_an_island(points):
    """A positive with no area is not filled back in: it would put voxels
    back along a line where the old fill had cleared them."""
    traces = [(OUTER, False), (HOLE, True), (points, False)]
    surf = _surface(traces)
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all()
    assert islandCuts([OUTER, points], [HOLE]) == []


# ---------------------------------------------------- unchanged without one
@pytest.mark.parametrize("name, traces", [
    ("ring", [(OUTER, False), (HOLE, True)]),
    ("solid", [(OUTER, False)]),
    ("two_overlapping_positives", [(OUTER, False), (_square(2, 2, 4, 4), False)]),
    ("hole_crossing_the_edge", [(OUTER, False), (_square(2.5, 1, 3.5, 2), True)]),
    ("positive_crossing_the_hole", [
        (OUTER, False), (HOLE, True), (_square(1.5, 1.5, 2.5, 2.5), False),
    ]),
    ("negative_alone", [(HOLE, True)]),
    ("hole_touching_the_edge", [(OUTER, False), (_square(2, 1, 3, 2), True)]),
    ("two_holes", [(OUTER, False), (_square(0.2, 0.2, 0.8, 0.8), True), (HOLE, True)]),
    ("two_point_trace", [(OUTER, False), ([(1, 1), (2, 2)], True), (ISLAND, False)]),
    ("coincident_pair_no_hole", [(OUTER, False), (ISLAND, False), (ISLAND, True)]),
])
def test_without_an_island_the_fill_is_unchanged(name, traces):
    surf = _surface(traces)
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all(), name


@pytest.mark.parametrize("name, traces", [
    ("ring", [(OUTER, False), (HOLE, True)]),
    ("positive_crossing_the_hole", [
        (OUTER, False), (HOLE, True), (_square(1.5, 1.5, 2.5, 2.5), False),
    ]),
])
def test_without_an_island_there_is_nothing_to_fill_back(name, traces):
    pos = [p for p, negative in traces if not negative]
    neg = [p for p, negative in traces if negative]
    assert islandCuts(pos, neg) == [], name


@pytest.mark.parametrize("fixture", ["shapes1.jser", "shapes2.jser"])
def test_fixture_series_fill_unchanged(tmp_path, fixture):
    """Every object of the in-repo series, through the real traces and
    section transforms, fills the same voxels as before."""
    src = os.path.join(FIXTURE_DIR, fixture)
    if not os.path.exists(src):
        pytest.skip(f"fixture {fixture} not found")
    fp = str(tmp_path / fixture)
    shutil.copyfile(src, fp)
    from PyReconstruct.modules.datatypes.series import Series

    series = Series.openJser(fp)
    try:
        surfaces = {}
        for snum, section in series.enumerateSections(show_progress=False):
            for name, contour in section.contours.items():
                surf = surfaces.setdefault(name, Surface(name, series, None, None, None))
                for trace in contour:
                    surf.addTrace(trace, snum, section.tform)
        assert surfaces
        for name, surf in surfaces.items():
            volume, _ = surf.generateVolume()
            assert (volume == _reference_volume(surf)).all(), name
    finally:
        series.close()


# ------------------------------------------ a hole drawn as several traces
# the hole around this island is two negatives sharing the edge x = 2.5;
# neither covers the island on its own
WIDE = _square(0, 0, 5, 5)
BIG_ISLAND = _square(1, 1, 4, 4)
H_A, H_B = _square(0.5, 0.5, 2.5, 4.5), _square(2.5, 0.5, 4.5, 4.5)


def _island_only(surf, island):
    """A volume with only the voxels of ``island`` set, on every section."""
    return _order_volume(surf, lambda pos, neg: [(island, True)])


def test_island_in_a_hole_drawn_as_two_traces_fills():
    surf = _surface([(WIDE, False), (H_A, True), (H_B, True), (BIG_ISLAND, False)])
    volume, _ = surf.generateVolume()
    full = np.ones_like(volume)
    assert _count(volume, BIG_ISLAND, surf) == _count(full, BIG_ISLAND, surf) > 0
    # the two passes clear the island with the hole; the fill is those two
    # passes with the island put back, and nothing else
    assert (volume == (_reference_volume(surf) | _island_only(surf, BIG_ISLAND))).all()


def test_two_passes_lose_the_island_in_a_two_trace_hole():
    surf = _surface([(WIDE, False), (H_A, True), (H_B, True), (BIG_ISLAND, False)])
    assert _count(_reference_volume(surf), BIG_ISLAND, surf) == 0


def test_island_cuts_lists_a_hole_drawn_as_two_traces():
    assert islandCuts([WIDE, BIG_ISLAND], [H_A, H_B]) == [(BIG_ISLAND, [])]
    assert islandCuts([WIDE, BIG_ISLAND], [H_A, H_B], REACH) == [(BIG_ISLAND, [])]


@pytest.mark.parametrize("name, pieces", [
    ("sharing an edge", (H_A, H_B)),
    ("overlapping", (_square(0.5, 0.5, 2.8, 4.5), _square(2.2, 0.5, 4.5, 4.5))),
    ("three strips", (
        _square(0.5, 0.5, 1.8, 4.5), _square(1.8, 0.5, 3.2, 4.5),
        _square(3.2, 0.5, 4.5, 4.5),
    )),
    ("a fraction of a voxel apart", (H_A, _square(2.52, 0.5, 4.5, 4.5))),
    ("a fraction of a voxel apart and barely larger than the island", (
        _square(1, 0.999, 2.5, 4.001), _square(2.52, 0.999, 4, 4.001),
    )),
    ("joined below the island with a slit through it", (
        H_A,
        [(2.5, 0.5), (4.5, 0.5), (4.5, 4.5), (2.52, 4.5), (2.52, 0.8), (2.5, 0.8)],
    )),
    ("one piece drawn twice", (H_A, H_A, H_B)),
])
def test_hole_drawn_as_several_traces_is_around_the_island(name, pieces):
    """The pieces of a hole together cover the island, so none of them cuts
    it: it fills completely. Two pieces a fraction of a voxel apart both
    reach into the voxels between them, so they count as one hole, whether
    the gap is between the pieces or a slit through them, and whatever their
    areas add up to before the gap is closed."""
    neg = list(pieces)
    assert islandCuts([WIDE, BIG_ISLAND], neg, REACH) == [(BIG_ISLAND, [])], name
    surf = _surface([(WIDE, False)] + [(p, True) for p in neg] + [(BIG_ISLAND, False)])
    volume, _ = surf.generateVolume()
    assert _count(volume, BIG_ISLAND, surf) == _count(np.ones_like(volume), BIG_ISLAND, surf), name
    assert (volume == (_reference_volume(surf) | _island_only(surf, BIG_ISLAND))).all(), name


def test_negative_inside_an_island_in_a_two_trace_hole_still_cuts_it():
    inner = _square(2, 2, 3, 3)  # across the seam between the two pieces
    assert islandCuts([WIDE, BIG_ISLAND], [H_A, H_B, inner], REACH) == [
        (BIG_ISLAND, [inner]),
    ]
    surf = _surface([
        (WIDE, False), (H_A, True), (H_B, True), (BIG_ISLAND, False), (inner, True),
    ])
    volume, _ = surf.generateVolume()
    full = np.ones_like(volume)
    assert _count(volume, inner, surf) == 0
    assert _count(volume, BIG_ISLAND, surf) == (
        _count(full, BIG_ISLAND, surf) - _count(full, inner, surf)
    )


def test_negative_across_the_edge_of_an_island_in_a_two_trace_hole_cuts_it():
    """A negative that crosses the island's edge, inside the hole, is not a
    piece of the hole: the hole covers the island without it."""
    across = _square(3.5, 2, 4.4, 3)
    assert islandCuts([WIDE, BIG_ISLAND], [H_A, H_B, across], REACH) == [
        (BIG_ISLAND, [across]),
    ]
    cut = _surface([(WIDE, False), (BIG_ISLAND, False), (across, True)])
    cut_ref = _reference_volume(cut)
    volume, _ = _surface([
        (WIDE, False), (H_A, True), (H_B, True), (BIG_ISLAND, False), (across, True),
    ]).generateVolume()
    assert 0 < _count(volume, BIG_ISLAND, cut) == _count(cut_ref, BIG_ISLAND, cut)


def test_pieces_further_apart_than_the_reach_are_not_one_hole():
    """Two negatives with a wall between them wider than a voxel's diagonal
    are two holes, and a positive across the wall is no island: the fill
    stays the two passes, wall included."""
    apart = _square(2.55, 0.5, 4.5, 4.5)
    assert islandCuts([WIDE, BIG_ISLAND], [H_A, apart], REACH) == []
    surf = _surface([(WIDE, False), (H_A, True), (apart, True), (BIG_ISLAND, False)])
    volume, _ = surf.generateVolume()
    reference = _reference_volume(surf)
    assert 0 < _count(reference, BIG_ISLAND, surf) < _count(np.ones_like(volume), BIG_ISLAND, surf)
    assert (volume == reference).all()


def test_two_traces_with_the_island_outline_between_them_cancel_it():
    """Two negatives that together have the island's own outline are not a
    hole around it, the same as one negative with that outline."""
    half_a, half_b = _square(1, 1, 2.5, 4), _square(2.5, 1, 4, 4)
    assert islandCuts([WIDE, BIG_ISLAND], [half_a, half_b], REACH) == []
    surf = _surface([(WIDE, False), (half_a, True), (half_b, True), (BIG_ISLAND, False)])
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all()


# a negative whose outline crosses itself; GEOS cannot join it with another
SELF_CROSSING = [(0.5, 0.5), (3, 4.5), (0.5, 4.5), (2, 0.5)]


def test_a_self_crossing_negative_beside_a_piece_fills_as_before():
    """GEOS cannot take the union of some self-crossing outlines. Such a
    negative is not a piece of a hole, so the positive is no island, and the
    fill is the two passes, as it was."""
    assert islandCuts([WIDE, BIG_ISLAND], [SELF_CROSSING, H_B], REACH) == []
    surf = _surface([
        (WIDE, False), (SELF_CROSSING, True), (H_B, True), (BIG_ISLAND, False),
    ])
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all()


def test_one_covering_negative_keeps_the_others_as_cuts():
    """When one negative covers the island on its own, the others are cuts,
    whatever their union covers: a negative from inside the island out past
    the hole's edge still clears its part of the island."""
    out = _square(2.5, 2, 4.8, 3)
    assert islandCuts([WIDE, BIG_ISLAND], [_square(0.5, 0.5, 4.5, 4.5), out], REACH) == [
        (BIG_ISLAND, [out]),
    ]
