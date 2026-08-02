"""Regression tests for opacity ``0.0`` being read as "no value chosen".

Full transparency is a legitimate opacity. Two call sites already treated it
that way: ``FieldWidgetObject.edit3D`` validates against an inclusive ``(0,1)``
range and guards its write with ``is not None``, and ``VPlotter.incAlpha`` (the
``[`` shortcut) clamps to exactly ``0`` and persists it through
``SceneObject.setAlpha``. Four others tested the value for truth and so dropped
a stored ``0.0``:

* ``VPlotter.modifySelected``, in both of its branches (scale cubes, and the
  mixed-object branch), which read the opacity field back from ``QuickDialog``
  and applied it under ``if alpha:``.
* ``Surface.generate3D``, ``Spheres.generate3D`` and ``Contours.generate3D``,
  which fell back to the series' stored ``3D_opacity`` under
  ``self.alpha if self.alpha else ...``.
* ``Ztrace3D.generate3D``, which fell back to a literal ``1`` under the same
  pattern.

The reachable divergence, which ``test_saved_zero_survives_a_reload`` drives
end to end: press ``[`` until an object in the 3D scene is fully transparent
(``incAlpha`` clamps to ``0`` and writes ``3D_opacity = 0.0``), the scene's
export dict then carries ``alpha = 0.0``; change that object's opacity from the
object list to something else; reload the scene. ``placeInScene`` feeds the
saved ``0.0`` back through ``generateVolumes``, whose ``generate3D`` call
discarded it and re-read the object-list value, so the object came back at the
object-list opacity rather than the saved one.

The mesh tests go through ``generateVolumes`` against the checked-in fixture
series rather than constructing a mesher directly, because that is the function
``placeInScene`` actually calls and because the three object mesher classes do
not share a constructor path (``Contours.generate3D`` builds its vertices
inline and never calls ``generateTrimesh``).

``QuickDialog``'s float field returns ``None`` for a blank entry and a real
``float`` otherwise, so ``is not None`` is the exact distinction the dialog
already draws. Its range check is ``lower <= n <= upper``, which is why the
``(0,1)`` on ``edit3D`` admits ``0``.
"""
import os
import shutil
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.backend.volume.generate_volumes import generateVolumes
from PyReconstruct.modules.gui.popup import custom_plotter as cp

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets", "checker", "files"
)


def _open_series(tmp_path, name="shapes1.jser"):
    src = os.path.join(FIXTURE_DIR, name)
    if not os.path.exists(src):
        pytest.skip(f"fixture {name} not found")
    fp = str(tmp_path / name)
    shutil.copyfile(src, fp)
    from PyReconstruct.modules.datatypes.series import Series

    return Series.openJser(fp)


# ---------------------------------------------------------------- the meshers

@pytest.mark.parametrize("mode", ["surface", "spheres", "contours"])
def test_saved_zero_survives_a_reload(tmp_path, mode):
    """The end-to-end divergence, one mesher class per 3D mode.

    ``alpha=0.0`` is what the saved scene carries; ``3D_opacity=0.5`` is what
    the object list holds. The saved value must win, as it does for any other
    saved value.
    """
    series = _open_series(tmp_path)
    try:
        name = sorted(series.data["objects"].keys())[0]
        series.setAttr(name, "3D_mode", mode)
        series.setAttr(name, "3D_opacity", 0.5)

        objs = [{"name": name, "color": None, "alpha": 0.0, "tform": None}]
        mesh_data_list, _ = generateVolumes(series, objs, [])

        assert len(mesh_data_list) == 1, mode
        assert mesh_data_list[0]["name"] == name
        assert mesh_data_list[0]["alpha"] == 0.0, (
            f"{mode}: saved 0.0 was replaced by the object-list value"
        )
    finally:
        series.close()


@pytest.mark.parametrize("mode", ["surface", "spheres", "contours"])
def test_absent_alpha_still_falls_back_to_the_stored_value(tmp_path, mode):
    """The fallback itself must survive: ``None`` still means "not supplied"."""
    series = _open_series(tmp_path)
    try:
        name = sorted(series.data["objects"].keys())[0]
        series.setAttr(name, "3D_mode", mode)
        series.setAttr(name, "3D_opacity", 0.5)

        objs = [{"name": name, "color": None, "alpha": None, "tform": None}]
        mesh_data_list, _ = generateVolumes(series, objs, [])

        assert mesh_data_list[0]["alpha"] == 0.5, mode
    finally:
        series.close()


