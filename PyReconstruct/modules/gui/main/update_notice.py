"""A compact status-bar update notice, colored by the current palette."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen

from .status_readout import StatusSegment


class UpdateNotice(StatusSegment):
    """A download arrow with the existing status-segment click behavior."""

    def __init__(self, parent=None):
        super().__init__("", parent, outlined=False)

    def sizeHint(self):
        line = self.fontMetrics().height()
        return QSize(line + 2 * self.H_PAD, line + 2 * self.V_PAD)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.fontMetrics().height(), self.contentsRect().height())
        painter.translate((self.width() - side) / 2, (self.height() - side) / 2)
        painter.scale(side / 16, side / 16)
        painter.setPen(QPen(self.palette().windowText().color(), 1.5,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        arrow = QPainterPath()
        arrow.moveTo(8, 2)
        arrow.lineTo(8, 10)
        arrow.moveTo(4, 6)
        arrow.lineTo(8, 10)
        arrow.lineTo(12, 6)
        arrow.moveTo(2, 11)
        arrow.lineTo(2, 14)
        arrow.lineTo(14, 14)
        arrow.lineTo(14, 11)
        painter.drawPath(arrow)
        painter.end()
