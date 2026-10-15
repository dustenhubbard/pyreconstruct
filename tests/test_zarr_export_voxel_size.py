"""Zarr export keeps fractional nanometer voxel sizes (fork #603).

``seriesToZarr`` wrote ``voxel_size`` with ``int(mag * 1000)``, so 2.54 nm
pixels were stored as 2 nm and 0.5 nm pixels as 0, and importing labels back
from a 0 nm Zarr divided by zero. Whole nanometer sizes stay ints, as before.
"""
import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Transform


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


@pytest.fixture
def export(tmp_path, real_series, monkeypatch):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    ## the images are not what this is about
    monkeypatch.setattr(conversions, "exportSection", lambda *a, **k: None)
    sections = sorted(real_series.sections)[1:3]

    def run(mag):
        out = tmp_path / f"{mag}.zarr"
        conversions.seriesToZarr(
            real_series, sections, mag, [0.0, 0.0, 0.05, 0.05], data_fp=str(out)
        )
        return zarr.open(str(out), "r+")

    return real_series, sections, run


@pytest.mark.parametrize(
    "mag, xy_nm",
    [(0.00254, 2.54), (0.0005, 0.5), (0.00125, 1.25)],
)
def test_fractional_voxel_size_is_kept(export, mag, xy_nm):
    series, sections, run = export
    raw = run(mag)["raw"]

    z, y, x = raw.attrs["voxel_size"]
    assert (y, x) == (pytest.approx(xy_nm), pytest.approx(xy_nm))
    thickness = series.loadSection(sections[0]).thickness
    assert z == pytest.approx(thickness * 1000)
    assert conversions.get_voxel_size_um(raw)[-1] == pytest.approx(mag)


@pytest.mark.parametrize("mag, xy_nm", [(0.002, 2), (0.004, 4), (0.008, 8)])
def test_whole_voxel_size_is_still_an_int(export, mag, xy_nm):
    _, _, run = export
    voxel_size = run(mag)["raw"].attrs["voxel_size"]

    assert voxel_size[1:] == [xy_nm, xy_nm]
    assert all(type(v) is int for v in voxel_size)


def test_labels_import_back_from_a_sub_nanometer_zarr(export):
    series, sections, run = export
    zg = run(0.0005)
    raw = zg["raw"]
    labels = zg.create_dataset("labels_x", shape=raw.shape, dtype=np.uint64)
    labels[1, 20:40, 20:40] = 7
    labels.attrs["offset"] = [0, 0, 0]
    labels.attrs["voxel_size"] = raw.attrs["voxel_size"]

    conversions.setDT()
    conversions.importSection(zg, "labels_x", sections[1], series)

    assert "autoseg_7" in series.loadSection(sections[1]).contours


@pytest.mark.parametrize("raw_size", ["zero_xy", "zero_all", "missing"])
@pytest.mark.parametrize("label_size", ["zero_xy", "zero_all", "missing"])
def test_legacy_voxel_sizes_resolve_to_the_exported_grid(export, raw_size, label_size):
    series, sections, run = export
    section = series.loadSection(sections[0])
    section.thickness = 0.0254
    section.save()
    zg = run(0.0005)
    raw = zg["raw"]
    expected = list(raw.attrs["voxel_size"])
    labels = zg.create_dataset("labels_legacy", shape=raw.shape, dtype=np.uint64)
    labels[1, 20:40, 20:40] = 7
    labels.attrs["offset"] = [0, 0, 0]

    for arr, size in ((raw, raw_size), (labels, label_size)):
        if size == "missing":
            if "voxel_size" in arr.attrs:
                del arr.attrs["voxel_size"]
        else:
            arr.attrs["voxel_size"] = [expected[0], 0, 0] if size == "zero_xy" else [0, 0, 0]

    resolutions = conversions.get_label_resolutions(labels, raw, series=series)
    assert resolutions == (expected, expected)
    assert all(v > 0 for res in resolutions for v in res)
    assert conversions.labelsToObjects(series, raw.store.path, "labels_legacy")
    points = [
        p for trace in series.loadSection(sections[1]).contours["autoseg_7"]
        for p in trace.points
    ]
    tform = Transform(raw.attrs["alignment"][str(sections[1])])
    points = np.array(tform.map(points))
    # Saved trace coordinates round to seven decimals before reapplying alignment.
    assert points.min(axis=0) == pytest.approx([0.010, 0.0305], abs=1e-7)
    assert points.max(axis=0) == pytest.approx([0.0195, 0.040], abs=1e-7)


