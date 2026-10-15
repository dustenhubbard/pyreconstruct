"""At the default XY resolution, a surface built from thin contours has far fewer
tunnels; the few that remain come from section fills that touch only at a corner.

``Surface.generateVolume`` rounded each trace point onto the voxel grid and
filled the voxels whose center fell inside the rounded outline. A synapse
contour at the default XY resolution is about one voxel wide, so a section
came out as a dotted line, or as a one-voxel band that sat one row over from
the band on the next section. Marching cubes joins voxels only across a
shared face, so the gaps and the offset rows became tunnels through the
sheet. Every trace now covers every voxel it reaches into (``traceVoxels``):
the voxels with their center inside the outline and the voxels the outline
passes through, which is a 4-connected band on every section, and two
outlines that overlap on consecutive sections always share a voxel.

A perforation drawn wider than a voxel keeps its tunnel: a ring-shaped
trace, a positive with a negative inside it, and a sheet drawn as two
separate traces on one section. A gap narrower than a voxel closes at that
resolution, so each of these draws its hole several voxels wide. Two
separate sheets stay two bodies.
"""
import math
import os

import numpy as np
import pytest
from scipy import ndimage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.backend.volume.objects_3D import Surface, traceVoxels
from PyReconstruct.modules.datatypes import Transform

VRES = 0.05  # the voxel width at 3D_xy_res 0: max(mag, thickness)
FOUR = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])


class _StubSeries:
    """The only series attributes the surface path reads."""

    avg_mag = 0.002
    avg_thickness = VRES

    def __init__(self, smoothing="none", res=0):
        self.options = {
            "3D_xy_res": res,
            "3D_smoothing": smoothing,
            "smoothing_iterations": 10,
        }

    def getOption(self, name):
        return self.options[name]

    def getAttr(self, name, attr):
        return 1.0


class _StubTrace:
    def __init__(self, points, negative=False, color=(255, 0, 0)):
        self.points = points
        self.negative = negative
        self.color = color


def _surface(sections, smoothing="none", tforms=None):
    """A Surface from ``{section: [(points, negative), ...]}``."""
    surf = Surface("obj", _StubSeries(smoothing), None, None, None)
    for snum, traces in sections.items():
        tform = tforms[snum] if tforms else None
        for points, negative in traces:
            surf.addTrace(_StubTrace(points, negative=negative), snum, tform)
    return surf


def _topology(tm):
    """(bodies, tunnels) of a watertight mesh."""
    assert tm.is_watertight
    parts = tm.split(only_watertight=False)
    return len(parts), sum(1 - int(p.euler_number) / 2 for p in parts)


def _bands(volume):
    """The number of 4-connected pieces the fill has on each section."""
    return [int(ndimage.label(volume[:, :, z], FOUR)[1]) for z in range(volume.shape[2])]


def _rect(x0, y0, width, height, angle=0.0, per_side=10):
    """A rectangle outline rotated about its corner, ``per_side`` points an edge."""
    corners = [(0, 0), (width, 0), (width, height), (0, height)]
    points = []
    for i in range(4):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
        for k in range(per_side):
            t = k / per_side
            points.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    c, s = math.cos(angle), math.sin(angle)
    return [(x0 + x * c - y * s, y0 + x * s + y * c) for x, y in points]


def _square(x0, y0, side):
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


ANGLE = math.radians(20)
NORMAL = (-math.sin(ANGLE), math.cos(ANGLE))


def _sheet(width, shift, nsec=6, x0=1.0, y0=2.0, length=40):
    """A sheet ``width`` voxels wide and ``length`` long on ``nsec`` sections,
    each section moved ``shift`` voxels along the sheet's normal."""
    return {
        z: [(_rect(x0 + z * shift * VRES * NORMAL[0], y0 + z * shift * VRES * NORMAL[1],
                   length * VRES, width * VRES, ANGLE), False)]
        for z in range(nsec)
    }


# ------------------------------------------------------------- thin sheets
@pytest.mark.parametrize("width, shift", [
    (0.3, 0.0),   # thinner than a voxel: a dotted line before
    (0.5, 0.3),   # thinner than a voxel and drifting: dots that tunnel
    (1.1, 0.5),   # one voxel wide and drifting: one-row bands that tunnel
    (1.3, 0.7),
])
def test_thin_sheet_fills_one_band_on_every_section(width, shift):
    volume, _ = _surface(_sheet(width, shift)).generateVolume()
    assert _bands(volume) == [1] * 6


@pytest.mark.parametrize("width, shift", [(0.5, 0.3), (1.1, 0.5), (1.3, 0.7)])
@pytest.mark.parametrize("smoothing", ["none", "humphrey"])
def test_thin_sheet_is_one_body_with_no_tunnel(width, shift, smoothing):
    tm = _surface(_sheet(width, shift), smoothing).generateTrimesh()
    assert _topology(tm) == (1, 0)


