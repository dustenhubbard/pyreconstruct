import math
from collections import defaultdict
from itertools import chain, starmap

import numpy as np

from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, QPoint, QLine, QByteArray, QDataStream, QIODevice
from PySide6.QtGui import (
    QPixmap,
    QPen,
    QColor,
    QPainter,
    QBrush,
    QFont,
    QPolygon
)
from PyReconstruct.modules.datatypes import (
    Series, 
    Section,
    Trace,
    Ztrace,
    Transform,
    Flag
)
from PyReconstruct.modules.calc import (
    pointInPoly,
    pixmapPointToField,
    fieldPointToPixmap,
    getDistanceFromTrace,
    getExterior
)
from PyReconstruct.modules.calc.nesting import islandCuts
from PyReconstruct.modules.datatypes.default_settings import MAX_SELECTION_GLOW_OPACITY
from PyReconstruct.modules.gui.utils import drawOutlinedText

# The looks a selected trace can have, set by the selected_trace_style option.
# "standard" is drawn inline in _drawTrace: the trace's 1 px line, then the same
# path again, 8 px wide at 40% opacity, under any fill. The others replace the
# line with pens drawn after the fill, widest first, so a fill never covers them.
# Each pen is (color, width in pixels, opacity): color None is the trace's own
# color, and opacity None is the selection_glow_opacity option.
SELECTED_TRACE_PENS = {
    "outline": (
        ((0, 0, 0), 6, 1),
        ((255, 255, 255), 4, 1),
        (None, 2, 1),
    ),
    "glow": (
        (None, 5, None),
        (None, 2, 1),
    ),
}
SELECTED_TRACE_STYLES = ("standard", *SELECTED_TRACE_PENS)


def selectionGlowOpacity(percent) -> float:
    """Return the painter opacity for a selection_glow_opacity value.

    The value is a percent; above MAX_SELECTION_GLOW_OPACITY it draws as that
    maximum.
    """
    return min(max(percent, 0), MAX_SELECTION_GLOW_OPACITY) / 100


