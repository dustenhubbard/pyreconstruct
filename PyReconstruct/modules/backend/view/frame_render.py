"""Render a framed part of a section, fresh, at an output size.

A screenshot of the field holds only the screen's pixels, so a figure made
from one is soft when it is sized up. This draws the frame again at the output
size instead: the image is read for that size, and every width the field draws
in screen pixels (trace pens, the selection highlight, z-traces, flags and the
scale bar) is multiplied by the output factor, so a 3x render looks like the
screen, only sharper.
"""
import types
from dataclasses import dataclass

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter

from PyReconstruct.modules.datatypes import Series, Section
from PyReconstruct.modules.datatypes.default_settings import pinnedLengthFor

from .section_layer import SectionLayer

# where the bar sits when no position is given: its top-left corner, in screen
# pixels from the frame's bottom-left corner
BAR_MARGIN = (16, 12)


@dataclass
class FrameLayers:
    """What goes into a frame. Traces are drawn as the field shows them;
    the selection highlight, z-traces and flags are left out unless asked
    for. Palettes, corner text and the hover box are never drawn."""
    image: bool = True
    traces: bool = True
    selection: bool = False
    ztraces: bool = False
    flags: bool = False
    scale_bar: bool = True


def renderFrame(
    series : Series,
    section : Section,
    window : list,
    frame_dim : tuple,
    out_dim : tuple,
    layers : FrameLayers = None,
    bar_pos : tuple = None,
    bar_length : float = None,
) -> QImage:
    """Render the part of a section in `window` as an image `out_dim` in size.

    The series window and screen mag are put back afterward, and the render
    uses its own section layer, so the field is left as it was.

        Params:
            series (Series): the series
            section (Section): the section to draw
            window (list): the x, y, w, h of the frame, in field units
            frame_dim (tuple): the w, h of the frame on screen, in pixels
            out_dim (tuple): the w, h of the output, in pixels
            layers (FrameLayers): what to draw; the defaults if None
            bar_pos (tuple): the bar's top-left corner, in screen pixels from
                the frame's top-left; bottom-left by default
            bar_length (float): the bar's length in µm, as set from its
                right-click menu, or None for the stored sizing
        Returns:
            (QImage): the frame
    """
    if layers is None:
        layers = FrameLayers()
    factor = out_dim[0] / frame_dim[0]
    out_dim = (int(out_dim[0]), int(out_dim[1]))

    saved_window = series.window
    saved_mag = series.screen_mag
    try:
        layer = SectionLayer(section, series, load_image_layer=layers.image)
        layer.pen_scale = factor
        # flags and z-traces are drawn with the traces, so leaving the
        # traces out skips only their own loop
        layer.draw_traces = layers.traces
        layer.draw_selection = layers.selection
        layer.draw_ztraces = layers.ztraces
        layer.draw_flags = layers.flags
        view = layer.generateView(
            out_dim,
            list(window),
            hide_image=not layers.image,
        )
    finally:
        series.window = saved_window
        series.screen_mag = saved_mag

    image = view.toImage().convertToFormat(QImage.Format_ARGB32)
    if layers.scale_bar:
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        paintScaleBar(
            painter,
            series,
            window[2] / frame_dim[0],
            frame_dim,
            factor,
            bar_pos,
            bar_length,
        )
        painter.end()
    return image


def paintScaleBar(painter, series, scale, frame_dim, factor, pos=None, length=None):
    """Draw the field's scale bar into a frame, `factor` times its screen size.

    For now this renders the real `ScaleBar` widget through the painter,
    scaled, so the bar, its ticks and its outlined labels are drawn as
    vectors at the output size. Its label sizes are the on-screen ones.

        Params:
            painter (QPainter): a painter on the output image
            series (Series): the series, for the scale bar options
            scale (float): µm per screen pixel in the frame
            frame_dim (tuple): the w, h of the frame on screen, in pixels
            factor (float): output pixels per screen pixel
            pos (tuple): the bar's top-left, in screen pixels, or None for the
                bottom-left corner
            length (float): a length in µm to draw whatever the mode, or None
    """
    from PyReconstruct.modules.gui.palette.scale_bar import ScaleBar

    room = int(series.getOption("scale_bar_width") / 100 * frame_dim[0])
    pinned = pinnedLengthFor(
        series.getOption("scale_bar_mode"),
        series.getOption("scale_bar_length_um"),
    )
    manager = types.SimpleNamespace(series=series)
    bar = ScaleBar(
        None, manager, room, series.getOption("scale_bar_thickness"), scale,
        micron_length=pinned, max_pixel_length=room,
    )
    try:
        if length:
            bar.setOverride(length, frame_dim[0])
        if pos is None:
            pos = (BAR_MARGIN[0], frame_dim[1] - bar.height() - BAR_MARGIN[1])
        painter.save()
        painter.scale(factor, factor)
        bar.render(
            painter,
            QPoint(int(pos[0]), int(pos[1])),
            renderFlags=bar.RenderFlag.DrawChildren,
        )
        painter.restore()
    finally:
        bar.deleteLater()
