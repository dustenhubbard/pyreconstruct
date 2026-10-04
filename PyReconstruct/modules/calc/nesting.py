"""Order the positive and negative traces of one object on one section.

A positive trace fills and a negative trace clears. A positive inside a
negative of the same object is an island in that hole, so it has to fill
again after the hole clears it. The 3D volume and the label export both
draw an object's traces in the order ``nestedFillOrder`` returns.
"""


def _tracePolygon(points : list):
    """Return a shapely polygon for a trace, or None if it cannot be one.

    A trace with no area (a line, or one point repeated) is neither an island
    nor a hole, so it comes back as None and fills the way it did before.
    """
    from shapely.geometry import Polygon

    if len(points) < 3:
        return None
    try:
        poly = Polygon(points)
        if poly.area == 0:
            return None
    except Exception:
        return None
    return poly


def _covers(outer, inner, allow_equal=False) -> bool:
    """Return whether one trace polygon covers another.

    Two identical outlines are not nested unless ``allow_equal`` says so: a
    negative with the same outline as an island cancels that island, so the
    step that picks the holes after a refill allows it. A trace GEOS cannot
    compare (some self-crossing outlines) counts as not covered, so it fills
    the way it did before.
    """
    if outer is None or inner is None:
        return False
    ob, ib = outer.bounds, inner.bounds
    if ib[0] < ob[0] or ib[1] < ob[1] or ib[2] > ob[2] or ib[3] > ob[3]:
        return False  # the box test is cheap and settles most pairs
    try:
        if not outer.covers(inner):
            return False
        return allow_equal or not outer.equals(inner)
    except Exception:
        return False


def _coversOrEquals(outer, inner) -> bool:
    """``_covers`` with an identical outline counted."""
    return _covers(outer, inner, allow_equal=True)


def _boxesApart(a, b) -> bool:
    """Return whether the boxes of two shapes miss each other."""
    ab, bb = a.bounds, b.bounds
    return bb[0] > ab[2] or bb[2] < ab[0] or bb[1] > ab[3] or bb[3] < ab[1]


def _overlaps(a, b) -> bool:
    """Return whether two trace polygons share area with neither covering
    the other, so one cuts across the other's edge."""
    if a is None or b is None or _boxesApart(a, b):
        return False
    try:
        return a.overlaps(b)
    except Exception:
        return False


def _intersects(a, b) -> bool:
    """Return whether two trace shapes touch at all."""
    if a is None or b is None or _boxesApart(a, b):
        return False
    try:
        return a.intersects(b)
    except Exception:
        return False


def _traceLine(points : list):
    """Return a trace with no area as a line or a point, or None.

    Such a negative still clears the voxels it runs along, so after an
    island refills it has to be applied again if it touches the island.
    """
    from shapely.geometry import LineString, Point

    distinct = list(dict.fromkeys(tuple(pt) for pt in points))
    try:
        if len(distinct) >= 2:
            return LineString(distinct)
        if distinct:
            return Point(distinct[0])
    except Exception:
        return None
    return None


def _matching(geoms : list, others : list, other_idx, test) -> list:
    """Return the indices of the geometries that ``test`` relates to one of
    the chosen others.

    A tree over the chosen others narrows each geometry to the others whose
    box touches its own, and only those pairs go through ``test``. Every test
    used here needs the two boxes to touch, so the answer is the one a scan
    of every pair gives, in the same order.

        Params:
            geoms (list): the shapes to report (None allowed)
            others (list): the shapes to compare against (None allowed)
            other_idx: the indices into others to consider
            test: ``test(other, geom)`` -> bool
        Returns:
            (list): the indices into geoms, ascending
    """
    from shapely import STRtree

    chosen = [j for j in other_idx if others[j] is not None]
    present = [i for i, g in enumerate(geoms) if g is not None]
    if not chosen or not present:
        return []

    tree = STRtree([others[j] for j in chosen])
    hits = tree.query([geoms[i] for i in present])
    candidates = {}
    for a, b in zip(*hits):
        candidates.setdefault(present[int(a)], []).append(chosen[int(b)])

    return [
        i for i in present
        if any(test(others[j], geoms[i]) for j in candidates.get(i, ()))
    ]


def nestedFillOrder(pos : list, neg : list) -> list:
    """Return the traces of one section in the order they fill the volume.

    Every positive trace fills first and every negative trace clears after it.
    A positive trace inside a negative trace is an island in that hole, so it
    fills again after the holes. The negatives that touch the refilled island
    without being the hole around it clear again after that: one inside the
    island (or with its own outline, which cancels it), one that cuts across
    its edge, and one with no area that runs over it. Islands inside those
    fill next, and so on down the nesting. A section with no island comes
    back in the same order as before.

        Params:
            pos (list): the point lists of the positive traces
            neg (list): the point lists of the negative traces
        Returns:
            (list): (points, fill) pairs in fill order
    """
    order = [(pts, True) for pts in pos] + [(pts, False) for pts in neg]
    if not pos or not neg:
        return order

    pos_polys = [_tracePolygon(pts) for pts in pos]
    neg_polys = [_tracePolygon(pts) for pts in neg]
    neg_lines = [
        None if poly is not None else _traceLine(pts)
        for poly, pts in zip(neg_polys, neg)
    ]

    holes = range(len(neg))
    seen = set()
    # each level follows from the islands of the one before, so a set of
    # islands that comes back is a cycle of crossing traces with no end;
    # the walk stops there, and the count bound is a second safeguard
    for _ in range(len(pos) + len(neg)):
        islands = _matching(pos_polys, neg_polys, holes, _covers)
        if not islands or tuple(islands) in seen:
            break
        seen.add(tuple(islands))
        order.extend((pos[i], True) for i in islands)
        inside = _matching(neg_polys, pos_polys, islands, _coversOrEquals)
        across = _matching(neg_polys, pos_polys, islands, _overlaps)
        along = _matching(neg_lines, pos_polys, islands, _intersects)
        holes = sorted({*inside, *across, *along})
        if not holes:
            break
        order.extend((neg[j], False) for j in holes)

    return order
