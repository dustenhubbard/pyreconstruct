"""Offer a zarr's image names to a series that names its images another way.

Opened from the image folder change when the chosen zarr holds none of the
series' image names and every section pairs with one image there by the
number in its name (backend.image_name_match). The dialog lists the pairs,
draws a few sections' traces over the images they would get, and asks before
anything is applied. The zarr is read and never written.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QAbstractItemView,
)

from PyReconstruct.modules.datatypes import Series, Section
from PyReconstruct.modules.backend.image_name_match import plural, spans
from PyReconstruct.modules.backend.view.section_layer import SectionLayer


def previewSections(section_numbers, renumbered, limit : int = 3):
    """The sections to draw: the renumbered ones first, then first, middle, last.

    A section whose image name's number is not its section number is the one
    a wrong pairing would show, so it is drawn before the regular picks.

        Params:
            section_numbers (iterable): every section number in the match
            renumbered (iterable): the sections numbered unlike their image
            limit (int): how many sections to draw
        Returns:
            (list): section numbers, in the order to draw them
    """
    ordered = sorted(section_numbers)
    if not ordered:
        return []
    picks = []
    for snum in list(renumbered) + [ordered[0], ordered[len(ordered) // 2], ordered[-1]]:
        if snum not in picks:
            picks.append(snum)
        if len(picks) == limit:
            break
    return picks


def renderPreview(series : Series, snum : int, image_name : str, width : int):
    """A section's traces drawn over one of the zarr's images, framed whole.

    Works on a fresh copy of the section, so the name is changed in memory
    only and nothing is saved. The series' view (window, screen mag) is left
    as it was.

        Params:
            series (Series): the series, with src_dir already the zarr
            snum (int): the section number
            image_name (str): the image name in the zarr to draw it over
            width (int): the width of the picture in pixels
        Returns:
            (QPixmap): the picture, or None when the image cannot be read
    """
    section = series.loadSection(snum)
    section.src = Section.imageName(image_name)
    saved_window, saved_mag = series.window, series.screen_mag
    try:
        layer = SectionLayer(section, series)
        if not layer.image_found:
            return None
        mag, tform = section.mag, section.tform
        corners = [tform.map(x * mag, y * mag) for x, y in layer.base_corners]
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0, max(ys) - y0
        if w <= 0 or h <= 0:
            return None
        height = max(1, round(width * h / w))
        # the field keeps one pixels-per-unit ratio on both axes, so the
        # window's height follows the picture's
        window = [x0, y0, w, height * w / width]
        return layer.generateView((width, height), window)
    finally:
        series.window, series.screen_mag = saved_window, saved_mag


def _noImage(width : int, height : int) -> QPixmap:
    """A gray picture saying the image could not be read."""
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(80, 80, 80))
    painter = QPainter(pixmap)
    painter.setPen(Qt.white)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "image not readable")
    painter.end()
    return pixmap


class MatchImageNamesDialog(QDialog):

    PREVIEWS = 3
    PREVIEW_WIDTH = 240

    def __init__(self, parent, series : Series, series_names : dict, match : dict, zarr_dir : str):
        """Create the dialog.

            Params:
                parent (QWidget): the parent widget
                series (Series): the series, with src_dir already the zarr
                series_names (dict): section number: the series' image name
                match (dict): the match from matchByNumber
                zarr_dir (str): the zarr folder
        """
        super().__init__(parent)
        self.setWindowTitle("Match Image Names")
        self.series = series
        self.match = match
        zarr_name = os.path.basename(os.path.normpath(zarr_dir))
        names = match["names"]

        vlayout = QVBoxLayout()
        vlayout.addWidget(QLabel(
            self,
            text=(
                f"No section image in this series is in {zarr_name}.\n"
                "Every section matches one image there by the number in its image name.\n"
                "Use the names below in this series? The zarr is not changed, and the\n"
                "series file changes when you save."
            ),
        ))

        table = QTableWidget(len(names), 3, self)
        table.setHorizontalHeaderLabels(["Section", "In this series", f"In {zarr_name}"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        for row, snum in enumerate(sorted(names)):
            for column, text in enumerate((str(snum), series_names[snum], names[snum])):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(140)
        vlayout.addWidget(table)
        self.table = table

        renumbered = match["renumbered"]
        if renumbered:
            warning = QLabel(
                self,
                text=(
                    f"On {plural(len(renumbered), 'section')} ({spans(renumbered, 4)}) the "
                    "number in the image name is not the section number. Check those "
                    "sections below."
                ),
            )
            warning.setWordWrap(True)
            vlayout.addWidget(warning)

        vlayout.addWidget(QLabel(self, text="Traces over the proposed images:"))
        previews = QHBoxLayout()
        self.preview_sections = previewSections(names, renumbered, self.PREVIEWS)
        self.previews = {}
        for snum in self.preview_sections:
            column = QVBoxLayout()
            caption = QLabel(self, text=f"Section {snum}\n{names[snum]}")
            caption.setAlignment(Qt.AlignCenter)
            column.addWidget(caption)
            pixmap = renderPreview(series, snum, names[snum], self.PREVIEW_WIDTH)
            if pixmap is None:
                pixmap = _noImage(self.PREVIEW_WIDTH, self.PREVIEW_WIDTH * 3 // 4)
            picture = QLabel(self)
            picture.setPixmap(pixmap)
            picture.setAlignment(Qt.AlignCenter)
            column.addWidget(picture)
            column.addStretch()
            previews.addLayout(column)
            self.previews[snum] = pixmap
        vlayout.addLayout(previews)

        buttonbox = QDialogButtonBox(self)
        buttonbox.addButton("Use these names", QDialogButtonBox.AcceptRole)
        buttonbox.addButton(QDialogButtonBox.Cancel)
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.reject)
        vlayout.addWidget(buttonbox)

        self.setLayout(vlayout)