def test_drift_from_the_section_transforms_keeps_the_sheet_whole():
    """The same outline on every section, moved by each section's transform."""
    outline = _rect(1.0, 2.0, 40 * VRES, 1.1 * VRES, ANGLE)
    tforms = {
        z: Transform([1, 0, z * 0.5 * VRES * NORMAL[0], 0, 1, z * 0.5 * VRES * NORMAL[1]])
        for z in range(6)
    }
    surf = _surface({z: [(outline, False)] for z in range(6)}, tforms=tforms)
    volume, _ = surf.generateVolume()
    assert _bands(volume) == [1] * 6
    assert _topology(surf.generateTrimesh()) == (1, 0)


def test_curved_thin_sheet_is_whole():
    def arc(cx, width, n=30):
        r = 20 * VRES
        outer = [(cx + (r + width / 2) * math.cos(a), 3.0 + (r + width / 2) * math.sin(a))
                 for a in np.linspace(0.3, 2.4, n)]
        inner = [(cx + (r - width / 2) * math.cos(a), 3.0 + (r - width / 2) * math.sin(a))
                 for a in np.linspace(2.4, 0.3, n)]
        return outer + inner

    surf = _surface({z: [(arc(3.0 + z * 0.3 * VRES, 0.4 * VRES), False)] for z in range(5)})
    volume, _ = surf.generateVolume()
    assert _bands(volume) == [1] * 5
    assert _topology(surf.generateTrimesh()) == (1, 0)


# ------------------------------------------------- perforations that stay
def _ring(cx, cy, r_out, r_in, slit=0.05, n=48):
    """An annulus drawn as one outline, around the outside and back around
    the inside, with a slit narrower than a voxel between the two passes."""
    angles = np.linspace(slit, 2 * math.pi - slit, n)
    outer = [(cx + r_out * math.cos(a), cy + r_out * math.sin(a)) for a in angles]
    inner = [(cx + r_in * math.cos(a), cy + r_in * math.sin(a)) for a in angles[::-1]]
    return outer + inner


def test_ring_shaped_trace_keeps_its_tunnel():
    surf = _surface({z: [(_ring(3.0, 3.0, 8 * VRES, 4 * VRES), False)] for z in range(5)})
    assert _topology(surf.generateTrimesh()) == (1, 1)


def test_thin_ring_keeps_exactly_one_tunnel():
    """A ring half a voxel wide, drifting, used to be dots with many tunnels."""
    sections = {z: [(_ring(3.0 + z * 0.3 * VRES, 3.0, 8 * VRES, 7.5 * VRES), False)]
                for z in range(5)}
    surf = _surface(sections)
    assert _bands(surf.generateVolume()[0]) == [1] * 5
    assert _topology(surf.generateTrimesh()) == (1, 1)


def test_negative_inside_a_positive_keeps_its_tunnel():
    sections = {z: [(_square(1.0, 1.0, 12 * VRES), False),
                    (_square(1.0 + 4 * VRES, 1.0 + 4 * VRES, 4 * VRES), True)] for z in range(5)}
    assert _topology(_surface(sections).generateTrimesh()) == (1, 1)


def test_sheet_drawn_as_two_traces_on_one_section_keeps_its_hole():
    """A perforation drawn as two separate traces on the middle section, with
    the whole sheet above and below it, is one tunnel."""
    sections = _sheet(1.1, 0.5)
    whole = sections[3][0][0]
    left = _rect(1.0 + 3 * 0.5 * VRES * NORMAL[0], 2.0 + 3 * 0.5 * VRES * NORMAL[1],
                 15 * VRES, 1.1 * VRES, ANGLE)
    offset = 25 * VRES
    right = _rect(1.0 + 3 * 0.5 * VRES * NORMAL[0] + offset * math.cos(ANGLE),
                  2.0 + 3 * 0.5 * VRES * NORMAL[1] + offset * math.sin(ANGLE),
                  15 * VRES, 1.1 * VRES, ANGLE)
    sections[3] = [(left, False), (right, False)]
    surf = _surface(sections)
    assert _bands(surf.generateVolume()[0])[3] == 2
    assert _topology(surf.generateTrimesh()) == (1, 1)
    del whole


def test_two_sheets_apart_stay_two_bodies():
    far = {z: [(points, False) for points, _ in traces]
           for z, traces in _sheet(0.5, 0.3, y0=6.0).items()}
    sections = {z: _sheet(0.5, 0.3)[z] + far[z] for z in range(6)}
    assert _topology(_surface(sections).generateTrimesh()) == (2, 0)


