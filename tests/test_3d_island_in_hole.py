"""The 3D surface keeps an island that sits inside one of the object's own holes.

``Surface.generateVolume`` filled every positive trace of a section and then
cleared every negative trace, so a positive trace drawn inside a negative one
(an island in a hole) was cleared along with the hole. The mesh, and the volume
``3D ▸ Export quantitative data`` measures from it, lost the island.

``nestedFillOrder`` now fills positives, clears negatives, fills the positives
a negative covers, clears the negatives those islands cover, and so on. A
section with no island keeps exactly the order it had, which the reference
loop below (the shipped fill, frozen) pins voxel for voxel.
"""
import math
import os
import shutil

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from skimage.draw import polygon

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.backend.volume.objects_3D import (  # noqa: E402
    Surface,
    _clearsAgain,
    _covers,
    _traceLine,
    _tracePolygon,
    nestedFillOrder,
)
from PyReconstruct.modules.calc.nesting import _cutsInto  # noqa: E402

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
# touching its corner, and two that miss it by less than a voxel's diagonal
# (the voxels here are 0.03 wide), so both round onto its edge voxels
TOUCH = _square(1.7, 1.4, 1.9, 1.6)
CORNER = _square(1.7, 1.7, 1.9, 1.9)
NEAR = _square(1.724, 1.4, 1.9, 1.6)
NEAR_CORNER = _square(1.724, 1.724, 1.9, 1.9)
# one too far to round onto the island at all
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


def _reference_volume(surf):
    """The fill as it shipped: every positive, then every negative."""
    series = surf.series
    vres_min = min(series.avg_mag, series.avg_thickness)
    vres_max = max(series.avg_mag, series.avg_thickness)
    vres = vres_min + (1 - series.getOption("3D_xy_res") / 100) * (vres_max - vres_min)
    xmin, xmax, ymin, ymax, smin, smax = tuple(surf.extremes)
    volume = np.zeros(
        (round((xmax - xmin) / vres) + 1, round((ymax - ymin) / vres) + 1, smax - smin + 1),
        dtype=bool,
    )
    for snum, trace_lists in surf.traces.items():
        for fill, key in ((True, "pos"), (False, "neg")):
            for trace in trace_lists[key]:
                xs = np.array([round((x - xmin) / vres) for x, _ in trace])
                ys = np.array([round((y - ymin) / vres) for _, y in trace])
                xx, yy = polygon(xs, ys)
                volume[xx, yy, snum - smin] = fill
    return volume


def _count(volume, points, surf):
    """Voxels of ``volume`` inside the trace ``points``, on every section."""
    series = surf.series
    vres_min = min(series.avg_mag, series.avg_thickness)
    vres_max = max(series.avg_mag, series.avg_thickness)
    vres = vres_min + (1 - series.getOption("3D_xy_res") / 100) * (vres_max - vres_min)
    xmin, _, ymin, _, _, _ = tuple(surf.extremes)
    xs = np.array([round((x - xmin) / vres) for x, _ in points])
    ys = np.array([round((y - ymin) / vres) for _, y in points])
    xx, yy = polygon(xs, ys)
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


def test_nested_fill_order_three_levels():
    order = nestedFillOrder(
        [OUTER, ISLAND, INNER_ISLAND], [HOLE, INNER_HOLE]
    )
    # the inner island is covered by the outer hole too, so it is drawn with
    # the first islands; the inner hole clears it; the next level fills it
    assert order == [
        (OUTER, True), (ISLAND, True), (INNER_ISLAND, True),
        (HOLE, False), (INNER_HOLE, False),
        (ISLAND, True), (INNER_ISLAND, True),
        (INNER_HOLE, False),
        (INNER_ISLAND, True),
    ]


