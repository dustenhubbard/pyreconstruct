"""The 3D scene makes no X11 call when Qt runs as a native Wayland client.

VTK's Qt widget hands its native window id to an X11 render window on Linux.
Under a native Wayland session that id is a Wayland handle, so the first render
resized a window the X server did not know (BadWindow on X_ConfigureWindow) and
Xlib's default error handler ended the whole app. On Wayland the scene now
draws through a QOpenGLWidget with VTK's generic render window, which never
opens a window or speaks X11.

Each case runs in a fresh interpreter: the widget's base class is chosen when
the module first loads, from the Qt platform name. The Wayland case reports
"wayland" from an offscreen app, which is enough to build the widget; drawing
it needs a real GL context, so that part was checked in a GNOME Wayland VM.
"""
import json
import os
import subprocess
import sys

PROBE = r"""
import json, sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

app = QApplication([])
if sys.argv[1] == "wayland":
    QGuiApplication.platformName = staticmethod(lambda: "wayland")

from PyReconstruct.modules.gui.popup import custom_plotter as cp

got = {
    "gl_scene": cp.GL_SCENE,
    "opengl_widget": issubclass(cp.CustomPlotter, QOpenGLWidget),
}
if cp.GL_SCENE:
    # the native VTK widget cannot be built offscreen; this one can
    widget = cp.GLSceneWidget()
    got["render_window"] = widget.GetRenderWindow().GetClassName()
    got["native"] = widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
print(json.dumps(got))
"""


def probe(platform):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", PROBE, platform],
                       check=True, capture_output=True, text=True, env=env)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_wayland_scene_draws_through_qt_without_an_x11_window():
    got = probe("wayland")
    assert got["gl_scene"] is True
    assert got["opengl_widget"] is True
    # the generic window takes the GL context Qt made and ignores window ids,
    # so nothing can resize an X11 window
    assert got["render_window"] == "vtkGenericOpenGLRenderWindow"
    # VTK's constructor asks for winId(); a native child here would be a
    # Wayland subsurface handle again
    assert got["native"] is False


def test_other_platforms_keep_the_native_vtk_widget():
    got = probe("offscreen")
    assert got["gl_scene"] is False
    assert got["opengl_widget"] is False
