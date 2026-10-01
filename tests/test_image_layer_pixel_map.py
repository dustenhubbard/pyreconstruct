"""The section image is drawn from the same geometry the traces use.

A trace point at field (x, y) lands on the screen through fieldPointToPixmap,
and the Zarr label overlay reads the label under each screen pixel's center
(ZarrLayer._zarrIndex). The section image has to agree with both: the screen
pixel whose center falls in image pixel (col, row) shows that pixel, not a
neighbor. These tests render an image whose red channel is the column and
green channel the row through the real ImageLayer and compare every screen
pixel with the pixel its center sits in, computed from the window and the
section transform independently of the layer.
"""

import math

import numpy as np
import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

pytestmark = pytest.mark.gui

IW, IH = 200, 160
MAG = 0.01
DIM = (977, 700)


@pytest.fixture
def grid_section(qapp, real_series, tmp_path):
    """A section over an image that encodes each pixel's own coordinates."""
    img = QImage(IW, IH, QImage.Format.Format_RGB32)
    for y in range(IH):
        for x in range(IW):
            img.setPixelColor(x, y, QColor(x, y, 7))
    img.save(str(tmp_path / "grid.png"))

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(tmp_path)
    section.src = "grid.png"
    section.mag = MAG
    return section


def _layer(section, tform):
    from PyReconstruct.modules.datatypes import Transform
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    section.tforms[section.series.alignment] = Transform(tform)
    layer = ImageLayer(section, section.series)
    assert layer.image_found, "the synthetic image failed to load"
    return layer


def _drawn(layer, window):
    """(col, row, is_image) per screen pixel, decoded from the rendered layer."""
    image = layer._generateImage(DIM, window, bc=False)
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = image.width(), image.height()
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    rgba = buf.reshape(h, image.bytesPerLine())[:, : w * 4].reshape(h, w, 4)
    return rgba[:, :, 0].astype(int), rgba[:, :, 1].astype(int), rgba[:, :, 2] == 7


def _expected(window, tform):
    """The image pixel under each screen pixel's center, by the trace geometry.

    Also flags centers that sit on an image pixel edge to within floating
    point, where either neighbor is a correct answer.
    """
    from PyReconstruct.modules.datatypes import Transform

    pmw, pmh = DIM
    wx, wy, ww, wh = window
    sx = pmw * MAG / ww
    sy = pmh * MAG / wh
    fx = wx + (np.arange(pmw) + 0.5) * (MAG / sx)
    fy = wy + (pmh - np.arange(pmh) - 0.5) * (MAG / sy)
    a, b, c, d, e, f = Transform(tform)._affine(True)
    ux = (a * fx[None, :] + b * fy[:, None] + c) / MAG
    uy = (d * fx[None, :] + e * fy[:, None] + f) / MAG
    col = np.floor(ux).astype(int)
    row = IH - 1 - np.floor(uy).astype(int)
    on_edge = (np.abs(ux - np.round(ux)) < 1e-7) | (np.abs(uy - np.round(uy)) < 1e-7)
    return col, row, on_edge


def _mismatches(layer, window, tform):
    """Count the screen pixels drawn from the wrong image pixel, and how far off."""
    dcol, drow, is_image = _drawn(layer, window)
    col, row, on_edge = _expected(window, tform)
    inside = (col >= 0) & (col < IW) & (row >= 0) & (row < IH)
    right = np.where(inside, is_image & (dcol == col) & (drow == row), ~is_image)
    wrong = ~right & ~on_edge
    off_x = int(np.where(inside & is_image, np.abs(dcol - col), 0).max())
    off_y = int(np.where(inside & is_image, np.abs(drow - row), 0).max())
    blank = int((inside & ~is_image & ~on_edge).sum())
    return int(wrong.sum()), int(inside.sum()), off_x, off_y, blank