class TraceLayer():

    def __init__(self, section : Section, series : Series):
        """Create a trace layer.
        
            Params:
                section (Section): the section object for the layer
                series (Series): the series object
        """
        self.section = section
        self.series = series
        self.traces_in_view = []
        self.zsegments_in_view = []
        self.show_all_traces = False
        # membership sets recomputed each generateTraceLayer call
        self._selected_set = set()
        self._temp_hide_set = set()
        self._group_hide_set = set()
        self._group_hidden_names = set()
        # the field's ROI box (center x, center y, width, height in field
        # units), or None. View-only: set by every draw, never saved
        self.roi_box = None
        # True while every trace is hidden (H): nothing is drawn, so
        # nothing can be picked
        self.traces_hidden = False
        # the (style, glow percent) the options dialog shows while it is open;
        # None draws from the stored options
        self.selected_style_preview = None
        self._selected_pens = None
        # the untransformed bounds of every trace on one section, valid for
        # one columnar store generation (see _storeBounds and _cullMask)
        self._raw_bounds = None
        self._raw_bounds_key = None
        # an offscreen render at k times the screen size sets these: every
        # width drawn in screen pixels is multiplied by pen_scale, and the
        # traces, selection, z-traces and flags can each be left out
        self.pen_scale = 1
        self.draw_traces = True
        self.draw_selection = True
        self.draw_ztraces = True
        self.draw_flags = True

    def penWidth(self, width):
        """A pen width in screen pixels, times pen_scale."""
        return width * self.pen_scale
    
    def pointToPix(self, pt : tuple, apply_tform=True, tform : Transform = None, qpoint=False) -> tuple:
        """Return the pixel point corresponding to a field point.
        
            Params:
                pt (tuple): the trace to convert
                apply_tform (bool): true if section transform should be applied to the point
                tform (Transform): the transform to apply (otherwise, uses series data)
                qpoints (bool): True if points should be converted QPoint
            Returns:
                (tuple): the pixel point
        """
        x, y = tuple(pt)
        if apply_tform:
            if tform is None:
                tform = self.section.tform
            x, y = tform.map(x, y)
        x, y = fieldPointToPixmap(x, y, self.series.window, self.pixmap_dim, self.section.mag)

        if qpoint:
            new_pt = QPoint(x, y)
        else:
            new_pt = (x, y)
        
        return new_pt
    
    def traceToPixArray(self, trace : Trace, tform : Transform = None) -> np.ndarray:
        """Return the pixel points corresponding to a trace as an integer array.

        Vectorized equivalent of calling pointToPix on every point: the section
        transform is applied with mapPointsArray and the window-to-pixmap
        conversion as numpy affine ops, instead of per-point Python calls.

            Params:
                trace (Trace): the trace to convert
                tform (Transform): the transform to apply (otherwise, uses series data)
            Returns:
                (np.ndarray): (N, 2) array of integer pixel points
        """
        if not trace.points:
            return np.empty((0, 2), dtype=np.int64)

        if tform is None:
            tform = self.section.tform
        return self._fieldToPixArray(tform.mapPointsArray(trace.points))

    def _fieldToPixArray(self, pts : np.ndarray) -> np.ndarray:
        """Convert (N, 2) field points to integer pixel points.

        The same math as fieldPointToPixmap, round-half-even included. Every
        step works point by point, so one call on many traces' points gives
        each point the same pixel as a call on its own trace.

            Params:
                pts (np.ndarray): (N, 2) field points, transform applied
            Returns:
                (np.ndarray): (N, 2) array of integer pixel points
        """
        window_x, window_y, window_w, window_h = tuple(self.series.window)
        pixmap_w, pixmap_h = tuple(self.pixmap_dim)
        mag = self.section.mag
        x_scaling = pixmap_w / (window_w / mag)
        y_scaling = pixmap_h / (window_h / mag)
        px = (pts[:, 0] - window_x) / mag * x_scaling
        py = pixmap_h - (pts[:, 1] - window_y) / mag * y_scaling

        return np.column_stack((
            np.rint(px).astype(np.int64),
            np.rint(py).astype(np.int64)
        ))

    def traceToPix(self, trace : Trace, tform : Transform = None, qpoints=False) -> list:
        """Return the set of pixel points corresponding to a trace.

            Params:
                trace (Trace): the trace to convert
                tform (Transform): the transform to apply
                qpoints (bool): True if points should be converted QPoint
            Returns:
                (list): list of pixel points
        """
        pix_pts = self.traceToPixArray(trace, tform)
        if qpoints:
            return qPointList(pix_pts)
        else:
            # tolist() converts the whole array to Python ints in one C call;
            # iterating the array instead unboxes a numpy scalar per coordinate
            # and pays an int() call on each (~5x slower for the same result)
            return list(map(tuple, pix_pts.tolist()))
    
    def getTrace(self, pix_x : float, pix_y : float) -> Trace:
        """"Return the closest trace to the given field coordinates.
        
            Params:
                pix_x (float): the x-coord of the point in the widget
                pix_y (float): the y-coord of the point in the widget
            Returns:
                (Trace): the closest trace
        """
        field_x, field_y = pixmapPointToField(pix_x, pix_y, self.pixmap_dim, self.series.window, self.section.mag)

        # calculate radius based on window size (5% of window size)
        window_size = max(self.series.window[2:])
        radius = window_size * (0.05)

        # findClosest searches the whole section when it gets no traces. With
        # the ROI box on, no traces in view means none inside the box, and
        # the traces outside it must not be picked. With every trace hidden,
        # none is on the screen to pick.
        if self.traces_in_view or self.roi_box is not None or self.traces_hidden:
            traces_in_view = self.traces_in_view
        else:
            traces_in_view = None

        closest, closest_type = self.section.findClosest(
            field_x,
            field_y,
            radius=radius,
            traces_in_view=traces_in_view,
            include_hidden=self.show_all_traces
        )

        # the list is from the last draw; the box may have moved since
        if closest_type == "trace" and not self.insideRoiBox(closest):
            return None, None

        return closest, closest_type
    
    def getTraces(self, pix_poly : list) -> list[Trace]:
        """"Select all traces that are completely in a polygon
        
            Params:
                pix_poly (list): a list of screen points
            Returns:
                (list[Trace]): the list of traces within the polygon
        """
        if len(pix_poly) < 3:
            return
        
        # convert the pix_poly into its exterior
        pix_poly = getExterior(pix_poly)

        traces_in_poly = []
        # check if ANY point is inside the polygon for inc
        # check if EVERY point is inside the polygon for exc
        # (settings-backed option: read once, not per trace)
        inc = self.series.getOption("pointer")[1] == "inc"
        # only check traces in the view
        for trace in self.traces_in_view:
            pix_points = self.traceToPix(trace)
            inside_poly = True
            for point in pix_points:
                if inc and pointInPoly(*point, pix_poly):
                    traces_in_poly.append(trace)
                    break
                elif not inc and not pointInPoly(*point, pix_poly):
                    inside_poly = False
                    break
            if not inc and inside_poly:
                traces_in_poly.append(trace)
        
        # ztraces_in_poly = []
        # if self.series.options["show_ztraces"]:
        #     for ztrace in self.series.ztraces.values():
        #         # check if point is inside polygon
        #         for i, (x, y, snum) in enumerate(ztrace.points):
        #             if snum == self.section.n:
        #                 pix_point = self.pointToPix((x, y))
        #                 if pointInPoly(*pix_point, pix_poly):
        #                     ztraces_in_poly.append((ztrace, i))

        return traces_in_poly

    def getZsegment(self, pix_x : float, pix_y : float, radius = 10):
        """Find the closest ztrace segment (does not have a point on the section).
        
            Params:
                pix_x (float): the screen pixel x
                pix_y (float): the screen pixel y
                radius (float): the max radius for finding a ztrace segment
        """
        if not self.zsegments_in_view:
            return None
        
        closest_dist = None
        closest_ztrace = None
        for line, ztrace in self.zsegments_in_view:
            d = getDistanceFromTrace(
                pix_x,
                pix_y,
                line,
                factor=1,
                absolute=True
            )
            if (d < radius and 
                (closest_dist is None or d < closest_dist)
            ):
                closest_dist = d
                closest_ztrace = ztrace
        
        return closest_ztrace
    
    def getCopiedTraces(self, cut=False) -> list:
        """Called when user presses Ctrl+C or Ctrl+X.
        
            Params:
                cut (bool): whether or not to delete the traces
            Returns:
                (list): the traces to copy
        """
        copied_traces = []
        for trace in self.section.selected_traces:
            trace = trace.copy()
            tform = self.section.tform
            trace.points = [tform.map(*p) for p in trace.points]
            copied_traces.append(trace)
        
        if cut:
            # pass an explicit trace list so deleting the cut traces does not
            # also remove the section's selected flags as a side effect
            self.section.deleteTraces(self.section.selected_traces.copy())
        
        return copied_traces
    
    def _drawTrace(self, painter : QPainter, trace : Trace, tform : Transform, fill_opacity : float, color=None, qpoints=None) -> bool:
        """Draw a trace on the current trace layer and return bool indicating if trace is in the current view.

            Params:
                painter (QPainter): the painter (shared across the per-trace loop)
                trace (Trace): the trace to draw on the pixmap
                tform (Transform): the section transform (hoisted out of the loop)
                fill_opacity (float): the fill_opacity option (hoisted out of the loop)
                color (bool): optionally force a color
                qpoints (QPolygon): the trace in pixmap coordinates, already
                    known to reach the screen (see _screenPolygons); None
                    converts and tests the trace here
            Returns:
                (bool) if the trace is within the current field window view
        """
        if qpoints is None:
            ## Convert to screen coordinates (vectorized; no QPoints yet)
            pix_pts = self.traceToPixArray(trace, tform)

            if not len(pix_pts):
                print("EMPTY TRACE DETECTED")
                return

            ## Get bounds and cull before allocating any QPoint/QPolygon
            xmin, ymin = pix_pts.min(axis=0)
            xmax, ymax = pix_pts.max(axis=0)
            trace_bounds = xmin, ymin, xmax, ymax
            screen_bounds = 0, 0, *self.pixmap_dim

            if not boundsOverlap(trace_bounds, screen_bounds):
                return False

            qpoints = qPointList(pix_pts)

        ## Get color
        draw_color = color if color else trace.color

        selected = trace in self._selected_set
        # the fill follows the selection whether or not it is highlighted
        highlighted = selected and self.draw_selection

        ## Set up painter (shared: reset state left over from the previous trace)
        painter.setOpacity(1)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(*draw_color), self.penWidth(1)))

        ## Draw trace (another selected style draws its own line after the fill)
        pens = self._selected_pens if highlighted else None
        if not pens:
            if trace.closed:
                painter.drawPolygon(qpoints)
            else:
                painter.drawPolyline(qpoints)

        ## Draw highlight
        if highlighted and not pens:

            painter.setPen(QPen(QColor(*draw_color), self.penWidth(8)))
            painter.setOpacity(0.4)

            if trace.closed:
                painter.drawPolygon(qpoints)
            else:
                painter.drawPolyline(qpoints)

        ## Determine if user requested fill
        if (
            (trace.closed) and
            (trace.fill_mode[0] != "none") and (
                (trace.fill_mode[1] == "always") or
                ((trace.fill_mode[1] == "selected") == selected)
            )
        ):

            fill = True

        elif trace.closed and color:  # in order words, color forced

            fill = True

        else:

            fill = False

        ## Fill in shape if requested
        if fill:

            painter.setPen(QPen(QColor(*draw_color), self.penWidth(1)))
            painter.setBrush(QBrush(QColor(*draw_color)))

            ## determine fill type
            if color:  # color forced:
                painter.setOpacity(0.25)

            elif trace.fill_mode[0] == "transparent":  # transparent fill
                painter.setOpacity(fill_opacity)

            elif trace.fill_mode[0] == "solid":  # solid
                painter.setOpacity(1)

            painter.drawPolygon(qpoints)

        ## Draw the selected style's pens last, so a fill never covers them
        if pens:
            self._drawSelectedPens(painter, qpoints, trace.closed, draw_color, pens)

        return True

    def _drawSelectedPens(self, painter : QPainter, qpoints, closed : bool, draw_color, pens):
        """Draw a selected trace with the pens of its selected_trace_style.

            Params:
                painter (QPainter): the painter
                qpoints: the trace in pixmap coordinates
                closed (bool): True to draw a polygon, False for a polyline
                draw_color: the color the trace line is drawn in
                pens: (color, width, opacity) tuples, widest first
        """
        painter.setBrush(Qt.NoBrush)
        draw = painter.drawPolygon if closed else painter.drawPolyline
        for color, width, opacity in pens:
            if not opacity:
                continue
            pen = QPen(QColor(*(color or draw_color)), self.penWidth(width))
            # round joins cost about twice the stroke time on long traces, so
            # corners keep the default bevel; round caps only on open ends
            if not closed:
                pen.setCapStyle(Qt.RoundCap)
            painter.setOpacity(opacity)
            painter.setPen(pen)
            draw(qpoints)

    def _selectedPens(self):
        """Return the pens for a selected trace, or None for the standard look.

        Reads the dialog's preview when there is one, else the stored options.
        An unknown style draws as standard.
        """
        if self.selected_style_preview is not None:
            style, percent = self.selected_style_preview
        else:
            style = self.series.getOption("selected_trace_style")
            percent = self.series.getOption("selection_glow_opacity")
        pens = SELECTED_TRACE_PENS.get(style)
        if pens is None:
            return None
        glow = selectionGlowOpacity(percent)
        return tuple(
            (color, width, glow if opacity is None else opacity)
            for color, width, opacity in pens
        )
    
    def _drawZtrace(self, trace_layer : QPixmap, ztrace : Ztrace):
        """Draw points on the current trace layer.
        
            Params:
                trace_layer (QPixmap): the pixmap to draw the point
                points (list): the list of points to draw
        """
        points, lines = ztrace.getSectionData(self.series, self.section)
        # convert to screen coordinates
        qpoints = []
        for pt in points:
            qpoints.append(self.pointToPix(
                pt,
                apply_tform=False,
                qpoint=True
            ))
        qlines = []
        for p1, p2 in lines:
            qp1 = self.pointToPix(
                p1[:2],
                apply_tform=False,
                qpoint=True
            )
            qp2 = self.pointToPix(
                p2[:2],
                apply_tform=False,
                qpoint=True
            )
            qlines.append(QLine(qp1, qp2))
        
        # set up painter
        painter = QPainter(trace_layer)
        painter.setPen(QPen(QColor(*ztrace.color), self.penWidth(6)))

        # draw points and lines
        painter.drawPoints(qpoints)
        painter.setPen(QPen(QColor(*ztrace.color), self.penWidth(1)))
        for line in qlines:
            p1 = line.p1()
            p2 = line.p2()
            p1_arrow = True
            p2_arrow = True
            if p1 in qpoints:
                p1_arrow = False
            if p2 in qpoints:
                p2_arrow = False
            drawArrow(
                painter,
                line,
                p1_arrow,
                p2_arrow,
                self.penWidth(5)
            )
            self.zsegments_in_view += [(
                ((p1.x(), p1.y()),
                (p2.x(), p2.y())),
                ztrace
            )]
        painter.end()

    def _drawZtraceHighlights(self, trace_layer : QPixmap, fill_opacity : float = None):
        """Draw highlighted points on the current trace layer.

            Params:
                trace_layer (QPixmap): the pixmap to draw the points
                fill_opacity (float): the fill_opacity option (read here if not provided)
        """
        if fill_opacity is None:
            fill_opacity = self.series.getOption("fill_opacity")
        points = []
        colors = []
        for ztrace, i in self.section.selected_ztraces:
            if ztrace not in self.section.temp_hide:
                points.append(ztrace.points[i][:2])
                colors.append(ztrace.color)

        # convert to screen coordinates
        qpoints = []
        for pt in points:
            qpoints.append(self.pointToPix(
                pt,
                qpoint=True
            ))
        
        # set up painter
        painter = QPainter(trace_layer)
        painter.setOpacity(fill_opacity)

        # draw points
        for qpoint, color in zip(qpoints, colors):
            painter.setPen(QPen(QColor(*color), self.penWidth(15)))
            painter.drawPoint(qpoint)
        painter.end()
    
    def _drawFlag(self, trace_layer : QPixmap, flag : Flag, flag_size : int = None):
        """Draw the flag on the field.

            Params:
                flag (Flag): the flag to draw on the field
                flag_size (int): the flag_size option (read here if not provided)
        """
        if flag_size is None:
            flag_size = self.series.getOption("flag_size")

        x, y = self.pointToPix((flag.x, flag.y))
        c = flag.color

        painter = QPainter(trace_layer)
        if self.pen_scale != 1:
            # the glyph, its outline and the highlight box all grow together
            painter.scale(self.pen_scale, self.pen_scale)
            x, y = x / self.pen_scale, y / self.pen_scale
        drawOutlinedText(
            painter,
            x,
            y,
            "⚑",
            c,
            None,
            flag_size
        )
        # draw highlight if necessary
        if self.draw_selection and flag in self.section.selected_flags:
            painter.setPen(QPen(QColor(*flag.color), 2))
            painter.setOpacity(1)
            painter.setBrush(Qt.transparent)
            lbl = QLabel(text="⚑")
            lbl.setFont(QFont("Courier New", flag_size, QFont.Bold))
            lbl.adjustSize()
            w, h = lbl.width(), lbl.height() * 3/4
            x += -w/2 - (h - w)
            y += 4 - 3*h/2
            h *= 2
            painter.drawRect(x, y, h, h)
        painter.end()

    def trace_visibile_p(self, trace) -> bool:
        """Determine visibility of a trace in the field."""

        temp_hide = trace in self._temp_hide_set
        show_all_traces = self.show_all_traces
        group_hide = (
            trace in self._group_hide_set
            or trace.name in self._group_hidden_names
        )
        trace_not_hidden = not trace.hidden

        if temp_hide:  # always hide when dragging
        
            show_trace = False

        elif show_all_traces:  # show all temporarily

            show_trace = True
                
        elif trace_not_hidden:  # trace unhidden, check group viz

            show_trace = True if not group_hide else False

        else:  # trace hidden

            show_trace = False

        return show_trace

    def insideRoiBox(self, trace : Trace, tform : Transform = None) -> bool:
        """Whether a trace is inside this layer's ROI box (see traceInRoiBox).

            Params:
                trace (Trace): the trace to test
                tform (Transform): the section transform (read here if not given)
            Returns:
                (bool): True if the trace is inside the box or the box is off
        """
        if tform is None:
            tform = self.section.tform
        return traceInRoiBox(trace, tform, self.roi_box)

    def _storeBounds(self, columns) -> tuple:
        """The bounds of every trace in the section's store, before any transform.

        Read in one pass from the store's float64 rows, so no trace's list of
        points is converted again. The section writes a trace's row whenever
        its points change and checks the row against the trace, and undo,
        redo and resync build every row again from the traces.

            Params:
                columns (SectionColumns): the section's store
            Returns:
                (tuple): {trace: index}, the point count at each index and an
                    (n + 1, 4) array of xmin, ymin, xmax, ymax at each index
                    (NaN for no points); the last index matches no trace
        """
        rows = self.section.traceRows()
        # a row that is gone gets no points, so no trace's count matches it
        empty = np.empty((0, 2))
        arrays = [
            columns.getCoordinates(row) if columns.isLive(row) else empty
            for row in rows.values()
        ]
        n = len(arrays)
        counts = np.full(n + 1, -1, dtype=np.int64)
        counts[:n] = np.fromiter(map(len, arrays), dtype=np.int64, count=n)
        bounds = np.full((n + 1, 4), np.nan)
        nonempty = np.flatnonzero(counts[:n] > 0)
        if len(nonempty):
            # each row's bounds, from where its points start in one array
            starts = (np.cumsum(counts[:n]) - counts[:n])[nonempty]
            pts = np.concatenate(arrays)
            bounds[nonempty, :2] = np.minimum.reduceat(pts, starts)
            bounds[nonempty, 2:] = np.maximum.reduceat(pts, starts)
        return dict(zip(rows, range(n))), counts, bounds

    def _cullMask(self, trace_list : list, tform : Transform):
        """Which traces could reach the screen, without transforming their points.

        Each trace's untransformed bounds box is mapped through the transform;
        the box of its four corners holds every mapped point under any affine
        transform (rotation and shear included), so a trace is dropped only
        when that box misses the window grown by two pixels on each side,
        wider than the half pixel the draw rounds by. A kept trace still meets
        the exact pixel test in _drawTrace, so what is drawn and
        traces_in_view do not change.

            Params:
                trace_list (list): the traces to test
                tform (Transform): the section transform
            Returns:
                (np.ndarray): one bool per trace, or None to keep every trace
        """
        # the store generation moves on every trace add, remove and edit,
        # undo and redo included; a Section built without a store has none,
        # and then nothing is culled
        columns = self.section._columns
        if columns is None or not trace_list:
            return None
        key = (self.section, columns.generation)
        if key != self._raw_bounds_key:
            self._raw_bounds = self._storeBounds(columns)
            self._raw_bounds_key = key

        window_x, window_y, window_w, window_h = tuple(self.series.window)
        pixmap_w, pixmap_h = tuple(self.pixmap_dim)
        if window_w <= 0 or window_h <= 0 or pixmap_w <= 0 or pixmap_h <= 0:
            return None
        margin_x = 2 * window_w / pixmap_w
        margin_y = 2 * window_h / pixmap_h

        index, counts, bounds = self._raw_bounds
        n = len(trace_list)
        at = np.fromiter((index.get(t, -1) for t in trace_list), dtype=np.int64, count=n)
        lengths = np.fromiter((len(t.points) for t in trace_list), dtype=np.int64, count=n)
        b = bounds[at]
        # a trace with no row, or with another point count than its row,
        # takes its bounds from its own points
        for i in np.flatnonzero(counts[at] != lengths):
            b[i] = pointBounds(trace_list[i].points)
        # the four corners of every box, one block of n per corner
        mapped = tform.mapPointsArray(np.concatenate((
            b[:, (0, 1)], b[:, (2, 1)], b[:, (0, 3)], b[:, (2, 3)]
        )))
        blocks = [mapped[k * n:(k + 1) * n] for k in range(4)]
        lo = np.minimum.reduce(blocks)
        hi = np.maximum.reduce(blocks)

        # a NaN box (no points) compares False everywhere and is kept
        return ~(
            (hi[:, 0] < window_x - margin_x) |
            (lo[:, 0] > window_x + window_w + margin_x) |
            (hi[:, 1] < window_y - margin_y) |
            (lo[:, 1] > window_y + window_h + margin_y)
        )

    def _screenPolygons(self, trace_list : list, tform : Transform):
        """Convert the traces to pixmap coordinates in one pass.

        The points of every trace are mapped and rounded together, each
        trace's pixel bounds meet the screen together, and the traces that
        reach it are read into QPolygons from one buffer, with no Python QPoint
        per point. Each polygon holds the points traceToPixArray gives its
        trace alone, so Qt draws the same pixels. The traces are still drawn
        one at a time, in order: one path for many traces would change which
        of two overlapping traces is on top and how transparent fills add up.

            Params:
                trace_list (list): the traces, in draw order
                tform (Transform): the section transform
            Returns:
                (list): per trace, its QPolygon, False when it misses the
                    screen, or None when it has no points (_drawTrace then
                    reports it); None for the whole list when a point is too
                    far out for Qt's 32-bit coordinates, and each trace then
                    goes through _drawTrace on its own
        """
        n = len(trace_list)
        result = [None] * n
        counts = np.fromiter((len(t.points) for t in trace_list), dtype=np.int64, count=n)
        nonempty = np.flatnonzero(counts)
        if not len(nonempty):
            return result

        pts = np.array(list(chain.from_iterable(t.points for t in trace_list)), dtype=float)
        pix = self._fieldToPixArray(tform.mapPointsArray(pts))
        int32 = np.iinfo(np.int32)
        if pix.min() < int32.min or pix.max() > int32.max:
            return None

        # each trace's pixel bounds, from where its points start in pix
        starts = (np.cumsum(counts) - counts)[nonempty]
        lo = np.minimum.reduceat(pix, starts)
        hi = np.maximum.reduceat(pix, starts)
        pixmap_w, pixmap_h = tuple(self.pixmap_dim)
        on_screen = ~(
            (hi[:, 0] < 0) | (lo[:, 0] > pixmap_w) |
            (hi[:, 1] < 0) | (lo[:, 1] > pixmap_h)
        )
        for i in nonempty[~on_screen]:
            result[i] = False
        drawn = nonempty[on_screen]
        if not len(drawn):
            return result

        # QDataStream's QPolygon: a big-endian 32-bit point count, then x and
        # y for each point
        drawn_counts = counts[drawn]
        heads = np.cumsum(1 + 2 * drawn_counts) - (1 + 2 * drawn_counts)
        buf = np.empty(len(drawn) + 2 * int(drawn_counts.sum()), dtype=">i4")
        is_point = np.ones(len(buf), dtype=bool)
        is_point[heads] = False
        buf[heads] = drawn_counts
        keep = np.zeros(n, dtype=bool)
        keep[drawn] = True
        buf[is_point] = pix[np.repeat(keep, counts)].reshape(-1)

        # the stream reads from data, which must live as long as it does
        data = QByteArray(buf.tobytes())
        stream = QDataStream(data, QIODevice.ReadOnly)
        for i in drawn:
            polygon = QPolygon()
            stream >> polygon
            result[i] = polygon
        if stream.status() != QDataStream.Status.Ok:
            return None
        return result

    def generateTraceLayer(
            self,
            pixmap_dim :
            tuple, window : list,
            show_all_traces=False,
            window_moved=True,
            focus_on=False,
            roi_box=None,
    ) -> QPixmap:
        """Draw traces on a transparent background.
        
            Params:
                pixmap_dim (tuple): the w and h of the pixmap to be output
                window (list): the view of the window (x, y, w, h)
                show_all_traces (bool): True if all traces are displayed regardless of hidden status
                focus_mode (bool): True if in focus mode
                window_moved (bool): True if the window has moved (upstream: same as generate_image)
                roi_box (tuple): the ROI box (center x, center y, width,
                    height in field units); only traces inside it are drawn
            Returns:
                (QPixmap): the pixmap with traces drawn in
        """
        self.series.window = window
        self.pixmap_dim = pixmap_dim
        self.show_all_traces = show_all_traces
        self.roi_box = roi_box
        pixmap_w, pixmap_h = tuple(pixmap_dim)
        trace_layer = QPixmap(pixmap_w, pixmap_h)
        trace_layer.fill(Qt.transparent)

        # precompute membership sets for the per-trace loop below; testing
        # against these is O(1) instead of an O(n) scan of the backing lists
        # (which is O(n^2) overall when many traces are selected or hidden)
        self._selected_set = set(self.section.selected_traces)
        self._temp_hide_set = set(self.section.temp_hide)
        self._group_hide_set = set(self.section.traces_group_hide)
        # by name too, for traces drawn or restored since the section loaded
        self._group_hidden_names = self.section.groupHiddenNames()

        # hoist settings-backed options out of the render loops: each getOption
        # for a non-series option constructs a QSettings and re-reads the
        # platform store (~60 us), and these values cannot change mid-render
        fill_opacity = self.series.getOption("fill_opacity")
        show_ztraces = self.series.getOption("show_ztraces")
        show_flags = self.series.getOption("show_flags")
        flag_size = self.series.getOption("flag_size")
        self._selected_pens = self._selectedPens()

        if window_moved:
            trace_list = self.section.tracesAsList()
            
        else:
            trace_list = self.traces_in_view.copy()

            # recently removed traces should be taken out of the view
            for trace in self.section.removed_traces:
                if trace in trace_list:
                    trace_list.remove(trace)

            # assume any recently added traces will be in view
            for trace in self.section.added_traces:
                trace_list.append(trace)

            # Guard against a stale cache. An attribute edit (color/name/tags/
            # fill via Section.editTraceAttributes) REPLACES a trace object with
            # a fresh copy - it does not mutate in place. The incremental cache
            # above only stays correct while section.added_traces /
            # removed_traces still describe that swap; a table refresh calls
            # section.clearTracking() and empties those lists, after which
            # trace_list can still hold the old, replaced object and would draw
            # its stale color. Detect any cached trace that is no longer a live
            # member of its contour and fall back to a full rebuild so current
            # attributes are drawn. Check each contour in one scan, stopping
            # once all cached traces are found. This avoids quadratic scans
            # when many visible traces share a name, without building a set of
            # every off-screen trace when only a few are visible.
            cached_traces_by_name = defaultdict(set)
            for trace in trace_list:
                cached_traces_by_name[trace.name].add(trace)
            for name, remaining in cached_traces_by_name.items():
                contour = self.section.contours.get(name)
                if contour is not None:
                    for trace in contour:
                        remaining.discard(trace)
                        if not remaining:
                            break
                if remaining:
                    trace_list = self.section.tracesAsList()
                    break

        self.traces_in_view = []

        # hoist the transform lookup and a single painter out of the per-trace
        # loop (previously one QPainter was constructed per visible trace)
        tform = self.section.tform
        painter = QPainter(trace_layer)

        # skip traces whose bounds miss the window before any per-point work
        in_window = self._cullMask(trace_list, tform)

        to_draw = []
        for i, trace in enumerate(trace_list if self.draw_traces else ()):

            if in_window is not None and not in_window[i]:
                continue

            if self.trace_visibile_p(trace) and self.insideRoiBox(trace, tform):

                to_draw.append(trace)

        # convert every trace to draw at once, then draw them in order
        polygons = self._screenPolygons(to_draw, tform) if to_draw else None
        if polygons is None:
            polygons = [None] * len(to_draw)

        for trace, qpoints in zip(to_draw, polygons):

            if qpoints is False:
                continue

            color = None  # default to assigned color

            if focus_on:

                if trace.name == focus_on:
                    color = (246, 249, 72)
                else:
                    color = (42, 255, 128)

            trace_in_view = self._drawTrace(
                painter,
                trace,
                tform,
                fill_opacity,
                color,
                qpoints=qpoints
            )

            if trace_in_view:

                self.traces_in_view.append(trace)

        painter.end()

        ## Draw ztraces
        self.zsegments_in_view = []

        if show_ztraces and self.draw_ztraces and not focus_on:

            for ztrace in self.series.ztraces.values():

                if ztrace not in self.section.temp_hide:

                    self._drawZtrace(trace_layer, ztrace)

            if self.draw_selection:
                self._drawZtraceHighlights(trace_layer, fill_opacity)

        ## Draw flags
        self.flags_in_view = []
        if show_flags != "none" and self.draw_flags and not focus_on:
            for flag in self.section.flags:
                if show_flags == "unresolved" and flag.resolved:
                    continue
                if flag not in self.section.temp_hide:
                    self._drawFlag(trace_layer, flag, flag_size)

        return trace_layer

    def _drawTraceLabel(self, arr : np.ndarray, trace : Trace, label : int, tform : Transform = None):
        """Draw labels of a trace on a trace layer.
        
            Params:
                arr (np.ndarray): the array to draw the labels on
                trace (Trace): the trace to draw
                label (int): the label to use
                tform (Transform): the transform to apply to the trace
        """
        # convert to screen coordinates
        points = self.traceToPix(trace, tform=tform)

        # get polygon coords
        from skimage.draw import polygon  # deferred: skimage is slow to import
        y_vals = [y for x, y in points]
        x_vals = [x for x, y in points]
        yy, xx = polygon(y_vals, x_vals, arr.shape)

        # insert in trace_layer
        arr[yy, xx] = label
    
    def _drawHoledLabel(self, arr : np.ndarray, traces : list[Trace], label : int, tform : Transform = None):
        """Draw one object's traces as a label, with its negative traces as holes.

        The positives fill and then the holes clear. A positive inside a hole
        (an island) is then filled back in, less the pixels of every negative
        that islandCuts says cuts it, the same way the 3D volume does: one
        that cuts or touches the island, or comes within a pixel's diagonal
        of it. The islands come from the traces before they are rounded to
        pixels, the same points the 3D volume uses, so rounding cannot make a
        trace an island or stop it being one. The mask covers only the box of
        the object's positive traces, not the whole array, so a large export
        stays fast.

            Params:
                arr (np.ndarray): the array to draw the label on
                traces (list[Trace]): the object's traces
                label (int): the label to use
                tform (Transform): the transform to apply to the traces
        """
        from skimage.draw import polygon  # deferred: skimage is slow to import

        map_tform = tform if tform is not None else self.section.tform
        positive, holes, pix = [], [], {}
        for trace in traces:
            if not trace.points:
                continue
            field = map_tform.mapPointsArray(trace.points)
            pix[id(field)] = self.traceToPixArray(trace, tform)
            (holes if trace.negative else positive).append(field)
        if not positive:
            return

        h, w = arr.shape
        pts = np.concatenate([pix[id(field)] for field in positive])
        x0, y0 = np.maximum(pts.min(axis=0), 0)
        x1 = min(int(pts[:, 0].max()) + 1, w)
        y1 = min(int(pts[:, 1].max()) + 1, h)
        if x0 >= x1 or y0 >= y1:
            return  # entirely outside the array

        mask = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        for fill, fields in ((True, positive), (False, holes)):
            for field in fields:
                pts = pix[id(field)]
                yy, xx = polygon(pts[:, 1] - y0, pts[:, 0] - x0, mask.shape)
                mask[yy, xx] = fill
        # a negative within a pixel's diagonal of an island can round onto
        # its edge pixels, so it counts as cutting it. islandCuts measures in
        # field units, and one pixel spans window_w / pixmap_w of them across
        # and window_h / pixmap_h down at any mag.
        window_w, window_h = tuple(self.series.window)[2:]
        pixmap_w, pixmap_h = tuple(self.pixmap_dim)
        reach = math.hypot(window_w / pixmap_w, window_h / pixmap_h)
        for island, cuts in islandCuts(positive, holes, reach):
            # fill the island back in over its own box within the mask
            pts = pix[id(island)]
            ix0, iy0 = np.maximum(pts.min(axis=0), (x0, y0))
            ix1 = min(int(pts[:, 0].max()) + 1, x1)
            iy1 = min(int(pts[:, 1].max()) + 1, y1)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            keep = np.zeros((iy1 - iy0, ix1 - ix0), dtype=bool)
            for field, fill in [(island, True)] + [(c, False) for c in cuts]:
                pts = pix[id(field)]
                yy, xx = polygon(pts[:, 1] - iy0, pts[:, 0] - ix0, keep.shape)
                keep[yy, xx] = fill
            mask[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] |= keep

        arr[y0:y1, x0:x1][mask] = label

    def generateLabelsArray(self, pixmap_dim : tuple, window : list, traces : list[Trace], tform : Transform = None, name_ids : dict = None):
        """Generate numpy array with traces drawn as labels.
        
            Params:
                pixmap_dim (tuple): the w and h of the 2D array
                window (list): the view of the window (x, y, w, h)
                traces (list[Traces]): the traces to include as labels
                tform (Transform): the unique transform to apply to the traces
                name_ids (dict): the label for each object name; if None, the
                    names in traces are sorted and numbered from 1
            Returns:
                (np.ndarray): the numpy array with traces drawn in as labels
                (dict): the label of each object name drawn
        """
        if name_ids is None:
            name_ids = labelIds(trace.name for trace in traces)
        # set up the trace layer
        self.series.window = window
        self.pixmap_dim = pixmap_dim
        pixmap_w, pixmap_h = tuple(pixmap_dim)
        arr = np.zeros(shape=(pixmap_h, pixmap_w), dtype=np.uint32)   

        id_lookup_table = {}

        ## Draw one object at a time. An object with no negative traces is
        ## drawn straight into the array. One with holes fills a mask over its
        ## own box and its negative traces cut the holes out of it, so a hole
        ## stays 0 and another object drawn inside the hole keeps its label.
        by_name = {}
        for trace in traces:
            by_name.setdefault(trace.name, []).append(trace)

        for name, name_traces in by_name.items():

            name_id = name_ids[name]

            if any(trace.negative for trace in name_traces):
                self._drawHoledLabel(arr, name_traces, name_id, tform)
            else:
                for trace in name_traces:
                    self._drawTraceLabel(arr, trace, name_id, tform)

            id_lookup_table.update({name: name_id})

        return arr, id_lookup_table


