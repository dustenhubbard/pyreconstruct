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
from PySide6.QtGui import (
    QPainter,
    QPalette
)
from .quick_dialog import QuickDialog
from .backup import BackupDialog
from .autoseg_palette import AutosegColorsWidget

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.constants import is_frozen
from PyReconstruct.modules.backend.updater.updater import (
    channel_radio_index, radio_response_channel,
)
from PyReconstruct.modules.backend.func.utils import (
    zarr_worker_count, MAX_ZARR_WORKERS,
)
from PyReconstruct.modules.datatypes.default_settings import validPinnedLength


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

class AllOptionsDialog(QDialog):

    def __init__(self, parent, series : Series):
        """Create the dialog for all series/user options
        
            Params:
                parent (QWidget): the parent widget
                series (Series): the series with options to view/modify
        """
        super().__init__(parent)
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
                ["find_zoom"],
                ["autoseg_colors"],
                ["smoothing_3D"]
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
            "Updates": [
                ["updates"],
            ],
            "Backup": [
                ["backup"],
            ],
            "Lists": [
                ["object_columns"],
                ["trace_columns"],
                ["section_columns"],
                ["ztrace_columns"],
                ["flag_columns"],
            ]
        }

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
            [("check", ("Automatically merge selected traces", self.series.getOption("auto_merge", use_defaults)))]
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
        self.addOptionWidget("trace", structure, setOption)

        # grid
        w, h, dx, dy, nx, ny = self.series.getOption("grid", use_defaults)
        structure = [
            [None, "X", "Y"],
            ["Element size:", ("float", w), ("float", h)],
            ["Distance:", ("float", dx), ("float", dy)],
            ["Number", ("int", nx), ("int", ny)],
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
            ["Knife delete threshold (%):", ("float", self.series.getOption("knife_del_threshold", use_defaults), (0, 100)), None],
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
            ["Smoothing iterations:", ("int", self.series.getOption("smoothing_iterations", use_defaults))],
            ["Screenshot resolution (dpi):", ("int", self.series.getOption("screenshot_res", use_defaults))],
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

        # scale bar opts

        # scale_bar_width is a percentage of the field width and runs 20-100
        # (see MousePalette.createSB). The slider carries that range itself, so
        # the number on screen is the number stored. It used to be squeezed onto
        # an 0-100 groove on the way in and squeezed back on the way out, which
        # was invisible to the user and did not round trip: 60 of the 81 values
        # the option can hold came back one lower, the default of 25 included,
        # so pressing OK without touching anything narrowed the scale bar.
        #
        # The mode radio picks which of the two quantities below is in force.
        # Both are kept and both are always editable, so switching modes and
        # switching back returns the bar to exactly where it was. The default
        # mode is the historic screen-fraction one, so an installation that
        # never touches this radio sees no change at all.
        sbw = self.series.getOption("scale_bar_width", use_defaults)
        sb_mode = self.series.getOption("scale_bar_mode", use_defaults)
        sb_len = self.series.getOption("scale_bar_length_um", use_defaults)
        structure = [
            [("check",
              ("show numbers", self.series.getOption("show_scale_bar_text", use_defaults)),
              ("show ticks", self.series.getOption("show_scale_bar_ticks", use_defaults))
            )],
            ["Scale bar sizing:"],
            [("radio",
              ("Fixed share of the screen (the µm figure changes as you zoom)",
               sb_mode != "micron_pinned"),
              ("Fixed length in µm (the bar's width changes as you zoom)",
               sb_mode == "micron_pinned"),
            )],
            ["Scale bar size (percent of field width):"],
            [("slider", sbw, {"minimum": 20, "maximum": 100, "suffix": "%"})],
            ["Fixed length (µm):", ("float", sb_len)],
            ["Far enough out or in that the fixed length will not fit the field"],
            ["legibly, the bar steps by whole decades and the label follows"],
            ["(5 µm becomes 0.5 µm or 50 µm), so the bar always measures what"],
            ["it says."],
        ]

        def setOption(response):

            self.series.setOption("show_scale_bar_text", response[0][0][1])
            self.series.setOption("show_scale_bar_ticks", response[0][1][1])
            self.series.setOption(
                "scale_bar_mode",
                "micron_pinned" if response[1][1][1] else "screen_fraction",
            )
            self.series.setOption("scale_bar_width", response[2])
            # an empty or nonsensical box keeps the stored length rather than
            # pinning the bar to nothing.  "Nonsensical" has to mean more than
            # `<= 0`: `inf > 0` is True and `1e400` parses to inf, and this key
            # is global, so storing one would crash the palette on every launch
            # from here on.  validPinnedLength is the predicate the palette and
            # the bar itself apply to the same value.
            if validPinnedLength(response[3]):
                self.series.setOption("scale_bar_length_um", float(response[3]))

        self.addOptionWidget("scale_bar", structure, setOption)

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
            ["Flag size:", ("int", flag_size)]
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
            ["Transparent fill opacity:", ("float", self.series.getOption("fill_opacity", use_defaults))]
        ]
        def setOption(response):
            self.series.setOption("fill_opacity", response[0])
        self.addOptionWidget("fill_opacity", structure, setOption)

        # find_zoom
        structure = [
            ["Zoom level for finding contours:", ("float", self.series.getOption("find_zoom", use_defaults))]
        ]
        def setOption(response):
            self.series.setOption("find_zoom", response[0])
        self.addOptionWidget("find_zoom", structure, setOption)

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
            ["Coarse step:", ("float", self.series.getOption("big_dist", use_defaults))],
            ["Fine step:", ("float", self.series.getOption("med_dist", use_defaults))],
            ["Finest step:", ("float", self.series.getOption("small_dist", use_defaults))]
        ]
        def setOption(response):
            self.series.setOption("big_dist", response[0])
            self.series.setOption("med_dist", response[1])
            self.series.setOption("small_dist", response[2])
        self.addOptionWidget("2D_step", structure, setOption)

        # 3D step
        structure = [
            ["Translate step:", ("float", self.series.getOption("translate_step_3D", use_defaults))],
            ["Rotate step (degrees):", ("float", self.series.getOption("rotate_step_3D", use_defaults))],
        ]
        def setOption(response):
            self.series.setOption("translate_step_3D", response[0])
            self.series.setOption("rotate_step_3D", response[1])
        self.addOptionWidget("3D_step", structure, setOption)

        # updates
        if is_frozen():  # installed build: choose the release channel
            # channel_radio_index normalizes legacy values ("stable"/"edge") and
            # maps to the radio position; radio_response_channel is its inverse.
            channel_idx = channel_radio_index(
                self.series.getOption("update_channel", use_defaults))
            structure = [
                ["Update channel:"],
                [("radio",
                  ("Stable (recommended)", channel_idx == 0),
                  ("Beta (early features, may be unstable)", channel_idx == 1))],
                [("check", ("Check for updates on startup",
                            self.series.getOption("update_check_on_startup", use_defaults)))],
            ]
            def setOption(response):
                self.series.setOption("update_channel", radio_response_channel(response[0]))
                self.series.setOption("update_check_on_startup", response[1][0][1])
        else:  # source/pip install: choose the GitHub branch to reinstall from
            structure = [
                ["Update reinstalls from a GitHub branch (source install):"],
                ["Branch:", ("text", self.series.getOption("update_branch", use_defaults)), None],
            ]
            def setOption(response):
                self.series.setOption("update_branch", response[0])
        self.addOptionWidget("updates", structure, setOption)

        # backup
        backup_widget = BackupDialog(self, self.series, include_confirm=False)
        self.addOptionWidget("backup", backup_widget)
    
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
    
    def accept(self):
        """Overwritten--called when OK is pressed"""
        widgets = self.all_widgets.values()
        for n, w in self.all_widgets.items():
            if not w.accept(close=False):
                return False
        for w in widgets:
            w.set()
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
