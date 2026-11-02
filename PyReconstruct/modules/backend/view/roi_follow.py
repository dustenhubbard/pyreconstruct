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


class SeriesSquares:
    """Every trace's centroid, radius and measured transform, with its
    object, grouped by section: what keeping objects whole tests against the
    ROI box (KeepWhole in the field).

    Built once from the series data (fromSeries). After an edit on the shown
    section, that section is read again from the loaded section (setSection),
    so an edit costs one section, not the series. version counts the changes.
    """

    def __init__(self):
        self.names, self._name_ix = [], {}
        self.measured, self._tform_ix = [], {}
        # section number -> numpy arrays (owner, cx, cy, r, tkey); owner
        # indexes names, tkey indexes measured
        self.sections = {}
        self.version = 0

    def _owner(self, name):
        i = self._name_ix.get(name)
        if i is None:
            i = self._name_ix[name] = len(self.names)
            self.names.append(name)
        return i

    def _tkey(self, tform):
        i = self._tform_ix.get(id(tform))
        if i is None:
            i = self._tform_ix[id(tform)] = len(self.measured)
            self.measured.append(tform)
        return i

    @classmethod
    def fromSeries(cls, series):
        """Read every object's traces from the series data. The traces an
        open read into columns are taken a block at a time and the built ones
        in one walk, so many objects cost one pass of array work."""
        self = cls()
        parts = []
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
            arrays = columns.arrays
            size = len(arrays["snum"])
            owner = np.full(size, -1, dtype=int)
            for start, stop, name in runs:
                owner[start:stop] = self._owner(name)
            keep = owner >= 0  # rows of no run are not read
            tmap = np.asarray([self._tkey(t) for t in columns.tforms], dtype=int)
            tk = np.asarray(arrays["tform"], dtype=int)
            parts.append((
                owner[keep],
                np.asarray(arrays["snum"], dtype=int)[keep],
                np.asarray(arrays["cx"], dtype=float)[keep],
                np.asarray(arrays["cy"], dtype=float)[keep],
                np.asarray(arrays["radius"], dtype=float)[keep],
                tmap[tk[keep]] if len(tmap) else tk[keep],
            ))

        items = []
        for name in built:
            i = self._owner(name)
            for snum, tds in series.data["objects"][name].traces.items():
                for td in tds:
                    cx, cy = td.centroid
                    items.append((i, snum, cx, cy, td.radius, self._tkey(getattr(td, "_tform", None))))
        if items:
            arr = np.asarray(items, dtype=float)
            parts.append((
                arr[:, 0].astype(int), arr[:, 1].astype(int),
                arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5].astype(int),
            ))

        if parts:
            owner, snums, cx, cy, r, tk = (np.concatenate(col) for col in zip(*parts))
            order = np.argsort(snums, kind="stable")
            owner, snums, cx, cy, r, tk = (a[order] for a in (owner, snums, cx, cy, r, tk))
            cuts = np.flatnonzero(np.diff(snums)) + 1
            for chunk in zip(*(np.split(a, cuts) for a in (owner, snums, cx, cy, r, tk))):
                self.sections[int(chunk[1][0])] = (chunk[0], chunk[2], chunk[3], chunk[4], chunk[5])
        return self

    def setSection(self, section):
        """Read one loaded section's traces again, as the field draws them:
        the same centroid and radius the series data keeps (traceGeometry),
        under the section's own transform."""
        tform = section.tform
        tkey = self._tkey(tform)
        rows = []
        for trace in section.tracesAsList():
            if not trace.points:
                continue
            pts = tform.mapPointsArray(trace.points)
            _, _, (cx, cy), r = traceGeometry(pts, trace.closed)
            rows.append((self._owner(trace.name), cx, cy, r))
        if rows:
            arr = np.asarray(rows, dtype=float)
            self.sections[section.n] = (
                arr[:, 0].astype(int), arr[:, 1], arr[:, 2], arr[:, 3],
                np.full(len(arr), tkey, dtype=int),
            )
        else:
            self.sections.pop(section.n, None)
        self.version += 1

    def _touchingOn(self, snum, bounds, display, moves):
        """The owners of the rows on one section whose squares touch a box."""
        rows = self.sections.get(snum)
        if rows is None or bounds is None:
            return np.empty(0, dtype=int)
        owner, cx, cy, r, tk = rows
        xmin, ymin, xmax, ymax = displaySquares(
            np.full(len(owner), snum, dtype=int), cx, cy, r, tk,
            self.measured, lambda s: display, moves,
        )
        hit = (
            (xmin <= bounds[2]) & (xmax >= bounds[0])
            & (ymin <= bounds[3]) & (ymax >= bounds[1])
        )
        return owner[hit]

    def touching(self, boxes : dict, display_tform) -> dict:
        """For each object that touches the box somewhere, the sections where
        it does.

            Params:
                boxes (dict): section number -> (xmin, ymin, xmax, ymax)
                display_tform (callable): as in objectExtents
            Returns:
                (dict): object name -> frozenset of section numbers
        """
        found, moves = {}, {}
        for snum, bounds in boxes.items():
            for i in set(self._touchingOn(snum, bounds, display_tform(snum), moves).tolist()):
                found.setdefault(self.names[i], set()).add(snum)
        return {name: frozenset(snums) for name, snums in found.items()}

    def touchingOn(self, snum : int, bounds : tuple, display, exclude=()) -> set:
        """The objects with a trace on one section that touches a box, under
        the given drawn transform, leaving out the names in exclude."""
        names = {self.names[i] for i in self._touchingOn(snum, bounds, display, {}).tolist()}
        return names - set(exclude)


def touchingSections(series, boxes : dict, display_tform) -> dict:
    """The sections where each object has a trace that touches the ROI box,
    for keeping whole every object that crosses the box's edge, from the
    series data (SeriesSquares).

    A trace counts by its square in displayed coordinates (objectExtents:
    its centroid moved to where the field draws it, plus and minus its
    radius grown by that move's stretch), so a trace near the box may count
    when its outline does not reach it; it never misses one that does.

        Params:
            series (Series): the series
            boxes (dict): section number -> the box there as (xmin, ymin,
                xmax, ymax); a section not in it has no box
            display_tform (callable): as in objectExtents
        Returns:
            (dict): object name -> frozenset of section numbers, for the
                objects that touch the box somewhere
    """
    return SeriesSquares.fromSeries(series).touching(boxes, display_tform)


def objectsTouching(series, boxes : dict, display_tform) -> frozenset:
    """The objects with a trace that touches the ROI box on its section
    (touchingSections).

        Returns:
            (frozenset): the object names
    """
    return frozenset(touchingSections(series, boxes, display_tform))
