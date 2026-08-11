"""Opacity 0.0 is a valid value and must not be replaced by a fallback.

Five sites used ``if self.alpha:`` / ``if alpha:`` guards that treated the
falsy float ``0.0`` as "no value set" and fell through to a fallback (the
stored series attribute or the literal ``1``).  Pressing ``[`` to reach full
transparency, saving, then changing opacity from the object list reproduced
the divergence: the stored ``0.0`` was discarded and the object rendered at
the object-list value.

All five sites now use ``is not None`` so that an explicitly set ``0.0``
passes through.  Reverting any one guard makes the corresponding test fail.
"""
import types
import numpy as np
import pytest

import PyReconstruct.modules.backend.volume.objects_3D as obj3d
from PyReconstruct.modules.gui.popup import custom_plotter as cp


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

def _series_stub():
    """Series stub whose getAttr returns 0.7 as a non-zero sentinel.

    If any tested code path hits the fallback instead of using ``self.alpha``,
    the result is 0.7, not 0.0, and the assertion fails clearly.
    """
    return types.SimpleNamespace(
        getAttr=lambda *a, **kw: 0.7,
        alignment="default",
        avg_thickness=0.05,
        data={"sections": {}},
        ztraces={},
    )


def _trimesh_stub():
    """Minimal return value that satisfies generate3D's vertex/face unpacking."""
    return types.SimpleNamespace(
        vertices=np.zeros((3, 3)),
        faces=np.zeros((1, 3), dtype=int),
    )


# ---------------------------------------------------------------------------
# objects_3D: Surface, Spheres, Contours
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [obj3d.Surface, obj3d.Spheres])
def test_generate3D_passes_zero_alpha(monkeypatch, cls):
    """generate3D must return alpha=0.0 when the stored alpha is 0.0.

    The fallback (series.getAttr) returns 0.7.  Any code path that ignores
    the stored value and hits the fallback produces 0.7, failing this test.

    Reverting the ``is not None`` guard to the bare ``if self.alpha:`` check
    makes this test fail for both classes.
    """
    series = _series_stub()
    obj = cls.__new__(cls)
    obj.name = "test_obj"
    obj.series = series
    obj.color = (1, 0, 0)
    obj.default_color = (0, 1, 0)
    obj.alpha = 0.0
    obj.tform = None

    # bypass the real mesh computation
    monkeypatch.setattr(obj, "generateTrimesh", _trimesh_stub)

    mesh_data = obj.generate3D()
    assert mesh_data["alpha"] == 0.0, (
        f"{cls.__name__}.generate3D() replaced alpha=0.0 with {mesh_data['alpha']!r}; "
        f"the 'is not None' guard was likely reverted to a bare truthiness check"
    )


def test_contours_generate3D_passes_zero_alpha():
    """Contours.generate3D must return alpha=0.0 when the stored alpha is 0.0.

    Contours builds its verts/faces inline rather than via generateTrimesh, so
    this test initializes an empty trace dict (no loop iteration) and calls
    generate3D directly.  The fallback returns 0.7.

    Reverting the ``is not None`` guard to ``if self.alpha:`` makes this fail.
    """
    series = _series_stub()
    obj = obj3d.Contours.__new__(obj3d.Contours)
    obj.name = "test_obj"
    obj.series = series
    obj.color = (1, 0, 0)
    obj.default_color = (0, 1, 0)
    obj.alpha = 0.0
    obj.tform = None
    obj.traces = {}  # empty -> no loop iterations, verts/faces stay []

    mesh_data = obj.generate3D()
    assert mesh_data["alpha"] == 0.0, (
        f"Contours.generate3D() replaced alpha=0.0 with {mesh_data['alpha']!r}; "
        f"the 'is not None' guard was likely reverted to a bare truthiness check"
    )


# ---------------------------------------------------------------------------
# objects_3D: Ztrace3D
# ---------------------------------------------------------------------------

