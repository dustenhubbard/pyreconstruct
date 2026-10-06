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


def _covers(outer, inner) -> bool:
    """Return whether one trace polygon covers another, different one.

    Two identical outlines are not nested: a negative with the same outline
    as an island cancels it, so it is not a hole around it. A trace GEOS
    cannot compare (some self-crossing outlines) counts as not covered, so it
    fills the way it did before.
    """
    if outer is None or inner is None:
        return False
    ob, ib = outer.bounds, inner.bounds
    if ib[0] < ob[0] or ib[1] < ob[1] or ib[2] > ob[2] or ib[3] > ob[3]:
        return False  # the box test is cheap and settles most pairs
    try:
        return outer.covers(inner) and not outer.equals(inner)
    except Exception:
        return False


def _boxesApart(a, b, reach=0.0) -> bool:
    """Return whether the boxes of two shapes are more than ``reach`` apart."""
    ab, bb = a.bounds, b.bounds
    return (
        bb[0] > ab[2] + reach or bb[2] < ab[0] - reach
        or bb[1] > ab[3] + reach or bb[3] < ab[1] - reach
    )


def _clearsAgain(island, negative, reach=0.0) -> bool:
    """Return whether a negative has to clear again after an island refills.

    Every negative that touches the island or comes within ``reach`` of it
    does, unless it is a hole around the island. That takes in one inside the
    island, one with its outline (which cancels it), one that cuts across or
    only touches its edge, one with no area that runs over it, and one close
    enough that the two round onto the same voxel.

        Params:
            island: the island's polygon
            negative: the negative's polygon, or its line or point if it has
                no area
            reach (float): how far apart the two can be and still count
        Returns:
            (bool): whether the negative clears again
    """
    if island is None or negative is None:
        return False
    if _boxesApart(island, negative, reach):
        return False
    try:
        if reach > 0:
            near = island.dwithin(negative, reach)
        else:
            near = island.intersects(negative)
    except Exception:
        return False
    return near and not _covers(negative, island)


def _traceLine(points : list):
    """Return a trace with no area as a line or a point, or None.

    Such a negative still clears the voxels it runs along, so after an
    island refills it has to be applied again if it reaches the island.
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


def _matching(geoms : list, others : list, other_idx, test, reach=0.0) -> list:
    """Return the indices of the geometries that ``test`` relates to one of
    the chosen others.

    A tree over the chosen others narrows each geometry to the others whose
    box comes within ``reach`` of its own, and only those pairs go through
    ``test``. Every test used here needs the two boxes that close, so the
    answer is the one a scan of every pair gives, in the same order.

        Params:
            geoms (list): the shapes to report (None allowed)
            others (list): the shapes to compare against (None allowed)
            other_idx: the indices into others to consider
            test: ``test(other, geom)`` -> bool
            reach (float): how far apart two boxes can be and still pair
        Returns:
            (list): the indices into geoms, ascending
    """
    import shapely
    from shapely import STRtree

    chosen = [j for j in other_idx if others[j] is not None]
    present = [i for i, g in enumerate(geoms) if g is not None]
    if not chosen or not present:
        return []

    tree = STRtree([others[j] for j in chosen])
    query = [geoms[i] for i in present]
    if reach > 0:
        b = shapely.bounds(query)
        query = shapely.box(
            b[:, 0] - reach, b[:, 1] - reach, b[:, 2] + reach, b[:, 3] + reach
        )
    hits = tree.query(query)
    candidates : dict[int, list[int]] = {}
    for a, b in zip(*hits):
        candidates.setdefault(present[int(a)], []).append(chosen[int(b)])

    return [
        i for i in present
        if any(test(others[j], geoms[i]) for j in candidates.get(i, ()))
    ]


def nestedFillOrder(pos : list, neg : list, reach : float = 0.0) -> list:
    """Return the traces of one section in the order they fill the volume.

    Every positive trace fills first and every negative trace clears after it.
    A positive trace inside a negative trace is an island in that hole, so it
    fills again after the holes. Every negative that touches the refilled
    island, or comes within ``reach`` of it, clears again after that unless
    it is a hole around the island, so the island loses the same voxels to it
    that it would without the hole. Islands inside those negatives fill next,
    and so on down the nesting. A section with no island comes back in the
    same order as before.

        Params:
            pos (list): the point lists of the positive traces
            neg (list): the point lists of the negative traces
            reach (float): how far a negative can be from an island and still
                round onto the island's voxels; the diagonal of one voxel
                when the caller rounds the points to a grid
        Returns:
            (list): (points, fill) pairs in fill order
    """
    order = [(pts, True) for pts in pos] + [(pts, False) for pts in neg]
    if not pos or not neg:
        return order

    pos_polys = [_tracePolygon(pts) for pts in pos]
    neg_polys = [_tracePolygon(pts) for pts in neg]
    neg_shapes = [
        poly if poly is not None else _traceLine(pts)
        for poly, pts in zip(neg_polys, neg)
    ]

    def clears_again(island, negative):
        return _clearsAgain(island, negative, reach)

    holes : list[int] | range = range(len(neg))
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
        holes = _matching(neg_shapes, pos_polys, islands, clears_again, reach)
        if not holes:
            break
        order.extend((neg[j], False) for j in holes)

    return order
