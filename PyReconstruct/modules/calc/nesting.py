"""Find the islands among the positive and negative traces of one object on
one section.

A positive trace fills and a negative trace clears. A positive inside a
negative of the same object is an island in that hole: drawing every positive
and then every negative would clear it with the hole. The 3D volume and the
label export draw that way and then fill each island back in, less the voxels
of every negative that cuts it, so a negative clears an island the same way
whether or not the island sits in a hole.
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


def _cutsIsland(island, negative, reach=0.0) -> bool:
    """Return whether a negative clears part of an island.

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
            (bool): whether the negative clears part of the island
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

    Such a negative still clears the voxels it runs along, so it cuts an
    island it reaches.
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


def _pairs(geoms : list, others : list, reach=0.0) -> dict:
    """Return, for each geometry, the others whose box comes within
    ``reach`` of its own, in ascending order.

        Params:
            geoms (list): the shapes to look up (None allowed)
            others (list): the shapes to find (None allowed)
            reach (float): how far apart two boxes can be and still pair
        Returns:
            (dict): index into geoms -> ascending indices into others
    """
    import shapely
    from shapely import STRtree

    present = [i for i, g in enumerate(geoms) if g is not None]
    chosen = [j for j, g in enumerate(others) if g is not None]
    if not present or not chosen:
        return {}

    tree = STRtree([others[j] for j in chosen])
    query = [geoms[i] for i in present]
    if reach > 0:
        b = shapely.bounds(query)
        query = shapely.box(
            b[:, 0] - reach, b[:, 1] - reach, b[:, 2] + reach, b[:, 3] + reach
        )
    hits = tree.query(query)
    found : dict[int, list[int]] = {}
    for a, b in zip(*hits):
        found.setdefault(present[int(a)], []).append(chosen[int(b)])
    return {i: sorted(js) for i, js in found.items()}


def islandCuts(pos : list, neg : list, reach : float = 0.0) -> list:
    """Return the islands of one section, each with the negatives that cut it.

    An island is a positive trace inside a negative trace (a hole). Drawing
    every positive and then every negative clears it with the hole, so the
    caller fills each island back in afterward, less the voxels of the
    negatives listed with it: every negative that touches it or comes within
    ``reach`` of it, except the holes around it. Each island is filled back
    on its own, so one island's holes never clear another island, and the
    island loses the voxels it would lose with no hole around it. A section
    with no island comes back empty and draws exactly as before.

        Params:
            pos (list): the point lists of the positive traces
            neg (list): the point lists of the negative traces
            reach (float): how far a negative can be from an island and still
                round onto the island's voxels; the diagonal of one voxel
                when the caller rounds the points to a grid
        Returns:
            (list): (island points, [negative points]) pairs, in the order
                of pos
    """
    if not pos or not neg:
        return []

    pos_polys = [_tracePolygon(pts) for pts in pos]
    neg_polys = [_tracePolygon(pts) for pts in neg]
    neg_shapes = [
        poly if poly is not None else _traceLine(pts)
        for poly, pts in zip(neg_polys, neg)
    ]

    holes = _pairs(pos_polys, neg_polys)
    islands = [
        i for i in sorted(holes)
        if any(_covers(neg_polys[j], pos_polys[i]) for j in holes[i])
    ]
    if not islands:
        return []

    near = _pairs([pos_polys[i] for i in islands], neg_shapes, reach)
    return [
        (pos[i], [
            neg[j] for j in near.get(k, ())
            if _cutsIsland(pos_polys[i], neg_shapes[j], reach)
        ])
        for k, i in enumerate(islands)
    ]
