"""Every Zarr reader takes voxel sizes and offsets in the units they declare.

``seriesToLabels``, the label overlay and ``ng_view.py`` read ``resolution``
as nm without looking at ``units``, so a Zarr in µm came out 1000 times too
small there. Label import and the overlay also placed labels by their own
offset alone, so raw and labels sharing one nonzero offset came in shifted by
it. Labels sit where their offset puts them against raw's.
"""

import runpy
import sys
import types

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.datatypes import Trace, Transform  # noqa: E402

IDENTITY = [1, 0, 0, 0, 1, 0]


def _array(attrs):
    arr = zarr.zeros((1, 4, 4), dtype=np.uint8)
    arr.attrs.update(attrs)
    return arr


def test_the_same_grid_in_um_and_nm_reads_the_same():
    um = _array({"units": ["um", "um", "um"]})
    nm = _array({"units": ["nm", "nm", "nm"]})

    assert conversions.as_nm([0.05, 0.0041, 0.0041], um) == [50, 4.1, 4.1]
    assert conversions.as_nm([0.05, 0.0041, 0.0041], um) == conversions.as_nm(
        [50, 4.1, 4.1], nm
    )


def test_nm_values_come_back_unchanged():
    nm = _array({"units": "nm"})

    assert conversions.as_nm([50, 4.1000000000000005, 7], nm) == [
        50, 4.1000000000000005, 7,
    ]


@pytest.mark.parametrize(
    "labels_attrs, expected",
    [
        ({"offset": [100, 400, 800]}, [0, 0, 0]),  # shared with raw
        ({"offset": [150, 440, 880]}, [50, 40, 80]),
        ({"offset": [0.15, 0.44, 0.88], "units": "um"}, [50, 40, 80]),
        ({}, [0, 0, 0]),  # no offset: raw's corner, as before
    ],
)
def test_label_offset_is_measured_from_raw(labels_attrs, expected):
    raw = _array({"offset": [100, 400, 800]})
    labels = _array(labels_attrs)

    assert conversions.get_label_offset(labels, raw) == pytest.approx(expected)


## four entries are channel first; the channel entry pairs with no axis
@pytest.mark.parametrize(
    "raw_attrs, labels_attrs",
    [
        ({"offset": [100, 200, 300]}, {"offset": [0, 140, 208, 304]}),
        ({"offset": [0, 100, 200, 300]}, {"offset": [140, 208, 304]}),
        ({"offset": [1, 100, 200, 300]}, {"offset": [0, 140, 208, 304]}),
        (
            {"offset": [100, 200, 300]},
            {"offset": [0, 0.14, 0.208, 0.304], "units": ["um", "um", "um"]},
        ),
        (
            {"offset": [0.1, 0.2, 0.3], "units": ["", "um", "um", "um"]},
            {"offset": [140, 208, 304]},
        ),
    ],
)
def test_four_entry_label_offset_is_channel_first(raw_attrs, labels_attrs):
    raw = _array(raw_attrs)
    labels = _array(labels_attrs)

    assert conversions.get_label_offset(labels, raw) == pytest.approx([40, 8, 4])


@pytest.mark.parametrize(
    "values, units",
    [
        ([1, 0.05, 0.004, 0.008], ["um", "um", "um"]),
        ([1, 0.05, 0.004, 0.008], "um"),
        ([0.05, 4, 8], ["", "um", "nm", "nm"]),
        ([1, 0.05, 4, 8], ["", "um", "nm", "nm"]),
    ],
)
def test_four_entry_units_pair_with_the_spatial_axes(values, units):
    assert conversions.as_nm(values, _array({"units": units})) == pytest.approx([50, 4, 8])


## seriesToLabels


class _Contour:
    def __init__(self, trace):
        self._traces = [trace]

    def getTraces(self):
        return list(self._traces)


class _Series:
    def __init__(self):
        trace = Trace("cell", (255, 0, 0), closed=True)
        trace.points = [(2, 3), (6, 3), (6, 7), (2, 7)]
        self.section = types.SimpleNamespace(
            mag=1.0, contours={"cell": _Contour(trace)}, tform=None
        )
        self.object_groups = types.SimpleNamespace(
            getGroupObjects=lambda g: {"cell"} if g == "cells" else set()
        )

    def loadSection(self, snum):
        return self.section


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


