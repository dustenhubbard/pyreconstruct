"""The scale cube's edge length, read from a real vedo mesh.

Edit attributes on a selected scale cube crashed with
``AttributeError: 'Cube' object has no attribute 'GetScale'`` (reported from
1.23.0-beta-4 on Windows, September 2026). Since vedo 2024 a Mesh no longer
subclasses vtkActor, so the actor-level GetScale() is gone; the edge length
now comes from the mesh's own LinearTransform. The sibling test in
test_modify_selected_scale_cubes.py stubs getSideLength out, which is how
this slipped past it: these tests drive the real vedo object.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import vedo

from PyReconstruct.modules.gui.popup.custom_plotter import SceneObject


def make_scene_object(type_str="scale_cube"):
    # createScaleCube builds the cube with side 1 and scales it from there
    msh = vedo.Cube(side=1, c=(150, 150, 150))
    series = SimpleNamespace(jser_fp="/tmp/current.jser")
    return SceneObject(msh, series, "Scale Cube", type_str, (150, 150, 150), 1)


def test_a_fresh_cube_has_an_edge_of_one():
    assert make_scene_object().getSideLength() == pytest.approx(1.0)


def test_edge_length_follows_a_uniform_scale():
    cube = make_scene_object()
    cube.msh.scale(2.5)
    assert cube.getSideLength() == pytest.approx(2.5)


def test_rotating_and_moving_the_cube_leaves_its_edge_alone():
    cube = make_scene_object()
    cube.msh.scale(2.5)
    cube.msh.rotate_z(30)
    cube.msh.rotate_x(20)
    cube.translate(3, 4, 5)
    assert cube.getSideLength() == pytest.approx(2.5)


def test_the_edit_dialog_rescale_lands_on_the_typed_length():
    """modifySelected scales by new/old; twice in a row must not compound."""
    cube = make_scene_object()
    for wanted in (0.5, 3.0):
        cube.msh.scale(wanted / cube.getSideLength())
        assert cube.getSideLength() == pytest.approx(wanted)


def test_only_scale_cubes_report_an_edge_length():
    assert make_scene_object(type_str="object").getSideLength() is None