@pytest.mark.parametrize("raw_size", ["missing", "zero"])
def test_recovery_without_true_mag_uses_raw_metadata_not_section_mag(export, monkeypatch, raw_size):
    series, sections, run = export
    section = series.loadSection(sections[0])
    section.thickness = 0.0254
    section.save()
    zg = run(0.0005)
    raw = zg["raw"]
    if raw_size == "missing":
        del raw.attrs["voxel_size"]
    else:
        raw.attrs["voxel_size"] = [0, 0, 0]
    del raw.attrs["true_mag"]
    labels = zg.create_dataset("labels_legacy", shape=raw.shape, dtype=np.uint64)
    monkeypatch.setattr(series, "loadSection", lambda *a: pytest.fail("Recovery must use cached thickness"))

    if raw_size == "missing":
        assert conversions.get_label_resolutions(labels, raw, series=series) == (
            [25.4, 4, 4], [25.4, 4, 4]
        )
    else:
        with pytest.raises(ValueError, match="series.*resolution"):
            conversions.get_label_resolutions(labels, raw, series=series)


def test_zero_raw_size_without_recoverable_values_reports_the_problem():
    raw = zarr.zeros((1, 8, 8), dtype=np.uint8)
    raw.attrs["voxel_size"] = [0, 0, 0]
    labels = zarr.zeros((1, 8, 8), dtype=np.uint64)

    with pytest.raises(ValueError, match="series.*resolution"):
        conversions.get_label_resolutions(labels, raw)


@pytest.mark.parametrize("attrs", [{}, {"voxel_size": [0, 0, 0]}])
@pytest.mark.parametrize("unreachable", ["no_series", "no_sections", "deleted_section"])
def test_unreachable_series_section_keeps_metadata_fallback(real_series, attrs, unreachable):
    raw = zarr.zeros((1, 8, 8), dtype=np.uint8)
    raw.attrs.update(attrs)
    labels = zarr.zeros((1, 8, 8), dtype=np.uint64)
    series = real_series
    if unreachable == "no_series":
        series = None
        raw.attrs["sections"] = [min(real_series.sections)]
    elif unreachable == "deleted_section":
        raw.attrs["sections"] = [max(real_series.sections) + 1]

    if "voxel_size" in attrs:
        with pytest.raises(ValueError, match="series.*resolution"):
            conversions.get_label_resolutions(labels, raw, series=series)
    else:
        assert conversions.get_label_resolutions(labels, raw, series=series) == (
            [50, 4, 4], [50, 4, 4]
        )


def test_recovery_uses_import_metadata_and_preserves_valid_label_axes(export):
    series, _, run = export
    zg = run(0.0005)
    raw = zg["raw"]
    expected = list(raw.attrs["voxel_size"])
    attrs = dict(raw.attrs)
    raw.attrs["true_mag"] = 1.0
    raw.attrs["voxel_size"] = [0, 0, 0]
    labels = zg.create_dataset("labels_legacy", shape=raw.shape, dtype=np.uint64)
    labels.attrs.update({"voxel_size": [0, 0.001, 0], "units": "um"})

    labels_res, raw_res = conversions.get_label_resolutions(
        labels, raw, series=series, raw_attrs=attrs
    )
    assert raw_res == expected
    assert labels_res == [expected[0], 1, expected[2]]


@pytest.mark.parametrize("attribute", ["voxel_size", "resolution"])
@pytest.mark.parametrize(
    "label_size, expected",
    [
        ([1, 0, 0, 0], [50, 8, 8]),
        ([1, 40, 4, 4], [40, 4, 4]),
        ([1, 40, 0, 4], [40, 8, 4]),
        ([0, 50, 8, 8], [50, 8, 8]),
        ([0, 4, 0], [50, 4, 8]),
        ([40, 4, 4], [40, 4, 4]),
        ([40, 4], [40, 4]),
        ([40, 4, 4, 2, 3], [40, 4, 4, 2, 3]),
        ([0, 0], [50, 8]),
        ([0, 0, 0, 0, 0], [50, 8, 8, 0, 0]),
    ],
)
def test_label_resolution_uses_spatial_axes(attribute, label_size, expected):
    raw = zarr.zeros((1, 8, 8), dtype=np.uint8)
    raw.attrs[attribute] = [50, 8, 8]
    labels = zarr.zeros((1, 1, 8, 8), dtype=np.uint64)
    labels.attrs[attribute] = label_size

    assert conversions.get_label_resolutions(labels, raw) == (expected, [50, 8, 8])
    assert labels.attrs[attribute] == label_size