def qPointList(pix_pts : np.ndarray) -> list:
    """Convert an (N, 2) integer pixel array into a list of QPoint.

    Qt has to receive one QPoint object per point -- PySide6 exposes no bulk
    constructor for QPolygon (its only sequence overload is
    Sequence[QPoint]), so the allocations are unavoidable. What *is* avoidable
    is how the coordinates reach the constructor: iterating the array directly
    yields a 1-D array per row, unboxes a numpy scalar per coordinate and then
    pays an int() call on each. tolist() does the whole conversion in a single
    C call, and starmap applies QPoint without a Python-level loop body.

    This is a pure allocation-path change: the QPoint values are identical, so
    Qt rasterizes exactly the same pixels as before (verified in
    tests/test_trace_layer_qpoint_batching.py). Measured 2.5x faster on the
    listcomp itself and 2.0x on a full 500-trace / 60k-point paint pass, which
    is the rank-1 self-time entry of a dense-view profile.

        Params:
            pix_pts (np.ndarray): (N, 2) integer array of pixel points
        Returns:
            (list): list of QPoint
    """
    return list(starmap(QPoint, pix_pts.tolist()))


def labelIds(names) -> dict:
    """Give each distinct object name its own label, numbered from 1.

    0 is background, so no object gets it. Case and punctuation count, as they
    do everywhere else in the app: "Axon", "axon", and "axon_1" are three
    labels.

        Params:
            names (iterable): the object names
        Returns:
            (dict): name to label
    """
    return {name: i for i, name in enumerate(sorted(set(names)), start=1)}

