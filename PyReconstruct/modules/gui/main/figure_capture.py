"""Frame the field and render a figure independently of its screen pixels."""

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSaveFile, QIODevice, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QImageWriter, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from PyReconstruct.modules.backend.view.frame_render import (
    FrameLayers, renderFrame, scaleBarGeometry,
)
from PyReconstruct.modules.gui.dialog import FileDialog

from .wheel_steps import WheelSteps, zoom_factor


SHAPES = {"Free": None, "1:1": 1, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9}
MIN_FRAME = 48
MAX_PIXELS = 100_000_000


def fitFrame(rect, bounds, ratio=None):
    """Fit a positive rectangle inside the available field, about its center."""
    width, height = max(MIN_FRAME, rect.width()), max(MIN_FRAME, rect.height())
    if ratio:
        height = width / ratio
    factor = min(1, bounds.width() / width, bounds.height() / height)
    width, height = width * factor, height * factor
    left = min(max(rect.center().x() - width / 2, bounds.left()), bounds.right() - width)
    top = min(max(rect.center().y() - height / 2, bounds.top()), bounds.bottom() - height)
    return QRectF(left, top, width, height).intersected(bounds)


def resizeFrame(rect, handle, point, bounds, ratio=None):
    """Resize from a handle, keeping its opposite corner or edge fixed."""
    anchor_x = rect.right() if "w" in handle else rect.left()
    anchor_y = rect.bottom() if "n" in handle else rect.top()
    width = max(MIN_FRAME, abs(point.x() - anchor_x)) if "w" in handle or "e" in handle else rect.width()
    height = max(MIN_FRAME, abs(point.y() - anchor_y)) if "n" in handle or "s" in handle else rect.height()
    if ratio:
        if handle in ("n", "s"):
            width = height * ratio
        elif handle in ("w", "e") or width / height > ratio:
            height = width / ratio
        else:
            width = height * ratio
    max_width = (anchor_x - bounds.left() if "w" in handle else
                 bounds.right() - anchor_x if "e" in handle else
                 2 * min(rect.center().x() - bounds.left(), bounds.right() - rect.center().x()))
    max_height = (anchor_y - bounds.top() if "n" in handle else
                  bounds.bottom() - anchor_y if "s" in handle else
                  2 * min(rect.center().y() - bounds.top(), bounds.bottom() - rect.center().y()))
    if ratio:
        factor = min(1, max_width / width, max_height / height)
        width, height = width * factor, height * factor
    else:
        width, height = min(width, max_width), min(height, max_height)
    left = anchor_x - width if "w" in handle else anchor_x
    top = anchor_y - height if "n" in handle else anchor_y
    if handle in ("n", "s"):
        left = rect.center().x() - width / 2
    elif handle in ("w", "e"):
        top = rect.center().y() - height / 2
    return QRectF(left, top, width, height).intersected(bounds)