def _window(zoom, shift):
    """A field window `shift` image pixels in, at `zoom` screen pixels per image pixel."""
    return [shift[0] * MAG, shift[1] * MAG, DIM[0] / zoom * MAG, DIM[1] / zoom * MAG]


IDENTITY = [1, 0, 0, 0, 1, 0]
TRANSLATE = [1, 0, 0.0123, 0, 1, -0.0456]
ROTATE = [math.cos(0.2), -math.sin(0.2), 0.05, math.sin(0.2), math.cos(0.2), 0.02]

ZOOMS = [0.37, 1.0, 1.7, 3.2567, 25.3]
SHIFTS = [(0.0, 0.0), (0.5, 0.5), (0.1234, 0.9876), (13.37, 7.77)]


@pytest.mark.parametrize("tform", [IDENTITY, TRANSLATE], ids=["identity", "translate"])
@pytest.mark.parametrize("zoom", ZOOMS)
@pytest.mark.parametrize("shift", SHIFTS, ids=["aligned", "half", "fraction", "far"])
def test_image_pixels_land_where_the_traces_say(grid_section, tform, zoom, shift):
    """Every screen pixel shows the image pixel under its center."""
    layer = _layer(grid_section, tform)
    wrong, total, off_x, off_y, blank = _mismatches(layer, _window(zoom, shift), tform)
    assert wrong == 0, (
        f"{wrong} of {total} screen pixels show a neighboring image pixel "
        f"(up to {off_x} across, {off_y} down, {blank} drawn black) at zoom "
        f"{zoom}, pan {shift}"
    )


@pytest.mark.parametrize("zoom", ZOOMS)
@pytest.mark.parametrize("shift", SHIFTS, ids=["aligned", "half", "fraction", "far"])
def test_rotated_image_pixels_land_where_the_traces_say(grid_section, zoom, shift):
    """The same, through a rotation, where the old path also left black holes."""
    layer = _layer(grid_section, ROTATE)
    wrong, total, off_x, off_y, blank = _mismatches(layer, _window(zoom, shift), ROTATE)
    assert wrong == 0, (
        f"{wrong} of {total} screen pixels show a neighboring image pixel "
        f"(up to {off_x} across, {off_y} down, {blank} drawn black) at zoom "
        f"{zoom}, pan {shift}"
    )


def test_a_whole_pixel_at_one_to_one_is_not_duplicated(grid_section):
    """At one screen pixel per image pixel with no pan, nothing moves at all.

    `s` comes out as 1.0000000000000002 here, and ceiling the scaled crop size
    once turned a 200 by 160 crop into 201 by 161, shifting the lower right of
    the image by a full pixel.
    """
    layer = _layer(grid_section, IDENTITY)
    dcol, drow, is_image = _drawn(layer, _window(1.0, (0.0, 0.0)))
    pmh = DIM[1]
    for px, py in [(0, pmh - 1), (100, pmh - 100), (199, pmh - 160)]:
        assert is_image[py, px]
        assert (dcol[py, px], drow[py, px]) == (px, IH - 1 - (pmh - 1 - py)), (
            f"screen ({px}, {py}) shows image ({dcol[py, px]}, {drow[py, px]})"
        )


