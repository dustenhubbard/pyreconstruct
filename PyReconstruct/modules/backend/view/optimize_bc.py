import os
import cv2
import zarr
import numpy as np

from PyReconstruct.modules.datatypes import Series, Section
from .section_layer import SectionLayer

# Brightness and contrast are whole numbers from -100 to 100 (the field clamps
# them there), and ImageLayer draws them in this order:
#   brightness b >= 0: white over the image at opacity b/100
#   brightness b < 0:  black over the image at opacity |b|/100
#   contrast c >= 0:   the image composited onto itself in Overlay mode c/20
#                      times (the fraction as one pass at partial opacity)
#   contrast c < 0:    gray 128 over the image at opacity |c|/100
# Overlay of an image onto itself is not a linear stretch. It maps a level x
# (0-1) to 2x^2 below 0.5 and 1 - 2(1-x)^2 above, an S-curve around 128.
# QPainter stores whole levels after every pass, so the curves round there
# too; on a low contrast image that needs four or five passes it adds up.
LEVELS = np.arange(256, dtype=np.float64)
SETTINGS = np.arange(-100, 101)


def _overlay(levels):
    """Composite levels (0-255) onto themselves in Overlay mode."""
    x = levels / 255
    return np.rint(np.where(x < 0.5, 2 * x * x, 1 - 2 * (1 - x) ** 2) * 255)


def _brightnessCurves():
    """Return every brightness setting's level curve, one row per setting."""
    b = SETTINGS[:, None] / 100
    return np.rint(np.where(
        b >= 0,
        LEVELS + (255 - LEVELS) * b,
        LEVELS * (1 + b),
    ))


def applyContrastAndBrightness(levels, brightness : int, contrast : int):
    """Return levels (0-255) as ImageLayer renders them with this brightness and contrast.

        Params:
            levels (array): pixel values from 0 to 255
            brightness (int): the brightness setting (-100 to 100)
            contrast (int): the contrast setting (-100 to 100)
    """
    x = np.asarray(levels, dtype=np.float64)
    b = brightness / 100
    x = np.rint(x + (255 - x) * b if b >= 0 else x * (1 + b))
    if contrast >= 0:
        passes = contrast / 20
        for _ in range(int(passes)):
            x = _overlay(x)
        opacity = passes % 1
        if opacity > 0:
            x = x + (_overlay(x) - x) * opacity
    else:
        opacity = abs(contrast) / 100
        x = x * (1 - opacity) + 128 * opacity
    return x


def adjustPixelsToStats(image, desired_mean, desired_std):
    """Find the brightness and contrast that render an image closest to a mean and standard deviation.

    Every whole-number pair from -100 to 100 is scored on the image's histogram
    with the same curves ImageLayer draws, and the closest one wins.

    Params:
        image (array): image as numpy array
        desired_mean (float): The target mean for the adjusted pixels.
        desired_std (float): The target standard deviation for the adjusted pixels.

    Returns:
        brightness (int): The brightness setting (-100 to 100), None for an empty image.
        contrast (int): The contrast setting (-100 to 100), None if the image has
            no spread for contrast to act on.
    """
    pixels = np.clip(np.rint(np.asarray(image, dtype=np.float64)), 0, 255)
    if pixels.size == 0:
        return None, None
    weights = np.bincount(pixels.astype(np.intp).ravel(), minlength=256) / pixels.size
    flat = np.std(pixels) < 1e-6

    def score(curves):
        # a plain weighted sum, not a matrix product: on a busy machine the
        # threaded matrix product took about 20 ms a call, this takes 0.1 ms
        mean = (curves * weights).sum(axis=1)
        var = (curves * curves * weights).sum(axis=1) - mean ** 2
        std = np.sqrt(np.maximum(var, 0))
        return (mean - desired_mean) ** 2 + (std - desired_std) ** 2

    # one row per brightness setting, after brightness and before contrast
    bright = _brightnessCurves()
    if flat:
        return int(SETTINGS[np.argmin(score(bright))]), None

    # the curves after 0 to 5 full Overlay passes
    passes = [bright]
    for _ in range(5):
        passes.append(_overlay(passes[-1]))

    best = (np.inf, 0, 0)
    for c in SETTINGS:
        if c >= 0:
            full, opacity = divmod(c, 20)
            curves = passes[full]
            if opacity:
                curves = curves + (passes[full + 1] - curves) * (opacity / 20)
        else:
            opacity = -c / 100
            curves = bright * (1 - opacity) + 128 * opacity
        errors = score(curves)
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
    
        

