"""One placement calculation for Zarr labels, shared by the overlay and import.

Both read the same magnification, crop origin and label offsets from it. They
anchor rows and pick a section's slice each their own way, and the fixtures
below pin each to the placement it had before the calculation was shared.
"""
import types

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions, placement
from PyReconstruct.modules.backend.autoseg.placement import label_placement
from PyReconstruct.modules.datatypes import Transform


## the calculation


def test_magnification_is_raw_true_mag_at_the_label_size():
    p = label_placement([50, 8, 8], [50, 4, 4], [0, 0, 0], [0, 0], [0], 0.004, 10)
    assert p.mag == pytest.approx(0.008)
    assert p.overlay_mag == pytest.approx(0.008)
    assert p.raw_rows == 5


def test_import_rows_count_down_from_the_top_of_raw():
    """Label row 0 is raw's top edge; field y counts up from raw's bottom."""
    p = label_placement([50, 4, 4], [50, 4, 4], [0, 0, 0], [1, 2], [0], 0.004, 10)
    assert p.to_field([[0, 0], [3, 10]]).ravel() == pytest.approx(
        [1, 2.04, 1.012, 2]
    )


def test_import_offsets_move_labels_right_and_down_in_label_pixels():
    """An offset of 16 nm across and 8 nm down is 2 and 1 pixels at 8 nm."""
    p = label_placement([50, 8, 8], [50, 4, 4], [0, 8, 16], [1, 2], [0], 0.004, 10)
    assert p.to_field([[0, 0]]).ravel() == pytest.approx([1.016, 2.032])


def test_overlay_origin_moves_by_the_offsets_in_label_pixels():
    """2 pixels right, 1 up and 1 section in, from the crop origin (1, 2)."""
    p = label_placement([50, 8, 8], [50, 4, 4], [50, 8, 16], [1, 2], [3, 4], 0.004, 10)
    assert p.overlay_origin() == pytest.approx((1.016, 2.008, 4))


def test_unit_conversion_happens_before_the_calculation():
    """µm metadata reads as the same nm, so it places the labels the same."""
    nm = zarr.zeros((1, 10, 10), dtype="u1")
    nm.attrs.update({"voxel_size": [50, 8, 8], "offset": [0, 8, 16]})
    um = zarr.zeros((1, 10, 10), dtype="u1")
    um.attrs.update({
        "voxel_size": [0.05, 0.008, 0.008], "offset": [0, 0.008, 0.016], "units": "um",
    })
    raw = zarr.zeros((1, 10, 10), dtype="u1")
    raw.attrs["voxel_size"] = [50, 4, 4]

    def placed(labels):
        res, raw_res = conversions.get_label_resolutions(labels, raw)
        offset = conversions.get_label_offset(labels, raw)
        return label_placement(res, raw_res, offset, [1, 2], [0], 0.004, 10)

    assert placed(um) == placed(nm)


@pytest.mark.parametrize(
    "z_offset_nm, snum, expected",
    [
        (0, 3, 0), (0, 5, 1), (0, 4, None), (0, 9, None),
        (50, 3, None), (50, 5, 0), (50, 7, 1),
    ],
)
def test_import_slices_follow_raw_sections(z_offset_nm, snum, expected):
    """Raw's slices are sections 3, 5 and 7."""
    p = label_placement(
        [50, 4, 4], [50, 4, 4], [z_offset_nm, 0, 0], [0, 0], [3, 5, 7], 0.004, 10
    )
    assert p.slice_index(snum) == expected


## each caller keeps its own placement


def _ids(depth, rows, cols):
    """Label 7 in a small block near the top left, and 0 around it.

    The block is a column further right on each slice, so the slice each
    section shows is visible.
    """
    labels = np.zeros((depth, rows, cols), dtype=np.uint32)
    for z in range(depth):
        labels[z, 1:3, 2 + z:5 + z] = 7
    return labels


