"""`Optimize...` renders sections at the mean and standard deviation asked for.

`adjustPixelsToStats` used to assume brightness shifts every pixel by the same
fraction of the mean and contrast stretches linearly by `1 + c/20`. Neither is
how `ImageLayer` draws them: positive brightness blends toward white, and
positive contrast composites the image onto itself in Overlay mode. With a
target of 128/60, an image at 63/20 rendered at 253/22 and one at 100/20 at
172/40. These tests measure the image `ImageLayer.generateImageLayer` actually
draws after `optimizeSeriesBC`.
"""
import cv2
import numpy as np
import pytest
from PySide6.QtGui import QImage

from PyReconstruct.modules.backend.view.image_layer import ImageLayer
from PyReconstruct.modules.backend.view.optimize_bc import (
    adjustPixelsToStats,
    applyContrastAndBrightness,
    optimizeSeriesBC,
)
from PyReconstruct.modules.datatypes import Transform

MEAN_TOLERANCE = 5
STD_TOLERANCE = 3
# An image with a std of 10 or less needs four or more Overlay passes, and one
# contrast step moves it a long way. Checked over every whole-number pair, the
# closest these two can get is about 8 and 5.5 from the target mean.
FLAT_MEAN_TOLERANCE = 9
FLAT = {"very_dark_flat", "gray_flat"}

# (distribution, input mean, input std, target mean, target std)
CASES = {
    "dark": ("gauss", 63, 20, 128, 60),
    "dim": ("gauss", 100, 20, 128, 60),
    "bright": ("gauss", 190, 20, 128, 60),
    "very_dark_flat": ("gauss", 30, 10, 128, 60),
    "very_bright_flat": ("gauss", 220, 15, 128, 60),
    "gray_flat": ("gauss", 128, 5, 128, 60),
    "too_much_contrast": ("bimodal", 128, 90, 128, 60),
    "other_target": ("gauss", 150, 30, 90, 40),
}


def _image(kind, mean, std):
    rng = np.random.default_rng(0)
    if kind == "gauss":
        a = rng.normal(mean, std, (256, 256))
    else:
        a = np.where(rng.random((256, 256)) < 0.5, mean - std, mean + std)
    return np.clip(np.round(a), 0, 255).astype(np.uint8)


def _rendered(section, series):
    """The grayscale pixels ImageLayer draws for the whole image."""
    layer = ImageLayer(section, series)
    assert layer.image_found
    w, h, mag = layer.bw, layer.bh, section.mag
    image = layer.generateImageLayer((w, h), [0, 0, w * mag, h * mag]).toImage()
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    arr = np.frombuffer(gray.constBits(), np.uint8, gray.sizeInBytes())
    arr = arr.reshape(gray.height(), gray.bytesPerLine())[:, : gray.width()].copy()
    # the brightness polygon does not always cover the top row and left column
    return arr[1:, 1:].astype(np.float64)


@pytest.fixture
def image_section(qapp, real_series, tmp_path):
    """Put a generated image on the first section and return a writer for it."""
    src = tmp_path / "images"
    src.mkdir()
    real_series.src_dir = str(src)
    snum = sorted(real_series.sections)[0]

    def place(pixels):
        cv2.imwrite(str(src / "img.png"), pixels)
        section = real_series.loadSection(snum)
        section.src = "img.png"
        section.tform = Transform.identity()
        section.brightness, section.contrast = 0, 0
        section.save()
        return snum

    return place


@pytest.mark.parametrize("case", list(CASES))
def test_optimized_section_renders_at_the_target(real_series, image_section, case):
    kind, mean, std, target_mean, target_std = CASES[case]
    snum = image_section(_image(kind, mean, std))

    optimizeSeriesBC(real_series, target_mean, target_std, section_nums=[snum])

    section = real_series.loadSection(snum)
    pixels = _rendered(section, real_series)
    detail = (
        f"b={section.brightness} c={section.contrast} rendered "
        f"{pixels.mean():.1f}/{pixels.std():.1f}, target {target_mean}/{target_std}"
    )
    mean_tolerance = FLAT_MEAN_TOLERANCE if case in FLAT else MEAN_TOLERANCE
    assert abs(pixels.mean() - target_mean) < mean_tolerance, detail
    assert abs(pixels.std() - target_std) < STD_TOLERANCE, detail


@pytest.mark.parametrize("brightness", [-70, -25, 0, 25, 70])
@pytest.mark.parametrize("contrast", [-60, -15, 0, 10, 30, 50, 75])
def test_model_matches_what_image_layer_draws(real_series, image_section, brightness, contrast):
    """The curve the search scores is the one ImageLayer paints."""
    pixels = _image("gauss", 128, 40)
    snum = image_section(pixels)
    section = real_series.loadSection(snum)
    section.brightness, section.contrast = brightness, contrast

    drawn = _rendered(section, real_series)
    modeled = applyContrastAndBrightness(pixels[1:, 1:], brightness, contrast)

    assert abs(drawn.mean() - modeled.mean()) < 1.5
    assert abs(drawn.std() - modeled.std()) < 1.5


def test_flat_image_sets_brightness_only():
    b, c = adjustPixelsToStats(np.full((8, 8), 64, np.uint8), 128, 60)
    assert c is None
    assert abs(applyContrastAndBrightness(64, b, 0) - 128) < 2
