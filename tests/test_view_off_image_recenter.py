"""A saved view that shows no part of the section image is set to the image.

A series can be saved with a view window that lies entirely outside its
image. The reported file carried ``window = [-9.06913, -0.94384, 1, 1]`` on
an image at the origin: opening it, and locating its images, showed a black
field with no image and no trace, and only ``View > Set view to image``
brought both back.

Now the field sets such a view to the image when the series opens and when
its images are located, and says so in the status bar. A view that overlaps
the image at all is kept, so a zoom and position the user chose survive a
reopen, and any view is kept when no image is found, since a series without
images is viewed by its traces.

The window came from the legacy XML import, which kept the lower-left
corner of the Reconstruct viewport and gave it a one-micron size. The import
now writes the window a new series gets, and the import path sets the view
to the image once the series is open, as the other new-series paths do.

The GUI tests open a real ``MainWindow`` on a copy of the fixture series
with a generated image beside it, under the identity alignment the fixture
already carries, so the image sits at the origin.
"""
import json
import sys
import types

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtGui import QColor, QImage

from PyReconstruct.modules.backend.func import xml_json_conversions as conv
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import blank_section, blank_series
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.main.field_widget_7_view import (
    VIEW_OFF_IMAGE_NOTICE,
    viewMissesBounds,
)
from test_field_status_readout import paint_the_field


REPORTED_WINDOW = [-9.06913, -0.94384, 1, 1]

# the generated image: pixels, and microns per pixel, so under the identity
# alignment it covers 7.2 by 4.8 microns from the origin
IMAGE_SIZE = (120, 80)
IMAGE_MAG = 0.06
IMAGE_BOUNDS = (0.0, 0.0, IMAGE_SIZE[0] * IMAGE_MAG, IMAGE_SIZE[1] * IMAGE_MAG)
IDENTITY_ALIGNMENT = "LOCAL_d03"


def write_image(path):
    image = QImage(*IMAGE_SIZE, QImage.Format.Format_RGB32)
    image.fill(QColor(90, 140, 200))
    assert image.save(str(path))


