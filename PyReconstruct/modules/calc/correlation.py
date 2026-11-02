"""Translation from masked, normalized image correlation."""
import numpy as np


def correlate(
    image1: np.ndarray,
    image2: np.ndarray,
    *,
    dark_cutoff: int = 5,
    bright_cutoff: int = 250,
) -> tuple[int, int] | None:
    """Return the pixel shift of image1 onto image2, or None for a weak match.

    Intensities at or outside the cutoffs are excluded. Each candidate shift
    uses the mean and variance of its shared valid pixels, so a fold, tear or
    padded image edge cannot contribute to the score.
    """
    # Deferred because scipy is needed only when alignment is requested.
    from scipy.signal import correlate as cross_correlate

    if not 0 <= dark_cutoff < bright_cutoff <= 255:
        raise ValueError("Correlation cutoffs must satisfy 0 <= dark < bright <= 255.")

    images = []
    masks = []
    for image in (image1, image2):
        image = np.asarray(image, dtype=np.float64)
        if image.ndim == 3:
            image = image.mean(axis=2)
        if image.ndim != 2:
            raise ValueError("Correlation needs grayscale or RGB images.")
        mask = np.isfinite(image) & (image > dark_cutoff) & (image < bright_cutoff)
        if mask.sum() < 64:
            return None
        # Center before the FFT to limit cancellation in the local variance.
        images.append(np.where(mask, image - image[mask].mean(), 0))
        masks.append(mask.astype(np.float64))

    a, b = images
    ma, mb = masks

    def cross(left, right):
        return cross_correlate(left, right, mode="full", method="fft")

    count = np.maximum(np.rint(cross(ma, mb)), 0)
    divisor = np.maximum(count, 1)
    sum_a = cross(a, mb)
    sum_b = cross(ma, b)
    covariance = cross(a, b) - sum_a * sum_b / divisor
    variance_a = np.maximum(cross(a * a, mb) - sum_a * sum_a / divisor, 0)
    variance_b = np.maximum(cross(ma, b * b) - sum_b * sum_b / divisor, 0)
    denominator = np.sqrt(variance_a * variance_b)

    # Tiny overlaps can give perfect scores by chance. Require 64 pixels and
    # 30% of the smaller valid region before considering a candidate.
    enough_overlap = count >= max(64, 0.3 * min(ma.sum(), mb.sum()))
    # FFT roundoff can leave a positive variance in a constant overlap.
    # Scale the tolerance to the image rather than accepting that false peak.
    tolerance = max(1e-12, 1000 * np.finfo(float).eps * denominator.max())
    scores = np.full(count.shape, -np.inf)
    np.divide(covariance, denominator, out=scores,
              where=enough_overlap & (denominator > tolerance))
    peak_y, peak_x = np.unravel_index(np.argmax(scores), scores.shape)
    # A normalized coefficient below 0.3 does not support an automatic shift.
    if scores[peak_y, peak_x] < 0.3:
        return None

    return int(b.shape[1] - 1 - peak_x), int(b.shape[0] - 1 - peak_y)