## three units name the three spatial axes, not the channel and two of them
@pytest.mark.parametrize("units", ["um", ["nm", "um", "nm", "um"], ["um", "nm", "um"]])
def test_channel_first_label_resolution_keeps_declared_units(units):
    raw = zarr.zeros((1, 8, 8), dtype=np.uint8)
    raw.attrs["voxel_size"] = [50, 8, 8]
    labels = zarr.zeros((1, 1, 8, 8), dtype=np.uint64)
    labels.attrs.update({
        "voxel_size": [1, 0.04, 0, 0.004], "units": units,
    })

    assert conversions.get_label_resolutions(labels, raw) == ([40, 8, 4], [50, 8, 8])


## raw's channel entry is no more a section thickness than the labels' is
@pytest.mark.parametrize("raw_size", [[1, 50, 8, 8], [0, 50, 8, 8]])
def test_four_entry_raw_voxel_size_is_channel_first(raw_size):
    raw = zarr.zeros((1, 1, 8, 8), dtype=np.uint8)
    raw.attrs["voxel_size"] = raw_size
    labels = zarr.zeros((1, 1, 8, 8), dtype=np.uint64)
    labels.attrs["voxel_size"] = [1, 40, 4, 4]

    assert conversions.get_label_resolutions(labels, raw) == ([40, 4, 4], [50, 8, 8])
    assert conversions.get_voxel_size_um(raw) == pytest.approx([0.05, 0.008, 0.008])
    assert conversions.get_thickness(raw) == pytest.approx(0.05)
    assert conversions.get_true_mag(raw) == pytest.approx(0.008)
    assert raw.attrs["voxel_size"] == raw_size


@pytest.mark.parametrize(
    "label_size, expected",
    [([1, 0, 0, 0], [50, 4, 8]), ([0, 0, 0], [50, 4, 8]), ([1, 40, 0, 2], [40, 4, 2])],
)
def test_label_zeros_fill_from_raws_spatial_axes(label_size, expected):
    raw = zarr.zeros((1, 8, 8), dtype=np.uint8)
    raw.attrs["voxel_size"] = [1, 50, 4, 8]
    labels = zarr.zeros((1, 8, 8), dtype=np.uint64)
    labels.attrs["voxel_size"] = label_size

    assert conversions.get_label_resolutions(labels, raw) == (expected, [50, 4, 8])


@pytest.mark.parametrize(
    "units", [["um", "um", "um"], ["", "um", "um", "um"], "um"]
)
def test_four_entry_raw_voxel_size_keeps_declared_units(units):
    raw = zarr.zeros((1, 8, 8), dtype=np.uint8)
    raw.attrs.update({"voxel_size": [1, 0.05, 0.004, 0.008], "units": units})
    labels = zarr.zeros((1, 8, 8), dtype=np.uint64)  # no size: raw's grid

    assert conversions.get_voxel_size_um(raw) == pytest.approx([0.05, 0.004, 0.008])
    assert conversions.get_thickness(raw) == pytest.approx(0.05)
    assert conversions.get_true_mag(raw) == pytest.approx(0.008)
    assert conversions.get_label_resolutions(labels, raw) == ([50, 4, 8], [50, 4, 8])


def test_channel_first_label_metadata_imports_on_raw_grid(export):
    series, sections, run = export
    zg = run(0.008)
    raw = zg["raw"]
    labels = zg.create_dataset("labels_channel_metadata", shape=raw.shape, dtype=np.uint64)
    labels[1, 1:4, 1:4] = 7
    labels.attrs.update({"voxel_size": [1, 0, 0, 0], "offset": [0, 0, 0]})

    assert conversions.labelsToObjects(series, raw.store.path, "labels_channel_metadata")
    assert "autoseg_7" in series.loadSection(sections[1]).contours