## (label size, raw size, label offset, units, raw shape, label shape, sections)
CASES = {
    "same-grid": ([50, 4, 4], [50, 4, 4], [0, 0, 0], None, (2, 12, 12), (2, 12, 12), (0, 1)),
    "coarser": ([50, 8, 8], [50, 4, 4], [0, 0, 0], None, (2, 12, 12), (2, 6, 6), (0, 1)),
    "finer": ([50, 2, 2], [50, 4, 4], [0, 0, 0], None, (2, 6, 6), (2, 12, 12), (0, 1)),
    "offset-crop": ([50, 8, 8], [50, 4, 4], [0, 8, 24], None, (2, 16, 16), (2, 4, 5), (0, 1)),
    "um": ([0.05, 0.008, 0.008], [50, 4, 4], [0, 0.008, 0.024], "um", (2, 16, 16), (2, 4, 5), (0, 1)),
    "section-offset": ([50, 4, 4], [50, 4, 4], [50, 8, 0], None, (3, 12, 12), (2, 6, 8), (0, 1, 2)),
    "section-gap": ([50, 4, 4], [50, 4, 4], [0, 0, 0], None, (2, 12, 12), (2, 12, 12), (0, 2)),
    "4d-labels": ([1, 50, 8, 8], [50, 4, 4], [0, 0, 8, 8], None, (2, 16, 16), (1, 2, 4, 5), (0, 1)),
    "4d-raw": ([50, 8, 8], [1, 50, 4, 4], [0, 8, 8], None, (1, 2, 16, 16), (2, 4, 5), (0, 1)),
}


def _zarr(tmp_path, series, case):
    """A Zarr exported from series at a crop origin of (1, 2), with labels."""
    label_size, raw_size, offset, units, raw_shape, label_shape, picks = CASES[case]
    snums = sorted(series.sections)
    sections = [snums[i] for i in picks]
    fp = str(tmp_path / f"{case}.zarr")
    zg = zarr.open_group(fp, mode="w")
    raw = zg.create_dataset("raw", shape=raw_shape, dtype="u1")
    raw.attrs.update({
        "voxel_size": raw_size, "offset": [0] * len(raw_size), "true_mag": 0.004,
        "window": [1, 2, raw_shape[-1] * 0.004, raw_shape[-2] * 0.004],
        "sections": sections,
        "alignment": {str(n): Transform.identity().getList() for n in sections},
    })
    labels = _ids(*label_shape[-3:]).reshape(label_shape)
    attrs = {"voxel_size": label_size, "offset": offset}
    if units:
        attrs["units"] = units
    zg.create_dataset("labels_x", data=labels).attrs.update(attrs)
    return fp, zg, sections


def _overlay(fp):
    from PyReconstruct.modules.backend.view.zarr_layer import ZarrLayer

    series = types.SimpleNamespace(
        zarr_overlay_fp=fp, zarr_overlay_group="labels_x",
        sections={}, data={"sections": {}}, getOption=lambda name: None,
    )
    return ZarrLayer(series)


def _metadata(zg, series):
    labels, raw = zg["labels_x"], zg["raw"]
    res, raw_res = conversions.get_label_resolutions(labels, raw, series)
    offset = conversions.get_label_offset(labels, raw)
    return res, raw_res, offset, raw.attrs


def _base_overlay(zg, series):
    """The overlay's mag, x, y and first section, worked out as it always was."""
    res, raw_res, offset, attrs = _metadata(zg, series)
    x, y = tuple(attrs["window"][:2])
    s = attrs["sections"][0]
    mag = conversions.get_true_mag(zg["raw"]) * (res[-1] / raw_res[-1])
    pixel_offset = [o / r for o, r in zip(offset, res)]
    field_offset = [p * mag for p in pixel_offset]
    return mag, x + field_offset[2], y + field_offset[1], s + pixel_offset[0]