@pytest.mark.parametrize(
    "units, voxel_size, offset",
    [
        ("nm", [50, 1000, 1000], [100, 2000, 3000]),
        ("um", [0.05, 1, 1], [0.1, 2, 3]),
    ],
)
def test_label_export_writes_nm_from_a_raw_in_any_units(
    tmp_path, monkeypatch, units, voxel_size, offset
):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    fp = str(tmp_path / "export.zarr")
    raw = zarr.open(fp, mode="w").create_dataset(
        "raw", shape=(1, 10, 10), dtype=np.uint8
    )
    raw.attrs.update({
        "alignment": {"0": IDENTITY},
        "window": [0, 0, 10, 10],
        "offset": offset,
        "sections": [0],
        "true_mag": 1.0,
        "voxel_size": voxel_size,
        "units": [units] * 3,
    })

    assert conversions.seriesToLabels(_Series(), fp, group="cells")

    labels = zarr.open(fp, mode="r")["labels_cells"]
    assert labels.attrs["units"] == ["nm", "nm", "nm"]
    assert labels.attrs["voxel_size"] == [50, 1000, 1000]
    assert labels.attrs["offset"] == [100, 2000, 3000]


## label import


def _import_box(tmp_path, real_series, raw_attrs, label_attrs):
    """Import a label box over rows and columns 20 to 39 of a 4 nm raw."""
    snum = sorted(real_series.sections)[1]
    zg = zarr.open(str(tmp_path / "labels.zarr"), "w")
    raw = zg.create_dataset("raw", shape=(1, 100, 100), dtype=np.uint8)
    raw.attrs.update({
        "true_mag": 0.004, "window": [0, 0, 0.4, 0.4], "sections": [snum],
        "alignment": {str(snum): Transform.identity().getList()},
        **raw_attrs,
    })
    labels = zg.create_dataset("labels_x", shape=(1, 100, 100), dtype=np.uint64)
    labels[0, 20:40, 20:40] = 7
    labels.attrs.update(label_attrs)

    conversions.setDT()
    conversions.importSection(zg, "labels_x", snum, real_series)

    section = real_series.loadSection(snum)
    pts = np.array([p for t in section.contours["autoseg_7"] for p in t.points])
    return pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()


AT_ZERO = (0.08, 0.156, 0.244, 0.32)


@pytest.mark.parametrize(
    "raw_attrs, label_attrs",
    [
        (
            {"voxel_size": [50, 4, 4], "offset": [0, 0, 0]},
            {"voxel_size": [50, 4, 4], "offset": [0, 0, 0]},
        ),
        (
            {"voxel_size": [50, 4, 4], "offset": [500, 1200, 2000]},
            {"voxel_size": [50, 4, 4], "offset": [500, 1200, 2000]},
        ),
        (
            {"voxel_size": [50, 4, 4], "offset": [500, 1200, 2000]},
            {
                "voxel_size": [0.05, 0.004, 0.004],
                "offset": [0.5, 1.2, 2.0],
                "units": "um",
            },
        ),
    ],
)
def test_a_shared_offset_does_not_move_the_labels(
    tmp_path, real_series, raw_attrs, label_attrs
):
    bounds = _import_box(tmp_path, real_series, raw_attrs, label_attrs)

    assert bounds == pytest.approx(AT_ZERO)


def test_labels_offset_from_raw_move_by_the_difference(tmp_path, real_series):
    ## 40 nm right and 40 nm down of raw's corner: 10 raw pixels each way
    bounds = _import_box(
        tmp_path,
        real_series,
        {"voxel_size": [50, 4, 4], "offset": [500, 1200, 2000]},
        {"voxel_size": [50, 4, 4], "offset": [500, 1240, 2040]},
    )

    x0, x1, y0, y1 = AT_ZERO
    assert bounds == pytest.approx((x0 + 0.04, x1 + 0.04, y0 - 0.04, y1 - 0.04))


@pytest.mark.parametrize("raw_offset", [[0, 0, 0], [0, 40, 80]])
@pytest.mark.parametrize("units", ["nm", "um"])
def test_raw_offset_shifts_imported_points(tmp_path, real_series, raw_offset, units):
    stored_offset = [v / 1000 for v in raw_offset] if units == "um" else raw_offset
    bounds = _import_box(
        tmp_path, real_series,
        {"voxel_size": [0.05, 0.004, 0.004] if units == "um" else [50, 4, 4],
         "offset": stored_offset, "units": units},
        {"voxel_size": [50, 4, 4], "offset": [0, 0, 0]},
    )

    x0, x1, y0, y1 = AT_ZERO
    dx, dy = -raw_offset[2] / 1000, raw_offset[1] / 1000
    assert bounds == pytest.approx((x0 + dx, x1 + dx, y0 + dy, y1 + dy))


