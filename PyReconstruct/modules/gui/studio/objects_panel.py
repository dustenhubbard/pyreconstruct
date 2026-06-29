"""The Objects panel — the promoted, first-class, filterable object list.

268px wide, ``panel`` ground. A tracked uppercase ``OBJECTS`` header with a mono
count; a filter field; a model/view list whose rows read
``[swatch] [name · type] …… [status dot]``; and a curation legend in the footer.

The list is a ``QListView`` over a lightweight model with a custom delegate, so
it virtualizes (only visible rows are painted) and scales to thousands of
objects. The delegate honours the spec's row anatomy precisely: the data color
is a small *swatch* (never tinted text), the type is a faint mono suffix, the
curation status is a colored dot, and the selected row carries a teal left bar
over a wash that fades to nothing.

Pure view layer: feed it dicts via :meth:`set_objects`
(``{"name", "type", "color", "status"}``); it emits :attr:`object_activated`.
"""
from PySide6.QtCore import (
    Qt, Signal, QAbstractListModel, QModelIndex, QSortFilterProxyModel, QSize, QRectF,
)
from PySide6.QtGui import QColor, QBrush, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListView,
    QStyledItemDelegate, QStyle,
)

from ..utils import theme, icons

_OBJ_ROLE = Qt.UserRole + 1
#: curation status -> chrome token key for the status dot
_STATUS_TOKEN = {"curated": "ok", "review": "warn", "flagged": "bad"}
_ROW_H = 30


class _ObjectModel(QAbstractListModel):
    """Holds the object dicts; exposes each row's dict under ``_OBJ_ROLE``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._objs = []

    def set_objects(self, objs):
        self.beginResetModel()
        self._objs = list(objs)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._objs)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        obj = self._objs[index.row()]
        if role == _OBJ_ROLE:
            return obj
        if role == Qt.DisplayRole:
            return obj.get("name", "")
        return None


class _ObjectFilter(QSortFilterProxyModel):
    """Case-insensitive substring filter over name + type."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._needle = ""

    def set_needle(self, text):
        self._needle = (text or "").strip().lower()
        self.invalidateRowsFilter()

    def filterAcceptsRow(self, row, parent):
        if not self._needle:
            return True
        obj = self.sourceModel().index(row, 0, parent).data(_OBJ_ROLE) or {}
        hay = f"{obj.get('name', '')} {obj.get('type', '')}".lower()
        return self._needle in hay


