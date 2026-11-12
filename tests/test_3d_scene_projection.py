"""Projection controls use the real scene menu and VTK camera."""

from types import SimpleNamespace

import pytest

from conftest import menu_action

pytestmark = pytest.mark.gui


@pytest.fixture
def scene(qtbot, monkeypatch):
    from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    # Qt's offscreen platform has no native window for VTK. Keep the real
    # widget, plotter, renderer and camera, but disable drawing to OpenGL.
    init = cp.QVTKRenderWindowInteractor.__init__

    def headless_init(self, parent):
        window = vtkGenericOpenGLRenderWindow()
        window.SetReadyForRendering(False)
        init(self, parent, rw=window)

    monkeypatch.setattr(cp.QVTKRenderWindowInteractor, "__init__", headless_init)
    window = SimpleNamespace(
        screen_info={"dpi": 96},
        series=SimpleNamespace(getOption=lambda key: False, jser_fp="test.jser"),
    )
    viewer = cp.CustomPlotter(window)
    qtbot.addWidget(viewer.container)
    yield viewer


def test_new_scene_is_orthographic(scene):
    assert scene.plt.camera.GetParallelProjection() == 1
    action = menu_action(scene.menubar_widget, "Scene > View > Orthographic")
    assert action.isCheckable()
    assert action.isChecked()


def test_menu_switches_projection_without_moving_the_camera(scene):
    camera = scene.plt.camera
    camera.SetPosition(0, 0, 10)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(0, 1, 0)
    camera.SetParallelScale(2)
    action = menu_action(scene.menubar_widget, "Scene > View > Orthographic")

    def projected_x(z):
        matrix = camera.GetCompositeProjectionTransformMatrix(1, -1, 1)
        x, _, _, w = matrix.MultiplyPoint((1, 0, z, 1))
        return x / w

    assert projected_x(0) == pytest.approx(0.5)
    assert projected_x(-10) == pytest.approx(0.5)
    action.trigger()
    assert not action.isChecked()
    assert camera.GetParallelProjection() == 0
    assert projected_x(0) == pytest.approx(2 * projected_x(-10))
    action.trigger()
    assert action.isChecked()
    assert camera.GetParallelProjection() == 1
    assert projected_x(0) == pytest.approx(projected_x(-10))
    assert camera.GetPosition() == (0, 0, 10)
    assert camera.GetFocalPoint() == (0, 0, 0)
    assert camera.GetViewUp() == (0, 1, 0)


@pytest.mark.parametrize("orthographic", [True, False])
def test_focus_and_axis_views_keep_the_projection(scene, orthographic):
    import vedo

    scene.plt.add(vedo.Cube())
    projection = menu_action(scene.menubar_widget, "Scene > View > Orthographic")
    if not orthographic:
        projection.trigger()
    for path in (
        "Focus on all", "Set view to axis > x-axis",
        "Set view to axis > y-axis", "Set view to axis > z-axis",
    ):
        menu_action(scene.menubar_widget, f"Scene > View > {path}").trigger()
        assert scene.plt.camera.GetParallelProjection() == orthographic
        assert projection.isChecked() == orthographic


@pytest.mark.parametrize("orthographic", [True, False])
def test_saved_scene_restores_projection_and_zoom(
    scene, orthographic, tmp_path, monkeypatch,
):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    projection = menu_action(scene.menubar_widget, "Scene > View > Orthographic")
    if not orthographic:
        projection.trigger()
    camera = scene.plt.camera
    camera.SetParallelScale(3.25)
    path = tmp_path / "scene.json"
    monkeypatch.setattr(cp.FileDialog, "get", lambda *args: str(path))
    scene.saveScene()
    projection.trigger()
    camera.SetParallelScale(99)

    scene.loadScene(str(path), add_only=True)
    assert camera.GetParallelProjection() == (not orthographic)
    assert projection.isChecked() == (not orthographic)
    assert camera.GetParallelScale() == 99

    scene.loadScene(str(path))

    assert camera.GetParallelProjection() == orthographic
    assert projection.isChecked() == orthographic
    assert camera.GetParallelScale() == pytest.approx(3.25)


def test_legacy_scene_keeps_its_perspective_view(scene, tmp_path):
    import json

    path = tmp_path / "legacy-scene.json"
    path.write_text(json.dumps({
        "scene_objects": {"series_fps": {}, "scale_cubes": []},
        "camera": {
            "position": [0, 0, 10], "focal_point": [0, 0, 0],
            "view_up": [0, 1, 0], "distance": 10,
        },
    }))

    scene.loadScene(str(path))

    assert scene.plt.camera.GetParallelProjection() == 0
    assert not menu_action(
        scene.menubar_widget, "Scene > View > Orthographic",
    ).isChecked()
    assert scene.plt.camera.GetPosition() == (0, 0, 10)