class FigureCapture(QWidget):
    """A field overlay with its own frame, bar placement and output settings.

    Field navigation is intentional. Capture options never write series or
    palette settings, and closing the overlay restores the ordinary tools.
    """

    def __init__(self, field):
        super().__init__(field.mainwindow)
        self.field = field
        self.setObjectName("figureCapture")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.ratio = None
        self.frame = QRectF()
        self.bar_fraction = QPointF(0.04, 0.7)
        self.drag = None
        self.preview = None
        self.out_width = 1200
        self.bar_length = field.mainwindow.mouse_palette.sb.override_length
        self.wheel_steps = WheelSteps()
        self._buildPanel()
        self.escape = QShortcut("Esc", self)
        self.escape.setContext(Qt.WidgetWithChildrenShortcut)
        self.escape.activated.connect(self.close)
        field.installEventFilter(self)
        self.setGeometry(field.geometry())
        self.frame = fitFrame(QRectF(32, 32, self.bounds().width() * 0.85,
                                     self.bounds().height() * 0.8), self.bounds())
        self.refresh()
        self.show()
        self.raise_()
        self.setFocus()

    def _buildPanel(self):
        self.panel = QScrollArea(self)
        self.panel.setWidgetResizable(True)
        self.panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        contents = QFrame()
        layout = QVBoxLayout(contents)
        title = QLabel("Figure capture")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        shapes = QHBoxLayout()
        shapes.setSpacing(3)
        self.shape_group = QButtonGroup(self)
        self.shape_buttons = {}
        for name, ratio in SHAPES.items():
            button = QPushButton(name)
            button.setFixedWidth(46)
            button.setCheckable(True)
            button.setChecked(name == "Free")
            button.clicked.connect(lambda checked=False, ratio=ratio: self.setShape(ratio))
            self.shape_group.addButton(button)
            self.shape_buttons[name] = button
            shapes.addWidget(button)
        layout.addLayout(shapes)
        instructions = QLabel(
            "Drag handles to resize; drag an edge to move the frame. "
            "Drag inside to pan; scroll or pinch to zoom. "
            "Drag outside to draw a new frame. Drag the bar to place it. Esc exits."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        form = QFormLayout()
        self.units = QComboBox()
        self.units.addItems(["Pixels", "Inches"])
        form.addRow("Output units", self.units)
        self.width_input = QDoubleSpinBox()
        self.height_input = QDoubleSpinBox()
        for spin in (self.width_input, self.height_input):
            spin.setRange(1, 30000)
            spin.setDecimals(0)
            spin.setKeyboardTracking(False)
        form.addRow("Width", self.width_input)
        form.addRow("Height", self.height_input)
        self.dpi = QSpinBox()
        self.dpi.setRange(1, 2400)
        self.dpi.setValue(300)
        form.addRow("DPI", self.dpi)
        self.native_button = QPushButton("Native")
        self.native_button.setToolTip("One output pixel per image pixel")
        form.addRow(self.native_button)
        self.pixel_label = QLabel()
        form.addRow(self.pixel_label)
        self.label_size = QSpinBox()
        self.label_size.setRange(6, 36)
        self.label_size.setValue(12)
        form.addRow("Bar label size", self.label_size)
        self.tick_size = QSpinBox()
        self.tick_size.setRange(6, 36)
        self.tick_size.setValue(10)
        form.addRow("Tick label size", self.tick_size)
        layout.addLayout(form)
        self.layer_checks = {}
        for name, label in (("flags", "Flags"), ("ztraces", "Z-traces"),
                            ("selection", "Selection highlights")):
            check = QCheckBox(label)
            check.toggled.connect(self.refresh)
            layout.addWidget(check)
            self.layer_checks[name] = check
        self.save_button = QPushButton("Save as PNG...")
        self.copy_button = QPushButton("Copy to clipboard")
        self.close_button = QPushButton("Close capture")
        for button in (self.save_button, self.copy_button, self.close_button):
            layout.addWidget(button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.panel.setWidget(contents)
        self.units.currentIndexChanged.connect(self.syncSizeInputs)
        self.width_input.valueChanged.connect(lambda value: self.setOutputSize(value, False))
        self.height_input.valueChanged.connect(lambda value: self.setOutputSize(value, True))
        self.dpi.valueChanged.connect(self.dpiChanged)
        self.label_size.valueChanged.connect(self.refresh)
        self.tick_size.valueChanged.connect(self.refresh)
        self.native_button.clicked.connect(self.nativeSize)
        self.save_button.clicked.connect(self.savePng)
        self.copy_button.clicked.connect(self.copyImage)
        self.close_button.clicked.connect(self.close)

    def bounds(self):
        return QRectF(8, 8, max(1, self.width() - self.panel.width() - 24),
                      max(1, self.height() - 16))

    def resizeEvent(self, event):
        self.panel.setGeometry(max(0, self.width() - 300), 0, 300, self.height())
        if not self.frame.isEmpty():
            self.frame = fitFrame(self.frame, self.bounds(), self.ratio)
            self.refresh()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Move):
            self.setGeometry(self.field.geometry())
        elif event.type() == QEvent.Hide:
            self.close()
        return False

    def closeEvent(self, event):
        self.field.removeEventFilter(self)
        self.field.figure_capture = None
        self.field.setFocus()
        self.deleteLater()

    def setShape(self, ratio):
        self.ratio = ratio
        self.frame = fitFrame(self.frame, self.bounds(), ratio)
        self.refresh()

    def frameDim(self):
        return max(1, round(self.frame.width())), max(1, round(self.frame.height()))

    def outputDim(self):
        width, height = self.frameDim()
        return self.out_width, max(1, round(self.out_width * height / width))

    def frameWindow(self):
        x, y, width, height = self.field.series.window
        pw, ph = self.field.pixmap_dim
        fw, fh = self.frameDim()
        return [x + self.frame.left() * width / pw,
                y + (ph - self.frame.top() - fh) * height / ph,
                fw * width / pw, fh * height / ph]

    def scaleBarRect(self):
        size = scaleBarGeometry(
            self.field.series, self.frameWindow()[2] / self.frameDim()[0],
            self.frameDim(), self.bar_length, self.label_size.value(), self.tick_size.value(),
        )[2]
        width, height = self.frameDim()
        x = min(max(4, self.bar_fraction.x() * width), max(4, width - size[0] - 4))
        y = min(max(4, self.bar_fraction.y() * height), max(4, height - size[1] - 4))
        return QRectF(x, y, *size)

    def renderImage(self, out_dim):
        field = self.field
        layers = FrameLayers(
            image=not field.hide_image, traces=not field.hide_trace_layer,
            **{name: check.isChecked() for name, check in self.layer_checks.items()},
        )
        bar = self.scaleBarRect()
        return renderFrame(
            field.series, field.section, self.frameWindow(), self.frameDim(), out_dim,
            layers, (bar.x(), bar.y()), self.bar_length,
            self.label_size.value(), self.tick_size.value(),
            show_all_traces=field.show_all_traces, focus_on=field.focus_mode,
            roi_box=field.roiBox(),
        )

    def refresh(self):
        if self.frame.isEmpty():
            return
        self.preview = self.renderImage(self.frameDim())
        self.syncSizeInputs()
        self.raise_()
        self.update()

    def syncSizeInputs(self):
        if self.frame.isEmpty():
            return
        width, height = self.outputDim()
        divisor = self.dpi.value() if self.units.currentText() == "Inches" else 1
        for spin, value in ((self.width_input, width), (self.height_input, height)):
            with QSignalBlocker(spin):
                spin.setDecimals(4 if divisor != 1 else 0)
                spin.setRange(0.0001 if divisor != 1 else 1, 30000)
                spin.setValue(value / divisor)
        self.pixel_label.setText(f"{width} × {height} pixels")
        self.native_button.setEnabled(self.field.section_layer.image_found)
        bar = self.scaleBarRect()
        fits = bar.width() + 8 <= self.frameDim()[0] and bar.height() + 8 <= self.frameDim()[1]
        allowed = width * height <= MAX_PIXELS
        self.save_button.setEnabled(fits and allowed)
        self.copy_button.setEnabled(fits and allowed)
        self.status.setText("Scale bar does not fit. Enlarge the frame or reduce the label size."
                            if not fits else "Output is too large. Choose at most 100 million pixels."
                            if not allowed else "")

    def setOutputSize(self, value, from_height):
        if self.units.currentText() == "Inches":
            value *= self.dpi.value()
        if from_height:
            width, height = self.frameDim()
            value *= width / height
        self.out_width = max(1, round(value))
        self.syncSizeInputs()

    def dpiChanged(self):
        if self.units.currentText() == "Inches":
            self.setOutputSize(self.width_input.value(), False)
        else:
            self.syncSizeInputs()

    def nativeSize(self):
        # Source pixel area after alignment; rotations and translations keep
        # the native density, and a uniform scale changes it proportionally.
        pixel_size = self.field.section.mag * math.sqrt(abs(self.field.section.tform.det))
        if pixel_size > 0:
            self.out_width = max(1, round(self.frameWindow()[2] / pixel_size))
            self.syncSizeInputs()

    def outputImage(self):
        image = self.renderImage(self.outputDim())
        dots_per_meter = round(self.dpi.value() / 0.0254)
        image.setDotsPerMeterX(dots_per_meter)
        image.setDotsPerMeterY(dots_per_meter)
        return image

    def savePng(self):
        path = FileDialog.get("save", self, "Save figure", "PNG image (*.png)",
                              f"figure_sec_{self.field.section.n}.png")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        output = QSaveFile(path)
        if not output.open(QIODevice.WriteOnly):
            self.status.setText(f"Could not save figure: {output.errorString()}")
            return
        try:
            writer = QImageWriter(output, b"png")
            if not writer.write(self.outputImage()):
                self.status.setText(f"Could not save figure: {writer.errorString()}")
                output.cancelWriting()
                return
            if not output.commit():
                self.status.setText(f"Could not save figure: {output.errorString()}")
                return
        except Exception as error:
            output.cancelWriting()
            self.status.setText(f"Could not save figure: {error}")
            return
        self.status.setText(f"Saved {path}")

    def copyImage(self):
        try:
            QApplication.clipboard().setImage(self.outputImage())
        except Exception as error:
            self.status.setText(f"Could not copy figure: {error}")
            return
        self.status.setText("Figure copied to clipboard.")

    def handles(self):
        r = self.frame
        return {
            "nw": r.topLeft(), "n": QPointF(r.center().x(), r.top()), "ne": r.topRight(),
            "e": QPointF(r.right(), r.center().y()), "se": r.bottomRight(),
            "s": QPointF(r.center().x(), r.bottom()), "sw": r.bottomLeft(),
            "w": QPointF(r.left(), r.center().y()),
        }

    def hitTarget(self, point):
        for name, handle in self.handles().items():
            if (point - handle).manhattanLength() <= 12:
                return name
        if self.scaleBarRect().translated(self.frame.topLeft()).contains(point):
            return "bar"
        if self.frame.contains(point) and not self.frame.adjusted(8, 8, -8, -8).contains(point):
            return "frame"
        return "pan" if self.frame.contains(point) else "new"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.field.field_pixmap)
        mask = QPainterPath()
        mask.addRect(QRectF(self.rect()))
        mask.addRect(self.frame)
        painter.fillPath(mask, QColor(0, 0, 0, 150))
        if self.preview is not None:
            painter.drawImage(self.frame.topLeft(), self.preview)
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.frame)
        painter.setBrush(QColor("white"))
        for point in self.handles().values():
            painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.MiddleButton):
            return
        point = event.position()
        if not self.bounds().contains(point):
            return
        self.setFocus()
        self.drag = "pan" if event.button() == Qt.MiddleButton else self.hitTarget(point)
        self.press = point
        self.start_frame = QRectF(self.frame)
        self.start_window = list(self.field.series.window)
        self.start_bar = self.scaleBarRect().topLeft()

    def mouseMoveEvent(self, event):
        point = event.position()
        if self.drag is None:
            target = self.hitTarget(point)
            cursors = {"nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                       "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
                       "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                       "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
                       "bar": Qt.SizeAllCursor, "frame": Qt.SizeAllCursor,
                       "pan": Qt.OpenHandCursor, "new": Qt.CrossCursor}
            self.setCursor(cursors[target])
            return
        delta = point - self.press
        if self.drag == "pan":
            x, y, width, height = self.start_window
            pw, ph = self.field.pixmap_dim
            self.field.series.window = [x - delta.x() * width / pw,
                                        y + delta.y() * height / ph, width, height]
            self.field.generateView()
            return
        if self.drag == "bar":
            pos = self.start_bar + delta
            width, height = self.frameDim()
            self.bar_fraction = QPointF(pos.x() / width, pos.y() / height)
        elif self.drag == "frame":
            self.frame = fitFrame(self.start_frame.translated(delta), self.bounds(), self.ratio)
        elif self.drag == "new":
            self.frame = fitFrame(QRectF(self.press, point).normalized(), self.bounds(), self.ratio)
        else:
            self.frame = resizeFrame(self.start_frame, self.drag, point, self.bounds(), self.ratio)
        self.refresh()

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            self.mouseMoveEvent(event)
        self.drag = None

    def zoom(self, factor, point):
        if self.drag or factor == 1:
            return
        x, y, width, height = self.field.series.window
        new_width = max(self.field.section.mag, width / factor)
        new_height = height * new_width / width
        pw, ph = self.field.pixmap_dim
        self.field.series.window = [x + point.x() / pw * (width - new_width),
                                    y + (1 - point.y() / ph) * (height - new_height),
                                    new_width, new_height]
        self.field.generateView()

    def wheelEvent(self, event):
        with self.wheel_steps.reading(event) as units:
            self.zoom(zoom_factor(units), event.position())
        event.accept()

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and event.key() != Qt.Key_Escape:
            # Field editing shortcuts must not act on selected traces behind
            # the capture. Editors in the panel get first refusal as usual.
            event.accept()
            return True
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            self.zoom(1 + event.value(), event.position())
            event.accept()
            return True
        return super().event(event)
