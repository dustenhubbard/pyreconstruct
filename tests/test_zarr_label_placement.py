"""One placement for Zarr labels, shared by the label overlay and label import.

The overlay and the import each worked out where labels sit in the field. They
agreed in x, but in y the overlay hung the labels from raw's bottom edge and
moved them up by their offset, while import (rightly) hangs them from raw's top
edge and moves them down. Labels shorter than raw, or offset in y, were drawn
away from where they imported. The overlay also picked a section's slice by
section number, so a gap in raw's sections showed the wrong slice. Both use
``label_placement`` now, and these fixtures check the drawn label against the
imported trace.
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
    assert p.raw_rows == 5


def test_rows_count_down_from_the_top_of_raw():
    """Label row 0 is raw's top edge; field y counts up from raw's bottom."""
    p = label_placement([50, 4, 4], [50, 4, 4], [0, 0, 0], [1, 2], [0], 0.004, 10)
    assert p.to_field([[0, 0], [3, 10]]).ravel() == pytest.approx(
        [1, 2.04, 1.012, 2]
    )


def test_offsets_move_labels_right_and_down_in_label_pixels():
    """An offset of 16 nm across and 8 nm down is 2 and 1 pixels at 8 nm."""
    p = label_placement([50, 8, 8], [50, 4, 4], [0, 8, 16], [1, 2], [0], 0.004, 10)
    assert p.to_field([[0, 0]]).ravel() == pytest.approx([1.016, 2.032])


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


def test_to_label_undoes_to_field():
    p = label_placement([50, 8, 8], [50, 4, 4], [0, 8, 16], [1, 2], [0], 0.004, 10)
    (x, y), = p.to_field([[3.25, 1.5]])
    assert p.to_label(x, y) == pytest.approx((3.25, 1.5))


@pytest.mark.parametrize(
    "z_offset_nm, snum, expected",
    [
        (0, 3, 0), (0, 5, 1), (0, 4, None), (0, 9, None),
        (50, 3, None), (50, 5, 0), (50, 7, 1),
    ],
)
def test_slices_follow_raw_sections_and_skip_a_gap(z_offset_nm, snum, expected):
    """Raw's slices are sections 3, 5 and 7; section 4 was deleted."""
    p = label_placement(
        [50, 4, 4], [50, 4, 4], [z_offset_nm, 0, 0], [0, 0], [3, 5, 7], 0.004, 10
    )
    assert p.slice_index(snum) == expected


## the overlay and the import agree


def _ids(depth, rows, cols):
    """Label 7 in a small block near the top left, and 0 around it.

    The block is a column further right on each slice, so a section shown
    with another section's slice shows.
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


def _drawn_id(layer, snum, x, y):
    """The label the overlay draws at field point (x, y) on section snum."""
    size = layer.placement.mag / 8
    window = [x - size / 2, y - size / 2, size, size]
    if layer.generateZarrLayer(types.SimpleNamespace(n=snum), (1, 1), window) is None:
        return None
    label = layer.getID(0, 0)
    return None if label is None else int(label)


@pytest.mark.parametrize("case", list(CASES))
def test_overlay_draws_labels_where_they_import(qapp, tmp_path, real_series, case):
    fp, zg, sections = _zarr(tmp_path, real_series, case)
    layer = _overlay(fp)
    mag = layer.placement.mag
    conversions.setDT()

    imported = 0
    for snum in sections:
        conversions.importSection(zg, "labels_x", snum, real_series)
        contours = real_series.loadSection(snum).contours
        if "autoseg_7" not in contours:
            assert _drawn_id(layer, snum, 1.001, 2.001) is None
            continue
        imported += 1
        pts = np.array([p for t in contours["autoseg_7"] for p in t.points])
        x0, x1 = pts[:, 0].min(), pts[:, 0].max()
        y0, y1 = pts[:, 1].min(), pts[:, 1].max()
        ## trace points are the top left corners of the block's edge pixels,
        ## so the block's corner pixels are centered half a pixel right and
        ## down from them, and their neighbors outside are a pixel further
        half = mag / 2
        inside = [(x0 + half, y1 - half), (x1 + half, y0 - half)]
        outside = [
            (x0 - half, y1 - half), (x0 + half, y1 + half),
            (x1 + 3 * half, y0 - half), (x1 + half, y0 - 3 * half),
        ]
        assert [_drawn_id(layer, snum, x, y) for x, y in inside] == [7, 7]
        assert 7 not in [_drawn_id(layer, snum, x, y) for x, y in outside]
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
