from PySide6.QtWidgets import (
    QTextEdit,
)
from PySide6.QtCore import (
    QPoint, 
    QLine,
    QRect,
)
from PySide6.QtGui import (
    QPen,
    QColor,
    QPainter, 
    QFont,
    QFontMetrics,
)

from PyReconstruct.modules.backend.autoseg.palette import palette_color
from PyReconstruct.modules.backend.view import drawArrow
from PyReconstruct.modules.gui.utils import drawOutlinedText
from PyReconstruct.modules.datatypes import Flag, Trace

from .field_widget_5_mouse import (
    FieldWidgetMouse,
    POINTER, 
    KNIFE, 
    CLOSEDTRACE, 
    OPENTRACE, 
    STAMP, 
    HOST
)

def hoverDisplayPosition(field, size, prefer_right, scale_bar=None, others=(),
                         text=None, margin=3):
    """Where the hover box goes: its top-left point, in the field's parent's
    coordinates.

    The box goes in a bottom corner, the one opposite the tool palette first.
    If something is in that corner (the scale bar, the section buttons), the
    box is lifted until it sits just above it, so it stays near where it
    always was without covering the bar. The corner text (the selected trace
    and z-trace names) is on the same side at the top, and the box must not
    cover it either. If that side has no room, the other bottom corner is
    tried the same way, then the two top corners. If no candidate is clear
    of everything, the one that covers the least wins: the bar and the corner
    text count worst, then the number of palette widgets covered, and on a
    tie the unlifted bottom corners come first, where the box always went.
    The scale bar itself is never moved or hidden.

    Run when the box is placed, not on every paint.

        Params:
            field (QRect): the field
            size (QSize): the box's size
            prefer_right (bool): True for the bottom-right corner first
            scale_bar (QRect): the scale bar on show, or None
            others (list[QRect]): the other palette widgets on show
            text (QRect): the corner text, or None when there is none
            margin (int): the gap kept from the field's edge and from obstacles
        Returns:
            (QPoint): where to move the box
    """
    left = field.x() + margin
    right = field.x() + field.width() - size.width() - margin
    top = field.y() + margin
    bottom = field.y() + field.height() - size.height() - margin
    near, far = (right, left) if prefer_right else (left, right)
    worst = [r for r in (scale_bar, text) if r is not None]
    solid = ([scale_bar] if scale_bar is not None else []) + list(others)

    def lifted(x):
        """The bottom-corner spot at `x`, lifted above anything in the way,
        or None when it would leave the field."""
        y = bottom
        while True:
            box = QRect(QPoint(x, y), size)
            hits = [r for r in solid if box.intersects(r)]
            if not hits:
                return QPoint(x, y)
            y = min(r.top() for r in hits) - margin - size.height()
            if y < top:
                return None

    candidates = [lifted(near), lifted(far), QPoint(near, top), QPoint(far, top)]
    candidates = [c for c in candidates if c is not None]
    fallback = [QPoint(near, bottom), QPoint(far, bottom)]

    def cost(point):
        box = QRect(point, size)
        return (sum(box.intersects(r) for r in worst),
                sum(box.intersects(r) for r in others))

    for point in candidates:
        if cost(point) == (0, 0):
            return point
    # nothing is clear: the least covered, and on a tie the box's usual
    # bottom corners before anything else, as it was placed before
    pool = fallback + candidates
    return min(pool, key=lambda p: (cost(p), pool.index(p)))


