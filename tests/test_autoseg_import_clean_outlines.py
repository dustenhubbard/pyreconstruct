"""The label import writes no trace that Series > Clean up would then repair.

On a real autoseg series (124 sections, 54,380 traces) the importer's outlines
gave Clean up 477 self-crossing traces, 184 pixel-dust traces and 1,174 open
two-point lines. Every self-crossing one came from findContours walking twice
through a pixel where a label touches itself at a corner, not from the point
reduction. The import now splits such an outline into its loops, and skips an
outline that is a line or a speck at or below the pixel-dust default.
"""
import numpy as np
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Series


def _figure_eight():
    """Two 6 x 6 squares that touch only at one corner pixel.

    Smaller ones do not reach the split: the point reduction drops the pixel
    the outline visits twice, and returns one valid outline round both.
    """
    mask = np.zeros((16, 16), dtype=bool)
    mask[2:8, 2:8] = True
    mask[8:14, 8:14] = True
    return mask


def _area(ext):
    x, y = np.asarray(ext, dtype=float).T
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def test_a_corner_touch_becomes_two_simple_outlines():
    from shapely.geometry import Polygon

    exteriors = conversions.getExteriors(_figure_eight())

    assert len(exteriors) == 2
    assert all(Polygon(ext).is_valid for ext in exteriors)
    ## each loop is the 5 x 5 square through the centers of its edge pixels
    assert sorted(_area(ext) for ext in exteriors) == [25.0, 25.0]


def test_a_simple_outline_is_returned_as_it_was():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:8, 3:7] = True

    (ext,) = conversions.getExteriors(mask)

    assert ext.tolist() == [[3, 2], [3, 7], [6, 7], [6, 2]]


def _import(tmp_path, real_series, labels_2d):
    """Import one section of labels drawn at the section's own pixel size."""
    snum = sorted(real_series.sections)[1]
    section = real_series.loadSection(snum)
    mag = section.mag
    rows, cols = labels_2d.shape
    zg = zarr.open(str(tmp_path / "labels.zarr"), "w")
    raw = zg.create_dataset("raw", shape=(1, rows, cols), dtype=np.uint8)
    raw.attrs.update({
        "voxel_size": [50, 4, 4], "offset": [0, 0, 0],
        "true_mag": mag, "window": [0, 0, cols * mag, rows * mag],
        "sections": [snum],
        ## the section's own transform, so a label pixel is a field pixel
        "alignment": {str(snum): section.tform.getList()},
    })
    labels = zg.create_dataset("labels_x", shape=(1, rows, cols), dtype=np.uint64)
    labels[0] = labels_2d
    labels.attrs.update({"voxel_size": [50, 4, 4], "offset": [0, 0, 0]})

    conversions.setDT()
    conversions.importSection(zg, "labels_x", snum, real_series)
    return snum


def test_import_leaves_nothing_for_clean_up(tmp_path, real_series):
    labels = np.zeros((80, 80), dtype=np.uint64)
    labels[5:25, 5:25] = 7               # a real object
    labels[40:56, 40:56][_figure_eight()] = 8  # touches itself at a corner
    labels[60:62, 60:62] = 9             # 2 x 2 speck: area 1 px^2
    labels[70, 10:30] = 10               # one pixel wide: a line
    labels[30:33, 60:63] = 11            # 3 x 3 speck: area 4 px^2
    labels[5:9, 60:64] = 12              # 4 x 4: area 9 px^2, still dust
    labels[5:10, 70:75] = 13             # 5 x 5: area 16 px^2, kept

    snum = _import(tmp_path, real_series, labels)

    contours = real_series.loadSection(snum).contours
    autoseg = {name: len(contours[name]) for name in contours
               if name.startswith("autoseg_") and len(contours[name])}
    assert autoseg == {"autoseg_7": 1, "autoseg_8": 2, "autoseg_13": 1}
    assert all(t.closed for name in autoseg for t in contours[name])

    clean_up = (
        real_series.findPixelDustTraces(Series.PIXEL_DUST_DEFAULT_PX, include_locked=True)
        + real_series.findSelfCrossingTraces()
        + real_series.findEmptyTraces(include_locked=True)
    )
    assert [r for r in clean_up if r["name"].startswith("autoseg_")] == []

    ## an id with nothing left on the section joins no group from it
    grouped = set(real_series.object_groups.getGroupObjects("seg_labels_x"))
    assert grouped == {"autoseg_7", "autoseg_8", "autoseg_13"}