def test_ztrace3D_generate3D_passes_zero_alpha(monkeypatch):
    """Ztrace3D.generate3D must return alpha=0.0, not the literal-1 fallback.

    Reverting the ``is not None`` guard to ``if self.alpha:`` makes this fail.
    """
    ztrace_stub = types.SimpleNamespace(
        points=[],
        getDistance=lambda series: 0.1,
        color=(0, 1, 0),
    )
    series = _series_stub()
    series.ztraces = {"zt": ztrace_stub}

    stub_verts = np.zeros((0, 3))
    stub_faces = np.zeros((0, 3), dtype=int)
    monkeypatch.setattr(obj3d, "createTube", lambda pts, radius: (stub_verts, stub_faces))

    obj = obj3d.Ztrace3D.__new__(obj3d.Ztrace3D)
    obj.name = "zt"
    obj.series = series
    obj.color = (0, 1, 0)
    obj.alpha = 0.0
    obj.tform = None
    obj.extremes = []

    mesh_data = obj.generate3D()
    assert mesh_data["alpha"] == 0.0, (
        f"Ztrace3D.generate3D() replaced alpha=0.0 with {mesh_data['alpha']!r}; "
        f"the 'is not None' guard was likely reverted to a bare truthiness check"
    )


# ---------------------------------------------------------------------------
# VPlotter.modifySelected — scale cube branch
# ---------------------------------------------------------------------------

def test_modify_selected_scale_cube_applies_zero_alpha(monkeypatch):
    """The scale-cube branch of modifySelected must call setAlpha(0.0).

    Reverting ``if alpha is not None:`` to ``if alpha:`` makes this fail.
    """
    alpha_calls = []

    cube = types.SimpleNamespace(
        type="scale_cube",
        getSideLength=lambda: 1.0,
        color=(1, 1, 1),
        alpha=0.5,
        msh=types.SimpleNamespace(
            lw=lambda *a: 1,  # called as lw() to read and lw(val) to set
            scale=lambda ratio: None,
        ),
        setColor=lambda c: None,
        setAlpha=lambda alpha, series: alpha_calls.append(alpha),
    )
    stub = types.SimpleNamespace(
        selected=[cube],
        series=None,
        saveState=lambda: None,
        updateSelected=lambda: None,
        render=lambda: None,
    )

    def fake_dialog(parent, structure, title):
        # simulate user confirming with opacity=0.0 and no size/color/lw change
        side_len = structure[0][1][1]
        color = structure[1][1][1]
        lw = structure[3][1][1]
        return (side_len, color, 0.0, lw), True

    monkeypatch.setattr(cp, "QuickDialog", types.SimpleNamespace(get=fake_dialog))

    cp.VPlotter.modifySelected(stub)

    assert alpha_calls == [0.0], (
        f"modifySelected (scale-cube branch) ignored alpha=0.0; calls={alpha_calls!r}; "
        f"the 'is not None' guard was likely reverted to a bare truthiness check"
    )


# ---------------------------------------------------------------------------
# VPlotter.modifySelected — mixed branch (non-scale-cube objects)
# ---------------------------------------------------------------------------

def test_modify_selected_mixed_applies_zero_alpha(monkeypatch):
    """The mixed branch of modifySelected must call setAlpha(0.0).

    Reverting ``if alpha is not None:`` to ``if alpha:`` makes this fail.
    """
    alpha_calls = []

    mesh_obj = types.SimpleNamespace(
        type="object",
        color=(1, 0, 0),
        alpha=0.5,
        setColor=lambda c: None,
        setAlpha=lambda alpha, series: alpha_calls.append(alpha),
    )
    stub = types.SimpleNamespace(
        selected=[mesh_obj],
        series=None,
        saveState=lambda: None,
        updateSelected=lambda: None,
        render=lambda: None,
    )

    def fake_dialog(parent, structure, title):
        color = structure[0][1][1]
        return (color, 0.0), True

    monkeypatch.setattr(cp, "QuickDialog", types.SimpleNamespace(get=fake_dialog))

    cp.VPlotter.modifySelected(stub)

    assert alpha_calls == [0.0], (
        f"modifySelected (mixed branch) ignored alpha=0.0; calls={alpha_calls!r}; "
        f"the 'is not None' guard was likely reverted to a bare truthiness check"
    )