def _zarr_section(real_series, tmp_path):
    """A section over a two-level Zarr whose values encode their own pixel.

    Each level is its own image: at scale 2 a value names a scale-2 pixel, so
    the test also pins which level is read and how its pixels are indexed.
    """
    import zarr

    fp = tmp_path / "images.zarr"
    group = zarr.open_group(str(fp), mode="w")
    levels = {}
    for k in (1, 2):
        rr, cc = np.meshgrid(np.arange(IH // k), np.arange(IW // k), indexing="ij")
        values = ((cc * 7 + rr * 13) % 255 + 1).astype("u1")
        group.create_group(f"scale_{k}").create_dataset("grid.png", data=values)
        levels[k] = values
    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(fp)
    section.src = "grid.png"
    section.mag = MAG
    return section, levels


def _zarr_mismatches(layer, levels, window, tform):
    """Like _mismatches, for a gray Zarr read at whichever level the layer picked."""
    image = layer._generateImage(DIM, window, bc=False)
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = image.width(), image.height()
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    gray = buf.reshape(h, image.bytesPerLine())[:, : w * 4].reshape(h, w, 4)[:, :, 0]
    col, row, on_edge = _expected(window, tform)
    inside = (col >= 0) & (col < IW) & (row >= 0) & (row < IH)
    k = layer.selected_scale
    level = levels[k]
    want = level[np.clip(row // k, 0, level.shape[0] - 1), np.clip(col // k, 0, level.shape[1] - 1)]
    right = np.where(inside, gray == want, gray == 0)
    wrong = ~right & ~on_edge
    return int(wrong.sum()), int(inside.sum()), k


@pytest.mark.parametrize("tform", [TRANSLATE, ROTATE], ids=["translate", "rotate"])
@pytest.mark.parametrize("zoom", [0.37, 1.7, 25.3])
@pytest.mark.parametrize("shift", SHIFTS, ids=["aligned", "half", "fraction", "far"])
def test_zarr_image_pixels_land_where_the_traces_say(qapp, real_series, tmp_path, tform, zoom, shift):
    """The Zarr path reads the right level and the right pixel in it."""
    section, levels = _zarr_section(real_series, tmp_path)
    layer = _layer(section, tform)
    assert layer.is_zarr_file
    wrong, total, k = _zarr_mismatches(layer, levels, _window(zoom, shift), tform)
    assert k == (2 if zoom < 0.5 else 1), f"read scale_{k} at zoom {zoom}"
    assert wrong == 0, (
        f"{wrong} of {total} screen pixels show a neighboring scale_{k} pixel "
        f"at zoom {zoom}, pan {shift}"
    )


def test_indexed8_outside_a_rotated_image_is_black(qapp, real_series, tmp_path):
    """A palette image whose entry 0 is red draws black, not red, past its edge.

    The outside mask has to apply after the color table maps values to colors,
    or the fill value 0 names palette entry 0.
    """
    img = QImage(IW, IH, QImage.Format.Format_Indexed8)
    img.setColorTable([QColor(200, 30, 30).rgb()] + [QColor(i, i, i).rgb() for i in range(1, 256)])
    img.fill(77)
    img.save(str(tmp_path / "grid.png"))
    assert QImage(str(tmp_path / "grid.png")).format() == QImage.Format.Format_Indexed8

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(tmp_path)
    section.src = "grid.png"
    section.mag = MAG
    layer = _layer(section, ROTATE)

    window = _window(1.7, (13.37, 7.77))
    rgba = layer._generateImage(DIM, window, bc=False).convertToFormat(QImage.Format.Format_RGBA8888)
    buf = np.frombuffer(rgba.constBits(), np.uint8, rgba.sizeInBytes())
    rgb = buf.reshape(DIM[1], rgba.bytesPerLine())[:, : DIM[0] * 4].reshape(DIM[1], DIM[0], 4)[:, :, :3]
    col, row, on_edge = _expected(window, ROTATE)
    inside = (col >= 0) & (col < IW) & (row >= 0) & (row < IH)
    outside = ~inside & ~on_edge
    assert outside.sum() > 1000, "the view should reach past the image"
    red_outside = int(((rgb[:, :, 0] == 200) & outside).sum())
    assert red_outside == 0, f"{red_outside} screen pixels outside the image show palette entry 0"
    assert int((rgb[outside] != 0).sum()) == 0, "the area outside the image is not black"
    assert int((rgb[inside & ~on_edge][:, 0] == 77).all())


def _write_png(path, w, h, color_type, depth, rows):
    """A PNG written by hand, so the file's own format reaches Qt's loader."""
    import struct
    import zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + r for r in rows)
    head = struct.pack(">IIBBBBB", w, h, depth, color_type, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _alpha_png(path, kind):
    """A 200 by 160 PNG with varying alpha: 16-bit RGBA, 16-bit gray with
    alpha, or 8-bit gray with alpha. Returns the format Qt loads it as."""
    import struct

    if kind == "rgba16":
        rows = [b"".join(struct.pack(">HHHH", (x * 700) % 65536, (y * 900) % 65536,
                                     7, ((x + y) * 300) % 65536) for x in range(IW))
                for y in range(IH)]
        _write_png(path, IW, IH, 6, 16, rows)
        return QImage.Format.Format_RGBA64
    if kind == "gray16+alpha":
        rows = [b"".join(struct.pack(">HH", (x * 700 + y * 1300) % 65536,
                                     ((x + y) * 300) % 65536) for x in range(IW))
                for y in range(IH)]
        _write_png(path, IW, IH, 4, 16, rows)
        return QImage.Format.Format_RGBA64
    rows = [bytes(v for x in range(IW) for v in ((x * 7 + y * 13) % 256, (x + y) % 256))
            for y in range(IH)]
    _write_png(path, IW, IH, 4, 8, rows)
    return QImage.Format.Format_ARGB32


@pytest.mark.parametrize("kind", ["rgba16", "gray16+alpha", "gray8+alpha"])
def test_crop_only_keeps_the_values_of_an_image_with_alpha(qapp, real_series, tmp_path, kind):
    """`get_crop_only` on an image with alpha gives the values the file holds.

    The brightness and contrast optimizer reads this crop. Converting the
    image to a premultiplied format at load scales every value by its alpha,
    and sending a gray image with alpha to Grayscale8 drops the alpha; either
    changes the optimizer's picks.
    """
    expected_format = _alpha_png(tmp_path / "grid.png", kind)
    loaded = QImage(str(tmp_path / "grid.png"))
    assert loaded.format() == expected_format and loaded.hasAlphaChannel()
    # what the optimizer saw when the crop came straight from the file
    want = loaded.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = np.frombuffer(want.constBits(), np.uint8, want.sizeInBytes())
    want = buf.reshape(IH, want.bytesPerLine())[:, : IW * 4].reshape(IH, IW, 4)[:, :, 0].copy()

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(tmp_path)
    section.src = "grid.png"
    section.mag = MAG
    layer = _layer(section, IDENTITY)
    assert layer.image.hasAlphaChannel(), "the alpha channel was dropped at load"
    got = layer.generateImageArray((IW, IH), [0, 0, IW * MAG, IH * MAG], get_crop_only=True)

    assert got.shape == want.shape
    differ = int((got != want).sum())
    assert differ == 0, f"{differ} of {want.size} crop values differ from the file's"


def _rotated_alpha(real_series, tmp_path, img):
    """Alpha per screen pixel of a rotated view that reaches past the image,
    plus the outside mask from the geometry."""
    img.save(str(tmp_path / "grid.png"))
    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(tmp_path)
    section.src = "grid.png"
    section.mag = MAG
    layer = _layer(section, ROTATE)
    window = _window(1.7, (13.37, 7.77))
    out = layer._generateImage(DIM, window, bc=False)
    assert out.format() == QImage.Format.Format_ARGB32_Premultiplied
    rgba = out.convertToFormat(QImage.Format.Format_RGBA8888)
    buf = np.frombuffer(rgba.constBits(), np.uint8, rgba.sizeInBytes())
    # copied: rebinding `rgba` frees the QImage that `buf` points into
    rgba = buf.reshape(DIM[1], rgba.bytesPerLine())[:, : DIM[0] * 4].reshape(DIM[1], DIM[0], 4).copy()
    col, row, on_edge = _expected(window, ROTATE)
    inside = (col >= 0) & (col < IW) & (row >= 0) & (row < IH)
    assert (~inside).sum() > 1000, "the view should reach past the image"
    return layer, rgba, inside, on_edge


def test_rgb32_outside_a_rotated_image_is_opaque_black(qapp, real_series, tmp_path):
    """An 8-bit RGB image (loaded as RGB32) leaves no see-through area.

    RGB32 has no alpha of its own, so Qt copies the word as is; a fill of 0
    arrived as alpha 0 and the window background showed through outside the
    image. The fill has to be opaque black.
    """
    img = QImage(IW, IH, QImage.Format.Format_RGB32)
    img.fill(QColor(90, 120, 150))
    layer, rgba, inside, on_edge = _rotated_alpha(real_series, tmp_path, img)
    assert layer.image.format() == QImage.Format.Format_RGB32
    see_through = int((rgba[:, :, 3] != 255).sum())
    assert see_through == 0, f"{see_through} screen pixels are not opaque"
    outside = ~inside & ~on_edge
    assert int((rgba[outside][:, :3] != 0).sum()) == 0, "the area outside the image is not black"
    assert (rgba[inside & ~on_edge][:, :3] == (90, 120, 150)).all()


def test_indexed8_with_a_short_palette_draws_rotated(qapp, real_series, tmp_path):
    """A palette image with four colors renders a rotated view.

    The lookup table is padded to 256 entries, so a row's padding bytes or a
    value past the palette cannot index beyond it.
    """
    img = QImage(IW, IH, QImage.Format.Format_Indexed8)
    img.setColorTable([QColor(200, 30, 30).rgb(), QColor(10, 200, 10).rgb(),
                       QColor(10, 10, 200).rgb(), QColor(250, 250, 250).rgb()])
    img.fill(2)
    layer, rgba, inside, on_edge = _rotated_alpha(real_series, tmp_path, img)
    assert layer.image.format() == QImage.Format.Format_Indexed8
    assert layer._pixels.lut.shape == (256,)
    assert int((rgba[:, :, 3] != 255).sum()) == 0, "not every screen pixel is opaque"
    outside = ~inside & ~on_edge
    assert int((rgba[outside][:, :3] != 0).sum()) == 0, "the area outside the image is not black"
    assert (rgba[inside & ~on_edge][:, :3] == (10, 10, 200)).all()


def _premultiplied_bytes(image):
    """The raw bytes of an ARGB32_Premultiplied image, one row per screen row."""
    assert image.format() == QImage.Format.Format_ARGB32_Premultiplied
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    return buf.reshape(image.height(), image.bytesPerLine())[:, : image.width() * 4].copy()


@pytest.mark.parametrize("kind", ["rgba16", "gray16+alpha", "gray8+alpha"])
def test_image_with_alpha_draws_as_qt_draws_it(qapp, real_series, tmp_path, kind):
    """At one screen pixel per image pixel the layer matches a direct Qt draw.

    A 16-bit image with alpha is premultiplied at 16 bits before it comes
    down to 8, the way Qt draws the file itself. Drawing from the 8-bit copy
    kept for the crop would round twice and leave a quarter of the pixels one
    level off.
    """
    _alpha_png(tmp_path / "grid.png", kind)
    loaded = QImage(str(tmp_path / "grid.png"))
    want = QImage(IW, IH, QImage.Format.Format_ARGB32_Premultiplied)
    want.fill(Qt.black)
    painter = QPainter(want)
    painter.drawImage(0, 0, loaded)
    painter.end()

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = str(tmp_path)
    section.src = "grid.png"
    section.mag = MAG
    layer = _layer(section, IDENTITY)
    got = layer._generateImage((IW, IH), [0, 0, IW * MAG, IH * MAG], bc=False)

    differ = int((_premultiplied_bytes(got) != _premultiplied_bytes(want)).sum())
    assert differ == 0, f"{differ} of {IW * IH * 4} drawn bytes differ from a direct Qt draw"
