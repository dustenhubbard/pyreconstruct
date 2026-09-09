"""The 3D scene keeps its render window in step with the display it is on.

Qt sends a resizeEvent only when the logical size changes. Dragging the scene
between a 2x and a 1x display keeps the logical size, so VTK's render window
stayed at the old screen's pixel size while mouse positions were scaled by
the new ratio: hover named the wrong object, double-click went nowhere,
right-click selected nothing (the "1x vs 2x display" reports, September
2026). CustomPlotter now checks the size before each paint and re-runs the
resize when it drifted. Exercised against a duck-typed stub, the way the
other plotter tests do; the real widget needs a GL context.
"""
import inspect
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyReconstruct.modules.gui.popup.custom_plotter import CustomPlotter


class Stub:
    def __init__(self, ratio, width, height, render_size):
        self._ratio = ratio
        self._width = width
        self._height = height
        self._RenderWindow = SimpleNamespace(GetSize=lambda: render_size)
        self.resizes = 0

    def _getPixelRatio(self):
        return self._ratio

    def width(self):
        return self._width

    def height(self):
        return self._height

    def resizeEvent(self, ev):
        self.resizes += 1


def sync(stub):
    return CustomPlotter._syncRenderWindowSize(stub)


def test_a_matching_render_window_is_left_alone():
    stub = Stub(2.0, 400, 300, (800, 600))
    assert sync(stub) is False
    assert stub.resizes == 0


def test_moving_from_a_2x_to_a_1x_display_resizes():
    # render window still holds the 2x pixel size; the widget now reads 1x
    stub = Stub(1.0, 400, 300, (800, 600))
    assert sync(stub) is True
    assert stub.resizes == 1


def test_moving_from_a_1x_to_a_2x_display_resizes():
    stub = Stub(2.0, 400, 300, (400, 300))
    assert sync(stub) is True
    assert stub.resizes == 1


def test_fractional_scaling_rounds_the_way_resize_event_does():
    # VTK's resizeEvent sizes by int(round(scale * dim)); the check must agree
    # or every paint would trigger a resize on a 125% Windows display
    stub = Stub(1.25, 401, 301, (501, 376))
    assert sync(stub) is False


def test_the_check_runs_before_every_paint():
    assert "paintEvent" in CustomPlotter.__dict__
    assert "_syncRenderWindowSize" in inspect.getsource(CustomPlotter.paintEvent)
