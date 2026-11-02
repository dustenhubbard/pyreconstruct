"""Where the ROI mode box sits while it follows an object, and which objects
it keeps whole.

The box keeps its size and is centered on the object, section by section. The
object's place on a section comes from the series data, not the section: each
trace's centroid and radius (its farthest point from the centroid), so paging
loads nothing extra. The center is the middle of the range of the object's
trace centroids on that section; for one trace it is that trace's centroid.

The series data measures an object under its own alignment when it has one
(ObjectData.sectionTransform), and the field draws every trace under the
series alignment. So each centroid is moved into the displayed coordinates,
and each radius grows by the most that move can stretch a length. An affine
move takes a centroid to the centroid of the moved trace, so a center from
the series data is the center the shown section gives; a grown radius is an
upper bound only, used for touching the box (objectsTouching), never for the
center.

The shown section is the exception: its traces are read live, as drawn
(sectionSquares), since an edit there reaches the series data only when it
is saved, after the view that shows it is drawn.

On a section without the object, the box takes its place on the nearest
section with it, ties going to the earlier section. The zarr crop uses the
same rule for a section without its object (backend/crop_zarr.py, planCrop).
"""
import numpy as np

from PyReconstruct.modules.calc import traceGeometry

## The move from measured to displayed coordinates when they are the same
_SAME = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0)


def measuredToDisplay(measured, display) -> tuple:
    """The affine that takes a point measured under one transform to where
    the field draws it under another, and the most it stretches a length.

        Params:
            measured (Transform): the transform the numbers were measured with
            display (Transform): the transform the field draws with
        Returns:
            (tuple): a, b, c, d, e, f (x' = a x + b y + c, y' = d x + e y + f)
                and the stretch; no move when either transform is missing
                or the measured one cannot be inverted
    """
    if measured is None or display is None or measured is display:
        return _SAME
    if measured.equals(display):
        return _SAME
    try:
        a, b, c, d, e, f = (measured.inverted() * display).getList()
    except Exception:
        return _SAME
    stretch = float(np.linalg.norm(np.array([[a, b], [d, e]], dtype=float), 2))
    return (a, b, c, d, e, f, stretch)


