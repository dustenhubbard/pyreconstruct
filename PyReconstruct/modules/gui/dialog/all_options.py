import os

from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialogButtonBox,
    QPushButton,
    QScrollArea,
    QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QPainter,
    QPalette
)
from .quick_dialog import QuickDialog
from .backup import BackupDialog
from .autoseg_palette import AutosegColorsWidget
from .local_store_option import LocalStoreOptionWidget

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.backend.func.utils import (
    zarr_worker_count, MAX_ZARR_WORKERS,
)
from PyReconstruct.modules.datatypes.default_settings import (
    MAX_SELECTION_GLOW_OPACITY,
)
from PyReconstruct.modules.backend.view.trace_layer import SELECTED_TRACE_STYLES
from .scale_bar_settings import (
    scaleBarStructure,
    storeScaleBarResponse,
    wireScaleBarControls,
)


def cpuSliderReadout(percent : int) -> str:
    """Say what a CPU-usage percentage buys, in workers.

    The complaint this answers was that a setting the user believed was four
    workers ran eight, with nothing on screen to check it against. The option is
    a share of the cores, so the share alone is not the answer to "how many
    workers"; both go in the readout, resolved the same way the converter
    resolves them -- ``zarr_worker_count``, cap included. On a machine with more
    cores than ``MAX_ZARR_WORKERS`` the top of the slider therefore reads as a
    plateau (``100% (5 of 10 workers)``) rather than claiming workers that will
    not start.
    """
    workers = zarr_worker_count(percent)
    total = os.cpu_count() or 1
    return f"{percent}% ({workers} of {total} workers)"

# The options window's opening size, in logical pixels, before the screen
# clamps it. Wide enough for the lists tab's columns, tall enough for the
# colors page's embedded picker.
DEFAULT_SIZE = (1100, 850)