def prepare(series_jser, window, image_dir=None):
    """Save `window` into the fixture series.

    With `image_dir`, every section is pointed at ``image.png`` in that folder
    at IMAGE_MAG, and the series is put on its identity alignment, so the
    image sits at IMAGE_BOUNDS wherever the field opens.
    """
    series = Series.openJser(str(series_jser), progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    try:
        series.window = list(window)
        if image_dir is not None:
            series.src_dir = str(image_dir)
            series.alignment = IDENTITY_ALIGNMENT
            for snum in list(series.sections.keys()):
                section = series.loadSection(snum)
                section.src = "image.png"
                section.mag = IMAGE_MAG
                section.save()
        series.saveJser()
    finally:
        series.close()


def center(window):
    return window[0] + window[2] / 2, window[1] + window[3] / 2


def covers(window, bounds):
    wx, wy, ww, wh = window
    min_x, min_y, max_x, max_y = bounds
    eps = 1e-9
    return (
        wx <= min_x + eps and wy <= min_y + eps
        and wx + ww >= max_x - eps and wy + wh >= max_y - eps
    )


@pytest.fixture
def open_series(qapp, qsettings_snapshot, main_window_dialogs):
    """Open a real `MainWindow` on a jser, torn down as the `main_window`
    fixture does it (see its docstring for why each step matters)."""
    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP,
        ORG,
        current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    previous_excepthook = sys.excepthook
    windows = []

    def _open(jser):
        window = MainWindow(str(jser))
        window._captureListLayout = lambda: None
        windows.append(window)
        return window

    try:
        yield _open
    finally:
        sys.excepthook = previous_excepthook
        for window in windows:
            window.series.modified = False
            window.close()
            window.deleteLater()


# ---- the geometry ---------------------------------------------------------

def test_the_reported_window_misses_an_image_at_the_origin():
    assert viewMissesBounds(REPORTED_WINDOW, IMAGE_BOUNDS)


@pytest.mark.parametrize("window", [
    [1.0, 1.0, 2.0, 1.5],        # inside the image
    [-0.5, -0.5, 1.0, 1.0],      # over the origin corner only
    [-1.0, -1.0, 10.0, 7.0],     # the whole image and more
    [7.0, 4.7, 3.0, 3.0],        # a sliver of the far corner
])
def test_a_window_that_overlaps_the_image_does_not_miss_it(window):
    assert not viewMissesBounds(window, IMAGE_BOUNDS)


@pytest.mark.parametrize("window", [
    [-1.0, 0.0, 1.0, 1.0],       # flush against the left edge
    [0.0, -1.0, 1.0, 1.0],       # flush against the bottom edge
    [7.2, 0.0, 1.0, 1.0],        # flush against the right edge
    [0.0, 4.8, 1.0, 1.0],        # flush against the top edge
    [-3.0, 10.0, 1.0, 1.0],      # beside and above
])
def test_a_window_that_only_touches_or_leaves_the_image_misses_it(window):
    assert viewMissesBounds(window, IMAGE_BOUNDS)


# ---- opening a series -----------------------------------------------------

def test_a_saved_view_outside_the_image_opens_on_the_image(
    series_jser, tmp_path, open_series
):
    write_image(tmp_path / "image.png")
    prepare(series_jser, REPORTED_WINDOW, image_dir=tmp_path)

    window = open_series(series_jser)
    field = window.field

    assert field.section_layer.image_found
    assert field.imageBounds() == pytest.approx(IMAGE_BOUNDS)
    assert covers(field.series.window, IMAGE_BOUNDS)
    assert not field.viewIsOffImage()
    # the notice survives the repaint that follows an open
    paint_the_field(window)
    assert window.statusbar.currentMessage() == VIEW_OFF_IMAGE_NOTICE


@pytest.mark.parametrize("saved", [
    [1.0, 1.0, 2.0, 1.5],        # a zoomed-in view inside the image
    [-0.5, -0.5, 1.0, 1.0],      # a view over one corner of the image
])
def test_a_saved_view_over_any_part_of_the_image_is_kept(
    series_jser, tmp_path, open_series, saved
):
    write_image(tmp_path / "image.png")
    prepare(series_jser, saved, image_dir=tmp_path)

    window = open_series(series_jser)
    field = window.field

    assert field.section_layer.image_found
    assert not viewMissesBounds(saved, field.imageBounds())
    # the open only fits the saved window to the field's size and
    # proportions, which scales it around the same center
    assert center(field.series.window) == pytest.approx(center(saved))
    assert not covers(field.series.window, IMAGE_BOUNDS)
    assert window.statusbar.currentMessage() == ""


def test_a_saved_view_is_kept_when_the_series_has_no_image(
    series_jser, open_series
):
    prepare(series_jser, REPORTED_WINDOW)

    window = open_series(series_jser)
    field = window.field

    assert not field.section_layer.image_found
    assert field.imageBounds() is None
    assert not field.viewIsOffImage()
    assert center(field.series.window) == pytest.approx(center(REPORTED_WINDOW))
    assert window.statusbar.currentMessage() == ""


# ---- locating the images --------------------------------------------------

def test_locating_the_images_sets_an_outside_view_to_the_image(
    series_jser, tmp_path, open_series
):
    images = tmp_path / "images"
    images.mkdir()
    write_image(images / "image.png")
    # the series points at a folder that is gone, and the image is not beside
    # the jser either, so it opens with no image and the view where it was
    prepare(series_jser, REPORTED_WINDOW, image_dir=tmp_path / "elsewhere")

    window = open_series(series_jser)
    field = window.field
    assert not field.section_layer.image_found
    assert center(field.series.window) == pytest.approx(center(REPORTED_WINDOW))

    window.changeSrcDir(str(images))

    assert field.section_layer.image_found
    assert covers(field.series.window, IMAGE_BOUNDS)
    assert not field.viewIsOffImage()
    paint_the_field(window)
    assert window.statusbar.currentMessage() == VIEW_OFF_IMAGE_NOTICE


def test_locating_the_images_keeps_a_view_that_overlaps_them(
    series_jser, tmp_path, open_series
):
    images = tmp_path / "images"
    images.mkdir()
    write_image(images / "image.png")
    saved = [1.0, 1.0, 2.0, 1.5]
    prepare(series_jser, saved, image_dir=tmp_path / "elsewhere")

    window = open_series(series_jser)
    field = window.field
    assert not field.section_layer.image_found

    window.changeSrcDir(str(images))

    assert field.section_layer.image_found
    assert center(field.series.window) == pytest.approx(center(saved))
    assert not covers(field.series.window, IMAGE_BOUNDS)
    assert window.statusbar.currentMessage() == ""


# ---- the writer: the legacy XML import -----------------------------------

def test_the_xml_import_writes_the_new_series_window(monkeypatch, tmp_path):
    """The viewport corner with a one-micron size was the reported window."""
    legacy = types.SimpleNamespace(
        index=0, viewport=(-9.06913, -0.94384, 0.00254), contours=[], zcontours=[]
    )
    monkeypatch.setattr(conv, "process_series_file", lambda fp: legacy)

    out = conv.seriesXMLToJSON("legacy.ser", [], str(tmp_path))

    with open(out) as f:
        written = json.load(f)
    assert written["window"] == [0, 0, 1, 1]


def _write_legacy_series(folder):
    """A one-section Reconstruct series whose image is beside it, with the
    reported viewport."""
    (folder / "S.ser").write_text(
        blank_series.replace("[SECTION_NUM]", "1")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "1")
        .replace("[LASTTHUMBSECTION]", "1")
        .replace('viewport="0 0 0.00254"', 'viewport="-9.06913 -0.94384 0.00254"')
    )
    (folder / "S.1").write_text(
        blank_section.replace("[SECTION_INDEX]", "1")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[TRANSFORM_DIM]", "3")
        .replace("[XCOEF]", "0 1 0 0 0 0")
        .replace("[YCOEF]", "0 0 1 0 0 0")
        .replace("[IMAGE_MAG]", str(IMAGE_MAG))
        .replace("[IMAGE_SOURCE]", "image.png")
        .replace("[IMAGE_LENGTH]", str(IMAGE_SIZE[0]))
        .replace("[IMAGE_HEIGHT]", str(IMAGE_SIZE[1]))
    )
    write_image(folder / "image.png")
    return folder / "S.ser"


def test_a_series_imported_from_xml_opens_on_its_image(
    main_window, main_window_dialogs, tmp_path, monkeypatch
):
    """The import flow, end to end, as a user at the screen sees it.

    An imported series has no image folder yet, so opening it asks where the
    images are; the recorder answers yes and names the legacy folder. The
    series code is detected from the name, so that prompt confirms it, and
    the save-as prompt at the end is answered with no file.
    """
    from PySide6.QtWidgets import QMessageBox

    from PyReconstruct.modules.gui.utils import utils as gui_utils

    folder = tmp_path / "xml"
    folder.mkdir()
    ser = _write_legacy_series(folder)
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    main_window_dialogs.message_box_response = QMessageBox.Yes
    main_window_dialogs.file_responses.append(str(folder))

    main_window.newFromXML(str(ser))
    field = main_window.field

    assert main_window.series.name == "S"
    assert field.section_layer.image_found
    assert field.imageBounds() == pytest.approx(IMAGE_BOUNDS)
    assert covers(field.series.window, IMAGE_BOUNDS)
