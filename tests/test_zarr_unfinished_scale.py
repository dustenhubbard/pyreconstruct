"""A zarr scale with chunks and no .zarray is not offered as an image.

A conversion that stops partway (a worker killed, a full disk, a chunk that
failed to write) leaves `scale_N/<image>/` holding chunks and no `.zarray`.
zarr cannot open that folder as an array, so `zarr_scales` used to list the
scale and then:

- zooming onto it raised `KeyError` in `ImageLayer._generateImage`;
- a section whose only scale was unfinished raised `KeyError` on load;
- `src_fp` did `min([])` once such scales were left out, which aborted
  `optimizeSeriesBC` for the whole batch and `saveFieldView`;
- `img_dims` opened the folder to write and planted a `.zgroup` in it, which
  the converter's update then counts as present and skips;
- falling back to a coarser scale for `src_fp` gave `img_dims` that scale's
  size while `mag` stayed scale_1's, so ROI import and export and the SVG
  export placed every point wrong.

Each test drives a consumer against a real zarr on disk. Only the .roi codec
is a stand-in (see `roifile_standin`).
"""
import enum
import json
import os
import sys
import types

import numpy as np
import pytest
from PySide6.QtGui import QImage

pytestmark = pytest.mark.gui

IW, IH = 200, 160
MAG = 0.01
DIM = (977, 700)


def _unfinish(zarr_fp, scale, name):
    """Leave the array's chunks and drop its .zarray, as a stopped write does."""
    folder = os.path.join(zarr_fp, f"scale_{scale}", name)
    os.remove(os.path.join(folder, ".zarray"))
    assert any(f[0].isdigit() for f in os.listdir(folder)), "no chunks left"
    return folder