def test_island_only_on_some_sections():
    """The order is decided per section, so an island on one section does
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


def test_nested_fill_order_shape():
    order = nestedFillOrder([OUTER, ISLAND], [HOLE, INNER_HOLE])
    assert order == [
        (OUTER, True), (ISLAND, True),
        (HOLE, False), (INNER_HOLE, False),
        (ISLAND, True),
        (INNER_HOLE, False),
    ]


def test_nested_fill_order_ends_on_identical_outlines():
    """A positive and a negative with the same outline are not nested, so the
    order is the plain one and the walk does not alternate forever."""
    order = nestedFillOrder([HOLE], [HOLE])
    assert order == [(HOLE, True), (HOLE, False)]


def test_coincident_negative_cancels_the_island():
    """A negative with the island's own outline is applied again after the
    island refills, so the pair cancels as it did in the old fill."""
    traces = [(OUTER, False), (HOLE, True), (ISLAND, False), (ISLAND, True)]
    surf = _surface(traces)
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all()
    order = nestedFillOrder([OUTER, ISLAND], [HOLE, ISLAND])
    assert order[-1] == (ISLAND, False)
    assert order == [
        (OUTER, True), (ISLAND, True), (HOLE, False), (ISLAND, False),
        (ISLAND, True), (ISLAND, False),
    ]


@pytest.mark.parametrize("hole", [True, False])
def test_negative_across_the_island_edge_still_cuts_it(hole):
    """A negative that crosses the island's edge is applied again after the
    refill. With no hole around the island the old fill already cut it, and
    the island inside a hole must end up cut the same way."""
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


def test_nested_fill_order_reapplies_cutting_negatives():
    assert nestedFillOrder([OUTER, ISLAND], [HOLE, CROSS, LINE]) == [
        (OUTER, True), (ISLAND, True),
        (HOLE, False), (CROSS, False), (LINE, False),
        (ISLAND, True),
        (CROSS, False), (LINE, False),
    ]


@pytest.mark.parametrize("name, near", [
    ("sharing an edge", TOUCH),
    ("touching a corner", CORNER),
    ("less than a voxel away", NEAR),
    ("less than a voxel's diagonal from a corner", NEAR_CORNER),
])
def test_negative_beside_the_island_still_cuts_it(name, near):
    """A negative that touches the island, or sits close enough that both
    round onto the same voxels, clears those voxels again after the island
    refills: the island ends up with the voxels it has with no hole around
    it, and the negative's own voxels stay clear as they did before."""
    cut = _surface([(OUTER, False), (ISLAND, False), (near, True)])
    cut_ref = _reference_volume(cut)
    full = np.ones_like(cut_ref)
    assert 0 < _count(cut_ref, ISLAND, cut) < _count(full, ISLAND, cut), name

    surf = _surface([(OUTER, False), (HOLE, True), (ISLAND, False), (near, True)])
    volume, vres = surf.generateVolume()
    assert vres == pytest.approx(VOXEL)
    assert _count(volume, ISLAND, cut) == _count(cut_ref, ISLAND, cut), name
    assert _count(volume, near, cut) == 0, name


def test_nested_fill_order_reapplies_negatives_beside_the_island():
    pos, neg = [OUTER, ISLAND], [HOLE, TOUCH, CORNER, NEAR, NEAR_CORNER, FAR]
    # touching counts with no reach; the ones a voxel away need it, and a
    # negative too far to round onto the island is left alone
    assert nestedFillOrder(pos, neg)[len(pos) + len(neg):] == [
        (ISLAND, True), (TOUCH, False), (CORNER, False),
    ]
    assert nestedFillOrder(pos, neg, REACH)[len(pos) + len(neg):] == [
        (ISLAND, True),
        (TOUCH, False), (CORNER, False), (NEAR, False), (NEAR_CORNER, False),
    ]


def test_hole_the_island_touches_is_not_reapplied():
    """An island against the inside of its hole's edge touches the hole, but
    the hole is around it, so clearing it again would erase the island."""
    against = _square(1, 1.3, 1.4, 1.7)
    assert nestedFillOrder([OUTER, against], [HOLE], REACH) == [
        (OUTER, True), (against, True), (HOLE, False), (against, True),
    ]
    surf = _surface([(OUTER, False), (HOLE, True), (against, False)])
    volume, _ = surf.generateVolume()
    assert _count(volume, against, surf) == _count(np.ones_like(volume), against, surf)


