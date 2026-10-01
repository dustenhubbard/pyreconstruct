"""The label overlay maps screen pixels to Zarr pixels the same way everywhere.

`ZarrLayer.getID` (hover, select, and so merge) and `ZarrLayer.generateZarrLayer`
(what is drawn) must both agree with the geometry: the label under a screen
pixel is the Zarr pixel that contains its field point, found by flooring, which
is also how `ImageLayer` crops and places the image under it. Before the fix,
`getID` rounded (so the right half of every label pixel reported its neighbor)
and the drawing truncated the crop start without applying the fractional
remainder (so a pan by part of a Zarr pixel shifted the whole overlay).
"""

import numpy as np
import pytest
import zarr

N = 10  # the label array is N x N
K = 4  # screen pixels per Zarr pixel


def _distinct_ids(series, count):
    """Label ids whose overlay colors are all different, so a render decodes."""
    from PyReconstruct.modules.backend.autoseg.palette import palette_color_array

    palette = series.getOption("autoseg_color_palette") or None
    seed = series.getOption("autoseg_color_seed") or 0
    ids, seen, cand = [], {(100, 100, 100)}, 1
    while len(ids) < count:
        color = tuple(
            palette_color_array(
                np.array([[cand]]), palette, seed, background=(100, 100, 100)
            )[0, 0]
        )
        if color not in seen:
            seen.add(color)
            ids.append(cand)
        cand += 1
    return ids


def _build(series, tmp_path):
    """A real `ZarrLayer` over an on-disk N x N label overlay on a real series.

    One Zarr pixel is K screen pixels at the section's magnification, and the
    labels repeat a 3 x 3 tile so every neighbor of a pixel has another id.
    """
    from PyReconstruct.modules.backend.view.zarr_layer import ZarrLayer

    section = series.loadSection(sorted(series.sections)[0])
    mag = section.mag
    fp = str(tmp_path / "overlay.zarr")
    group = zarr.open_group(fp, mode="w")
    raw = group.create_dataset("raw", shape=(1, N, N), dtype="u1")
    raw.attrs["resolution"] = [50, 2, 2]
    raw.attrs["window"] = [0, 0, N * K * mag, N * K * mag]
    raw.attrs["sections"] = [section.n]
    raw.attrs["true_mag"] = K * mag
    tile = np.array(_distinct_ids(series, 9), dtype="u4")
    rr, cc = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    ids = tile[3 * (rr % 3) + cc % 3]
    labels = group.create_dataset("labels", shape=(1, N, N), dtype="u4")
    labels[0] = ids
    labels.attrs["offset"] = [0, 0, 0]
    labels.attrs["resolution"] = [50, 2, 2]
    series.zarr_overlay_fp = fp
    series.zarr_overlay_group = "labels"
    return ZarrLayer(series), section, mag, ids


def _shown(layer, section, dim, window):
    """The label id drawn at each screen pixel, decoded from the palette colors."""
    from PySide6.QtGui import QImage

    from PyReconstruct.modules.backend.autoseg.palette import palette_color_array

    pixmap = layer.generateZarrLayer(section, dim, window)
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h = dim
    buf = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
    buf = buf.reshape(img.height(), img.bytesPerLine())
    rgb = buf[:, : img.width() * 3].reshape(img.height(), img.width(), 3)[:h, :w]
    palette = layer.series.getOption("autoseg_color_palette") or None
    seed = layer.series.getOption("autoseg_color_seed") or 0
    all_ids = np.unique(layer.zarr[0])
    colors = palette_color_array(
        all_ids[None, :], palette, seed, background=(100, 100, 100)
    )[0]
    lut = {tuple(c): int(i) for i, c in zip(all_ids, colors)}
    shown = np.full((h, w), -1, dtype=int)
    for y in range(h):
        for x in range(w):
            shown[y, x] = lut.get(tuple(rgb[y, x]), -1)
    return shown


def _true_id(ids, field_x, field_y, zmag):
    """The label whose Zarr pixel contains a field point, or None outside it."""
    c = int(np.floor(field_x / zmag))
    r = int(np.floor(N - field_y / zmag))
    if 0 <= c < N and 0 <= r < N:
        return int(ids[r, c])
    return None


def _mismatches(layer, section, mag, ids, dim, window):
    """Screen pixels where the drawing, `getID`, and the geometry disagree."""
    from PyReconstruct.modules.calc import pixmapPointToField

    shown = _shown(layer, section, dim, window)
    bad = []
    for py in range(dim[1]):
        for px in range(dim[0]):
            fx, fy = pixmapPointToField(px + 0.5, py + 0.5, dim, window, mag)
            want = _true_id(ids, fx, fy, layer.zarr_mag)
            got = layer.getID(px, py)
            got = None if got is None else int(got)
            drawn = int(shown[py, px])
            if want is None:
                # outside the overlay: nothing is drawn and nothing is picked
                if got is not None or drawn != -1:
                    bad.append((px, py, drawn, want, got))
            elif drawn != want or got != want:
                bad.append((px, py, drawn, want, got))
    return bad