def _write_zarr(tmp_path, images):
    """A zarr with {name: {scale: finished}}; each level a gray ramp."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for name, scales in images.items():
        for k in scales:
            if f"scale_{k}" not in group:
                group.create_group(f"scale_{k}")
            rr, cc = np.meshgrid(
                np.arange(IH // k), np.arange(IW // k), indexing="ij"
            )
            values = ((cc * 7 + rr * 13) % 200 + 20).astype("u1")
            group[f"scale_{k}"].create_dataset(
                name, data=values, chunks=(32, 32)
            )
    for name, scales in images.items():
        for k, finished in scales.items():
            if not finished:
                _unfinish(fp, k, name)
    return fp


def _section(real_series, zarr_fp, src, snum=None):
    from PyReconstruct.modules.datatypes import Transform

    if snum is None:
        snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = zarr_fp
    section.src = src
    section.mag = MAG
    section.tform = Transform.identity()
    return section


def _window(zoom):
    ww = DIM[0] * MAG / zoom
    wh = DIM[1] * MAG / zoom
    return [0.0, 0.0, ww, wh]


def _gray(image):
    """The layer's gray levels, copied out.

    A copy, not a view: the converted QImage is freed when this returns, and
    a view into it reads whatever the allocator writes there next (glibc's
    free-list pointers on Linux, which failed the blank-layer check in CI).
    """
    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    rows = buf.reshape(image.height(), image.bytesPerLine())
    return rows[:, : image.width()].copy()


def test_zarr_scales_lists_only_finished_arrays(qapp, real_series, tmp_path):
    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: False, 4: True}})
    section = _section(real_series, fp, "img.png")
    assert sorted(section.zarr_scales) == [1, 4]


def test_zooming_out_onto_an_unfinished_scale_reads_a_finished_one(
    qapp, real_series, tmp_path
):
    """The zoom that would pick scale_2 falls back to scale_1."""
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: False}})
    section = _section(real_series, fp, "img.png")
    layer = ImageLayer(section, real_series)
    assert layer.image_found
    assert layer.scales == [1]

    image = layer._generateImage(DIM, _window(0.37), bc=False)  # scale_2 zoom

    assert layer.selected_scale == 1
    assert _gray(image).any(), "the finished scale drew nothing"


def test_a_scale_2_section_whose_scale_1_is_unfinished_still_draws(
    qapp, real_series, tmp_path
):
    """Close zoom wants scale_1; the nearest finished scale is scale_2."""
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, {"img.png": {1: False, 2: True}})
    section = _section(real_series, fp, "img.png")
    layer = ImageLayer(section, real_series)
    assert layer.image_found

    image = layer._generateImage(DIM, _window(1.7), bc=False)

    assert layer.selected_scale == 2
    assert _gray(image).any()
    # the path is still scale_1's: its pixels are the ones mag describes
    assert section.src_fp == os.path.join(fp, "scale_1", "img.png")


def test_a_section_with_no_finished_scale_loads_as_no_image(
    qapp, real_series, tmp_path
):
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, {"img.png": {1: False, 2: False}})
    section = _section(real_series, fp, "img.png")
    assert section.zarr_scales == []

    layer = ImageLayer(section, real_series)
    assert not layer.image_found
    image = layer._generateImage(DIM, _window(0.37), bc=False)
    assert not _gray(image).any(), "expected the blank layer"


def test_src_fp_with_no_finished_scale_is_the_scale_1_path(
    qapp, real_series, tmp_path
):
    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    section = _section(real_series, fp, "img.png")
    assert section.src_fp == os.path.join(fp, "scale_1", "img.png")


def test_img_dims_of_an_unfinished_array_writes_nothing(
    qapp, real_series, tmp_path
):
    """Reading the size must not turn the folder into a group."""
    import zarr

    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    section = _section(real_series, fp, "img.png")
    folder = os.path.join(fp, "scale_1", "img.png")
    before = sorted(os.listdir(folder))

    with pytest.raises(FileNotFoundError):
        section.img_dims

    assert sorted(os.listdir(folder)) == before
    assert "img.png" not in zarr.open_group(fp, mode="r")["scale_1"]


def test_optimize_bc_reads_a_finished_scale(qapp, real_series, tmp_path):
    """lowest_res wants the coarsest scale; the unfinished one is passed over."""
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSectionBC

    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: True, 4: False}})
    section = _section(real_series, fp, "img.png")
    section.brightness, section.contrast = 0, 0

    optimizeSectionBC(section, desired_mean=200, desired_std=10)

    assert (section.brightness, section.contrast) != (0, 0)


def test_optimize_bc_with_no_scale_1_folder_reads_the_scale_it_has(
    qapp, real_series, tmp_path
):
    """src_fp names scale_1 whether or not that folder exists."""
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSectionBC

    fp = _write_zarr(tmp_path, {"img.png": {2: True}})
    section = _section(real_series, fp, "img.png")
    section.brightness, section.contrast = 0, 0

    optimizeSectionBC(section, desired_mean=200, desired_std=10)

    assert (section.brightness, section.contrast) != (0, 0)


def test_optimize_series_bc_goes_on_past_a_section_with_no_finished_scale(
    qapp, real_series, tmp_path, capsys
):
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSeriesBC

    fp = _write_zarr(
        tmp_path,
        {"gone.png": {1: False}, "img.png": {1: True}},
    )
    first, second = sorted(real_series.sections)[:2]
    for snum, src in ((first, "gone.png"), (second, "img.png")):
        section = _section(real_series, fp, src, snum)
        section.brightness, section.contrast = 0, 0
        section.save()

    optimizeSeriesBC(
        real_series, desired_mean=200, desired_std=10,
        section_nums=[first, second],
    )

    skipped = real_series.loadSection(first)
    optimized = real_series.loadSection(second)
    assert (skipped.brightness, skipped.contrast) == (0, 0)
    assert (optimized.brightness, optimized.contrast) != (0, 0)
    # an unfinished image is not a corrupt one
    assert "corrupt" not in capsys.readouterr().out


def test_save_field_view_with_no_finished_scale(main_window, tmp_path):
    from PySide6.QtWidgets import QApplication

    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    main_window.series.src_dir = fp
    main_window.field.section.src = "img.png"
    QApplication.clipboard().clear()

    main_window.saveFieldView(False)

    assert not QApplication.clipboard().image().isNull()


# --- the image size: always scale_1's -------------------------------------------

def test_img_dims_never_reports_a_coarser_scale(qapp, real_series, tmp_path):
    """scale_2 is half size; reading it as the image would halve every height."""
    fp = _write_zarr(tmp_path, {"img.png": {1: False, 2: True}})
    section = _section(real_series, fp, "img.png")

    with pytest.raises(FileNotFoundError):
        section.img_dims


def test_img_dims_reports_scale_1(qapp, real_series, tmp_path):
    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: True}})
    section = _section(real_series, fp, "img.png")
    assert section.img_dims == (IH, IW)


def test_a_malformed_zarray_raises_its_own_error(qapp, real_series, tmp_path):
    """Only a missing array reads as a missing image."""
    fp = _write_zarr(tmp_path, {"img.png": {1: True}})
    with open(os.path.join(fp, "scale_1", "img.png", ".zarray"), "w") as f:
        f.write("{")
    section = _section(real_series, fp, "img.png")

    with pytest.raises(json.JSONDecodeError):
        section.img_dims


def test_a_folder_already_turned_into_a_group_reads_as_no_image(
    qapp, real_series, tmp_path
):
    """The .zgroup the old reader planted holds no array either."""
    import zarr

    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    zarr.open_group(os.path.join(fp, "scale_1", "img.png"), mode="a")
    section = _section(real_series, fp, "img.png")

    assert section.zarr_scales == []
    with pytest.raises(FileNotFoundError):
        section.img_dims


# --- coordinates: ROI import and export, SVG export ---------------------------

ROI_PIXELS = [(10.0, 20.0), (60.0, 20.0), (60.0, 70.0), (10.0, 70.0)]


def _roi_field(points):
    """Field coordinates of image pixels on the full-resolution image."""
    return [(x * MAG, (IH - y) * MAG) for x, y in points]


class _RoiType(enum.IntEnum):
    POLYGON = 0
    POLYLINE = 5
    POINT = 10


class _ImagejRoi:
    """What `Roi` and `RoiExporter` use of roifile.ImagejRoi, kept as JSON."""

    def __init__(self, points):
        self.points = np.asarray(points, dtype=float)
        self.roitype = _RoiType.POLYGON
        self.options = 0
        self.name = ""

    @classmethod
    def frompoints(cls, points):
        return cls(points)

    @classmethod
    def fromfile(cls, fp):
        with open(fp) as f:
            return cls(json.load(f))

    def coordinates(self, multi=False):
        return [self.points] if multi else self.points

    def tofile(self, fp):
        with open(fp, "w") as f:
            json.dump(self.points.tolist(), f)


@pytest.fixture
def roifile_standin(monkeypatch):
    """A `roifile` the menu actions find without the package installed.

    roifile is optional and not installed with the suite, so with the real
    codec these tests would skip everywhere they run. What they check is the
    pixel height PyReconstruct hands the codec, not the .roi format, which
    test_roi_import_geometry.py covers with the real package.
    """
    module = types.ModuleType("roifile")
    module.ImagejRoi = _ImagejRoi
    module.ROI_TYPE = _RoiType
    monkeypatch.setitem(sys.modules, "roifile", module)
    return module


def _zarr_window(main_window, tmp_path, scales):
    """Point the open window's section at a zarr with these scales."""
    from PyReconstruct.modules.datatypes import Transform

    fp = _write_zarr(tmp_path, {"img.png": scales})
    main_window.series.src_dir = fp
    section = main_window.field.section
    section.src = "img.png"
    section.mag = MAG
    section.tform = Transform.identity()
    return section


