"""Where the ROI mode box sits while it follows an object.

The box keeps its size and is centered on the object, section by section. The
object's place on a section comes from the series data, not the section: each
trace's centroid and radius (its farthest point from the centroid), so paging
loads nothing extra. The center is the middle of the square that holds every
trace of the object on that section; for one trace that is its centroid.

On a section without the object, the box takes its place on the nearest
section with it, ties going to the earlier section. The zarr crop uses the
same rule for a section without its object (backend/crop_zarr.py, planCrop).
"""
import numpy as np


def objectExtents(series, name : str):
    """The square around each trace of an object, from the series data.

        Params:
            series (Series): the series
            name (str): the object's name
        Returns:
            (tuple): numpy arrays (section numbers, xmin, ymin, xmax, ymax),
                one entry per trace, in field coordinates; None when no
                section has the object
    """
    obj_data = series.data["objects"].get(name)
    if obj_data is None or obj_data.isEmpty():
        return None
    rows = obj_data.columnRows()
    if rows is not None:
        # an open from the local store: read its columns, building no TraceData
        columns, start, stop = rows
        arrays = columns.arrays
        snums = np.asarray(arrays["snum"][start:stop], dtype=int)
        cx = np.asarray(arrays["cx"][start:stop], dtype=float)
        cy = np.asarray(arrays["cy"][start:stop], dtype=float)
        r = np.asarray(arrays["radius"][start:stop], dtype=float)
    else:
        items = [
            (snum, *td.centroid, td.radius)
            for snum, tds in obj_data.traces.items()
            for td in tds
        ]
        if not items:
            return None
        arr = np.asarray(items, dtype=float)
        snums = arr[:, 0].astype(int)
        cx, cy, r = arr[:, 1], arr[:, 2], arr[:, 3]
    return snums, cx - r, cy - r, cx + r, cy + r


def objectCenters(series, name : str) -> dict:
    """The object's center on each section that has it.

        Returns:
            (dict): section number -> (x, y) in field coordinates; empty when
                no section has the object
    """
    extents = objectExtents(series, name)
    if extents is None:
        return {}
    snums, xmin, ymin, xmax, ymax = extents
    centers = {}
    for snum in np.unique(snums):
        on = snums == snum
        centers[int(snum)] = (
            float((xmin[on].min() + xmax[on].max()) / 2),
            float((ymin[on].min() + ymax[on].max()) / 2),
        )
    return centers


def nearestSection(snums, snum : int):
    """The nearest of snums to snum, ties going to the earlier section.

        Returns:
            (int): the section number, or None when snums is empty
    """
    if not snums:
        return None
    return min(snums, key=lambda k: (abs(k - snum), k))


def followCenter(centers : dict, snum : int):
    """Where a followed box is centered on a section.

        Params:
            centers (dict): objectCenters of the followed object
            snum (int): the section shown
        Returns:
            (tuple): ((x, y), the section the place comes from), or None when
                no section has the object
    """
    if snum in centers:
        return centers[snum], snum
    near = nearestSection(centers, snum)
    if near is None:
        return None
    return centers[near], near
