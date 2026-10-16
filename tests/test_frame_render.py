"""A frame renders a part of a section fresh at an output size.

At 1x a frame matches the field pixel for pixel. At 3x every width the field
draws in screen pixels is three times as wide: the trace outline, and the
scale bar with its label. Leaving the selection out drops its highlight and
keeps each trace's fill as the field shows it. A render leaves the series
window and the field as they were.
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
from PyReconstruct.modules.datatypes import Flag, Series, Trace, Ztrace

# a frame around the star on section 0 of shapes1
MOCK_FRAME = (480, 320)
MOCK_WINDOW = [1.2241075625, 0.9433716583333334, 2.140304375, 1.4268695833333331]


@pytest.fixture
def series_jser(shapes1_jser):
    """A series with images."""
    return shapes1_jser


@pytest.fixture
def shapes1(qapp, shapes1_jser):
    """The series with images, its options in memory."""
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
    """Show every layer the field draws: a selected trace, a selected flag
    beside a plain one, and the z-traces with one point selected."""
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


@pytest.mark.parametrize("style", ["standard", "outline", "glow"])
def test_1x_render_matches_the_field_pixmap(main_window, local_series_settings, style):
    series = local_series_settings(main_window)
    series.setOption("selected_trace_style", style)
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


def test_star_frame_renders_at_1x_and_3x(shapes1):
    section = shapes1.loadSection(0)
    window = shapes1.window
    for k in (1, 3):
        out = (MOCK_FRAME[0] * k, MOCK_FRAME[1] * k)
        frame = renderFrame(shapes1, section, MOCK_WINDOW, MOCK_FRAME, out)
        assert (frame.width(), frame.height()) == out
        # the image fills the frame: the window lies inside it
        assert lit(frame).mean() > 0.9
    assert shapes1.window is window


def square(section, fill_mode):
    """Leave the section one red square, from (2, 2) to (8, 8)."""
    for trace in list(section.tracesAsList()):
        section.removeTrace(trace, log_event=False)
    section.selected_traces = []
    section.flags = []
    section.selected_flags = []
    trace = Trace("square", (255, 0, 0))
    trace.points = [(2, 2), (8, 2), (8, 8), (2, 8)]
    trace.fill_mode = fill_mode
    section.addTrace(trace, log_event=False)
    return trace


@pytest.mark.parametrize("fill_when", ["selected", "unselected"])
def test_selection_left_out_keeps_the_fill(shapes1, fill_when):
    section = shapes1.loadSection(0)
    trace = square(section, ("solid", fill_when))
    section.selected_traces = [trace]
    centers = []
    for selection in (True, False):
        frame = renderFrame(
            shapes1, section, [0, 0, 10, 10], (100, 100), (100, 100),
            FrameLayers(image=False, selection=selection, scale_bar=False),
        )
        centers.append(int(pixels(frame)[50, 50]))
    filled = 0xFFFF0000 if fill_when == "selected" else 0xFF000000
    assert centers == [filled, filled]


def test_selection_left_out_drops_the_flag_box(shapes1):
    section = shapes1.loadSection(0)
    square(section, ("none", "none"))
    flag = Flag("f", 5, 5, section.n, (255, 0, 0))
    section.flags = [flag]
    shapes1.setOption("show_flags", "all")
    layers = FrameLayers(image=False, flags=True, scale_bar=False)
    frames = []
    for selected in ([flag], []):
        section.selected_flags = selected
        frames.append(pixels(renderFrame(
            shapes1, section, [0, 0, 10, 10], (300, 300), (300, 300), layers)))
    assert np.array_equal(*frames)


@pytest.mark.parametrize("overlay", ["flags", "ztraces"])
def test_overlay_draws_without_the_traces(shapes1, overlay):
    section = shapes1.loadSection(0)
    for trace in list(section.tracesAsList()):
        section.removeTrace(trace, log_event=False)
    section.selected_traces = []
    section.selected_flags = []
    section.selected_ztraces = []
    section.flags = [Flag("f", 5, 5, section.n, (255, 0, 0))]
    shapes1.ztraces = {"z": Ztrace("z", (255, 0, 0), [(3, 5, section.n), (7, 5, section.n)])}
    shapes1.setOption("show_flags", "all")
    shapes1.setOption("show_ztraces", True)
    frames = []
    for traces in (True, False):
        layers = FrameLayers(
            image=False, traces=traces, scale_bar=False,
            flags=overlay == "flags", ztraces=overlay == "ztraces",
        )
        frames.append(pixels(renderFrame(
            shapes1, section, [0, 0, 10, 10], (100, 100), (100, 100), layers)))
    # with no traces on the section, the overlay alone is drawn either way
    assert (frames[0] != 0xFF000000).any()
    assert np.array_equal(*frames)
