"""Screenshot tests: the field, with and without a section image, and the trace
attribute dialogs against baselines.

Each test renders a view from the synthetic series in ``tests/fixtures/``,
grabs the widget (never the window, so no title bar and no file path), and
compares it with ``tests/visual_baselines/<platform>/<name>.png`` through
``tests/visual_regression.py``, which also documents the tolerance and how to
update the images.

What is pinned so the images do not drift: the Fusion style and its standard
palette (the default theme), one font at a fixed pixel size, one monospace
font for the field's labels, the field's size in pixels, the view window onto
the section, and the series itself. The
settings store every test gets is empty, so every option is its default.
"""

import math
import shutil
from pathlib import Path

import numpy as np
import pytest

# No `importorskip("pytestqt")`: see tests/conftest.py's collection guard.
pytestmark = pytest.mark.gui

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QStyleFactory

import visual_regression as vr
from PyReconstruct.modules.gui.dialog.trace import TraceDialog

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"

FIELD_SIZE = (640, 400)
# x, y, width, height in series units. Same 1.6 aspect as FIELD_SIZE, so
# resizeWindow leaves it alone, and wide enough to hold every trace on
# section 0 with a margin.
FIELD_WINDOW = [-0.2, -0.5, 11.2, 7.0]

# the checker image for the image test: pixels, and series units per pixel
IMAGE_SIZE = (120, 80)
IMAGE_MAG = 0.06

FONT_FAMILY = "DejaVu Sans"
# the field draws its labels in "Courier New", which Linux does not ship, so
# fontconfig would pick whatever monospace font the machine has. Substituting
# one named font keeps the labels the same on every Linux box.
MONO_FAMILY = "DejaVu Sans Mono"
FONT_PIXELS = 12


@pytest.fixture
def series_jser(tmp_path):
    """Overrides the conftest fixture: the synthetic parity series, not the
    checker's class series, so `main_window` opens it."""
    destination = tmp_path / "series.jser"
    shutil.copy(FIXTURE, destination)
    return destination


@pytest.fixture
def update_baselines(request):
    return request.config.getoption("--update-baselines")


@pytest.fixture
def pinned_look(qapp):
    """Fusion, its standard palette, no stylesheet, one font, a steady caret.
    Restored after, since `qapp` lives for the whole session."""
    style_name = qapp.style().name()
    palette = qapp.palette()
    font = qapp.font()
    sheet = qapp.styleSheet()
    flash = qapp.cursorFlashTime()
    mono_substitutes = QFont.substitutes("Courier New")

    qapp.setStyle(QStyleFactory.create("Fusion"))
    qapp.setPalette(qapp.style().standardPalette())
    qapp.setStyleSheet("")
    pinned = QFont(FONT_FAMILY)
    pinned.setPixelSize(FONT_PIXELS)
    pinned.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    qapp.setFont(pinned)
    QFont.removeSubstitutions("Courier New")
    QFont.insertSubstitutions("Courier New", [MONO_FAMILY])
    # a text caret that blinks is on in one grab and off in the next; with no
    # flash time it is drawn steadily
    qapp.setCursorFlashTime(0)
    yield
    QFont.removeSubstitutions("Courier New")
    if mono_substitutes:
        QFont.insertSubstitutions("Courier New", mono_substitutes)
    qapp.setCursorFlashTime(flash)
    qapp.setFont(font)
    qapp.setStyleSheet(sheet)
    qapp.setStyle(QStyleFactory.create(style_name))
    qapp.setPalette(palette)


@pytest.fixture
def window(pinned_look, main_window):
    """The main window with its field pinned to FIELD_SIZE and FIELD_WINDOW."""
    main_window.setTheme("default")
    field = main_window.field
    field.setFixedSize(*FIELD_SIZE)
    main_window.resize(FIELD_SIZE[0] + 600, FIELD_SIZE[1] + 400)
    QApplication.processEvents()
    assert (field.width(), field.height()) == FIELD_SIZE
    # far from every trace, so no hover name is painted
    field.mouse_x = field.mouse_y = -10_000
    main_window.series.window = list(FIELD_WINDOW)
    field.generateView()
    QApplication.processEvents()
    return main_window


def trace_named(section, name, index=0):
    return section.contours[name][index]


def grab_field(field):
    field.repaint()
    return field.grab().toImage()


def grab_dialog(dialog):
    dialog.show()
    QApplication.processEvents()
    image = dialog.grab().toImage()
    dialog.reject()
    return image


# --------------------------------------------------------------------------- #
# the baselines                                                               #
# --------------------------------------------------------------------------- #
def test_field(window, update_baselines):
    vr.check_image(grab_field(window.field), "field", update_baselines)


def test_field_with_a_selected_trace(window, update_baselines):
    """The green dendrite fills only when unselected, so selecting it swaps
    the fill for the selected outline, and its name is listed in the corner."""
    field = window.field
    field.selectTrace(trace_named(field.section, "dendrite01", 1))
    vr.check_image(grab_field(field), "field_selected", update_baselines)