def test_ztrace_saved_zero_survives_a_reload(tmp_path):
    """``Ztrace3D.generate3D`` fell back to a literal ``1``, so a saved ``0.0``
    came back fully opaque rather than fully transparent."""
    series = _open_series(tmp_path)
    try:
        names = sorted(series.ztraces.keys())
        assert names, "fixture had no ztraces"
        name = names[0]

        ztraces = [{"name": name, "color": None, "alpha": 0.0, "tform": None}]
        mesh_data_list, _ = generateVolumes(series, [], ztraces)

        assert len(mesh_data_list) == 1
        assert mesh_data_list[0]["type"] == "ztrace"
        assert mesh_data_list[0]["alpha"] == 0.0

        ztraces = [{"name": name, "color": None, "alpha": None, "tform": None}]
        mesh_data_list, _ = generateVolumes(series, [], ztraces)
        assert mesh_data_list[0]["alpha"] == 1
    finally:
        series.close()


# ----------------------------------------------------------- modifySelected

def _patch_dialog(monkeypatch, response):
    """Stand in for the modal dialog and hand back a confirmed response."""
    monkeypatch.setattr(
        cp,
        "QuickDialog",
        types.SimpleNamespace(get=lambda parent, structure, *a, **k: (response, True)),
    )


class _SceneObjectStub:
    """The slice of SceneObject that modifySelected touches."""

    def __init__(self, type_):
        self.type = type_
        self.color = (1, 2, 3)
        self.alpha = 0.0
        self.alpha_calls = []
        self.msh = types.SimpleNamespace(lw=lambda: 2, scale=lambda f: None)

    def getSideLength(self):
        return 1.0

    def setColor(self, new_color):
        self.color = new_color

    def setAlpha(self, new_alpha, series=None):
        self.alpha = new_alpha
        self.alpha_calls.append(new_alpha)


def _plotter(selected):
    return types.SimpleNamespace(
        selected=selected,
        series=object(),
        saveState=lambda *a, **k: None,
        updateSelected=lambda *a, **k: None,
        render=lambda *a, **k: None,
    )


def test_modify_selected_scale_cube_applies_zero(monkeypatch):
    """Scale cube branch: response is (side_len, color, alpha, lw)."""
    cube = _SceneObjectStub("scale_cube")
    _patch_dialog(monkeypatch, [None, None, 0.0, None])

    cp.VPlotter.modifySelected(_plotter([cube]))

    assert cube.alpha_calls == [0.0]


def test_modify_selected_mixed_applies_zero(monkeypatch):
    """Mixed-object branch: response is (color, alpha)."""
    obj = _SceneObjectStub("object")
    _patch_dialog(monkeypatch, [None, 0.0])

    cp.VPlotter.modifySelected(_plotter([obj]))

    assert obj.alpha_calls == [0.0]


@pytest.mark.parametrize(
    "type_, response",
    [("scale_cube", [None, None, None, None]), ("object", [None, None])],
)
def test_modify_selected_blank_opacity_is_still_ignored(monkeypatch, type_, response):
    """A blank field comes back as ``None`` and must remain a no-op, or every
    multi-selection edit would stamp the first object's opacity onto the rest."""
    obj = _SceneObjectStub(type_)
    _patch_dialog(monkeypatch, response)

    cp.VPlotter.modifySelected(_plotter([obj]))

    assert obj.alpha_calls == []


# ------------------------------------------------- the two already-correct ones

def test_inc_alpha_clamps_to_zero_and_persists():
    """``[`` at the bottom of the range. This already worked; pin it, since the
    saved ``0.0`` the reload tests start from is the value it writes."""
    stored = {}

    class _Series:
        jser_fp = "/tmp/stub.jser"

        def setAttr(self, name, attr_name, value, ztrace=False):
            stored[(name, attr_name)] = value

    series = _Series()
    obj = cp.SceneObject(
        types.SimpleNamespace(alpha=lambda v: None, metadata={}),
        series,
        "obj",
        "object",
        (1, 2, 3),
        0.05,
    )
    plt = _plotter([obj])
    plt.series = series

    cp.VPlotter.incAlpha(plt, -0.1)

    assert obj.alpha == 0
    assert stored[("obj", "3D_opacity")] == 0


def test_edit3d_opacity_range_admits_zero():
    """The inclusive ``(0,1)`` on the opacity field is what lets a user type
    ``0`` into ``Edit 3D settings...`` at all."""
    from PyReconstruct.modules.gui.dialog.quick_dialog import InputField

    field = InputField(
        "float", types.SimpleNamespace(text=lambda: "0"), [0, 1], required=False
    )
    value, valid = field.getResponse()
    assert valid and value == 0.0
