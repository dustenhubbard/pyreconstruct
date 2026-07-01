"""StudioShell — the composite that assembles the Studio layout grammar.

It lays out the regions exactly as the spec's grammar describes ::

    title strip  (full width)
    body:  [ activity rail | main column ]
           main column:  [ objects panel | canvas | tool rail ]   (the "work row")
                         [ palette strip                       ]
    status bar   (full width)

and wires enough behavior to be demonstrable: the rail repoints the left panel,
the object list filters and reports selection, selecting an object updates the
in-canvas badge, the section pill steps sections, the tool rail and palette
select, and :meth:`apply_theme` toggles Studio ↔ Atlas (same layout, light/dark
shell, always-dark canvas).

It is a plain ``QWidget`` so it can be a standalone preview window *or* the main
window's central widget. :meth:`demo` returns one populated with the mockup's
content (including a 3,809-row object list, to prove the list virtualizes).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication

from ..utils import theme
from . import qss
from ._common import logo_path
from .title_strip import StudioTitleStrip
from .rail import ActivityRail
from .objects_panel import ObjectsPanel
from .canvas import CanvasArea
from .tool_rail import ToolRail
from .palette_strip import PaletteStrip
from .status_bar import StudioStatusBar


class StudioShell(QWidget):
    """The whole Studio layout, assembled from the region widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioShell")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("PyReconstruct")
        _logo = logo_path()
        if _logo:
            self.setWindowIcon(QIcon(_logo))
        self._theme = None
        self._section_idx, self._section_total = 148, 287
        self._datasets = {}
        self._by_name = {}

        # regions
        self.title_strip = StudioTitleStrip(self)
        self.rail = ActivityRail(self)
        self.objects_panel = ObjectsPanel(self)
        self.canvas = CanvasArea(self)
        self.tool_rail = ToolRail(self)
        self.palette_strip = PaletteStrip(self)
        self.status_bar = StudioStatusBar(self)

        # assemble
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.title_strip)

        body = QWidget(self)
        body.setObjectName("studioBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)
        body_l.addWidget(self.rail)

        main_col = QWidget(body)
        main_col.setObjectName("studioMainColumn")
        main_col.setAttribute(Qt.WA_StyledBackground, True)
        main_l = QVBoxLayout(main_col)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        work = QWidget(main_col)
        work.setObjectName("studioWorkRow")
        work.setAttribute(Qt.WA_StyledBackground, True)
        work_l = QHBoxLayout(work)
        work_l.setContentsMargins(0, 0, 0, 0)
        work_l.setSpacing(0)
        work_l.addWidget(self.objects_panel)
        work_l.addWidget(self.canvas, 1)
        work_l.addWidget(self.tool_rail)

        main_l.addWidget(work, 1)
        main_l.addWidget(self.palette_strip)
        body_l.addWidget(main_col, 1)

        root.addWidget(body, 1)
        root.addWidget(self.status_bar)

        self._wire()
        self.apply_theme("studio", app_wide=False)

    # --- wiring -----------------------------------------------------------
    def _wire(self):
        self.rail.activated.connect(self._on_rail)
        self.objects_panel.object_activated.connect(self._on_object)
        self.canvas.section_changed.connect(self._on_section_step)

    def _on_rail(self, key):
        # the four list panels repoint the left panel; 3D / Settings are seams
        # for follow-up components (the panel stays put, the rail item lights).
        if key in self._datasets:
            self.objects_panel.set_title(key)
            self._set_dataset(key)

    def _on_object(self, name):
        status = self._by_name.get(name)
        if status:
            self.canvas.set_active_object(name, status)

    def _on_section_step(self, delta):
        self._section_idx = max(1, min(self._section_total, self._section_idx + delta))
        self.canvas.set_section(self._section_idx, self._section_total)
        self.status_bar.set_section(self._section_idx)

    def _set_dataset(self, key):
        objs = self._datasets.get(key, [])
        self._by_name = {o["name"]: o.get("status") for o in objs}
        self.objects_panel.set_objects(objs)

    # --- theming ----------------------------------------------------------
    def apply_theme(self, theme_name=None, app_wide=True):
        """Apply Studio (dark) or Atlas (light): same layout, different shell.

        ``app_wide`` also re-applies the qdarkstyle-remap base app stylesheet
        (for a standalone preview); the main window owns that when it adopts the
        shell, so it can pass ``app_wide=False``.
        """
        self._theme = theme_name
        if app_wide:
            try:
                theme.apply_theme(QApplication.instance(), theme_name)
            except Exception:
                pass
        self.setStyleSheet(qss.chrome_qss(theme_name))
        tok = theme.studio_tokens(theme_name)
        self.rail.retint(tok["faint"], tok["accent"])
        self.tool_rail.retint(tok["tool_icon_rest"], tok["tool_icon_active"])
        self.objects_panel.apply_theme(theme_name)
        self.canvas.apply_theme(theme_name)
        self.palette_strip.apply_theme(theme_name)
        self.status_bar.apply_theme(theme_name)
        self.title_strip.apply_theme(theme_name)

    def current_theme(self):
        return self._theme

    # --- demo content -----------------------------------------------------
    @classmethod
    def demo(cls, parent=None):
        """A shell populated with the mockup's content for preview / tests."""
        shell = cls(parent)
        shell._datasets = {
            "objects": _demo_objects(),
            "traces": _demo_traces(),
            "sections": _demo_sections(),
            "flags": _demo_flags(),
        }
        shell.objects_panel.set_title("objects")
        shell._set_dataset("objects")
        shell.palette_strip.set_colors(_PALETTE)
        shell.palette_strip.set_active(0)
        shell.palette_strip.set_readout("circle · r=0.045")
        shell.canvas.set_section(148, 287)
        shell.canvas.set_active_object("spine_042", "review")
        shell.canvas.set_brightness(38)
        shell.canvas.set_contrast(60)
        shell.status_bar.set_section(148)
        shell.status_bar.set_alignment("default")
        shell.status_bar.set_position("0.8072", "0.8439")
        shell.status_bar.set_traces("61,121")
        shell.status_bar.set_zoom("240%")
        shell.rail.set_active("objects")
        shell.tool_rail.set_active("pointer")
        return shell


# --- demo data (the mockup's content) ----------------------------------------
#: the mockup's palette swatches (trace colors — data, not chrome)
_PALETTE = ["#6ce0c4", "#f0a6d8", "#9bd35a", "#f4bd4f",
            "#5ab0f0", "#b06cf0", "#f07a72", "#37c0a6"]

#: the eight named rows shown in the mockup, verbatim
_NAMED = [
    {"name": "d001", "type": "dendrite", "color": "#6ce0c4", "status": "curated"},
    {"name": "spine_042", "type": "spine", "color": "#f0a6d8", "status": "review"},
    {"name": "axon_7", "type": "axon", "color": "#9bd35a", "status": "curated"},
    {"name": "psd_018", "type": "synapse", "color": "#f4bd4f", "status": "flagged"},
    {"name": "mito_113", "type": "mitochondrion", "color": "#5ab0f0", "status": "curated"},
    {"name": "autoseg_2207", "type": "", "color": "#b06cf0", "status": "review"},
    {"name": "autoseg_2208", "type": "", "color": "#f07a72", "status": "curated"},
    {"name": "autoseg_2209", "type": "", "color": "#37c0a6", "status": "review"},
]


def _demo_objects(total=3809):
    """The eight named rows, then autoseg_NNNN filler up to ``total`` rows.

    The count reads like the mockup's 3,809 and the list is long enough to prove
    the model/view only paints the visible rows (virtualization).
    """
    objs = [dict(o) for o in _NAMED]
    statuses = ("curated", "review", "curated", "flagged", "curated", "review")
    start = 2210
    for i in range(total - len(objs)):
        objs.append({
            "name": f"autoseg_{start + i}",
            "type": "",
            "color": _PALETTE[i % len(_PALETTE)],
            "status": statuses[i % len(statuses)],
        })
    return objs


def _demo_traces():
    return [
        {"name": "d001 · c12", "type": "closed", "color": "#6ce0c4", "status": "curated"},
        {"name": "spine_042 · c3", "type": "closed", "color": "#f0a6d8", "status": "review"},
        {"name": "axon_7 · c44", "type": "open", "color": "#9bd35a", "status": "curated"},
        {"name": "psd_018 · c1", "type": "closed", "color": "#f4bd4f", "status": "flagged"},
        {"name": "mito_113 · c8", "type": "closed", "color": "#5ab0f0", "status": "curated"},
    ]


def _demo_sections():
    out = []
    for n in range(146, 152):
        out.append({"name": f"section {n}", "type": "0.004 µm/px",
                    "color": "#5ab0f0", "status": "curated"})
    return out


def _demo_flags():
    return [
        {"name": "check merge", "type": "psd_018", "color": "#f07a72", "status": "flagged"},
        {"name": "verify split", "type": "autoseg_2207", "color": "#f4bd4f", "status": "review"},
        {"name": "re-trace", "type": "spine_042", "color": "#f4bd4f", "status": "review"},
    ]
