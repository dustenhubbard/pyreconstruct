"""Surface-mode meshes match the traces they are built from.

The voxel grid put voxel centers on xmin + i*vres and rounded the trace points
onto those centers, and skimage's polygon counts a center on the outline as
inside. A square 10 voxels wide filled 11 by 11, so every surface was about
half a voxel too big all around, and `Export quantitative data` reported
volumes 3 to 18% high at the default XY resolution. Voxel i now spans
xmin + i*vres to xmin + (i+1)*vres and is filled when its center is inside.
"""
import math
import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.backend.volume import objects_3D
from PyReconstruct.modules.backend.volume.objects_3D import Surface

VRES = 0.05  # voxel width at 3D_xy_res 0: max(mag, thickness)


class FakeSeries:
    """Only what Surface.generateTrimesh reads, so no settings are touched."""

    avg_mag = 0.002
    avg_thickness = VRES

    def __init__(self, smoothing="none"):
        self.options = {
            "3D_xy_res": 0,
            "3D_smoothing": smoothing,
            "smoothing_iterations": 10,
        }

    def getOption(self, key):
        return self.options[key]

    def getAttr(self, name, key):
        return 1


def _surface(points_per_section, smoothing="none"):
    surface = Surface("box", FakeSeries(smoothing))
    for snum, points in points_per_section.items():
        trace = SimpleNamespace(color=(255, 0, 0), points=points, negative=False)
        surface.addTrace(trace, snum)
    return surface


def _square(x0, y0, side):
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


@pytest.fixture
def voxel_counts(monkeypatch):
    counts = []
    real = objects_3D.trimesh.voxel.ops.matrix_to_marching_cubes

    def spy(matrix, *args, **kwargs):
        counts.append(matrix.sum(axis=(0, 1)).tolist())
        return real(matrix, *args, **kwargs)

    monkeypatch.setattr(objects_3D.trimesh.voxel.ops, "matrix_to_marching_cubes", spy)
    return counts


def test_square_ten_voxels_wide_fills_ten_by_ten(voxel_counts):
    side = 10 * VRES
    surface = _surface({s: _square(1.0, 2.0, side) for s in range(5)})

    tm = surface.generateTrimesh()

    assert voxel_counts == [[100] * 5]
    # the mesh sits on the trace outline, not half a voxel outside it
    (xlo, ylo, _), (xhi, yhi, _) = tm.bounds
    assert xlo == pytest.approx(1.0) and xhi == pytest.approx(1.0 + side)
    assert ylo == pytest.approx(2.0) and yhi == pytest.approx(2.0 + side)


@pytest.mark.parametrize("smoothing", ["none", "humphrey"])
@pytest.mark.parametrize("voxels", [10, 20, 40])
def test_box_volume_is_not_inflated(voxels, smoothing):
    side = voxels * VRES
    exact = side * side * VRES * 5
    surface = _surface({s: _square(1.0, 2.0, side) for s in range(5)}, smoothing)

    volume = surface.generateTrimesh().volume

    # marching cubes trims the box edges a little; it used to be 4.5 to 18% high
    assert 0.96 * exact < volume <= exact


def test_sphere_from_circles_matches_the_sphere():
    # a sphere 10 voxels in radius, one circle per section, default smoothing
    r = 10 * VRES
    sections = {}
    for snum in range(21):
        z = (snum - 10) * VRES
        rr = math.sqrt(max(r * r - z * z, 0))
        if rr > 0:
            sections[snum] = [
                (3.0 + rr * math.cos(a), 3.0 + rr * math.sin(a))
                for a in np.linspace(0, 2 * math.pi, 64, endpoint=False)
            ]
    surface = _surface(sections, smoothing="humphrey")

    tm = surface.generateTrimesh()

    # it used to measure 1.116 times the volume and 1.086 times the area
    assert tm.volume == pytest.approx(4 / 3 * math.pi * r ** 3, rel=0.02)
    assert tm.area == pytest.approx(4 * math.pi * r ** 2, rel=0.02)


def test_trace_smaller_than_a_voxel_keeps_one_voxel(voxel_counts):
    tiny = _square(1.0, 2.0, VRES / 4)
    surface = _surface({0: tiny, 1: tiny})

    tm = surface.generateTrimesh()

    assert voxel_counts == [[1, 1]]
    assert tm.volume > 0
    center = np.mean(tiny, axis=0)
    assert np.allclose(tm.bounds.mean(axis=0)[:2], center, atol=VRES)


def test_sliver_under_a_voxel_wide_fills_one_row(voxel_counts):
    # 20 voxels long and 0.6 of a voxel wide: one row of voxel centers is inside
    sliver = _square(1.0, 2.0, 20 * VRES)
    sliver = [(x, 2.0 + (y - 2.0) * 0.03) for x, y in sliver]
    surface = _surface({0: sliver, 1: sliver})

    tm = surface.generateTrimesh()

    assert voxel_counts == [[20, 20]]
    (xlo, _, _), (xhi, _, _) = tm.bounds
    assert xlo == pytest.approx(1.0) and xhi == pytest.approx(1.0 + 20 * VRES)
