"""The frame renderer draws a framed part of a section fresh at an output size.

At 1x it must match the field's own pixmap pixel for pixel, so a figure at
screen size is what the screen shows. At 3x every width the field draws in
screen pixels is three times as wide: the trace outline, and the scale bar
with its label. A render leaves the series window and the field as they were.

The field tests open a real `MainWindow` on a copy of the shipped checker
series ``shapes1.jser``, which carries images, through the suite's
`main_window` fixture with `series_jser` pointed at that copy.
"""
import numpy as np
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtGui import QImage

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.backend.view.frame_render import (
    FrameLayers,
    renderFrame,
)
from PyReconstruct.modules.datatypes import Flag, Series

# the frame and window of the design mockup, on section 0 of shapes1
MOCK_FRAME = (480, 320)
MOCK_WINDOW = [1.2241075625, 0.9433716583333334, 2.140304375, 1.4268695833333331]


@pytest.fixture
def series_jser(shapes1_jser):
    """`main_window` opens this: the shapes1 copy, which has images."""
    return shapes1_jser


@pytest.fixture
def shapes1(qapp, shapes1_jser):
    """shapes1 opened without a window, its options in memory."""
    series = Series.openJser(str(shapes1_jser))
    series.setSettingsStore(DictSettingsStore())
    series.src_dir = str(shapes1_jser.parent)
    try:
        yield series
    finally:
        series.setSettingsStore(None)
        series.close()


def pixels(image):
    """An image as an (h, w) array of 32-bit ARGB values."""
    image = image.convertToFormat(QImage.Format_ARGB32)
    w, h = image.width(), image.height()
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    return buf.view(np.uint32).reshape(h, image.bytesPerLine() // 4)[:, :w].copy()


def lit(image):
    """Where an image is anything but opaque black."""
    return pixels(image) != 0xFF000000


def unfilled(section):
    """Leave every trace an outline, so its ink is its pen."""
    for trace in section.tracesAsList():
        trace.fill_mode = ("none", "none")


def decorate(field):
    """Put something on screen for every layer the field draws: a selected
    trace, a selected flag beside a plain one, and the series' z-traces with
    one point selected, then redraw."""
    section = field.section
    x, y, w, h = field.series.window
    for i, dx in enumerate((0.4, 0.6)):
        flag = Flag(f"f{i}", x + w * dx, y + h / 2, section.n, (255, 0, 0))
        section.flags.append(flag)
    section.selected_flags = section.flags[-1:]
    section.selected_traces = section.tracesAsList()[:1]
    for ztrace in field.series.ztraces.values():
        for i, point in enumerate(ztrace.points):
            if point[2] == section.n:
                section.selected_ztraces = [(ztrace, i)]
                break
    field.generateView()


def test_1x_render_matches_the_field_pixmap(main_window, local_series_settings):
    local_series_settings(main_window)
    field = main_window.field
    field.generateView()
    assert field.section_layer.image_found
    decorate(field)

    frame = renderFrame(
        main_window.series,
        field.section,
        list(main_window.series.window),
        field.pixmap_dim,
        field.pixmap_dim,
        FrameLayers(selection=True, ztraces=True, flags=True, scale_bar=False),
    )

    assert (frame.width(), frame.height()) == tuple(field.pixmap_dim)
    assert np.array_equal(pixels(frame), pixels(field.field_pixmap.toImage()))


def test_render_leaves_the_window_and_the_field_alone(main_window, local_series_settings):
    series = local_series_settings(main_window)
    field = main_window.field
    field.generateView()
    window = series.window
    before = list(window)
    screen_mag = series.screen_mag
    view = pixels(field.field_pixmap.toImage())
    layer_dim = field.section_layer.pixmap_dim
    in_view = list(field.section_layer.traces_in_view)

    w, h = field.pixmap_dim
    renderFrame(series, field.section, [before[0] + 1, before[1], before[2] / 2,
                before[3] / 2], (w // 2, h // 2), (w * 3 // 2, h * 3 // 2))

    assert series.window is window and series.window == before
    assert series.screen_mag == screen_mag
    assert np.array_equal(pixels(field.field_pixmap.toImage()), view)
    assert field.section_layer.pixmap_dim == layer_dim
    assert field.section_layer.traces_in_view == in_view
    # and the field draws the same view again from its own state
    field.generateView()
    assert np.array_equal(pixels(field.field_pixmap.toImage()), view)


def test_3x_outline_is_three_times_as_wide(shapes1):
    section = shapes1.loadSection(0)
    unfilled(section)
    traces_only = FrameLayers(image=False, scale_bar=False)
    one = renderFrame(shapes1, section, MOCK_WINDOW, MOCK_FRAME, MOCK_FRAME,
                      traces_only)
    three = renderFrame(shapes1, section, MOCK_WINDOW, MOCK_FRAME,
                        (MOCK_FRAME[0] * 3, MOCK_FRAME[1] * 3), traces_only)

    # an outline's ink is its length times its width; at 3x the length is
    # three times as long, so a pen three times as wide gives nine times
    # the ink, where a pen left at 1 px gives three
    ratio = lit(three).sum() / lit(one).sum()
    assert 7.5 < ratio < 10.5, ratio


def test_3x_scale_bar_and_label_are_three_times_as_large(shapes1):
    section = shapes1.loadSection(0)
    bar_only = FrameLayers(image=False, traces=False)
    bar_pos = (20, 200)
    one = lit(renderFrame(shapes1, section, MOCK_WINDOW, MOCK_FRAME, MOCK_FRAME,
                          bar_only, bar_pos=bar_pos))
    three = lit(renderFrame(shapes1, section, MOCK_WINDOW, MOCK_FRAME,
                            (MOCK_FRAME[0] * 3, MOCK_FRAME[1] * 3), bar_only,
                            bar_pos=bar_pos))

    def extent(mask, top=0, bottom=None):
        """The ink's height and width between two rows."""
        rows = np.flatnonzero(mask[top:bottom].any(axis=1))
        cols = np.flatnonzero(mask[top:bottom].any(axis=0))
        return rows[-1] - rows[0] + 1, cols[-1] - cols[0] + 1

    from PyReconstruct.modules.gui.palette.scale_bar import LABEL_ROOM

    # the label sits in the band above the bar
    label_1 = extent(one, bar_pos[1], bar_pos[1] + LABEL_ROOM)
    label_3 = extent(three, bar_pos[1] * 3, (bar_pos[1] + LABEL_ROOM) * 3)
    for size_1, size_3 in zip(label_1, label_3):
        assert 2.6 < size_3 / size_1 < 3.4, (label_1, label_3)
    # and the whole bar with its ticks and tick labels
    whole_1, whole_3 = extent(one), extent(three)
    for size_1, size_3 in zip(whole_1, whole_3):
        assert 2.8 < size_3 / size_1 < 3.2, (whole_1, whole_3)


def test_mockup_frame_renders_at_1x_and_3x(shapes1):
    section = shapes1.loadSection(0)
    window = shapes1.window
    for k in (1, 3):
        out = (MOCK_FRAME[0] * k, MOCK_FRAME[1] * k)
        frame = renderFrame(shapes1, section, MOCK_WINDOW, MOCK_FRAME, out)
        assert (frame.width(), frame.height()) == out
        # the image fills the frame: the window lies inside it
        assert lit(frame).mean() > 0.9
    assert shapes1.window is window