class FieldWidgetPaint(FieldWidgetMouse):
    """
    PAINT FUNCTIONS
    ---------------
    These functions are related to the act of creating the view in the field.
    They include painting the appropriate border, painting any lines made by
    the user, and writing the text to the screen.
    """
    
    def drawBorder(self, painter : QPainter, color : tuple):
        """Draw a border around the field (called during paintEvent).
        
            Params:
                painter (QPainter): the painter for the field
                color(tuple): the color for the border
        """
        pen = QPen(QColor(*color), 8)
        if self.border_exists:
            pen.setDashPattern([2, 2, 2, 2])
        painter.setPen(pen)
        w, h = self.width(), self.height()
        points = [
            (0, 0),
            (0, h),
            (w, h),
            (w, 0)
        ]
        for i in range(len(points)):
            painter.drawLine(*points[i-1], *points[i])
        self.border_exists = True

    def paintBorder(self, field_painter : QPainter):
        """Paint the borders for the field."""
        # draw record dot on the screen if recording transforms
        if self.propagate_tform:
            field_painter.setBrush(QColor(255, 0, 0))
            field_painter.drawEllipse(20, 20, 40, 40)
        
        # add red border if trace layer is hidden
        self.border_exists = False
        if self.hide_trace_layer:
            self.drawBorder(field_painter, (255, 0, 0))
        # add green border if all traces are being shown
        elif self.show_all_traces:
            self.drawBorder(field_painter, (0, 255, 0))
        # add magenta border if image is hidden
        if self.hide_image:
            self.drawBorder(field_painter, (255, 0, 255))
        # add cyan border if sections are being blended
        if self.blend_sections:
            self.drawBorder(field_painter, (0, 255, 255))
    
    def paintWorkingTrace(self, field_painter : QPainter):
        """Paint the work trace on the field."""
        # draw the working trace on the screen
        if self.current_trace:
            pen = None
            # if drawing lasso
            if ((self.mouse_mode == POINTER and self.is_selecting_traces) or
                (self.mouse_mode == STAMP and self.is_drawing_rad)
            ):
                closed = True
                pen = QPen(QColor(255, 255, 255), 1)
                pen.setDashPattern([4, 4])
            # if drawing host line
            if self.mouse_mode == HOST:
                closed = False
                pen = QPen(QColor(255, 255, 255), 2)
            # if drawing knife
            elif self.mouse_mode == KNIFE:
                closed = False
                pen = QPen(QColor(255, 0, 0), 1)
            # if drawing trace
            elif (
                self.mouse_mode == OPENTRACE or
                self.mouse_mode == CLOSEDTRACE
            ):
                closed = (self.mouse_mode == CLOSEDTRACE and self.is_line_tracing or
                          self.mouse_mode == CLOSEDTRACE and self.closed_trace_shape != "trace")
                color = QColor(*self.tracing_trace.color)
                pen = QPen(color, 1)
            
            # draw current trace if exists
            if pen:
                if self.mouse_mode == HOST:
                    if len(self.current_trace) > 1:
                        line = QLine(*self.current_trace[0], *self.current_trace[1])
                        drawArrow(field_painter, line, False, True)
                else:
                    field_painter.setPen(pen)
                    if closed:
                        start = 0
                    else:
                        start = 1
                    for i in range(start, len(self.current_trace)):
                        field_painter.drawLine(*self.current_trace[i-1], *self.current_trace[i])
                    # draw dashed lines that connect to mouse pointer
                    if self.is_line_tracing:
                        pen.setDashPattern([2,5])
                        field_painter.setPen(pen)
                        field_painter.drawLine(*self.current_trace[-1], self.mouse_x, self.mouse_y)
                        if closed:
                            field_painter.drawLine(*self.current_trace[0], self.mouse_x, self.mouse_y)
            
        # unique method for drawing moving traces
        elif self.is_moving_trace:
            dx = self.mouse_x - self.clicked_x
            dy = self.mouse_y - self.clicked_y
            # redraw the traces with translatation
            for points, color, closed in self.moving_traces:
                field_painter.setPen(QPen(QColor(*color), 1))
                plot_points = [QPoint(x+dx, y+dy) for x,y in points]
                if closed:
                    field_painter.drawPolygon(plot_points)
                else:
                    field_painter.drawPolyline(plot_points)
            # redraw points with translation
            for (x, y), color in self.moving_points:
                field_painter.setPen(QPen(QColor(*color), 6))
                qpoint = QPoint(x+dx, y+dy)
                field_painter.drawPoint(qpoint)
            # redraw flag with translation
            # (settings-backed option: read once, not per flag)
            if self.moving_flags:
                flag_font = QFont("Courier New", self.series.getOption("flag_size"), QFont.Bold)
            for (x, y), color in self.moving_flags:
                field_painter.setPen(QPen(QColor(*color), 6))
                field_painter.setFont(flag_font)
                qpoint = QPoint(x+dx, y+dy)
                field_painter.drawText(qpoint, "⚑")

    def paintText(self, field_painter : QPainter):
        """Paint the corner text onto the field."""
        # place text on other side of mode palette (if applicable)
        if self.mainwindow.mouse_palette.mode_x > .5:
            x = 10
            right_justified = False
        else:
            x = self.width() - 10
            right_justified = True
        y = 0

        # the text in the corner opposite the palette (blended sections,
        # selected flags, traces and z-traces); its lines are kept so the
        # hover box can be placed clear of them (see cornerTextRect)
        corner_lines = []

        def drawCorner(y, text):
            corner_lines.append(text)
            drawOutlinedText(
                field_painter, x, y, text,
                (255, 255, 255), (0, 0, 0), st_size, right_justified,
            )
        
        # draw the name of the closest trace on the screen
        # draw the selected traces to the screen
        ct_size = 12
        st_size = 14
        closest = None
        closest_type = None
        close_hover_display = True  # assume the hover display will be closed
        if (
            not (self.lclick or self.rclick or self.mclick) and
            not self.is_gesturing
        ):
            # hoist settings-backed options out of this block: each getOption
            # for a non-series option constructs a QSettings and re-reads the
            # platform store, and paintText runs on every paint event
            display_closest = self.series.getOption("display_closest")
            left_handed = self.series.getOption("left_handed")

            # get closest trace
            closest, closest_type = self.section_layer.getTrace(self.mouse_x, self.mouse_y)

            # get zarr label
            if self.zarr_layer:
                label_id = self.zarr_layer.getID(self.mouse_x, self.mouse_y)
            else:
                label_id = None

            if (
                self.mouse_mode == POINTER or
                self.mouse_mode == HOST and not self.hosted_trace
            ):
                # prioritize showing label name
                if label_id is not None:
                    pos = self.mouse_x, self.mouse_y
                    c = palette_color(
                        label_id,
                        self.series.getOption("autoseg_color_palette") or None,
                        self.series.getOption("autoseg_color_seed") or 0,
                    )
                    drawOutlinedText(
                        field_painter,
                        *pos,
                        str(label_id),
                        c,
                        None,
                        ct_size
                    )
                # if no label found, check for closest traces
                else:
                    # check for ztrace segments
                    if not closest:
                        closest = self.section_layer.getZsegment(self.mouse_x, self.mouse_y)
                        closest_type = "ztrace_seg"
                    
                    # draw name of closest trace
                    if closest:
                        if closest_type == "trace":
                            name = closest.name
                            if closest.negative:
                                name += " (negative)"
                        elif closest_type == "ztrace_seg":
                            name = f"{closest.name} (ztrace)"
                        # ztrace tuple returned
                        elif closest_type == "ztrace_pt":
                            closest = closest[0]
                            name = f"{closest.name} (ztrace)"
                        # flag returned
                        elif closest_type == "flag":
                            name = closest.name
                        
                        if display_closest:
                            # set up the corner display for the attributes
                            if closest_type in ("trace", "flag"):
                                if closest != self.displayed_item:
                                    self.closeHoverDisplay()
                                    self.displayed_item = closest
                                    self.hover_display_timer.start(1000)
                                close_hover_display = False

                            # display the name of the item by the mouse
                            mouse_x, mouse_y = self.mouse_x, self.mouse_y
                            if left_handed: mouse_x += 10
                            c = closest.color
                            drawOutlinedText(
                                field_painter,
                                mouse_x, mouse_y,
                                name,
                                c,
                                None,
                                ct_size,
                                not left_handed
                            )
            elif self.mouse_mode == HOST and self.hosted_trace:
                # set up text position
                mouse_x, mouse_y = self.mouse_x, self.mouse_y
                if left_handed: mouse_x += 10
                # display the proposed host relationship by the mouse
                t = [
                    self.hosted_trace.name,
                    " hosted by ",
                    closest.name if closest_type == "trace" else "..."
                ]
                t_copy = t.copy()
                for i, text in enumerate(t_copy):
                    for j in range(len(t_copy)):
                        if j < i:
                            t[i] = " "*len(t_copy[j]) + t[i]
                        elif j > i:
                            t[i] += " "*len(t_copy[j])
                c = [
                    self.hosted_trace.color,
                    (255, 255, 255),
                    closest.color if closest_type == "trace" else (255, 255, 255)
                ]
                for text, color in zip(t, c):
                    drawOutlinedText(
                        field_painter,
                        mouse_x, mouse_y,
                        text,
                        color,
                        None,
                        ct_size,
                        not left_handed
                    )
            
            # get the names of the selected traces
            names = {}
            counter = 0
            height = self.height()
            for trace in self.section.selected_traces:
                # check for max number
                if counter * (st_size + 10) + 20 > height / 3:
                    names["..."] = 1
                    break
                if trace.name in names:
                    names[trace.name] += 1
                else:
                    names[trace.name] = 1
                    counter += 1
            self.selected_trace_names = names
            
            names = {}
            counter = 0
            for ztrace, i in self.section.selected_ztraces:
                # check for max number
                if counter * (st_size + 10) + 20 > height / 3:
                    names["..."] = 1
                    break
                if ztrace.name in names:
                    names[ztrace.name] += 1
                else:
                    names[ztrace.name] = 1
                    counter += 1
            self.selected_ztrace_names = names

        # draw the names of the blended sections
        if self.blend_sections and self.b_section:
            y += 20
            drawCorner(y, f"Blended sections: {self.b_section.n} and {self.section.n}")
            y += st_size
        
        # draw the number of selected flags
        if self.section.selected_flags:
            y += 20
            l = len(self.section.selected_flags)
            drawCorner(y, f"{l} flag{'s' if l > 1 else ''} selected")
            y += st_size
        
        # draw the names of the selected traces
        if self.selected_trace_names:
            y += 20
            drawCorner(y, "Selected Traces:")
            for name, n in self.selected_trace_names.items():
                y += st_size + 10
                if n == 1:
                    text = name
                else:
                    text = f"{name} * {n}"
                drawCorner(y, text)
            y += st_size
        
        # draw the names of the selected ztraces
        if self.selected_ztrace_names:
            y += 20
            drawCorner(y, "Selected Ztraces:")
            for name, n in self.selected_ztrace_names.items():
                y += st_size + 10
                if n == 1:
                    text = name
                else:
                    text = f"{name} * {n}"
                drawCorner(y, text)
            y += st_size
        
        self.corner_text = (corner_lines, y, x, right_justified, st_size)

        # close the flag display if needed
        if close_hover_display:
            self.closeHoverDisplay()

        # update the status bar
        if not self.is_panzooming:
            if closest_type == "flag":
                self.updateStatusBar()
            else:
                self.updateStatusBar(closest)
    
    def cornerTextRect(self):
        """Where paintText last drew the corner text, in the field's
        parent's coordinates, or None when it drew none. Measured only when
        asked (the hover box asks when it is placed), not on every paint."""
        lines, bottom, x, right_justified, size = getattr(
            self, "corner_text", ([], 0, 0, False, 0))
        if not lines:
            return None
        metrics = QFontMetrics(QFont("Courier New", size, QFont.Bold))
        width = max(metrics.horizontalAdvance(line) for line in lines)
        left = x - width if right_justified else x
        pad = 2   # the text's outline
        return QRect(self.x() + left - pad, self.y(),
                     width + 2 * pad, bottom + pad)

    def closeHoverDisplay(self):
        """Close the hover information display."""
        # hide (do not close/discard) the widget: it is reused across hovers so
        # that hidden QTextEdits do not accumulate as children of the main window
        if self.hover_display:
            self.hover_display.hide()
        self.displayed_item = None
        if self.hover_display_timer.isActive():
            self.hover_display_timer.stop()
    
    def displayHoverInfo(self):
        """Display the information for an item that has been hovered over."""
        text = ""
        if type(self.displayed_item) is Flag:
            # create text edit display for comments
            comments = []
            for c in self.displayed_item.comments:
                t = c.text.replace("\n", "<br>")
                comments.append(
                    f"<b>{c.user}</b> ({c.date}):<br>{t}"
                )
            text = "<hr>".join(comments)
        elif type(self.displayed_item) is Trace:
            t = self.displayed_item
            lines = []
            def addLine(header, desc):
                if desc: lines.append(f"<b>{header}</b> {desc}")

            enabled_columns = [col for col, enabled in self.hover_columns if enabled]
            for col in enabled_columns:
                if col == "Name":
                    addLine("Name:", t.name)
                elif col == "Host":
                    addLine("Host:", ", ".join(self.series.getObjHosts(t.name)))
                elif col == "Section Range":
                    start = self.series.data.getStart(t.name)
                    end = self.series.data.getEnd(t.name)
                    addLine("Section Range:", f"{start}-{end}")
                elif col == "Comment":
                    addLine("Comment:", self.series.getAttr(t.name, "comment"))
                elif col == "Object Alignment":
                    addLine("Object Alignment:", self.series.getAttr(t.name, "alignment"))
                elif col == "Object Groups":
                    addLine("Object Groups:", ", ".join(self.series.object_groups.getObjectGroups(t.name)))
                elif col == "Trace Tags":
                    addLine("Trace Tags:", ", ".join(t.tags))

            text = "<hr>".join(lines)
        
        if not text:
            return
        
        # create the widget once and reuse it across hovers
        if self.hover_display is None:
            self.hover_display = QTextEdit(self.mainwindow)
        self.hover_display.setText(text)
        # show
        self.hover_display.show()
        # adjust the width and height
        self.hover_display.resize(self.width() // 5, 1)
        h = self.hover_display.document().size().toSize().height() + 3
        if h == 3:
            self.hover_display.setText("X")
            h = self.hover_display.document().size().toSize().height()
            self.hover_display.setText("")
        elif h > self.height() - 6:
            h = self.height() - 6
        self.hover_display.resize(self.width() // 5, h)
        # a bottom corner, opposite the tool palette when there is room,
        # clear of the scale bar, the palette and the corner text
        palette = self.mainwindow.mouse_palette
        scale_bar, others = palette.hoverObstacles()
        self.hover_display.move(hoverDisplayPosition(
            self.geometry(),
            self.hover_display.size(),
            prefer_right=palette.mode_x <= .5,
            scale_bar=scale_bar,
            others=others,
            text=self.cornerTextRect(),
        ))
        # scroll all the way down
        sb = self.hover_display.verticalScrollBar()
        sb.setValue(sb.maximum())