def pointBounds(points) -> tuple:
    """The bounds of a list of points: xmin, ymin, xmax, ymax (NaN for none)."""
    if not points:
        return (np.nan,) * 4
    arr = np.asarray(points, dtype=float)
    return (*arr.min(axis=0), *arr.max(axis=0))


def traceInRoiBox(trace : Trace, tform : Transform, roi_box : tuple) -> bool:
    """Whether a trace is shown and can be picked under an ROI box.

    A trace is inside when its bounds in field coordinates (the section
    transform applied, as Trace.getBounds does) touch or overlap the box. It
    is then drawn whole, not clipped.

        Params:
            trace (Trace): the trace to test
            tform (Transform): the section transform
            roi_box (tuple): center x, center y, width, height, or None (off)
        Returns:
            (bool): True if the trace is inside the box or the box is off
    """
    if roi_box is None:
        return True
    if not trace.points:
        return False
    # vectorized: the same bounds as trace.getBounds(tform), without its
    # per-point Python loop, which every draw would pay for every trace
    pts = tform.mapPointsArray(trace.points)
    xmin, ymin = pts.min(axis=0)
    xmax, ymax = pts.max(axis=0)
    return boundsOverlap((xmin, ymin, xmax, ymax), roiBoxBounds(roi_box))


def roiBoxBounds(roi_box : tuple) -> tuple:
    """The bounds of an ROI box.

        Params:
            roi_box (tuple): center x, center y, width, height
        Returns:
            (tuple): xmin, ymin, xmax, ymax
    """
    cx, cy, w, h = roi_box
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def boundsOverlap(b1 : tuple, b2 : tuple):
    """Check if two bounding boxes intersect.
    
        Params:
            b1 (tuple): xmin, ymin, xmax, ymax
            b2 (tuple): xmin, ymin, xmax, ymax
        Returns:
            (bool): True if bounds have any overlap
    """

    return not (
        b1[2] < b2[0] or
        b1[0] > b2[2] or
        b1[3] < b2[1] or
        b1[1] > b2[3]
    )

