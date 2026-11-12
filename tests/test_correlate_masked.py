"""Correlation uses intact tissue and refuses unsupported shifts."""
import numpy as np
import pytest
from scipy.ndimage import gaussian_filter, shift

from PyReconstruct.modules.calc.correlation import correlate


def tissue(seed=1046, shape=(80, 96)):
    rng = np.random.default_rng(seed)
    image = gaussian_filter(rng.normal(size=shape), 0.7)
    return np.clip(100 + image * 8, 60, 125).astype(np.uint8)


@pytest.mark.parametrize("flaw", ["fold", "tear", "edge"])
def test_recovers_known_shift_despite_flaws(flaw):
    previous = tissue()
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    if flaw == "fold":
        previous[:, 20:35] = 0
        current[:, 44:59] = 0
    elif flaw == "tear":
        previous[15:30] = 255
        current[40:55] = 255
    else:
        previous[:, :25] = 0
        current[:, :25] = 0

    assert correlate(current, previous) == (7, -4)

@pytest.mark.parametrize("value", [0, 100, 255])
def test_constant_or_fully_masked_images_have_no_match(value):
    image = np.full((80, 96), value, dtype=np.uint8)
    assert correlate(image, image) is None


def test_unrelated_tissue_has_no_match():
    assert correlate(tissue(1), tissue(2)) is None


@pytest.mark.parametrize("dy,dx", [(0, 0), (5, 9), (-6, -8), (4, -7), (0, 55)])
def test_shift_direction_and_normalization(dy, dx):
    previous = tissue()
    current = shift(previous.astype(float) * 1.4 + 25, (dy, dx),
                    order=0, mode="constant", cval=0)
    assert correlate(current, previous) == (-dx, -dy)


def test_rgb_images():
    previous = np.repeat(tissue()[:, :, None], 3, axis=2)
    current = shift(previous, (-3, 5, 0), order=0, mode="constant", cval=0)
    assert correlate(current, previous) == (-5, 3)


def test_custom_cutoffs_mask_unsaturated_flaws():
    previous = tissue()
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    previous[:, 20:40] = 20
    current[:, 48:68] = 20
    previous[15:30] = 220
    current[45:60] = 220
    assert correlate(current, previous, dark_cutoff=25, bright_cutoff=215) == (7, -4)


def test_tiny_valid_region_is_not_enough_to_align():
    image = np.zeros((80, 96), dtype=np.uint8)
    image[20:25, 20:25] = tissue(shape=(5, 5))
    assert correlate(image, image) is None


@pytest.mark.parametrize("cutoffs", [(-1, 250), (5, 256), (100, 100), (200, 50)])
def test_invalid_cutoffs_are_rejected(cutoffs):
    with pytest.raises(ValueError, match="cutoffs"):
        correlate(tissue(), tissue(), dark_cutoff=cutoffs[0], bright_cutoff=cutoffs[1])


def test_flat_overlap_does_not_outscore_the_textured_match():
    previous = np.full((96, 128), 100, dtype=np.uint8)
    rng = np.random.default_rng(6)
    previous[30:55, 40:70] = rng.integers(90, 110, size=(25, 30))
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    assert correlate(current, previous) == (7, -4)


def test_noisy_tissue_still_aligns():
    previous = tissue()
    noise = np.random.default_rng(10).normal(0, 4, previous.shape)
    current = shift(previous + noise, (4, -7), order=0, mode="constant", cval=0)
    assert correlate(current, previous) == (7, -4)


@pytest.mark.parametrize("shape", [(80, 96), (128, 128), (512, 512)])
@pytest.mark.parametrize("pattern", ["gradient", "stripes", "tiles"])
def test_ambiguous_patterns_have_no_match(shape, pattern):
    image = ambiguous_pattern(pattern, shape)
    assert correlate(image, image) is None


def ambiguous_pattern(pattern, shape=(80, 96)):
    y, x = np.indices(shape)
    if pattern == "gradient":
        return (60 + x * 100 / shape[1]).astype(np.uint8)
    if pattern == "stripes":
        return (100 + 20 * np.sin(x * 2 * np.pi / 16)).astype(np.uint8)
    tile = np.random.default_rng(1132).integers(60, 160, size=(8, 8), dtype=np.uint8)
    return tile[y % 8, x % 8]


def test_nearly_repeating_pattern_with_flaws_has_no_match():
    previous = ambiguous_pattern("tiles").astype(float)
    previous += np.random.default_rng(1132).normal(0, 1, previous.shape)
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    previous[:, 20:35] = 0
    current[:, 44:59] = 255
    assert correlate(current, previous) is None


def test_smooth_unique_tissue_still_aligns():
    image = gaussian_filter(np.random.default_rng(1132).normal(size=(80, 96)), 2)
    previous = 100 + image * 20
    current = shift(previous, (4, -7), order=0, mode="constant", cval=0)
    assert correlate(current, previous) == (7, -4)