# two holes side by side with a thin wall between them, each with an island
# against that wall, closer to the other hole than a voxel
H_LEFT, H_RIGHT = _square(0.3, 0.3, 1.49, 2.7), _square(1.51, 0.3, 2.7, 2.7)
I_LEFT, I_RIGHT = _square(0.6, 0.9, 1.47, 2.1), _square(1.53, 0.9, 2.4, 2.1)


def test_islands_in_holes_side_by_side_both_fill():
    """Each hole comes within a voxel of the other hole's island. Clearing
    it again would erase its own island, so neither does, and both islands
    keep every voxel."""
    surf = _surface([
        (OUTER, False), (H_LEFT, True), (H_RIGHT, True),
        (I_LEFT, False), (I_RIGHT, False),
    ])
    volume, _ = surf.generateVolume()
    full = np.ones_like(volume)
    for island in (I_LEFT, I_RIGHT):
        assert _count(volume, island, surf) == _count(full, island, surf) > 0
    assert nestedFillOrder(
        [OUTER, I_LEFT, I_RIGHT], [H_LEFT, H_RIGHT], REACH
    )[5:] == [(I_LEFT, True), (I_RIGHT, True)]


def test_hole_around_another_island_that_cuts_this_one_clears_again():
    """The inner hole is a hole around the inner island, but it cuts into the
    island around it, so it still clears again after the refill."""
    order = nestedFillOrder([OUTER, ISLAND, INNER_ISLAND], [HOLE, INNER_HOLE], REACH)
    assert order[5:7] == [(ISLAND, True), (INNER_ISLAND, True)]
    assert order[7] == (INNER_HOLE, False)


def _pairwise_order(pos, neg, reach=0.0):
    """The walk with every pair compared, no index; the shipped walk must
    give the same answer."""
    order = [(pts, True) for pts in pos] + [(pts, False) for pts in neg]
    if not pos or not neg:
        return order
    pos_polys = [_tracePolygon(pts) for pts in pos]
    neg_polys = [_tracePolygon(pts) for pts in neg]
    neg_shapes = [poly if poly is not None else _traceLine(pts)
                  for poly, pts in zip(neg_polys, neg)]
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
        around = {
            j for j in range(len(neg))
            if any(_covers(neg_polys[j], pos_polys[i]) for i in islands)
        }
        holes = sorted(
            j for j in range(len(neg))
            if any(
                _cutsInto(pos_polys[i], neg_polys[j]) if j in around
                else _clearsAgain(pos_polys[i], neg_shapes[j], reach)
                for i in islands
            )
        )
        if not holes:
            break
        order.extend((neg[j], False) for j in holes)
    return order


@pytest.mark.parametrize("reach", [0.0, 0.05])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_indexed_walk_matches_the_pairwise_walk(seed, reach):
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

    got = nestedFillOrder(pos, neg, reach)
    assert got == _pairwise_order(pos, neg, reach)
    assert len(got) > len(pos) + len(neg), "the case has islands"


@pytest.mark.parametrize("points", [COLLINEAR, ONE_POINT])
def test_zero_area_positive_in_a_hole_is_not_an_island(points):
    """A positive with no area is not refilled: it would put voxels back along
    a line where the old fill had cleared them."""
    traces = [(OUTER, False), (HOLE, True), (points, False)]
    surf = _surface(traces)
    volume, _ = surf.generateVolume()
    assert (volume == _reference_volume(surf)).all()
    assert nestedFillOrder([OUTER, points], [HOLE]) == [
        (OUTER, True), (points, True), (HOLE, False),
    ]


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
def test_without_an_island_the_order_is_unchanged(name, traces):
    pos = [p for p, negative in traces if not negative]
    neg = [p for p, negative in traces if negative]
    assert nestedFillOrder(pos, neg) == (
        [(p, True) for p in pos] + [(n, False) for n in neg]
    ), name


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
