"""Crop the series' scaled images around one object, from PyReconstruct.

The crop is backend.crop_zarr, the module the command-line crop_zarr.py runs.
This dialog asks for its inputs, checks them the same way before anything is
written (checkObject, resolvePaths), and cropWithProgress runs it on a worker
thread behind the progress dialog, whose Cancel stops it after the section
being written. The crop reads the sections from the series' working folder,
so the window writes the field's unsaved edits first
(MainWindow.cropScaledImages). The source zarr and the series are never
changed; a stopped crop leaves its partial output in place, without a log.
"""
import math
import os
import threading
import time

from PySide6.QtCore import Qt, QEventLoop
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.crop_zarr import (
    LOG_NAME,
    CropError,
    appTool,
    checkObject,
    cropSections,
    defaultOutput,
    resolvePaths,
)
from PyReconstruct.modules.backend.progress import estimate_remaining, format_remaining
from PyReconstruct.modules.backend.threading import ThreadPool
from PyReconstruct.modules.gui.utils import CompleterBox, getProgbar, notify

from .file_dialog import FileDialog
from .helper import BrowseWidget, resizeLineEdit

## the gap handling of the crop, each on unless unchecked: (cropSections
## keyword, the box's label)
GAP_OPTIONS = [
    ("fill_untraced",
     "A section without the object keeps its image inside the window of the "
     "nearest section with it"),
    ("gray_missing",
     "A section with no image in the zarr gets a mid-gray stand-in in that window"),
    ("check_blank",
     "An image that is all 0 under the object counts as missing"),
    ("match_by_number",
     "When no image name in the series is in the zarr, match the images by the "
     "number in their names"),
    ("full_on_fail",
     "A section where no window keeps any of its pixels keeps its full image"),
]

DEFAULT_RADIUS = 2.0


class CropSettings:
    """The checked inputs of one crop, as cropSections takes them.

        Attributes:
            obj_name (str): the object to crop around
            radius (float): microns kept around the object's bounds
            src_group: the source zarr, open for reading
            scales (list): its scale factors
            out_fp (str): the output zarr, resolved and checked new
            gaps (dict): the gap handling keywords of cropSections
    """

    def __init__(self, obj_name, radius, src_group, scales, out_fp, gaps):
        self.obj_name = obj_name
        self.radius = radius
        self.src_group = src_group
        self.scales = scales
        self.out_fp = out_fp
        self.gaps = gaps


