"""The status bar — a slim mono strip of live readouts.

30px, ``panel-2`` ground, monospace. Section / alignment / cursor x,y on the
left; trace count and zoom on the right. The active *values* are teal; their
labels are muted.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel

from ..utils import theme


class StudioStatusBar(QWidget):
    """Mono status strip; set fields via the ``set_*`` methods."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioStatusBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(30)
        self._tok = theme.studio_tokens()
        self._fields = {
            "section": "148", "alignment": "default",
            "x": "0.8072", "y": "0.8439",
            "traces": "61,121", "zoom": "240%",
        }

        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 0, 13, 0)
        lay.setSpacing(17)
        self._section = self._seg(lay)
        self._alignment = self._seg(lay)
        self._xy = self._seg(lay)
        lay.addStretch(1)
        self._traces = self._seg(lay)
        self._zoom = self._seg(lay)
        self._refresh()

    def _seg(self, layout):
        lab = QLabel(self)
        lab.setObjectName("studioStatusText")
        lab.setTextFormat(Qt.RichText)
        layout.addWidget(lab)
        return lab

    # --- public API -------------------------------------------------------
    def set_section(self, value):
        self._fields["section"] = str(value)
        self._refresh()

    def set_alignment(self, value):
        self._fields["alignment"] = str(value)
        self._refresh()

    def set_position(self, x, y):
        self._fields["x"], self._fields["y"] = str(x), str(y)
        self._refresh()

    def set_traces(self, value):
        self._fields["traces"] = str(value)
        self._refresh()

    def set_zoom(self, value):
        self._fields["zoom"] = str(value)
        self._refresh()

    def apply_theme(self, theme_name=None):
        self._tok = theme.studio_tokens(theme_name)
        self._refresh()

    # --- internals --------------------------------------------------------
    def _v(self, value):
        return f"<span style='color:{self._tok['accent']}'>{value}</span>"

    def _refresh(self):
        f = self._fields
        self._section.setText(f"section {self._v(f['section'])}")
        self._alignment.setText(f"alignment {self._v(f['alignment'])}")
        self._xy.setText(f"x {self._v(f['x'])}  y {self._v(f['y'])}")
        self._traces.setText(f"{self._v(f['traces'])} traces")
        self._zoom.setText(f"zoom {self._v(f['zoom'])}")
