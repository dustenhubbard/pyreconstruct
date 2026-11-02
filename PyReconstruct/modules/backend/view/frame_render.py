"""Render a framed part of a section, fresh, at an output size.

A screenshot of the field holds only the screen's pixels, so a figure made
from one is soft when it is sized up. This draws the frame again at the output
size instead: the image is read for that size, and every width the field draws
in screen pixels (trace pens, the selection highlight, z-traces, flags and the
scale bar) is multiplied by the output factor, so a 3x render looks like the
screen, only sharper.
"""
from dataclasses import dataclass

from PySide6.QtGui import QFontMetrics, QImage, QPainter

from PyReconstruct.modules.datatypes import Series, Section
from PyReconstruct.modules.datatypes.default_settings import clampScaleBarThickness, pinnedLengthFor

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
    label_size : int = 12,
    tick_label_size : int = 10,
    *,
    show_all_traces=False,
    focus_on=False,
    roi_box=None,
    respect_overlay_visibility=True,
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
            label_size, tick_label_size (int): capture-only bar font sizes
            show_all_traces, focus_on, roi_box: the field's trace visibility
            respect_overlay_visibility (bool): apply the field's flag and
                z-trace visibility preferences and Focus-mode suppression
                in addition to the layer choices
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
        layer.respect_overlay_visibility = respect_overlay_visibility
        view = layer.generateView(
            out_dim,
            list(window),
            hide_image=not layers.image,
            show_all_traces=show_all_traces,
            focus_on=focus_on,
            roi_box=roi_box,
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
            label_size,
            tick_label_size,
        )
        painter.end()
    return image


def scaleBarGeometry(series, scale, frame_dim, length=None, label_size=12,
                     tick_label_size=10):
    """The bar's real length, subdivisions and screen size, without a widget."""
    from PyReconstruct.modules.gui.palette.scale_bar import (
        barLayout, labelText, niceLength, outlinedFont, pinnedLength,
        pinnedSubdivisions,
    )

    room = int(series.getOption("scale_bar_width") / 100 * frame_dim[0])
    pinned = pinnedLengthFor(
        series.getOption("scale_bar_mode"),
        series.getOption("scale_bar_length_um"),
    )
    if length or pinned:
        real_len, pix_len = pinnedLength(length or pinned, scale,
                                        frame_dim[0] if length else room)
        subdivs = pinnedSubdivisions(real_len)
    else:
        real_len, subdivs = niceLength(room * scale)
        pix_len = int(real_len / scale)
    text = series.getOption("show_scale_bar_text")
    label_w = (QFontMetrics(outlinedFont(label_size)).horizontalAdvance(labelText(real_len))
               if text else 0)
    height = barLayout(
        clampScaleBarThickness(series.getOption("scale_bar_thickness")), text,
        series.getOption("show_scale_bar_ticks"), label_size, tick_label_size,
    )[2]
    return real_len, subdivs, (max(pix_len, label_w + 2 if text else 0), height)


def paintScaleBar(painter, series, scale, frame_dim, factor, pos=None, length=None,
                  label_size=12, tick_label_size=10):
    """Draw the field's scale bar into a frame, `factor` times its screen size.

    Uses the same painter function as the field's bar, with capture-only
    label sizes. No widget is constructed or changed.

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
    from PyReconstruct.modules.gui.palette.scale_bar import paintScaleBar as paintBar

    real_len, subdivs, size = scaleBarGeometry(
        series, scale, frame_dim, length, label_size, tick_label_size,
    )
    if pos is None:
        pos = (BAR_MARGIN[0], frame_dim[1] - size[1] - BAR_MARGIN[1])
    painter.save()
    painter.translate(pos[0] * factor, pos[1] * factor)
    paintBar(
        painter, real_len, subdivs, scale,
        clampScaleBarThickness(series.getOption("scale_bar_thickness")),
        series.getOption("show_scale_bar_text"),
        series.getOption("show_scale_bar_ticks"),
        factor, label_size, tick_label_size,
    )
    painter.restore()