def getTheta(line : QLine):
    """Get the angle a line makes with the x-axis.
    
        Params:
            line (QLine): the qline to get the angle for
    """
    p1 = line.p1()
    p2 = line.p2()
    v = p2 - p1
    if v.x() == 0:
        if v.y() < 0:
            theta = 3*math.pi/2
        elif v.y() > 0:
            theta = math.pi/2
        else:
            theta = None
    elif v.x() < 0:
        theta = math.pi + math.atan(v.y()/v.x())
    elif v.x() > 0:
        theta = math.atan(v.y()/v.x())
    
    return theta
    
def drawArrowHead(painter : QPainter, pt : QPoint, theta : float, l = 5):
    """Draw an arrowhead in a given direction.
    
        Params:
            painter (QPainter): the painter to draw the arrowhead
            pt (QPoint): the point on which the arrowhead is located
            theta (float): the angle (in radians) of the arrowhead (cc from x-axis)
            l (int): the length of the arrowhead
    """
    theta += math.pi
    t1 = theta + math.pi/6
    t2 = theta - math.pi/6
    p1 = QPoint(
        pt.x() + l * math.cos(t1),
        pt.y() + l * math.sin(t1)
    )
    p2 = pt
    p3 = QPoint(
        pt.x() + l * math.cos(t2),
        pt.y() + l * math.sin(t2)
    )
    l1 = QLine(p1, p2)
    l2 = QLine(p2, p3)
    painter.drawLine(l1)
    painter.drawLine(l2)

def drawArrow(painter : QPainter, line : QLine, p1_arrow=True, p2_arrow=True, l=5):
    """Draw an line with one or two arrowheads.
    
        Params:
            painter (QPainter): the painter used to draw the arrow
            line (QLine): the ztrace qline
            p1_arrow (bool): True if arrowhead on the first point
            p2_arrow (bool): True if arrowhead on the second point
            l (int): the length of each arrowhead
    """
    painter.drawLine(line)
    theta = getTheta(line)
    if theta is not None:
        if p1_arrow:
            drawArrowHead(painter, line.p1(), theta, l)
        if p2_arrow:
            drawArrowHead(painter, line.p2(), theta, l)

        