@pytest.mark.parametrize(
    "raw_attrs, label_attrs",
    [
        (
            {"voxel_size": [1, 50, 4, 4], "offset": [0, 0, 0]},
            {"voxel_size": [50, 4, 4], "offset": [0, 0, 0]},
        ),
        (
            {"voxel_size": [50, 4, 4], "offset": [0, 500, 1200, 2000]},
            {"voxel_size": [1, 50, 4, 4], "offset": [500, 1200, 2000]},
        ),
        (
            {
                "voxel_size": [1, 0.05, 0.004, 0.004],
                "offset": [0, 0.5, 1.2, 2.0],
                "units": ["um", "um", "um"],
            },
            {"voxel_size": [50, 4, 4], "offset": [1, 500, 1200, 2000]},
        ),
    ],
)
def test_four_entry_metadata_imports_labels_in_place(
    tmp_path, real_series, raw_attrs, label_attrs
):
    bounds = _import_box(tmp_path, real_series, raw_attrs, label_attrs)

    assert bounds == pytest.approx(AT_ZERO)


def test_shared_z_offset_starts_at_raw_first_section(tmp_path):
    fp = str(tmp_path / "z.zarr")
    zg = zarr.open(fp, "w")
    raw = zg.create_dataset("raw", shape=(3, 4, 4), dtype=np.uint8)
    raw.attrs.update({"voxel_size": [50, 4, 4], "offset": [1000, 0, 0], "sections": [0, 1, 2]})
    labels = zg.create_dataset("labels_x", shape=(2, 4, 4), dtype=np.uint64)
    labels.attrs.update({"voxel_size": [50, 4, 4], "offset": [1050, 0, 0]})

    assert conversions.getLabelsToObjectsData(fp, "labels_x")[2] == 1


## the label overlay


def _overlay(tmp_path, raw_attrs, label_attrs, true_mag=0.004):
    from PyReconstruct.modules.backend.view.zarr_layer import ZarrLayer

    fp = str(tmp_path / "overlay.zarr")
    group = zarr.open_group(fp, mode="w")
    raw = group.create_dataset("raw", shape=(1, 10, 10), dtype="u1")
    raw.attrs.update({"window": [1, 2, 0.4, 0.4], "sections": [3]})
    if true_mag is not None:
        raw.attrs["true_mag"] = true_mag
    raw.attrs.update(raw_attrs)
    labels = group.create_dataset("labels", shape=(1, 5, 5), dtype="u4")
    labels.attrs.update(label_attrs)
    series = types.SimpleNamespace(
        zarr_overlay_fp=fp, zarr_overlay_group="labels", sections={}, data={"sections": {}}
    )
    layer = ZarrLayer(series)
    return layer.zarr_mag, layer.zarr_x, layer.zarr_y, layer.zarr_s


## 8 nm labels over 4 nm raw, 2 label pixels right, 1 down and 1 slice in
NM_OVERLAY = (0.008, 1.016, 2.008, 4)


@pytest.mark.parametrize(
    "raw_attrs, label_attrs",
    [
        (
            {"resolution": [50, 4, 4]},
            {"resolution": [50, 8, 8], "offset": [50, 8, 16]},
        ),
        (
            {"resolution": [50, 4, 4]},
            {
                "resolution": [0.05, 0.008, 0.008],
                "offset": [0.05, 0.008, 0.016],
                "units": ["um", "um", "um"],
            },
        ),
        (
            {"voxel_size": [0.05, 0.004, 0.004], "units": "um"},
            {"voxel_size": [50, 8, 8], "offset": [50, 8, 16]},
        ),
        (
            {"resolution": [50, 4, 4], "offset": [100, 200, 400]},
            {"resolution": [50, 8, 8], "offset": [150, 208, 416]},
        ),
    ],
)
def test_overlay_places_labels_the_same_in_any_units(tmp_path, raw_attrs, label_attrs):
    assert _overlay(tmp_path, raw_attrs, label_attrs) == pytest.approx(NM_OVERLAY)


## 4 nm raw and labels on raw's grid, 2 label pixels right, 1 down and 1 slice in
RAW_GRID_OVERLAY = (0.004, 1.008, 2.004, 4)


@pytest.mark.parametrize(
    "raw_attrs, label_attrs",
    [
        # labels with no size share raw's grid, as import reads them
        ({"resolution": [50, 4, 4]}, {"offset": [50, 4, 8]}),
        ({"voxel_size": [0.05, 0.004, 0.004], "units": "um"}, {"offset": [50, 4, 8]}),
        # raw with no size is on the series grid: true mag and 50 nm sections
        ({}, {"offset": [50, 4, 8]}),
        ({}, {"resolution": [50, 4, 4], "offset": [50, 4, 8]}),
    ],
)
def test_overlay_puts_labels_with_no_size_on_raws_grid(tmp_path, raw_attrs, label_attrs):
    assert _overlay(tmp_path, raw_attrs, label_attrs) == pytest.approx(RAW_GRID_OVERLAY)


