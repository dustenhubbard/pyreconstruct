"""The 3D scene makes no X11 call when Qt runs as a native Wayland client.

VTK's Qt widget hands its native window id to an X11 render window on Linux.
Under a native Wayland session that id is a Wayland handle, so the first render
resized a window the X server did not know (BadWindow on X_ConfigureWindow) and
Xlib's default error handler ended PyReconstruct. On Wayland the scene draws
through a QOpenGLWidget with VTK's generic render window, which never opens a
window or speaks X11, and copies each VTK frame into the widget.

Each case runs in a fresh interpreter: the widget's base class is chosen when
the module first loads, from the Qt platform name, so the probe reports
"wayland" before importing it. The drawing case needs an OpenGL context from
Qt. Qt's offscreen platform has none, so that case uses the platform's own
window system (macOS, or Linux with a display) and skips where there is none.
The Wayland compositor itself is not reached here.
"""
import json
import os
import subprocess
import sys

import pytest

PROBE = r"""
import json, sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

mode = sys.argv[1]
app = QApplication([])
if mode == "draw":
    # a platform with no screen (a sandbox that hides the display) has no
    # surface to make a context on, and asking for one ends the process
    if not QGuiApplication.screens():
        print(json.dumps({"no_screen": QGuiApplication.platformName()}))
        sys.exit(0)
    ctx, surface = QOpenGLContext(), QOffscreenSurface()
    surface.create()
    if not (ctx.create() and ctx.makeCurrent(surface)):
        print(json.dumps({"no_gl": QGuiApplication.platformName()}))
        sys.exit(0)
    ctx.doneCurrent()
if mode != "other":
    QGuiApplication.platformName = staticmethod(lambda: "wayland")

from PyReconstruct.modules.gui.popup import custom_plotter as cp

got = {
    "gl_scene": cp.GL_SCENE,
    "opengl_widget": issubclass(cp.CustomPlotter, QOpenGLWidget),
}
if cp.GL_SCENE:
    # the native VTK widget cannot be built offscreen; this one can
    widget = cp.GLSceneWidget()
    rw = widget.GetRenderWindow()
    got["render_window"] = rw.GetClassName()
    got["native"] = widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
if mode == "draw":
    from vtkmodules.vtkFiltersSources import vtkSphereSource
    from vtkmodules.vtkRenderingCore import (
        vtkActor, vtkPolyDataMapper, vtkRenderer
    )
    renderer = vtkRenderer()
    renderer.SetBackground(0, 0, 1)
    rw.AddRenderer(renderer)
    sphere = vtkSphereSource()
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(sphere.GetOutputPort())
    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(1, 0, 0)
    actor.GetProperty().LightingOff()
    renderer.AddActor(actor)
    renders = []
    rw.AddObserver("EndEvent", lambda obj, event: renders.append(event))
    widget.resize(120, 100)
    widget.Initialize()  # what vedo does before its first render
    frame = widget.grabFramebuffer()  # initializeGL, then paintGL
    got["renders"] = len(renders)
    got["center"] = frame.pixelColor(frame.width() // 2, frame.height() // 2).getRgb()
    got["corner"] = frame.pixelColor(1, 1).getRgb()
print(json.dumps(got))
"""


def probe(mode):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    if mode == "draw":
        # Qt's offscreen platform makes no OpenGL context
        if sys.platform != "linux" or env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
            env.pop("QT_QPA_PLATFORM")
    r = subprocess.run([sys.executable, "-c", PROBE, mode],
                       check=True, capture_output=True, text=True, env=env)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_wayland_scene_draws_through_qt_without_an_x11_window():
    got = probe("structure")
    assert got["gl_scene"] is True
    assert got["opengl_widget"] is True
    # the generic window takes the GL context Qt made and ignores window ids,
    # so nothing can resize an X11 window
    assert got["render_window"] == "vtkGenericOpenGLRenderWindow"
    # VTK's constructor asks for winId(); a native child here would be a
    # Wayland subsurface handle again
    assert got["native"] is False


def test_wayland_scene_shows_the_frame_vtk_drew():
    got = probe("draw")
    if "no_screen" in got:
        pytest.skip(f"Qt reports no screen on {got['no_screen']}")
    if "no_gl" in got:
        pytest.skip(f"Qt makes no OpenGL context on {got['no_gl']}")
    assert got["render_window"] == "vtkGenericOpenGLRenderWindow"
    assert got["renders"] >= 1
    # the red sphere in the middle and the blue background at the edge.
    # grabFramebuffer returns an opaque image, so this does not see alpha.
    assert got["center"] == [255, 0, 0, 255]
    assert got["corner"] == [0, 0, 255, 255]


def test_other_platforms_keep_the_native_vtk_widget():
    got = probe("other")
    assert got["gl_scene"] is False
    assert got["opengl_widget"] is False
