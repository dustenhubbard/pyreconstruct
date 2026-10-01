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
import os
import shutil

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from skimage.draw import polygon

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.backend.volume.objects_3D import (  # noqa: E402
    Surface,
    nestedFillOrder,
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
INNER_HOLE = _square(1.45, 1.45, 1.55, 1.55)


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
    """A positive and a negative with the same outline cover each other; the
    walk must stop rather than alternate forever."""
    order = nestedFillOrder([HOLE], [HOLE])
    assert order == [(HOLE, True), (HOLE, False), (HOLE, True), (HOLE, False)]


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