@pytest.mark.parametrize("attribute", ["voxel_size", "resolution"])
@pytest.mark.parametrize("label_size", [[1, 0, 0, 0], [1, 50, 4, 4]])
def test_overlay_uses_channel_first_label_resolution(tmp_path, attribute, label_size):
    assert _overlay(
        tmp_path,
        {"voxel_size": [50, 4, 4]},
        {attribute: label_size, "offset": [50, 4, 8]},
    ) == pytest.approx(RAW_GRID_OVERLAY)


@pytest.mark.parametrize(
    "raw_attrs, label_attrs",
    [
        ({"voxel_size": [1, 50, 4, 4]}, {"offset": [50, 4, 8]}),
        ({"voxel_size": [50, 4, 4]}, {"offset": [1, 50, 4, 8]}),
        (
            {"voxel_size": [1, 0.05, 0.004, 0.004], "units": ["um", "um", "um"]},
            {"voxel_size": [1, 0, 0, 0], "offset": [0, 50, 4, 8]},
        ),
    ],
)
def test_overlay_reads_four_entry_raw_and_offset_metadata(tmp_path, raw_attrs, label_attrs):
    assert _overlay(tmp_path, raw_attrs, label_attrs) == pytest.approx(RAW_GRID_OVERLAY)


def test_overlay_with_no_size_on_either_array_starts_at_raws_corner(tmp_path):
    assert _overlay(tmp_path, {}, {}) == pytest.approx((0.004, 1, 2, 3))


@pytest.mark.parametrize("raw_attrs", [{"voxel_size": [25.4, 0, 0]}, {}])
def test_overlay_recovers_legacy_grid_with_series_thickness(tmp_path, raw_attrs):
    from PyReconstruct.modules.backend.view.zarr_layer import ZarrLayer

    fp = str(tmp_path / "legacy-overlay.zarr")
    group = zarr.open_group(fp, mode="w")
    raw = group.create_dataset("raw", shape=(1, 10, 10), dtype="u1")
    raw.attrs.update({
        "window": [1, 2, 0.005, 0.005], "sections": [3], "true_mag": 0.0005,
        **raw_attrs,
    })
    labels = group.create_dataset("labels", shape=raw.shape, dtype="u4")
    labels.attrs["voxel_size"] = [0, 0, 0]
    series = types.SimpleNamespace(
        zarr_overlay_fp=fp, zarr_overlay_group="labels", sections={3: "section3"},
        data={"sections": {3: {"thickness": 0.0254}}},
    )

    layer = ZarrLayer(series)
    assert layer.raw_resolution == layer.resolution == [25.4, 0.5, 0.5]
    assert layer.zarr_mag == pytest.approx(0.0005)
    assert (layer.zarr_x, layer.zarr_y, layer.zarr_s) == (1, 2, 3)


@pytest.mark.parametrize(
    "raw_attrs, label_attrs, expected",
    [
        # true mag from raw's x voxel size, as label import reads it
        ({"resolution": [50, 8, 8]}, {"offset": [50, 8, 16]}, (0.008, 1.016, 2.008, 4)),
        ({"voxel_size": [0.05, 0.008, 0.008], "units": "um"}, {}, (0.008, 1, 2, 3)),
        # no size at all: the 4 nm default
        ({}, {}, (0.004, 1, 2, 3)),
    ],
)
def test_overlay_reads_a_raw_with_no_true_mag(tmp_path, raw_attrs, label_attrs, expected):
    assert _overlay(tmp_path, raw_attrs, label_attrs, true_mag=None) == pytest.approx(expected)


## ng_view.py


def test_ng_view_shows_a_um_zarr_at_its_size_in_nm(tmp_path, monkeypatch):
    fp = str(tmp_path / "view.zarr")
    zg = zarr.open(fp, "w")
    zg.create_dataset("raw", shape=(1, 4, 4), dtype=np.uint8).attrs.update(
        {"voxel_size": [0.05, 0.0041, 0.0041], "units": "um"}
    )

    scales = []

    class _Txn:
        def __enter__(self):
            return types.SimpleNamespace(layers=types.SimpleNamespace(
                append=lambda **kw: None
            ))

        def __exit__(self, *exc):
            return False

    fake_ng = types.SimpleNamespace(
        set_server_bind_address=lambda **kw: None,
        Viewer=lambda: types.SimpleNamespace(txn=_Txn),
        CoordinateSpace=lambda **kw: scales.append(kw["scales"]),
        LocalVolume=lambda *a, **kw: None,
    )
    monkeypatch.setitem(sys.modules, "neuroglancer", fake_ng)
    monkeypatch.setattr(sys, "argv", ["ng_view.py", fp])

    runpy.run_module(
        "PyReconstruct.assets.scripts.create_ng_zarr.ng_view", run_name="__main__"
    )

    assert scales == [[50, 4.1, 4.1]]
