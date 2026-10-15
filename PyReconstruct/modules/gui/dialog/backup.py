import os
import webbrowser
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog, 
    QDialogButtonBox, 
    QFrame,
    QGridLayout,
    QLabel, 
    QLineEdit, 
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QWidget
)

from .helper import BrowseWidget, BorderedWidget

from PyReconstruct.modules.datatypes import Series

# room for the dialog's frame and the screen's edges
SCREEN_SHARE = 0.85


def _box(parent, title : str, layout : QVBoxLayout) -> BorderedWidget:
    """A titled, bordered group with tight spacing."""
    layout.setSpacing(4)
    layout.setContentsMargins(8, 6, 8, 8)
    box = BorderedWidget(parent)
    box.setLayout(layout)
    box.addTitle(title)
    return box


def _folderRow(parent, folder : str) -> tuple:
    """A "Backup Folder:" label and browse field on one row."""
    widget = BrowseWidget(parent, "dir", folder)
    widget.layout().setContentsMargins(0, 0, 0, 0)
    row = QHBoxLayout()
    row.addWidget(QLabel(parent, text="Backup Folder:"))
    row.addWidget(widget)
    return widget, row


class BackupDialog(QDialog):

    def __init__(self, parent, series : Series, include_confirm=True):
        """Create a dialog for backing up.
        
            Params:
                series (Series): the series obj
                include_confirm (bool): True if dialog should include OK and Cancel buttons
        """
        super().__init__(parent)
        self.setWindowTitle("Backup Settings")
        self.series = series

        utc = self.series.getOption("utc")
        if utc:
            self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            self.now = datetime.now()
        self.fp = ""

        # the settings scroll on a short screen; OK and Cancel stay in view
        content = QWidget(self)
        vlayout = QVBoxLayout(content)
        vlayout.setSpacing(6)
        vlayout1 = QVBoxLayout()
        vlayout2 = QVBoxLayout()

        # this series: use the defaults, or its own folder and auto-backup
        self.use_defaults_cb = QCheckBox(content, text="Use my defaults for this series")
        self.use_defaults_cb.setChecked(series.usesBackupDefaults())
        self.use_defaults_cb.toggled.connect(self.updateEnabled)
        vlayout1.addWidget(self.use_defaults_cb)

        bdir = series.getOption("backup_dir")
        if not os.path.isdir(bdir):
            bdir = ""
        self.dir_widget, hbl = _folderRow(content, bdir)
        vlayout1.addLayout(hbl)

        # checkbox for autobackup
        self.auto_cb = QCheckBox(content, text="Auto-backup (create backup on every save)")
        self.auto_cb.setChecked(self.series.getOption("autobackup"))
        vlayout1.addWidget(self.auto_cb)

        vlayout.addWidget(_box(content, "This Series", vlayout1))

        # my defaults: used by every series set to use them. A folder saved
        # as ".../{series}" shows as its base folder with the subfolder on.
        vlayout3 = QVBoxLayout()
        folder, series_folder = Series.splitSeriesFolderTemplate(
            series.getOption("default_backup_dir")
        )
        if not series_folder:
            series_folder = series.backupSeriesFolderOn()
        self.default_dir_widget, hbl = _folderRow(content, folder)
        self.default_dir_widget.le.textChanged.connect(self.updateDefaultFolder)
        vlayout3.addLayout(hbl)

        self.default_series_cb = QCheckBox(
            content,
            text="Put each series' backups in a subfolder named by its series code"
        )
        self.default_series_cb.setChecked(series_folder)
        self.default_series_cb.toggled.connect(self.updateDefaultFolder)
        vlayout3.addWidget(self.default_series_cb)

        self.default_folder_lbl = QLabel(content)
        vlayout3.addWidget(self.default_folder_lbl)

        self.default_auto_cb = QCheckBox(content, text="Auto-backup (create backup on every save)")
        self.default_auto_cb.setChecked(series.getOption("default_autobackup"))
        vlayout3.addWidget(self.default_auto_cb)

        vlayout.addWidget(_box(content, "My Defaults (all series)", vlayout3))

        # create the delimiter widget
        r = QHBoxLayout()
        lbl = QLabel(content, text="Delimiter:")
        self.delimiter_le = QLineEdit(
            content, 
            text=self.series.getOption("backup_delimiter")
        )
        # resizeLineEdit(self.delimiter_le, "000")
        self.delimiter_le.textChanged.connect(self.updateWidgets)
        r.addWidget(lbl)
        r.addWidget(self.delimiter_le)

        vlayout2.addLayout(r)

        self.widgets = {}

        widget_info = [
            ("prefix", ""), # updated later
            ("series", self.series.code),
            ("filename", self.series.name),
            ("date", ""),  # updated later
            ("time", ""),  # updated later
            ("user", self.series.user),
            ("suffix", "") # updated later
        ]

        self.save_name_lbl = QLabel(content)

        # the fields with text to edit pair up in a grid; the ones that only
        # turn on or off share rows below it
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        grid_cells = {
            "prefix": (0, 0), "suffix": (0, 1),
            "date": (1, 0), "time": (1, 1),
        }
        fixed_rows = [QHBoxLayout(), QHBoxLayout()]
        fixed_cells = {"series": 0, "user": 0, "filename": 1}

        # create the widgets for each field
        for k, v in widget_info:
            r = QHBoxLayout()
            cb = QCheckBox(content)
            opt_heading = "Series" if k == "name" else k.title()
            cb.setText(opt_heading)
            cb.setChecked(series.getOption(f"backup_{k}"))
            cb.stateChanged.connect(self.updateWidgets)
            r.addWidget(cb)

            if k in fixed_cells:
                w = QLabel(content, text=v or "")
                r.addWidget(w)
                row = fixed_rows[fixed_cells[k]]
                row.addLayout(r)
                row.addSpacing(16)
            else:
                w = QLineEdit(content, text=v)
                w.textChanged.connect(self.updateWidgets)
                w.setText(self.series.getOption(f"backup_{k}_str"))
                r.addWidget(w)
                if k in ("date", "time"):
                    bttn = QPushButton(content, text="?")
                    bttn.setFixedWidth(bttn.fontMetrics().horizontalAdvance("?") + 24)
                    bttn.clicked.connect(openCodesLink)
                    tip = date_tip if k == "date" else time_tip
                    bttn.setToolTip(tip)
                    r.addWidget(bttn)
                grid.addLayout(r, *grid_cells[k])

            self.widgets[k] = (cb, w)

        vlayout2.addLayout(grid)
        for row in fixed_rows:
            row.addStretch()
            vlayout2.addLayout(row)

        # display name
        vlayout2.addSpacing(4)
        r = QHBoxLayout()
        r.addWidget(QLabel(content, text="Example Backup File Name:"))
        r.addWidget(self.save_name_lbl)
        r.addStretch()
        vlayout2.addLayout(r)

        vlayout.addWidget(_box(content, "Backup Naming", vlayout2))

        outer = QVBoxLayout()
        if include_confirm:
            outer.setContentsMargins(0, 0, 0, 8)
            vlayout.setContentsMargins(8, 8, 8, 0)
            self.scroll_area = QScrollArea(self)
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.setFrameShape(QFrame.NoFrame)
            self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scroll_area.setWidget(content)
            outer.addWidget(self.scroll_area)

            QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            buttonbox = QDialogButtonBox(QBtn)
            buttonbox.accepted.connect(self.accept)
            buttonbox.rejected.connect(self.reject)
            hbl = QHBoxLayout()
            hbl.setContentsMargins(8, 0, 8, 0)
            hbl.addWidget(buttonbox)
            outer.addLayout(hbl)
        else:
            # inside All Options, whose tab already scrolls
            self.scroll_area = None
            outer.setContentsMargins(0, 0, 0, 0)
            vlayout.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(content)

        self.setLayout(outer)
        self.updateWidgets()
        self.updateEnabled()
        self.updateDefaultFolder()
        if self.scroll_area is not None:
            self.resize(*self.defaultSize(content))

    def defaultSize(self, content : QWidget) -> tuple:
        """The opening size: all of the settings, but never past the screen."""
        bar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        self.scroll_area.setMinimumWidth(content.sizeHint().width() + bar)
        width = self.sizeHint().width()
        height = self.sizeHint().height() + content.sizeHint().height() \
            - self.scroll_area.sizeHint().height()
        owner = self.parentWidget()
        screen = owner.screen() if owner is not None else QApplication.primaryScreen()
        if screen is not None:
            height = min(height, int(screen.availableGeometry().height() * SCREEN_SHARE))
        return width, height

    def updateEnabled(self):
        """Lock this series' own folder and auto-backup while it uses the defaults."""
        own = not self.use_defaults_cb.isChecked()
        self.dir_widget.setEnabled(own)
        self.auto_cb.setEnabled(own)

    def updateDefaultFolder(self):
        """Show where the default folder puts this series' backups."""
        folder = self.series.defaultBackupFolder(
            self.default_dir_widget.text(), self.default_series_cb.isChecked()
        )
        if folder:
            self.default_folder_lbl.setText(f"For this series: {folder}")
        else:
            self.default_folder_lbl.setText("")
    
    def updateWidgets(self):
        """Update the display widgets."""
        l = []
        dl = self.delimiter_le.text()
        for name, (cb, w) in self.widgets.items():
            if cb.isChecked() and w.text():
                if name in ("date", "time"):
                    text = self.now.strftime(w.text())
                else:
                    text = w.text()
                l.append(text.replace(" ", dl))
        self.save_name_lbl.setText(dl.join(l) + ".jser")
    
    def accept(self, close=True):
        """Overwritten from parent class.
        
            Params:
                close (bool): True if close when successful
        """
        # bdir = self.dir_widget.text()
        # if not os.path.isdir(bdir):
        #     notify("Please enter a valid directory.")
        #     return False
        if close: super().accept()
        return True
    
    def set(self):
        """Set the series options with the requested backup data"""
        if self.accept():
            # set the series options
            self.series.setBackupUsesDefaults(self.use_defaults_cb.isChecked())
            self.series.setOption("autobackup", self.auto_cb.isChecked())
            self.series.setOption("backup_dir", self.dir_widget.text())
            self.series.setOption("default_autobackup", self.default_auto_cb.isChecked())
            self.series.setOption("default_backup_dir", self.default_dir_widget.text())
            self.series.setBackupSeriesFolder(self.default_series_cb.isChecked())
            for name, (cb, w) in self.widgets.items():
                self.series.setOption(
                    f"backup_{name}",
                    cb.isChecked()
                )
                if name in ("date", "time", "prefix", "suffix"):
                    self.series.setOption(
                        f"backup_{name}_str", 
                        w.text()
                    )
            self.series.setOption(
                "backup_delimiter",
                self.delimiter_le.text()
            )
    
    def exec(self):
        "Run the dialog."
        confirmed = super().exec()
        if confirmed:
            self.set()
            return True
        else:
            return False

date_tip = """Date codes:
%y = two-digit year (ex. 24)
%Y = four-digit year (ex. 2024)
%m = two-digit month (ex. 04)
%d = two-digit day (ex. 02)

Click for more information."""

time_tip = """Time codes:
%H = two-digit hour (24-hour clock; ex. 14)
%I = two-digit hour (12-hour clock; ex. 02)
%p = AM or PM
%M = two-digit minute (ex. 47)
%S = two-digit second (ex. 13)

Click for more information."""

def openCodesLink():
    dtcodes_link = "https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes"
    webbrowser.open(dtcodes_link)