class _ObjectRowDelegate(QStyledItemDelegate):
    """Paints one object row per the spec's anatomy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tok = theme.studio_tokens()
        self._mono = QLabel().font()  # cloned below in paint via setFamily
        self._mono.setStyleHint(self._mono.StyleHint.Monospace)
        self._mono.setFamily("DejaVu Sans Mono")

    def set_tokens(self, tokens):
        self._tok = tokens

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), _ROW_H)

    def paint(self, painter, option, index):
        obj = index.data(_OBJ_ROLE) or {}
        tok = self._tok
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
            grad.setColorAt(0.0, QColor(tok["row_sel_a"]))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect, QBrush(grad))
            painter.fillRect(rect.left(), rect.top(), 2, rect.height(),
                             QColor(tok["row_sel_bar"]))
        elif option.state & QStyle.State_MouseOver:
            hov = QColor(tok["row_sel_a"])
            hov.setAlpha(90)
            painter.fillRect(rect, hov)

        # per-row hairline (border-bottom)
        painter.setPen(QPen(QColor(tok["line_soft"]), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        pad = 11
        # data-color swatch (11x11, radius 3) — NEVER tinted text
        sw = 11
        sw_x = rect.left() + pad
        sw_y = rect.center().y() - sw // 2 + 1
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
        painter.setBrush(QColor(obj.get("color", "#888888")))
        painter.drawRoundedRect(QRectF(sw_x, sw_y, sw, sw), 3, 3)

        # curation status dot (8px), right-aligned
        dot = 8
        dot_x = rect.right() - pad - dot
        status = obj.get("status")
        if status in _STATUS_TOKEN:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(tok[_STATUS_TOKEN[status]]))
            painter.drawEllipse(QRectF(dot_x, rect.center().y() - dot / 2, dot, dot))

        # name (ink) + " · type" (faint mono), elided to fit
        name_x = sw_x + sw + 8
        avail = dot_x - 8 - name_x
        name_font = option.font
        type_font = self._mono
        type_font.setPointSizeF(max(7.5, name_font.pointSizeF() - 1.5)
                                if name_font.pointSizeF() > 0 else 8.5)
        painter.setFont(type_font)
        type_fm = painter.fontMetrics()
        type_text = f" · {obj['type']}" if obj.get("type") else ""
        type_w = type_fm.horizontalAdvance(type_text)

        painter.setFont(name_font)
        name_fm = painter.fontMetrics()
        name = name_fm.elidedText(obj.get("name", ""), Qt.ElideRight, max(0, avail - type_w))
        name_w = name_fm.horizontalAdvance(name)
        baseline = rect.center().y() + name_fm.ascent() // 2 - 1
        painter.setPen(QColor(tok["ink"]))
        painter.drawText(name_x, baseline, name)
        if type_text:
            painter.setFont(type_font)
            painter.setPen(QColor(tok["faint"]))
            painter.drawText(name_x + name_w, baseline, type_text)

        painter.restore()


def _dot(color_hex, d=8):
    """A small colored status dot as a QLabel (for the legend)."""
    lab = QLabel()
    lab.setFixedSize(d, d)
    lab.setStyleSheet(f"background:{color_hex}; border-radius:{d // 2}px;")
    return lab


class ObjectsPanel(QWidget):
    """First-class Objects list panel; emits :attr:`object_activated`."""

    object_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioObjectsPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(268)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header: TITLE + mono count
        header = QWidget(self)
        header.setObjectName("studioPanelHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(11, 8, 11, 8)
        self._title = QLabel("OBJECTS", header)
        self._title.setObjectName("studioPanelTitle")
        self._count = QLabel("0", header)
        self._count.setObjectName("studioPanelCount")
        hl.addWidget(self._title)
        hl.addStretch(1)
        hl.addWidget(self._count)
        root.addWidget(header)

        # filter field (with a vector magnifier, never a unicode glyph)
        filt_wrap = QWidget(self)
        fwl = QVBoxLayout(filt_wrap)
        fwl.setContentsMargins(11, 8, 11, 8)
        self.filter = QLineEdit(filt_wrap)
        self.filter.setObjectName("studioFilter")
        self.filter.setPlaceholderText("Filter objects…")
        self.filter.setClearButtonEnabled(True)
        self._search_action = self.filter.addAction(
            icons.tool_icon("search", 16, theme.studio_tokens()["faint"]),
            QLineEdit.LeadingPosition,
        )
        fwl.addWidget(self.filter)
        root.addWidget(filt_wrap)

        # the list (model / filter / view + custom delegate)
        self._model = _ObjectModel(self)
        self._proxy = _ObjectFilter(self)
        self._proxy.setSourceModel(self._model)
        self.view = QListView(self)
        self.view.setObjectName("studioObjectList")
        self.view.setModel(self._proxy)
        self._delegate = _ObjectRowDelegate(self.view)
        self.view.setItemDelegate(self._delegate)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setSelectionMode(QListView.SingleSelection)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.view, 1)

        # legend footer: Curated / Review / Flagged
        self._legend = QWidget(self)
        self._legend.setObjectName("studioLegend")
        self._legend.setAttribute(Qt.WA_StyledBackground, True)
        ll = QHBoxLayout(self._legend)
        ll.setContentsMargins(11, 8, 11, 8)
        ll.setSpacing(11)
        self._legend_dots = []
        for label, tok_key in (("Curated", "ok"), ("Review", "warn"), ("Flagged", "bad")):
            cell = QHBoxLayout()
            cell.setSpacing(5)
            dot = _dot(theme.studio_tokens()[tok_key])
            self._legend_dots.append((dot, tok_key))
            text = QLabel(label, self._legend)
            text.setObjectName("studioLegendLabel")
            cell.addWidget(dot)
            cell.addWidget(text)
            ll.addLayout(cell)
        ll.addStretch(1)
        root.addWidget(self._legend)

        # wiring
        self.filter.textChanged.connect(self._on_filter)
        self.view.selectionModel().currentChanged.connect(self._on_current)

    # --- public API -------------------------------------------------------
    def set_title(self, title):
        """Repoint the panel (e.g. OBJECTS / TRACES / SECTIONS / FLAGS)."""
        self._title.setText(title.upper())

    def set_objects(self, objs):
        """Replace the list contents (a list of object dicts)."""
        self._model.set_objects(objs)
        self._update_count()
        if self._proxy.rowCount():
            self.view.setCurrentIndex(self._proxy.index(0, 0))

    def selected_name(self):
        idx = self.view.currentIndex()
        obj = idx.data(_OBJ_ROLE) if idx.isValid() else None
        return obj.get("name") if obj else None

    def apply_theme(self, theme_name=None):
        """Re-tint the data-driven bits after a theme change."""
        tok = theme.studio_tokens(theme_name)
        self._delegate.set_tokens(tok)
        self._search_action.setIcon(icons.tool_icon("search", 16, tok["faint"]))
        for dot, key in self._legend_dots:
            dot.setStyleSheet(f"background:{tok[key]}; border-radius:4px;")
        self.view.viewport().update()

    # --- internals --------------------------------------------------------
    def _on_filter(self, text):
        self._proxy.set_needle(text)
        self._update_count()

    def _on_current(self, current, _previous):
        obj = current.data(_OBJ_ROLE) if current.isValid() else None
        if obj:
            self.object_activated.emit(obj.get("name", ""))

    def _update_count(self):
        self._count.setText(f"{self._proxy.rowCount():,}")