def _import_probe(main_window, main_window_dialogs, tmp_path):
    fp = tmp_path / "probe.roi"
    _ImagejRoi(ROI_PIXELS).tofile(fp)
    main_window_dialogs.file_responses.append([str(fp)])
    main_window.importROIFiles()


def test_roi_import_places_pixels_on_the_full_image(
    main_window, main_window_dialogs, roifile_standin, tmp_path
):
    section = _zarr_window(main_window, tmp_path, {1: True, 2: True})

    _import_probe(main_window, main_window_dialogs, tmp_path)

    (trace,) = section.contours["probe"].traces
    assert np.allclose(trace.points, _roi_field(ROI_PIXELS), atol=1e-9)


def test_roi_import_with_scale_1_unfinished_imports_nothing(
    main_window, main_window_dialogs, roifile_standin, tmp_path
):
    """No full-resolution height to place the pixels with: an error, not
    every point at half height."""
    section = _zarr_window(main_window, tmp_path, {1: False, 2: True})

    with pytest.raises(FileNotFoundError):
        _import_probe(main_window, main_window_dialogs, tmp_path)

    assert "probe" not in section.contours


def _export_probe(main_window, main_window_dialogs, tmp_path):
    from PyReconstruct.modules.datatypes import Trace

    trace = Trace("probe", (255, 255, 0), closed=True)
    trace.points = _roi_field(ROI_PIXELS)
    main_window.field.section.addTrace(trace, log_event=False)
    out = tmp_path / "rois"
    out.mkdir()
    main_window_dialogs.file_responses.append(str(out))
    main_window.exportROIFiles()
    return out


def test_roi_export_gives_back_the_full_image_pixels(
    main_window, main_window_dialogs, roifile_standin, tmp_path
):
    _zarr_window(main_window, tmp_path, {1: True, 2: True})

    out = _export_probe(main_window, main_window_dialogs, tmp_path)

    coords = _ImagejRoi.fromfile(out / "probe-exported.roi").points
    assert np.allclose(coords, ROI_PIXELS, atol=1e-6)


def test_roi_export_with_scale_1_unfinished_writes_nothing(
    main_window, main_window_dialogs, roifile_standin, tmp_path
):
    _zarr_window(main_window, tmp_path, {1: False, 2: True})

    with pytest.raises(FileNotFoundError):
        _export_probe(main_window, main_window_dialogs, tmp_path)

    assert not any((tmp_path / "rois").iterdir())


def test_svg_export_with_scale_1_unfinished_raises(qapp, real_series, tmp_path):
    """It would otherwise embed scale_2 at half size under full-size traces."""
    fp = _write_zarr(tmp_path, {"img.png": {1: False, 2: True}})
    section = _section(real_series, fp, "img.png")

    with pytest.raises(FileNotFoundError):
        section.exportAsSVG(str(tmp_path / "out.svg"))

    assert not (tmp_path / "out.svg").exists()