class AllOptionsDialog(QDialog):

    def __init__(self, parent, series : Series):
        """Create the dialog for all series/user options
        
            Params:
                parent (QWidget): the parent widget
                series (Series): the series with options to view/modify
        """
        # The title bar's zoom and minimize buttons come in through the
        # constructor's flags. Setting them afterwards with setWindowFlags
        # recreates the native window under a dialog that already holds an
        # embedded color picker, and that crashed on Linux (CI, 2026-09-14).
        super().__init__(
            parent,
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint,
        )
        self.series = series
        self.tabs = QTabWidget(self)
        self.createWidgets()
        self.placeWidgets()

        full_vlayout = QVBoxLayout()
        full_vlayout.addWidget(self.tabs)    

        QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        buttonbox = QDialogButtonBox(QBtn)
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.reject)

        reset_defaults_button = QPushButton("Reset Defaults")
        reset_defaults_button.clicked.connect(self.resetDefaults)
        buttonbox.addButton(reset_defaults_button, QDialogButtonBox.ResetRole)

        full_vlayout.addWidget(buttonbox)

        self.setLayout(full_vlayout)

        # A default size that fits the taller pages (the colors page carries
        # a picker) without scrolling on an ordinary laptop screen.
        self.resize(*self.defaultSize())

    def defaultSize(self):
        """The opening size: large, but never past the screen it opens on."""
        owner = self.parentWidget()
        screen = owner.screen() if owner is not None else QApplication.primaryScreen()
        if screen is None:
            return DEFAULT_SIZE
        avail = screen.availableGeometry()
        return (
            min(DEFAULT_SIZE[0], int(avail.width() * 0.75)),
            min(DEFAULT_SIZE[1], int(avail.height() * 0.85)),
        )
    
    def getWidgetsLayout(self, structure : list):
        """Create a layout from a predifined widget structure

        (Ideally the structure for a full tab)
        
            Params:
                structure (list): the desired layout structure
        """
        vlayout = QVBoxLayout()
        for line in structure:
            hlayout = QHBoxLayout()
            for item in line:
                if type(item) is list:
                    l = self.getWidgetsLayout(item)
                    hlayout.addLayout(l)
                else:
                    w = self.all_widgets[item]
                    hlayout.addWidget(w)
            vlayout.addLayout(hlayout)
        return vlayout

    def placeWidgets(self):
        """Arrange all of the widgets."""
        tab_structure = {
            "Mouse Tools": [
                ["pointer"],
                ["trace"],
                ["knife"],
                ["grid"],
                ["flag_defaults"]
            ],
            "View": [
                ["theme"],
                ["scale_bar"],
                ["show_ztraces"],
                ["show_flags"],
                ["fill_opacity"],
                ["selected_trace_style"],
                ["selection_glow_opacity"],
                ["find_zoom"],
                ["hover_columns"],
                ["smoothing_3D"]
            ],
            "Colors": [
                ["autoseg_colors"],
            ],
            "User/Series": [
                ["user"],
                ["series_code"],
                ["2D_step"],
                ["3D_step"],
                ["left_handed"],
                ["time"],
                ["computation"]

            ],
            "Backup": [
                ["backup"],
            ],
            # the local copy is not a backup (cleanup may remove it), so it
            # gets its own tab, and only a Dev build has one
            "Files": [
                ["local_store"],
            ],
            "Lists": [
                ["object_columns"],
                ["trace_columns"],
                ["section_columns"],
                ["ztrace_columns"],
                ["flag_columns"],
            ]
        }

        if "local_store" not in self.all_widgets:
            del tab_structure["Files"]

        for tab_name, structure, in tab_structure.items():
            widget = QWidget(self)
            vlayout = self.getWidgetsLayout(structure)
            widget.setLayout(vlayout)
            qsa = QScrollArea()
            qsa.setWidgetResizable(True)
            qsa.setWidget(widget)
            self.tabs.addTab(qsa, tab_name)
    
    def createWidgets(self, use_defaults=False):
        """Create the widgets for each of the options
        
            Params:
                use_defaults (bool): True if all values should be set at defaults instead of current settings
        """
        self.all_widgets = {}
        # pointer
        s, t = tuple(self.series.getOption("pointer", use_defaults))
        structure = [
            ["Shape:"],
            [("radio", ("Rectangle", s=="rect"), ("Lasso", s=="lasso"))],
            ["Select:"],
            [("radio", ("All touched traces", t=="inc"), ("Only completed encircled traces", t=="exc"))],
            [("check", ("Display closest field item", self.series.getOption("display_closest", use_defaults)))]
        ]
        def setOption(response):
            s = "rect" if response[0][0][1] else "lasso"
            t = "inc" if response[1][0][1] else "exc"
            self.series.setOption("pointer", [s, t])
            self.series.setOption("display_closest", response[2][0][1])
        self.addOptionWidget("pointer", structure, setOption)

        # trace
        trace_mode = self.series.getOption("trace_mode", use_defaults)
        structure = [
            ["Mode:"],
            [("radio",
                ("Scribble", trace_mode == "scribble"),
                ("Poly", trace_mode == "poly"),
                ("Combo", trace_mode == "combo")
            )],
            [("check", ("Automatically merge overlapping traces", self.series.getOption("auto_merge", use_defaults))),
             ("check", ("Only merge selected traces", self.series.getOption("auto_merge_selected_only", use_defaults)))]
        ]
        def setOption(response):
            if response[0][0][1]:
                new_mode = "scribble"
            elif response[0][1][1]:
                new_mode = "poly"
            else:
                new_mode = "combo"
            self.series.setOption("trace_mode", new_mode)
            self.series.setOption("auto_merge", response[1][0][1])
            self.series.setOption("auto_merge_selected_only", response[2][0][1])
        self.addOptionWidget("trace", structure, setOption)
        inputs = self.all_widgets["trace"].inputs
        auto_merge = inputs[1].widget.layout().itemAt(0).widget()
        selected_only = inputs[2].widget.layout().itemAt(0).widget()
        selected_only.setEnabled(auto_merge.isChecked())
        auto_merge.toggled.connect(selected_only.setEnabled)

        # grid
        w, h, dx, dy, nx, ny = self.series.getOption("grid", use_defaults)
        structure = [
            [None, "X", "Y"],
            ["Element size:", (True, "float", w), (True, "float", h)],
            ["Distance:", (True, "float", dx), (True, "float", dy)],
            ["Number", (True, "int", nx), (True, "int", ny)],
            [("check", ("Sampling frame", self.series.getOption("sampling_frame_grid", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("grid", response[:6])
            self.series.setOption("sampling_frame_grid", response[6][0][1])

        self.addOptionWidget("grid", structure, setOption, grid=True)

        ## Flag opts
        
        structure = [
            ["Default name:", ("text", self.series.getOption("flag_name", use_defaults)), None],
            ["Default color:", ("color", self.series.getOption("flag_color", use_defaults)), None],
        ]
        
        def setOption(response):
            
            self.series.setOption("flag_name", response[0])
            self.series.setOption("flag_color", response[1])

        self.addOptionWidget("flag_defaults", structure, setOption)

        ## Knife options
        
        structure = [
            ["When using the knife, objects smaller than this percent"],
            ["of the original trace area will be automatically deleted."],
            None,
            ["Knife delete threshold (%):", (True, "float", self.series.getOption("knife_del_threshold", use_defaults), (0, 100)), None],
            None,
            ["A press of another mouse button while a cut is being drawn"],
            ["can be ignored, so that a tablet's barrel button does not"],
            ["cancel the cut and open the field menu over the object."],
            None,
            [
                (
                    "check",
                    (
                        "Ignore other mouse buttons while cutting",
                        self.series.getOption("knife_ignore_secondary_click", use_defaults)
                    )
                )
            ]
        ]

        def setOption(response):

            self.series.setOption("knife_del_threshold", response[0])
            self.series.setOption("knife_ignore_secondary_click", response[1][0][1])

        self.addOptionWidget("knife", structure, setOption)

        ## 3D options
        
        opt = self.series.getOption("3D_smoothing", use_defaults)
        
        structure = [
            ["XY Resolution:"],
            # 3D_xy_res is a percentage: 0 puts the mesh voxel at the coarsest
            # of the section magnification and thickness, 100 at the finest.
            ["less detail (fast)",
             ("slider", self.series.getOption("3D_xy_res", use_defaults), {"suffix": "%"}),
             "more detail (slow)"],
            [" "],
            ["3D smoothing:"],
            [("radio",
                ("Humphrey (recommended)", opt == "humphrey"),
                ("Mutable Diffusion Laplacian", opt == "mut_dif_laplacian"),
                ("Taubin", opt == "taubin"),
                ("None (least smooth)", opt == "none"))],
            ["Smoothing iterations:", (True, "int", self.series.getOption("smoothing_iterations", use_defaults))],
            ["Screenshot resolution (dpi):", (True, "int", self.series.getOption("screenshot_res", use_defaults))],
            [("check", ("Auto-refresh edited objects", self.series.getOption("3D_auto_refresh", use_defaults)))]
        ]

        def setOption(response):
            
            self.series.setOption("3D_xy_res", response[0])
            
            if response[1][0][1]: smoothing_alg = "humphrey"
            elif response[1][1][1]: smoothing_alg = "mut_dif_laplacian"
            elif response[1][2][1]: smoothing_alg = "taubin"
            else: smoothing_alg = "none"
                
            self.series.setOption("3D_smoothing", smoothing_alg)
            self.series.setOption("smoothing_iterations", response[2])
            self.series.setOption("screenshot_res", response[3])
            self.series.setOption("3D_auto_refresh", response[4][0][1])

        self.addOptionWidget("smoothing_3D", structure, setOption)

        ## Theme opts

        theme = self.series.getOption("theme", use_defaults)
        
        structure = [
            ["Theme:"],
            [("radio", 
              ("default", theme == "default"),
              ("dark", theme == "qdark"),
            )],
        ]
        
        def setOption(response):

            theme = self.series.getOption("theme")  # keep current if neither radio matched
            if response[0][0][1]: theme = "default"
            elif response[0][1][1]: theme = "qdark"
            self.series.setOption("theme", theme)
            
        self.addOptionWidget("theme", structure, setOption)

        # scale bar opts: built, stored and wired by scale_bar_settings, which
        # also builds the bar's right-click "Scale bar settings..." dialog, so
        # the two cannot drift apart. Both quantities the mode radio picks
        # between are kept, so switching modes and back is lossless, and the
        # default mode is the historic screen-fraction one.
        self.addOptionWidget(
            "scale_bar",
            scaleBarStructure(self.series, use_defaults),
            lambda response: storeScaleBarResponse(self.series, response),
        )
        # every control previews on the field as it changes; nothing is
        # stored until OK, and Cancel restores (see _previewScaleBar)
        wireScaleBarControls(
            self.all_widgets["scale_bar"], self.series, self._previewScaleBar)

        # show_ztraces
        structure = [
            [("check", ("show ztraces in field", self.series.getOption("show_ztraces", use_defaults)))],
        ]
        def setOption(response):
            self.series.setOption("show_ztraces", response[0][0][1])
        self.addOptionWidget("show_ztraces", structure, setOption)

        # show_flags
        show_flags = self.series.getOption("show_flags", use_defaults)
        flag_size = self.series.getOption("flag_size", use_defaults)
        structure = [
            ["Display flags:"],
            [("radio",
              ("All flags", show_flags == "all"),
              ("Only unresolved flags", show_flags == "unresolved"),
              ("No flags", show_flags == "none")
            )],
            ["Flag size:", (True, "int", flag_size)]
        ]
        def setOption(response):
            if response[0][0][1]: show_flags = "all"
            elif response[0][2][1]: show_flags = "none"
            else: show_flags = "unresolved"
            self.series.setOption("show_flags", show_flags)
            self.series.setOption("flag_size", response[1])
        self.addOptionWidget("show_flags", structure, setOption)

        # fill_opacity
        structure = [
            ["Transparent fill opacity:", (True, "float", self.series.getOption("fill_opacity", use_defaults))]
        ]
        def setOption(response):
            self.series.setOption("fill_opacity", response[0])
        self.addOptionWidget("fill_opacity", structure, setOption)

        # selected_trace_style: how a selected trace is drawn, one radio button
        # per name in SELECTED_TRACE_STYLES, in that order. An unknown stored
        # name shows as the first, which is also how it draws.
        style = self.series.getOption("selected_trace_style", use_defaults)
        if style not in SELECTED_TRACE_STYLES:
            style = SELECTED_TRACE_STYLES[0]
        labels = (
            "Standard (a wide see-through stroke)",
            "Black and white outline",
            "Glow with a solid line",
        )
        structure = [
            [("radio", *(
                (label, name == style)
                for label, name in zip(labels, SELECTED_TRACE_STYLES)
            ))],
        ]
        def setOption(response):
            self.series.setOption("selected_trace_style", self._checkedStyle())
        self.addOptionWidget("selected_trace_style", structure, setOption)

        # selection_glow_opacity: how see-through the glow style's wide stroke
        # is, shown only while that style is chosen. The slider stops at 50%;
        # a larger stored value shows as 50%, which is also how it draws.
        glow = min(
            self.series.getOption("selection_glow_opacity", use_defaults),
            MAX_SELECTION_GLOW_OPACITY,
        )
        structure = [
            ["Glow opacity:",
             ("slider", glow, 10,
              {"maximum": MAX_SELECTION_GLOW_OPACITY, "suffix": "%"})],
        ]
        def setOption(response):
            self.series.setOption("selection_glow_opacity", response[0])
        self.addOptionWidget("selection_glow_opacity", structure, setOption)
        self.all_widgets["selection_glow_opacity"].setHidden(style != "glow")

        # the field previews the style as it changes (see _previewSelectedStyle)
        # (a radio change unchecks one button and checks another; redraw once)
        for button in self._styleButtons():
            button.toggled.connect(
                lambda checked: checked and self._previewSelectedStyle()
            )
        self._glowSlider().valueChanged.connect(self._previewSelectedStyle)

        # find_zoom
        structure = [
            ["Zoom level for finding contours:", (True, "float", self.series.getOption("find_zoom", use_defaults))]
        ]
        def setOption(response):
            self.series.setOption("find_zoom", response[0])
        self.addOptionWidget("find_zoom", structure, setOption)

        # hover columns configuration: a real page, so OK can call accept()
        # and set() on it like every other row
        from .hover_columns import HoverColumnsOptionWidget
        self.addOptionWidget(
            "hover_columns", HoverColumnsOptionWidget(self, self.series)
        )

        # autoseg import colors (seed + editable palette)
        autoseg_widget = AutosegColorsWidget(self, self.series, use_defaults)
        self.addOptionWidget("autoseg_colors", autoseg_widget)

        # user
        structure = [
            ["Username:", ("text", self.series.user)]
        ]
        def setOption(response):
            self.series.user = response[0]
        self.addOptionWidget("user", structure, setOption)

        # series_code
        structure = [
            ["Series code:", ("text", self.series.code)],
            ["Default series code regex: ", ("text", self.series.getOption("series_code_pattern", use_defaults))]
        ]
        def setOption(response):
            self.series.code = response[0]
            self.series.setOption("series_code_pattern", response[1])
        self.addOptionWidget("series_code", structure, setOption)

        # left_handed
        structure = [
            [("check", ("left-handed", self.series.getOption("left_handed", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("left_handed", response[0][0][1])
        self.addOptionWidget("left_handed", structure, setOption)

        # utc
        structure = [
            [("check", ("use UTC time", self.series.getOption("utc", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("utc", response[0][0][1])
        self.addOptionWidget("time", structure, setOption)

        # computational power
        cpu_max = self.series.getOption("cpu_max", use_defaults)

        structure = [
            ["CPU usage (image-to-zarr conversion):"],
            ["min", ("slider", cpu_max, 25, {"fmt": cpuSliderReadout}), "max"],
            ["Sets how many parallel workers convert images to zarr -- a share"],
            ["of your CPU, not a fixed number of cores. Recommended: about half"],
            ["(the default). Lower it if the program or computer feels sluggish"],
            ["during conversion."],
            ["The conversion is I/O bound, so raising this past"],
            [f"{MAX_ZARR_WORKERS} workers makes it slower, not faster: 8 workers"],
            [f"measured 8% slower than {MAX_ZARR_WORKERS} while using 19% more"],
            [f"CPU. The slider will not start more than {MAX_ZARR_WORKERS}."],
        ]
        
        def setOption(response):
            self.series.setOption("cpu_max", response[0])
            
        self.addOptionWidget("computation", structure, setOption)

        # columns
        structure = [
            [("check", *tuple(self.series.getOption("object_columns", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("object_columns", response[0])
        self.addOptionWidget("object_columns", structure, setOption)

        structure = [
            [("check", *tuple(self.series.getOption("trace_columns", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("trace_columns", response[0])
        self.addOptionWidget("trace_columns", structure, setOption)

        structure = [
            [("check", *tuple(self.series.getOption("section_columns", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("section_columns", response[0])
        self.addOptionWidget("section_columns", structure, setOption)

        structure = [
            [("check", *tuple(self.series.getOption("ztrace_columns", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("ztrace_columns", response[0])
        self.addOptionWidget("ztrace_columns", structure, setOption)

        structure = [
            [("check", *tuple(self.series.getOption("flag_columns", use_defaults)))]
        ]
        def setOption(response):
            self.series.setOption("flag_columns", response[0])
        self.addOptionWidget("flag_columns", structure, setOption)

        # 2D step
        structure = [
            ["Coarse step:", (True, "float", self.series.getOption("big_dist", use_defaults))],
            ["Fine step:", (True, "float", self.series.getOption("med_dist", use_defaults))],
            ["Finest step:", (True, "float", self.series.getOption("small_dist", use_defaults))]
        ]
        def setOption(response):
            self.series.setOption("big_dist", response[0])
            self.series.setOption("med_dist", response[1])
            self.series.setOption("small_dist", response[2])
        self.addOptionWidget("2D_step", structure, setOption)

        # 3D step
        structure = [
            ["Translate step:", (True, "float", self.series.getOption("translate_step_3D", use_defaults))],
            ["Rotate step (degrees):", (True, "float", self.series.getOption("rotate_step_3D", use_defaults))],
        ]
        def setOption(response):
            self.series.setOption("translate_step_3D", response[0])
            self.series.setOption("rotate_step_3D", response[1])
        self.addOptionWidget("3D_step", structure, setOption)


        # backup
        backup_widget = BackupDialog(self, self.series, include_confirm=False)
        self.addOptionWidget("backup", backup_widget)

        # the local store's setting and cleanup button, Dev builds only
        if build_flavor.is_dev_build():
            self.addOptionWidget(
                "local_store", LocalStoreOptionWidget(self, self.series, use_defaults)
            )
    
    def addOptionWidget(self, name : str, structure : list, setOption=None, grid=False):
        """Add a widget to the all_widgets dictionary
        
            Params:
                name (str): the desired name for the widget
                structure (list): the QuickDialog structure for the widget
                setOption (function): the function for setting the widget option once accepted
                grid (bool): True if widget structure should be a grid instead of rows
        """
        title = name.replace("_", " ").title()
        if isinstance(structure, QWidget):
            self.all_widgets[name] = structure
        else:
            self.all_widgets[name] = OptionWidget(self, title, structure, self.series, setOption, grid)
    
    def _palette(self):
        """The main window's mouse palette, or None when there is no window."""
        return getattr(self.parent(), "mouse_palette", None)

    def _previewScaleBar(self, settings):
        """Show the field's scale bar as the Scale Bar group would draw it;
        nothing is stored.

        Every control previews live, so a change can be judged before OK
        without closing and reopening the window. OK stores the options and
        the caller rebuilds the palette; Cancel puts the bar back through
        restoreScaleBar.
        """
        palette = self._palette()
        if palette is not None:
            palette.previewScaleBar(settings)
            self._scale_bar_previewed = True

    def _styleButtons(self):
        """The selected trace style's radio buttons, in SELECTED_TRACE_STYLES order."""
        layout = self.all_widgets["selected_trace_style"].inputs[0].widget.layout()
        return [layout.itemAt(i).widget() for i in range(layout.count())]

    def _checkedStyle(self) -> str:
        """The selected trace style the radio buttons show."""
        for button, name in zip(self._styleButtons(), SELECTED_TRACE_STYLES):
            if button.isChecked():
                return name
        return SELECTED_TRACE_STYLES[0]

    def _glowSlider(self):
        return self.all_widgets["selection_glow_opacity"].inputs[0].widget.slider

    def _styleLayers(self):
        """The field and the section layers it draws (two when blending).

        Returns (None, []) when there is no window.
        """
        field = getattr(self.parent(), "field", None)
        if field is None:
            return None, []
        layers = (field.section_layer, getattr(field, "b_section_layer", None))
        return field, [layer for layer in layers if layer is not None]

    def _previewSelectedStyle(self, *_):
        """Redraw the field with the selected trace style the window shows; nothing is stored.

        Which look reads best depends on the image under the traces, so it is
        judged on the field while the window is open. OK stores the options;
        Cancel redraws from the stored ones (_endStylePreview).
        """
        style = self._checkedStyle()
        self.all_widgets["selection_glow_opacity"].setHidden(style != "glow")
        field, layers = self._styleLayers()
        if field is None:
            return
        for layer in layers:
            layer.selected_style_preview = (style, self._glowSlider().value())
        field.generateView(generate_image=False)
        self._style_previewed = True

    def _endStylePreview(self, redraw : bool):
        """Hand the selected trace style back to the stored options.

            Params:
                redraw (bool): True to redraw the field now
        """
        if not getattr(self, "_style_previewed", False):
            return
        field, layers = self._styleLayers()
        if field is not None:
            for layer in layers:
                layer.selected_style_preview = None
            if redraw:
                field.generateView(generate_image=False)
        self._style_previewed = False

    def reject(self):
        """Overwritten: previewed views go back to their stored settings."""
        if getattr(self, "_scale_bar_previewed", False):
            palette = self._palette()
            if palette is not None:
                palette.restoreScaleBar()
            self._scale_bar_previewed = False
        self._endStylePreview(redraw=True)
        super().reject()

    def accept(self):
        """Overwritten--called when OK is pressed"""
        widgets = self.all_widgets.values()
        for n, w in self.all_widgets.items():
            if not w.accept(close=False):
                return False
        for w in widgets:
            w.set()
        # the caller redraws the field after OK, now from the stored options
        self._endStylePreview(redraw=False)
        super().accept()
        return True

    def resetDefaults(self):
        """Reset the default values for the widget inputs"""
        # keep track of the current tab
        current_tab = self.tabs.currentIndex()
        # reset the widget and use defaults
        self.tabs.clear()
        self.createWidgets(use_defaults=True)
        self.placeWidgets()
        # set the tab
        self.tabs.setCurrentIndex(current_tab)
        # the new style widgets start at the defaults without a signal, so show
        # the field that way too
        self._previewSelectedStyle()

# all widgets used in the options MUST have a accept() and set() method
# accept is used to check if the response are valid
# set is used to actually set the series options. This happens only if accept returns True

class OptionWidget(QuickDialog):

    def __init__(
            self, 
            parent, 
            title : str, 
            structure : list, 
            series : Series, 
            setOption, 
            grid=False
        ):
        """Create a widget for a series option
        
            Params:
                parent (QWidget): the parent widget
                title (str): the title of the widget
                structure (list): the structure for the widget
                series (Series): the series lnked to the options
                setOption (function): the function to set the options
                grid (bool): True if structure should be grid instead of rows
        """
        super().__init__(parent, structure, title, grid, include_confirm=False)
        self.series = series
        self.setOption = setOption
        
    def set(self):
        """Set the series option for the widget"""
        self.setOption(self.responses)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        ## Draw border manually
        painter = QPainter(self)
        painter.setPen(QApplication.palette().color(QPalette.WindowText))  # Set border color
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))  # Draw rectangle inside border