def _base_import_points(zg, series, ext):
    """Label import's trace points for ext, worked out as they always were."""
    res, raw_res, offset, attrs = _metadata(zg, series)
    mag = attrs["true_mag"] / raw_res[-1] * res[-1]
    ext = ext.astype(np.float64)
    ext[:, 0] += offset[2] / res[2]
    ext[:, 1] += offset[1] / res[1]
    ext[:, 1] *= -1
    ext[:, 1] += zg["raw"].shape[-2] * (raw_res[1] / res[1])
    ext *= mag
    ext[:, 0] += attrs["window"][0]
    ext[:, 1] += attrs["window"][1]
    return Transform.identity().map(ext.tolist(), inverted=True)


def _base_import_slice(zg, series, snum):
    res, raw_res, offset, attrs = _metadata(zg, series)
    if snum not in attrs["sections"]:
        return None
    zi = attrs["sections"].index(snum) - round(offset[0] / res[0])
    return zi if 0 <= zi < conversions.label_volume(zg["labels_x"]).shape[0] else None


def _drawn_id(layer, snum, x, y):
    """The label the overlay draws at field point (x, y) on section snum."""
    size = layer.zarr_mag / 8
    window = [x - size / 2, y - size / 2, size, size]
    if layer.generateZarrLayer(types.SimpleNamespace(n=snum), (1, 1), window) is None:
        return None
    label = layer.getID(0, 0)
    return None if label is None else int(label)


@pytest.mark.parametrize("case", list(CASES))
def test_overlay_places_labels_as_before(qapp, tmp_path, real_series, case):
    fp, zg, sections = _zarr(tmp_path, real_series, case)
    layer = _overlay(fp)
    mag, x0, y0, s0 = _base_overlay(zg, real_series)
    assert (layer.zarr_mag, layer.zarr_x, layer.zarr_y, layer.zarr_s) == (mag, x0, y0, s0)

    ## label pixel (c, r) on slice z is drawn from (x0, y0), rows hanging
    ## down from the labels' height, on section s0 + z
    ids = conversions.label_volume(zg["labels_x"])
    depth, rows, cols = ids.shape
    for snum in sections:
        z = round(snum - s0)
        for c, r in [(0, 0), (2, 1), (3, 2), (cols - 1, 1), (cols - 1, rows - 1)]:
            x = x0 + (c + 0.5) * mag
            y = y0 + (rows - r - 0.5) * mag
            want = int(ids[z, r, c]) if 0 <= z < depth else None
            assert _drawn_id(layer, snum, x, y) == want


@pytest.mark.parametrize("case", list(CASES))
def test_import_places_labels_as_before(qapp, tmp_path, real_series, case):
    fp, zg, sections = _zarr(tmp_path, real_series, case)
    ids = conversions.label_volume(zg["labels_x"])
    conversions.setDT()

    imported = 0
    for snum in sorted(real_series.sections):
        zi = _base_import_slice(zg, real_series, snum)
        conversions.importSection(zg, "labels_x", snum, real_series)
        traces = real_series.loadSection(snum).contours.get("autoseg_7", [])
        got = [[tuple(p) for p in t.points] for t in traces]
        if zi is None:
            assert got == []
            continue
        want = [
            [tuple(p) for p in _base_import_points(zg, real_series, ext)]
            for ext in conversions.getExteriors(ids[zi] == 7)
        ]
        assert got == want
        imported += 1
    assert imported >= 1


def test_overlay_and_import_both_use_the_shared_calculation(
    qapp, tmp_path, real_series, monkeypatch
):
    calls = []
    real = placement.label_placement

    def spy(*args):
        result = real(*args)
        calls.append(result)
        return result

    monkeypatch.setattr(placement, "label_placement", spy)
    monkeypatch.setattr(conversions, "label_placement", spy)
    fp, zg, sections = _zarr(tmp_path, real_series, "offset-crop")

    overlay = _overlay(fp).placement
    conversions.setDT()
    conversions.importSection(zg, "labels_x", sections[0], real_series)

    assert len(calls) == 2
    assert calls[0] is overlay
    assert calls[1] == overlay