def objectExtents(series, name : str, display_tform, moves : dict = None):
    """The square around each trace of an object, in displayed coordinates.

        Params:
            series (Series): the series
            name (str): the object's name
            display_tform (callable): section number -> the Transform the
                field draws that section with, or None
            moves (dict): a cache of measuredToDisplay results to share
                across calls
        Returns:
            (tuple): numpy arrays (section numbers, xmin, ymin, xmax, ymax),
                one entry per trace; None when no section has the object
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
        tkeys = np.asarray(arrays["tform"][start:stop], dtype=int)
        measured = columns.tforms
    else:
        items, measured, index = [], [], {}
        for snum, tds in obj_data.traces.items():
            for td in tds:
                tform = getattr(td, "_tform", None)
                key = index.get(id(tform))
                if key is None:
                    key = index[id(tform)] = len(measured)
                    measured.append(tform)
                items.append((snum, *td.centroid, td.radius, key))
        if not items:
            return None
        arr = np.asarray(items, dtype=float)
        snums = arr[:, 0].astype(int)
        cx, cy, r = arr[:, 1], arr[:, 2], arr[:, 3]
        tkeys = arr[:, 4].astype(int)

    return (snums, *displaySquares(snums, cx, cy, r, tkeys, measured, display_tform, moves))


def displaySquares(snums, cx, cy, r, tkeys, measured, display_tform, moves=None):
    """Move measured centroids and radii into displayed squares, one affine
    per (section, measured transform) pair.

        Params:
            snums, cx, cy, r, tkeys: numpy arrays, one entry per trace; tkeys
                index measured
            measured (list): the transforms the numbers were measured with
            display_tform, moves: as in objectExtents
        Returns:
            (tuple): numpy arrays xmin, ymin, xmax, ymax
    """
    if moves is None:
        moves = {}
    pairs, which = np.unique(np.stack([snums, tkeys], axis=1), axis=0, return_inverse=True)
    which = np.asarray(which).reshape(-1)
    table = np.empty((len(pairs), 7), dtype=float)
    for i, (snum, key) in enumerate(pairs):
        tform, shown = measured[int(key)], display_tform(int(snum))
        cache_key = (id(tform), id(shown))
        move = moves.get(cache_key)
        if move is None:
            move = moves[cache_key] = measuredToDisplay(tform, shown)
        table[i] = move
    a, b, c, d, e, f, stretch = table[which].T
    x = a * cx + b * cy + c
    y = d * cx + e * cy + f
    r = r * stretch
    return x - r, y - r, x + r, y + r


def sectionSquares(section, name : str, held=()):
    """The square around each trace of an object on a loaded section, as the
    field draws it: the same centroid and radius the series data keeps
    (traceGeometry), under the section's own transform.

        Params:
            held (list): traces a tool holds out of the section while it
                edits them (Scissors), counted as the section's own
        Returns:
            (tuple): numpy arrays (xmin, ymin, xmax, ymax), one entry per
                trace with points; empty when the section has none
    """
    tform = section.tform
    rows = []
    traces = list(section.contours.get(name, ()))
    traces += [t for t in held if t.name == name]
    for trace in traces:
        if not trace.points:
            continue
        pts = tform.mapPointsArray(trace.points)
        _, _, (cx, cy), r = traceGeometry(pts, trace.closed)
        rows.append((cx - r, cy - r, cx + r, cy + r))
    if not rows:
        return (np.empty(0),) * 4
    arr = np.asarray(rows, dtype=float)
    return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]


def objectCenters(series, name : str, display_tform, shown=None, held=()) -> dict:
    """The object's center on each section that has it, in displayed
    coordinates (display_tform as in objectExtents).

        Params:
            shown (Section): the loaded section the field shows, whose own
                traces are read in place of its series data
            held (list): traces a tool holds out of the shown section
                (sectionSquares)
        Returns:
            (dict): section number -> (x, y) in field coordinates; empty when
                no section has the object
    """
    extents = objectExtents(series, name, display_tform)
    if extents is None:
        extents = (np.empty(0, dtype=int),) + (np.empty(0),) * 4
    snums, xmin, ymin, xmax, ymax = extents
    if shown is not None:
        keep = snums != shown.n
        live = sectionSquares(shown, name, held)
        snums = np.concatenate([snums[keep], np.full(len(live[0]), shown.n, dtype=int)])
        xmin, ymin, xmax, ymax = (
            np.concatenate([a[keep], b]) for a, b in zip((xmin, ymin, xmax, ymax), live)
        )
    # each square's middle is its trace's centroid, exact under any affine
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    centers = {}
    for snum in np.unique(snums):
        on = snums == snum
        centers[int(snum)] = (
            float((cx[on].min() + cx[on].max()) / 2),
            float((cy[on].min() + cy[on].max()) / 2),
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


def _touching(snums, xmin, ymin, xmax, ymax, box_snums, bx):
    """Which squares touch the box on their own section (boxes sorted by
    section number in box_snums, bounds in bx)."""
    if not len(snums):
        return np.zeros(0, dtype=bool)
    at = np.searchsorted(box_snums, snums)
    at_ok = np.minimum(at, len(box_snums) - 1)
    boxed = (at < len(box_snums)) & (box_snums[at_ok] == snums)
    b = bx[at_ok]
    return boxed & (
        (xmin <= b[:, 2]) & (xmax >= b[:, 0]) & (ymin <= b[:, 3]) & (ymax >= b[:, 1])
    )


def touchingSections(series, boxes : dict, display_tform) -> dict:
    """The sections where each object has a trace that touches the ROI box,
    for keeping whole every object that crosses the box's edge, from the
    series data.

    A trace counts by its square in displayed coordinates (objectExtents:
    its centroid moved to where the field draws it, plus and minus its
    radius grown by that move's stretch), so a trace near the box may count
    when its outline does not reach it; it never misses one that does.

    The traces an open read into columns are tested together, a block at a
    time, so a series of many objects takes one pass of array work rather
    than one per object.

        Params:
            series (Series): the series
            boxes (dict): section number -> the box there as (xmin, ymin,
                xmax, ymax); a section not in it has no box
            display_tform (callable): as in objectExtents
        Returns:
            (dict): object name -> frozenset of section numbers, for the
                objects that touch the box somewhere
    """
    if not boxes:
        return {}
    snum_list = sorted(boxes)
    box_snums = np.asarray(snum_list, dtype=int)
    bx = np.asarray([boxes[s] for s in snum_list], dtype=float)
    moves = {}
    found = {}

    blocks, built = {}, []
    for name, obj_data in series.data["objects"].items():
        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, stop = rows
            if start < stop:
                blocks.setdefault(id(columns), (columns, []))[1].append((start, stop, name))
        elif not obj_data.isEmpty():
            built.append(name)

    for columns, runs in blocks.values():
        runs.sort()
        starts = np.asarray([run[0] for run in runs], dtype=int)
        stops = np.asarray([run[1] for run in runs], dtype=int)
        arrays = columns.arrays
        snums = np.asarray(arrays["snum"], dtype=int)
        squares = displaySquares(
            snums,
            np.asarray(arrays["cx"], dtype=float),
            np.asarray(arrays["cy"], dtype=float),
            np.asarray(arrays["radius"], dtype=float),
            np.asarray(arrays["tform"], dtype=int),
            columns.tforms, display_tform, moves,
        )
        rows = np.nonzero(_touching(snums, *squares, box_snums, bx))[0]
        # a row belongs to the run it falls in; rows of no run are not read
        run = np.searchsorted(starts, rows, side="right") - 1
        ok = (run >= 0) & (rows < stops[np.maximum(run, 0)])
        for row, i in zip(rows[ok].tolist(), run[ok].tolist()):
            found.setdefault(runs[i][2], set()).add(int(snums[row]))

    for name in built:
        extents = objectExtents(series, name, display_tform, moves)
        if extents is None:
            continue
        snums = extents[0]
        touch = _touching(snums, *extents[1:], box_snums, bx)
        if touch.any():
            found.setdefault(name, set()).update(snums[touch].tolist())

    return {name: frozenset(snums) for name, snums in found.items()}


def objectsTouching(series, boxes : dict, display_tform) -> frozenset:
    """The objects with a trace that touches the ROI box on its section
    (touchingSections).

        Returns:
            (frozenset): the object names
    """
    return frozenset(touchingSections(series, boxes, display_tform))