def checker_image(path, shift=0):
    """A checkerboard whose light squares each carry their own color, so a
    shift of one square, or a flip, changes the picture. `shift` moves the
    pattern left by that many pixels."""
    from PySide6.QtGui import QColor, QImage

    square = 10
    image = QImage(IMAGE_SIZE[0], IMAGE_SIZE[1], QImage.Format.Format_RGB32)
    for y in range(IMAGE_SIZE[1]):
        for x in range(IMAGE_SIZE[0]):
            col, row = (x + shift) // square, y // square
            if (col + row) % 2:
                image.setPixelColor(x, y, QColor(24, 24, 24))
            else:
                image.setPixelColor(x, y, QColor(40 + 16 * col, 40 + 24 * row, 160))
    assert image.save(str(path))


def test_field_over_a_rotated_section_image(window, tmp_path, update_baselines):
    """The section image drawn under the traces, on a rotated section. The
    image is sampled pixel for pixel, so the checker edges are exact."""
    from PyReconstruct.modules.datatypes import Transform

    field = window.field
    checker_image(tmp_path / "checker.png")
    window.series.src_dir = str(tmp_path)
    section = field.section
    section.src = "checker.png"
    section.mag = IMAGE_MAG
    angle = math.radians(8)
    section.tform = Transform([
        math.cos(angle), -math.sin(angle), 1.6,
        math.sin(angle), math.cos(angle), -0.4,
    ])
    field.reloadImage()
    assert field.section_layer.image_found
    vr.check_image(grab_field(field), "field_image", update_baselines)


def test_an_image_one_pixel_off_fails_the_field_check(window, tmp_path):
    """The image drawn one image pixel away from where the traces expect it,
    the bug the exact image sampling fixed."""
    field = window.field
    window.series.src_dir = str(tmp_path)
    field.section.src = "checker.png"
    field.section.mag = IMAGE_MAG

    checker_image(tmp_path / "checker.png")
    field.reloadImage()
    before = vr.image_to_array(grab_field(field))

    checker_image(tmp_path / "checker.png", shift=1)
    field.reloadImage()
    after = vr.image_to_array(grab_field(field))
    matches, message = vr.compare(after, before)
    assert not matches, message


def test_trace_attributes_dialog(window, update_baselines):
    field = window.field
    dialog = TraceDialog(
        field,
        [trace_named(field.section, "dendrite01", 0)],
        tag_sets=window.series.tag_sets,
    )
    vr.check_image(grab_dialog(dialog), "trace_dialog", update_baselines)


def test_palette_trace_dialog(window, update_baselines):
    button = window.mouse_palette.palette_buttons[0]
    series = window.series
    dialog = TraceDialog(
        button,
        [button.trace],
        is_palette=True,
        tag_sets=series.tag_sets,
        series=series,
    )
    vr.check_image(grab_dialog(dialog), "palette_trace_dialog", update_baselines)


# --------------------------------------------------------------------------- #
# the tolerance itself, on live renders, so it holds without any baseline     #
# --------------------------------------------------------------------------- #
def test_the_same_render_twice_matches(window):
    first = vr.image_to_array(grab_field(window.field))
    window.field.generateView()
    second = vr.image_to_array(grab_field(window.field))
    assert vr.compare(second, first)[0]


def test_one_recolored_trace_fails_the_field_check(window):
    """The trace color class of bug: one outline drawn the wrong color."""
    field = window.field
    before = vr.image_to_array(grab_field(field))
    trace = trace_named(field.section, "spine01")
    assert tuple(trace.color) == (255, 255, 0)
    trace.color = (0, 255, 255)
    field.generateView()
    after = vr.image_to_array(grab_field(field))
    matches, message = vr.compare(after, before)
    assert not matches, message


def test_antialiasing_noise_is_within_tolerance():
    rng = np.random.default_rng(445)
    base = rng.integers(0, 256, size=(400, 640, 3), dtype=np.uint8)
    noise = rng.integers(-vr.CHANNEL_TOLERANCE, vr.CHANNEL_TOLERANCE + 1, size=base.shape)
    noisy = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    assert vr.compare(noisy, base)[0]


def test_a_size_change_fails():
    base = np.zeros((10, 10, 3), dtype=np.uint8)
    matches, message = vr.compare(np.zeros((10, 11, 3), dtype=np.uint8), base)
    assert not matches
    assert "size changed" in message


def test_a_mismatch_writes_the_images_for_review(tmp_path, monkeypatch, qapp):
    monkeypatch.setattr(vr, "BASELINE_ROOT", tmp_path / "baselines")
    monkeypatch.setattr(vr, "DIFF_DIR", tmp_path / "diffs")
    base = np.zeros((20, 20, 3), dtype=np.uint8)
    vr.save_png(base, vr.baseline_dir() / "square.png")

    changed = base.copy()
    changed[5:15, 5:15] = 255
    with pytest.raises(AssertionError, match="does not match"):
        vr.check_image(vr.array_to_image(changed), "square")

    written = sorted(p.name for p in (tmp_path / "diffs").iterdir())
    assert written == ["square.diff.png", "square.expected.png", "square.png"]
    assert (vr.load_png(tmp_path / "diffs" / "square.png") == changed).all()

    copied = vr.accept(tmp_path / "diffs", vr.platform_key())
    assert [p.name for p in copied] == ["square.png"]
    vr.check_image(vr.array_to_image(changed), "square")
