import os
from types import SimpleNamespace

import cv2
import zarr
import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPolygon

from PyReconstruct.modules.datatypes import Series, Section
from .image_layer import ImageLayer
from .section_layer import SectionLayer

# Brightness and contrast are whole numbers from -100 to 100 (the field clamps
# them there). ImageLayer paints brightness as a white or black blend and then
# contrast as Overlay passes of the image onto itself or a gray blend, all in
# QPainter's 8-bit integer arithmetic. Every step acts on each pixel by its
# level alone, so a strip of the 256 levels painted once per setting gives
# lookup tables that match the render exactly, rounding included.
SETTINGS = np.arange(-100, 101)
_tables = None


def _paintStrip(brightness, contrast):
    """Paint the 256 levels with ImageLayer's own brightness and contrast code."""
    levels = np.arange(256, dtype=np.uint8).reshape(1, 256).copy()
    gray = QImage(levels.data, 256, 1, 256, QImage.Format.Format_Grayscale8)
    strip = gray.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    # the polygon reaches past the strip so its outline never lands on it
    layer = SimpleNamespace(
        section=SimpleNamespace(brightness=brightness, contrast=contrast),
        bc_poly=QPolygon([QPoint(-4, -4), QPoint(-4, 5), QPoint(260, 5), QPoint(260, -4)]),
    )
    ImageLayer._drawBrightness(layer, strip)
    ImageLayer._drawContrast(layer, strip)
    rgba = strip.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(rgba.constBits(), np.uint8, rgba.sizeInBytes())[:1024:4].copy()


def _lookupTables():
    """Return the brightness and contrast tables, one row of 256 levels per setting."""
    global _tables
    if _tables is None:
        bright = np.array([_paintStrip(int(b), 0) for b in SETTINGS])
        contrast = np.array([_paintStrip(0, int(c)) for c in SETTINGS])
        _tables = bright, contrast
    return _tables


def applyContrastAndBrightness(levels, brightness : int, contrast : int):
    """Return levels (0-255) as ImageLayer renders them with this brightness and contrast.

        Params:
            levels (array): pixel values from 0 to 255
            brightness (int): the brightness setting (-100 to 100)
            contrast (int): the contrast setting (-100 to 100)
    """
    bright, contrast_table = _lookupTables()
    curve = contrast_table[contrast + 100][bright[brightness + 100]]
    pixels = np.clip(np.rint(np.asarray(levels, dtype=np.float64)), 0, 255)
    return curve[pixels.astype(np.intp)].astype(np.float64)


def adjustPixelsToStats(image, desired_mean, desired_std):
    """Find the brightness and contrast that render an image closest to a mean and standard deviation.

    Every whole-number pair from -100 to 100 is scored on the image's histogram
    with the lookup tables above, and the closest one wins.

    Params:
        image (array): image as numpy array
        desired_mean (float): The target mean for the adjusted pixels.
        desired_std (float): The target standard deviation for the adjusted pixels.

    Returns:
        brightness (int): The brightness setting (-100 to 100), None when the
            image is empty or all black (a window with no image in it).
        contrast (int): The contrast setting (-100 to 100), 0 for a flat image,
            None along with brightness.
    """
    pixels = np.clip(np.rint(np.asarray(image, dtype=np.float64)), 0, 255)
    if pixels.size == 0 or not pixels.any():
        return None, None
    weights = np.bincount(pixels.astype(np.intp).ravel(), minlength=256) / pixels.size

    def score(curves):
        # a plain weighted sum, not a matrix product: on a busy machine the
        # threaded matrix product took about 20 ms a call, this takes 0.1 ms
        mean = (curves * weights).sum(axis=1)
        var = (curves * curves * weights).sum(axis=1) - mean ** 2
        std = np.sqrt(np.maximum(var, 0))
        return (mean - desired_mean) ** 2 + (std - desired_std) ** 2

    bright, contrast_table = _lookupTables()
    bright = bright.astype(np.intp)
    # a flat image has no spread for contrast to act on
    if np.std(pixels) < 1e-6:
        return int(SETTINGS[np.argmin(score(bright.astype(np.float64)))]), 0

    best = (np.inf, 0, 0)
    for c, table in zip(SETTINGS, contrast_table.astype(np.float64)):
        # one row per brightness setting, brightness first and then contrast
        errors = score(table[bright])
        i = int(np.argmin(errors))
        if errors[i] < best[0]:
            best = (errors[i], int(SETTINGS[i]), int(c))

    return best[1], best[2]

def optimizeSectionBC(section : Section, desired_mean=128, desired_std=60, window=None, lowest_res=True):
    """Optimize the brightness and contrast of the image for a single section.
    
        Params:
            section (Section): the section to optimize the brightness and contrast for
            desired_mean (int): the desired pixel average
            desired_std (float): the desired pixel standard deviation
            window (list): the x, y, w, h window (None if using full images)
    """
    # make sure the image exists
    fp = section.src_fp
    if not (os.path.isfile(fp) or os.path.isdir(fp)):
        return
    
    # get the image array
    if window is None:
        try:
            if os.path.isfile(fp):
                image = cv2.imread(fp, cv2.IMREAD_GRAYSCALE)
            else:  # get the smallest image if using a zarr
                if lowest_res:
                    scale_zg = f"scale_{max(section.zarr_scales)}"
                else:
                    scale_zg = f"scale_{min(section.zarr_scales)}"
                fp = os.path.join(
                    section.series.src_dir,
                    scale_zg,
                    section.src
                )
                image = zarr.open(fp, "r")[:]
            cv2.resize(image, (1024, 1024))
        except:
            print(f"Image at {fp} is corrupt. Skipping...")
            return
    else:
        slayer = SectionLayer(section, section.series)
        pixmap_dim = round(window[2] / section.mag), round(window[3] / section.mag)
        b, c = section.brightness, section.contrast
        section.brightness, section.contrast = 0, 0  # reset the brightness and contrast
        image = slayer.generateImageArray(pixmap_dim, window, get_crop_only=True)
        section.brightness, section.contrast = b, c

    # get desired brightness and contrast
    new_brightness, new_contrast = adjustPixelsToStats(
        image,
        desired_mean,
        desired_std
    )
    if new_brightness is not None:
        section.brightness = new_brightness
    if new_contrast is not None:
        section.contrast = new_contrast
    
def optimizeSeriesBC(series : Series, desired_mean=128, desired_std=60, section_nums=None, window=None):
    """Optimize the brightness and contrast of the images for a series.
    
        Params:
            series (Series): the series to optimize the brightness and contrast for
            desired_mean (int): the desired pixel average
            desired_std (float): the desired pixel standard deviation
            section_nums (list): the section numbers to optimize (None for every section)
            window (list): the x, y, w, h window (None if using full images)
    """
    for snum, section in series.enumerateSections():
        if section_nums is None or snum in section_nums:
            optimizeSectionBC(section, desired_mean, desired_std, window)
            section.save()
    
        