class CropZarrDialog(QDialog):

    def __init__(self, parent : QWidget, series : Series, obj_name : str = ""):
        """Create the dialog.

            Params:
                parent (QWidget): the parent widget
                series (Series): the open series
                obj_name (str): the object to offer first (the one selected
                    in the field), or blank for the first object by name
        """
        super().__init__(parent)
        self.series = series
        self.settings = None
        self.setWindowTitle("Crop Scaled Images")

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.object_box = CompleterBox(self, sorted(series.data["objects"]))
        if obj_name and self.object_box.findText(obj_name) != -1:
            self.object_box.setCurrentText(obj_name)
        form.addRow("Object:", self.object_box)

        self.radius_input = QLineEdit(self, text=f"{DEFAULT_RADIUS:g}")
        resizeLineEdit(self.radius_input, "0" * 10)
        radius_row = QHBoxLayout()
        radius_row.addWidget(self.radius_input)
        radius_row.addWidget(QLabel("microns around the object's bounds, on every side", self))
        radius_row.addStretch()
        form.addRow("Radius:", radius_row)

        src_dir = series.src_dir if _looksLikeZarr(series.src_dir) else ""
        self.source_input = BrowseWidget(self, type="dir", default_fp=src_dir)
        self.source_input.layout().setContentsMargins(0, 0, 0, 0)
        form.addRow("Source zarr:", self.source_input)

        self.output_input = QLineEdit(self)
        self.output_edited = False
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_input)
        browse = QPushButton("Browse", self)
        browse.clicked.connect(self.browseOutput)
        output_row.addWidget(browse)
        form.addRow("Output zarr:", output_row)

        gaps = QGroupBox("Gaps in the data", self)
        gaps_layout = QVBoxLayout()
        self.gap_boxes = {}
        for keyword, label in GAP_OPTIONS:
            box = QCheckBox(label, self)
            box.setChecked(True)
            gaps_layout.addWidget(box)
            self.gap_boxes[keyword] = box
        gaps.setLayout(gaps_layout)

        note = QLabel(
            "Every image keeps its size; the pixels outside the window are set "
            "to 0 and chunks that are all 0 are not stored, so the crop "
            "compresses small. Nothing is deleted. The crop writes "
            f"{LOG_NAME} inside the output, naming the tool: {appTool()}.",
            self,
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Crop")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(gaps)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.setMinimumWidth(640)

        # the output follows the object and the source until it is edited
        self.refreshOutput()
        self.object_box.currentTextChanged.connect(self.refreshOutput)
        self.source_input.le.textChanged.connect(self.refreshOutput)
        self.output_input.textEdited.connect(self.outputEdited)

    def outputEdited(self, text : str):
        """The user typed an output path: keep it, or clear it to start following again."""
        self.output_edited = bool(text.strip())
        if not self.output_edited:
            self.refreshOutput()

    def refreshOutput(self, *args):
        """Offer <stem>_<object>_crop.zarr beside the source, unless the output was edited."""
        if self.output_edited:
            return
        try:
            offered = defaultOutput(self.source_input.text().strip(), self.object_box.currentText())
        except CropError:
            offered = ""
        self.output_input.setText(offered)

    def browseOutput(self):
        """Pick the output path in a save dialog."""
        offered = self.output_input.text().strip()
        response = FileDialog.get(
            "save", self, "Cropped zarr",
            file_name=os.path.basename(offered) if offered else "",
            filter="Zarr Directory (*zarr)",
        )
        if response:
            self.output_input.setText(response)
            self.output_edited = True

    def values(self):
        """Check the inputs the way the crop does and return a CropSettings,
        or say what is wrong and return None. Nothing is written."""
        obj_name = self.object_box.currentText().strip()
        try:
            checkObject(self.series, obj_name)
        except CropError as error:
            notify(str(error))
            return None
        try:
            radius = float(self.radius_input.text())
            if not math.isfinite(radius) or radius < 0:
                raise ValueError(radius)
        except ValueError:
            notify("Enter a radius of zero or more microns.")
            return None
        src_dir = self.source_input.text().strip()
        if not src_dir:
            notify("Choose the source zarr.")
            return None
        try:
            out_fp, src_group, scales = resolvePaths(
                self.series, obj_name, src_dir, self.output_input.text().strip()
            )
        except CropError as error:
            notify(str(error))
            return None
        gaps = {keyword: box.isChecked() for keyword, box in self.gap_boxes.items()}
        return CropSettings(obj_name, radius, src_group, scales, out_fp, gaps)

    def accept(self):
        """Overwritten from QDialog: close only on inputs the crop accepts."""
        settings = self.values()
        if settings is None:
            return
        self.settings = settings
        super().accept()

    def exec(self):
        """Run the dialog. Returns (CropSettings, True) or (None, False)."""
        confirmed = super().exec()
        if confirmed:
            return self.settings, True
        return None, False


def _looksLikeZarr(path : str) -> bool:
    """True when the series' image folder is named as a zarr (defaultOutput's rule)."""
    if not path:
        return False
    try:
        defaultOutput(path, "x")
    except CropError:
        return False
    return True


class CropProgress:
    """The progress dialog of one crop, with Cancel wired to a stop flag.

    Cancel hides a QProgressDialog; this one comes back without its button,
    as a busy bar saying the crop stops after the section being written, so
    the wait for that section is not a blank screen. Closing a
    QProgressDialog emits canceled as well, so close() unhooks the flag
    first: a finished crop is not a stopped one.

        Attributes:
            dialog (QProgressDialog): the dialog, application-modal
            stop (threading.Event): set when Cancel is pressed
    """

    def __init__(self, text : str, stop : threading.Event):
        self.text = text
        self.stop = stop
        self.started = time.monotonic()
        self.dialog = getProgbar(text, cancel=True, window_modality=Qt.ApplicationModal)
        self.dialog.canceled.connect(self.onCancel)

    def onCancel(self):
        """Cancel was pressed: ask the crop to stop, and say so meanwhile."""
        self.stop.set()
        self.dialog.setCancelButton(None)
        self.dialog.setLabelText("Stopping after the section being written...")
        self.dialog.setRange(0, 0)
        self.dialog.show()

    def report(self, percent):
        """Show the percent the crop reports, with an estimate once there is one."""
        if self.stop.is_set():
            return
        # 100 would reset and hide the dialog before the log is written
        self.dialog.setValue(min(int(percent), 99))
        eta = estimate_remaining(time.monotonic() - self.started, percent)
        if eta is not None:
            self.dialog.setLabelText(f"{self.text}\n{format_remaining(eta)}")

    def close(self):
        """Take the dialog down once the crop has ended, however it ended."""
        self.dialog.canceled.disconnect(self.onCancel)
        self.dialog.close()


def cropWithProgress(series : Series, settings : CropSettings, stop : threading.Event = None):
    """Run the crop on a worker thread behind the progress dialog.

    The GUI thread waits in a local event loop, so the window repaints and
    Cancel works, while the worker reads the sections and writes the output.
    Returns the summary lines, ending with the log's path. Raises what the
    crop raised: CropStopped after Cancel, CropError for a refused output,
    SeriesClosedError when the series was closed under it.

        Params:
            series (Series): the series, with its sections saved
            settings (CropSettings): the checked inputs
            stop (threading.Event): the stop flag, when the caller holds it
    """
    if stop is None:
        stop = threading.Event()
    progress = CropProgress(f"Cropping images around {settings.obj_name}...", stop)
    lines = []

    def work(progress):
        return cropSections(
            series, settings.obj_name, settings.radius, settings.src_group,
            settings.scales, settings.out_fp,
            show_progress=False, echo=lines.append, progress=progress,
            should_stop=stop.is_set, jser_fp=series.jser_fp, **settings.gaps,
        )

    pool = ThreadPool()
    worker = pool.createWorker(work, progress=True)
    results, errors = [], []
    loop = QEventLoop()
    # queued, so the slots run on the GUI thread, inside the loop below
    worker.signals.progress.connect(progress.report, Qt.QueuedConnection)
    worker.signals.result.connect(results.append, Qt.QueuedConnection)
    worker.signals.error.connect(errors.append, Qt.QueuedConnection)
    worker.signals.finished.connect(loop.quit, Qt.QueuedConnection)
    try:
        pool.start(worker)
        loop.exec()
        pool.waitForDone()
    finally:
        progress.close()
    if errors:
        raise errors[0][1]
    return lines