# The window origin in Zarr pixels, per axis. 0 is edge aligned, the halves are
# the pan from the report, and the negative ones put blank space on the left
# and top so the placement has to include it. The zoom is screen pixels per
# image pixel; the fractional ones make the scale itself fractional. No case
# puts a screen pixel center exactly on a Zarr pixel edge, where the drawing
# and the float geometry could break the tie differently.
@pytest.mark.parametrize("zoom", [1, 1.3, 0.37], ids=["zoom1", "zoom1.3", "zoom0.37"])
@pytest.mark.parametrize(
    "shift",
    [(0, 0), (0.5, 0.5), (0.2, 0.7), (-1.5, -0.5), (2.3, -2.7)],
    ids=["aligned", "half", "fraction", "blank-edge", "mixed"],
)
def test_drawn_and_picked_labels_match_geometry(
    qapp, real_series, tmp_path, shift, zoom
):
    layer, section, mag, ids = _build(real_series, tmp_path)
    dim = (32, 32)
    window = [
        shift[0] * layer.zarr_mag,
        shift[1] * layer.zarr_mag,
        dim[0] * mag / zoom,
        dim[1] * mag / zoom,
    ]
    bad = _mismatches(layer, section, mag, ids, dim, window)
    # (px, py, drawn, true, getID) for the first few, if any
    assert not bad, f"{len(bad)} of {dim[0] * dim[1]} pixels disagree: {bad[:6]}"


def test_full_overlay_view_matches_geometry(qapp, real_series, tmp_path):
    layer, section, mag, ids = _build(real_series, tmp_path)
    dim = (N * K, N * K)
    window = [0, 0, N * K * mag, N * K * mag]
    bad = _mismatches(layer, section, mag, ids, dim, window)
    assert not bad, f"{len(bad)} of {dim[0] * dim[1]} pixels disagree: {bad[:6]}"


def test_merge_rewrites_the_labels_that_were_clicked(qapp, real_series, tmp_path):
    """Selecting two labels by clicking them merges those two on disk.

    Each click lands three quarters of the way across its Zarr pixel, where the
    old rounding picked the label one column to the right.
    """
    layer, section, mag, ids = _build(real_series, tmp_path)
    dim = (N * K, N * K)
    window = [0, 0, N * K * mag, N * K * mag]
    layer.generateZarrLayer(section, dim, window)

    # screen x = (column + 0.75) * K; screen y in the middle of row 5
    first, second = (2, 5), (4, 5)
    for col, row in (first, second):
        assert layer.selectID(int((col + 0.75) * K), int((row + 0.5) * K))
    clicked = {int(ids[first[1], first[0]]), int(ids[second[1], second[0]])}
    assert {int(i) for i in layer.selected_ids} == clicked
    # the selection highlight draws over the same crop
    assert layer.generateZarrLayer(section, dim, window) is not None

    _assert_merged(layer, real_series, ids, clicked)


def test_click_after_partial_pan_merges_the_drawn_labels(
    qapp, real_series, tmp_path
):
    """A click comes in as whole screen pixels, the way a mouse event gives it.

    After a pan of (0.2, 0.7) Zarr pixels, screen pixels (3, 0) and (7, 0) sit
    at the left edge of their labels: their corners fall in the label to the
    left, their centers in the label that is drawn there. The click must merge
    the drawn labels.
    """
    layer, section, mag, ids = _build(real_series, tmp_path)
    dim = (32, 32)
    window = [0.2 * layer.zarr_mag, 0.7 * layer.zarr_mag, dim[0] * mag, dim[1] * mag]
    shown = _shown(layer, section, dim, window)

    clicks = [(3, 0), (7, 0)]
    drawn = {int(shown[py, px]) for px, py in clicks}
    assert len(drawn) == 2
    for px, py in clicks:
        assert layer.selectID(px, py)
    assert {int(i) for i in layer.selected_ids} == drawn

    _assert_merged(layer, real_series, ids, drawn)


def _assert_merged(layer, series, ids, clicked):
    """Merge the selection and check only the clicked labels changed on disk."""
    layer.mergeLabels()
    on_disk = zarr.open_group(series.zarr_overlay_fp, mode="r")["labels"][0]
    keep, gone = min(clicked), max(clicked)
    assert not (on_disk == gone).any()
    expected = np.where(ids == gone, keep, ids)
    np.testing.assert_array_equal(on_disk, expected)