# -------------------------------------------------- the quantitative side
def test_square_ten_voxels_wide_fills_ten_by_ten():
    side = 10 * VRES
    surf = _surface({z: [(_square(1.0, 2.0, side), False)] for z in range(5)})
    volume, _ = surf.generateVolume()
    assert volume.sum(axis=(0, 1)).tolist() == [100] * 5
    # the mesh sits on the trace outline, not half a voxel outside it
    (xlo, ylo, _), (xhi, yhi, _) = surf.generateTrimesh().bounds
    assert xlo == pytest.approx(1.0) and xhi == pytest.approx(1.0 + side)
    assert ylo == pytest.approx(2.0) and yhi == pytest.approx(2.0 + side)


@pytest.mark.parametrize("smoothing", ["none", "humphrey"])
@pytest.mark.parametrize("voxels", [10, 20, 40])
def test_box_volume_is_not_inflated(voxels, smoothing):
    side = voxels * VRES
    exact = side * side * VRES * 5
    surf = _surface({z: [(_square(1.0, 2.0, side), False)] for z in range(5)}, smoothing)
    volume = surf.generateTrimesh().volume
    # marching cubes trims the box edges a little; it used to be 4.5 to 18% high
    assert 0.96 * exact < volume <= exact


@pytest.mark.parametrize("radius", [10, 20])
def test_sphere_from_circles_is_within_a_voxel_of_the_sphere(radius):
    """A round object covers the voxels its outline reaches into, so it reads
    up to half a voxel wide all around, as it did before."""
    r = radius * VRES
    sections = {}
    for snum in range(2 * radius + 1):
        z = (snum - radius) * VRES
        rr = math.sqrt(max(r * r - z * z, 0))
        if rr > 0:
            sections[snum] = [([(3.0 + rr * math.cos(a), 3.0 + rr * math.sin(a))
                               for a in np.linspace(0, 2 * math.pi, 64, endpoint=False)], False)]
    tm = _surface(sections, "humphrey").generateTrimesh()
    bound = (1 + 0.5 / radius) ** 3 * 1.02  # half a voxel all around, 2% for the mesh
    assert 1.0 < tm.volume / (4 / 3 * math.pi * r ** 3) < bound
    assert 1.0 < tm.area / (4 * math.pi * r ** 2) < (1 + 0.5 / radius) ** 2 * 1.02


def test_sliver_under_a_voxel_wide_fills_one_row():
    sliver = [(x, 2.0 + (y - 2.0) * 0.03) for x, y in _square(1.0, 2.0, 20 * VRES)]
    volume, _ = _surface({0: [(sliver, False)], 1: [(sliver, False)]}).generateVolume()
    assert volume.sum(axis=(0, 1)).tolist() == [20, 20]


def test_trace_smaller_than_a_voxel_fills_one_voxel():
    tiny = _square(1.0, 2.0, VRES / 4)
    volume, _ = _surface({0: [(tiny, False)], 1: [(tiny, False)]}).generateVolume()
    assert volume.sum(axis=(0, 1)).tolist() == [1, 1]


# -------------------------------------------------------- traceVoxels itself
def _cells(points, shape=(40, 40), vres=1.0):
    xs, ys = traceVoxels(points, 0.0, 0.0, vres, shape)
    return sorted(zip(xs.tolist(), ys.tolist()))


def test_square_on_the_grid_covers_only_the_voxels_it_reaches_into():
    assert len(_cells(_square(0, 0, 10))) == 100
    assert len(_cells(_square(0.5, 0.5, 10))) == 121


def test_outline_voxels_are_four_connected():
    grid = np.zeros((40, 40), dtype=bool)
    xs, ys = traceVoxels(_rect(3, 3, 30, 0.3, ANGLE), 0.0, 0.0, 1.0, grid.shape)
    grid[xs, ys] = True
    assert ndimage.label(grid, FOUR)[1] == 1


def test_trace_with_no_area_covers_the_voxels_it_runs_through():
    line = _cells([(1.5, 1.5), (6.5, 4.5)])
    assert line[0] == (1, 1) and line[-1] == (6, 4)
    grid = np.zeros((40, 40), dtype=bool)
    grid[tuple(np.array(line).T)] = True
    assert ndimage.label(grid, FOUR)[1] == 1
    assert _cells([(2.5, 2.5)] * 3) == [(2, 2)]
    assert _cells([]) == []


def test_voxels_outside_the_grid_are_dropped():
    xs, ys = traceVoxels(_square(-3, -3, 10), 0.0, 0.0, 1.0, (5, 5))
    assert xs.min() >= 0 and ys.min() >= 0 and xs.max() < 5 and ys.max() < 5
    assert len(xs) == 25
