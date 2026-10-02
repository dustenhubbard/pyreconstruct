"""Screenshot comparison for the visual regression tests.

A test renders a widget, grabs it, and hands the image to ``check_image``,
which compares it against a reference image committed under
``tests/visual_baselines/<platform>/``. The tests themselves live in
``tests/test_visual_regression.py``.

Why a baseline per platform: text is drawn by FreeType on Linux and by
CoreText on macOS, so the same dialog never matches pixel for pixel across the
two. CI runs on Linux, so ``linux`` is the set that is committed and gated. Any
other platform with no baseline folder skips these tests with a reason; on
Linux a missing folder fails them.

Tolerance, in two parts:

* ``CHANNEL_TOLERANCE``: a pixel counts as changed only when one of its color
  channels moves by more than this (out of 255). Antialiased edges and text
  shift by a few steps between CPUs and runner images; a wrong color moves a
  channel by far more.
* ``MAX_CHANGED_FRACTION``: the share of pixels allowed to change before the
  test fails. Small enough that recoloring a single one pixel trace outline
  fails it (see ``test_one_recolored_trace_fails_the_field_check``).

The image size must match exactly. A dialog that grows by a pixel has changed
layout, and that is worth a look.

Updating baselines:

* Locally: ``make baselines`` (or ``pytest tests/test_visual_regression.py
  --update-baselines``) writes the current platform's images and passes.
* For CI: every failing check writes ``<name>.png`` (what was rendered),
  ``<name>.expected.png`` and ``<name>.diff.png`` (changed pixels in magenta)
  to ``tests/visual_diffs/``, and the tests workflow uploads that folder as
  the ``visual-diffs`` artifact. When a change to the screen is intended,
  download it and copy the rendered images over the Linux baselines with
  ``python tests/visual_regression.py accept <artifact folder>``, which skips
  the expected and diff images.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
BASELINE_ROOT = TESTS_DIR / "visual_baselines"
DIFF_DIR = Path(os.environ.get("PYRECON_VISUAL_DIFF_DIR", TESTS_DIR / "visual_diffs"))

CHANNEL_TOLERANCE = 40
MAX_CHANGED_FRACTION = 0.0002

_SUFFIXES = (".expected.png", ".diff.png")


def platform_key() -> str:
    """The baseline folder for this platform: linux, darwin or win32."""
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def baseline_dir() -> Path:
    return BASELINE_ROOT / platform_key()


def image_to_array(image):
    """A QImage as an (h, w, 3) uint8 array, alpha dropped."""
    from PySide6.QtGui import QImage

    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    height, width = rgb.height(), rgb.width()
    stride = rgb.bytesPerLine()
    buffer = np.frombuffer(rgb.constBits(), dtype=np.uint8, count=stride * height)
    rows = buffer.reshape(height, stride)[:, : width * 3]
    return rows.reshape(height, width, 3).copy()


def array_to_image(array):
    """An (h, w, 3) uint8 array as a QImage that owns its pixels."""
    from PySide6.QtGui import QImage

    array = np.ascontiguousarray(array, dtype=np.uint8)
    height, width, _ = array.shape
    image = QImage(array.data, width, height, width * 3, QImage.Format.Format_RGB888)
    return image.copy()


def load_png(path: Path):
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"not a readable image: {path}")
    return image_to_array(image)


def save_png(array, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not array_to_image(array).save(str(path), "PNG"):
        raise OSError(f"could not write {path}")


def changed_mask(actual, expected, channel_tolerance=CHANNEL_TOLERANCE):
    """True where any channel differs by more than the tolerance."""
    delta = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
    return delta.max(axis=2) > channel_tolerance


def compare(actual, expected, channel_tolerance=CHANNEL_TOLERANCE,
            max_changed_fraction=MAX_CHANGED_FRACTION):
    """Compare two arrays. Returns (matches, message)."""
    if actual.shape != expected.shape:
        return False, (
            f"size changed: rendered {actual.shape[1]}x{actual.shape[0]}, "
            f"baseline {expected.shape[1]}x{expected.shape[0]}"
        )
    mask = changed_mask(actual, expected, channel_tolerance)
    changed = int(mask.sum())
    fraction = changed / mask.size
    if fraction > max_changed_fraction:
        return False, (
            f"{changed} of {mask.size} pixels changed ({fraction:.3%}, "
            f"limit {max_changed_fraction:.3%})"
        )
    return True, f"{changed} pixels changed, within the limit"


def diff_image(actual, expected, channel_tolerance=CHANNEL_TOLERANCE):
    """The baseline dimmed, with changed pixels in magenta."""
    out = (expected.astype(np.uint16) // 3).astype(np.uint8)
    out[changed_mask(actual, expected, channel_tolerance)] = (255, 0, 255)
    return out


def check_image(image, name: str, update: bool = False) -> None:
    """Compare a grabbed QImage with the baseline called ``name``.

    Raises AssertionError on a mismatch or a missing baseline, after writing
    the rendered image (and, when there is a baseline, the expected image and a
    diff) to ``DIFF_DIR``. With ``update`` the baseline is rewritten instead.
    """
    import pytest

    actual = image_to_array(image)
    baseline = baseline_dir() / f"{name}.png"

    if update:
        save_png(actual, baseline)
        return

    if not baseline_dir().is_dir():
        message = (
            f"no visual baselines for {platform_key()}; CI compares the linux "
            "set. Run with --update-baselines to make a local set."
        )
        # linux is the committed set, so a missing folder there is a failure,
        # not a reason to skip every check
        if platform_key() == "linux":
            raise AssertionError(message)
        pytest.skip(message)

    if not baseline.exists():
        save_png(actual, DIFF_DIR / f"{name}.png")
        raise AssertionError(
            f"no baseline {baseline.relative_to(TESTS_DIR.parent)}. The rendered "
            f"image is in {DIFF_DIR}; run with --update-baselines to accept it."
        )

    expected = load_png(baseline)
    matches, message = compare(actual, expected)
    if matches:
        return

    save_png(actual, DIFF_DIR / f"{name}.png")
    save_png(expected, DIFF_DIR / f"{name}.expected.png")
    if actual.shape == expected.shape:
        save_png(diff_image(actual, expected), DIFF_DIR / f"{name}.diff.png")
    raise AssertionError(
        f"{name} does not match its baseline: {message}. The rendered image, "
        f"the baseline and a diff are in {DIFF_DIR}. If the change is intended, "
        "run with --update-baselines (or accept the CI artifact, see "
        "tests/visual_regression.py)."
    )


def accept(folder: Path, platform: str = "linux") -> list[Path]:
    """Copy the rendered images from a diff folder over the baselines."""
    target = BASELINE_ROOT / platform
    copied = []
    for path in sorted(Path(folder).glob("*.png")):
        if path.name.endswith(_SUFFIXES):
            continue
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target / path.name)
        copied.append(target / path.name)
    return copied


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    accept_cmd = sub.add_parser(
        "accept", help="copy rendered images from a visual-diffs folder over the baselines"
    )
    accept_cmd.add_argument("folder", type=Path)
    accept_cmd.add_argument("--platform", default="linux")
    args = parser.parse_args(argv)

    copied = accept(args.folder, args.platform)
    for path in copied:
        print(f"updated {path.relative_to(TESTS_DIR.parent)}")
    if not copied:
        print(f"no rendered images in {args.folder}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
