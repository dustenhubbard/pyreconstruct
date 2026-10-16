"""Find the islands among the positive and negative traces of one object on
one section.

A positive trace fills and a negative trace clears. A positive inside a
negative of the same object is an island in that hole: drawing every positive
and then every negative would clear it with the hole. The 3D volume and the
label export draw that way and then fill each island back in, less the voxels
of every negative that cuts it, so a negative clears an island the same way
whether or not the island sits in a hole.

A hole may be drawn as several negatives that abut or overlap, none of which
covers the island on its own. Together they are the hole around it, and the
pieces the covering needs do not cut the island. A negative the covering does
not need (one inside the hole, or across the island's edge) cuts it as it
would with no hole around.
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
    if not _boxAround(outer.bounds, inner.bounds):
        return False  # the box test is cheap and settles most pairs
    return _around(outer, inner)


def _boxAround(outer_bounds, inner_bounds) -> bool:
    """Return whether one bounding box holds another."""
    ob, ib = outer_bounds, inner_bounds
    return not (ib[0] < ob[0] or ib[1] < ob[1] or ib[2] > ob[2] or ib[3] > ob[3])


def _around(cover, inner) -> bool:
    """Return whether a shape covers a polygon without being its outline."""
    try:
        return cover.covers(inner) and not cover.equals(inner)
    except Exception:
        return False


def _boxesApart(a, b, reach=0.0) -> bool:
    """Return whether the boxes of two shapes are more than ``reach`` apart."""
    ab, bb = a.bounds, b.bounds
    return (
        bb[0] > ab[2] + reach or bb[2] < ab[0] - reach
        or bb[1] > ab[3] + reach or bb[3] < ab[1] - reach
    )


def _reaches(island, negative, reach=0.0) -> bool:
    """Return whether a negative touches an island or comes within ``reach``
    of it.

    Such a negative clears part of the island unless it is a piece of the
    hole around it: one inside the island, one with its outline (which
    cancels it), one that cuts across or only touches its edge, one with no
    area that runs over it, and one close enough that the two round onto the
    same voxel.

        Params:
            island: the island's polygon
            negative: the negative's polygon, or its line or point if it has
                no area
            reach (float): how far apart the two can be and still count
        Returns:
            (bool): whether the negative reaches the island
    """
    if island is None or negative is None:
        return False
    if _boxesApart(island, negative, reach):
        return False
    try:
        if reach > 0:
            return island.dwithin(negative, reach)
        return island.intersects(negative)
    except Exception:
        return False


def _joined(polys : list, reach=0.0):
    """Return the union of several negatives as one shape, with any gap
    narrower than ``reach`` between them closed.

    Two pieces of a hole drawn a fraction of a voxel apart both reach into
    the voxels between them, so the fill shows no wall there; closing the gap
    (a mitre buffer out and back in by half the reach) makes the union cover
    what the two pieces clear. The closed shape is joined with the plain
    union so the pieces' own outlines stay exact.
    """
    from shapely.ops import unary_union

    union = unary_union(polys)
    if reach <= 0 or union.geom_type == "Polygon":
        return union
    try:
        closed = union.buffer(reach / 2, join_style="mitre")
        closed = closed.buffer(-reach / 2, join_style="mitre")
        return unary_union([union, closed])
    except Exception:
        return union


def _holeAround(island, negatives : list, reach=0.0) -> list:
    """Return the indices of the negatives that are the hole around an island,
    or an empty list when no hole is around it.

    A negative that covers the island on its own is a hole around it, and
    when any does, those are the hole: the other negatives are cuts, as they
    were. Otherwise the negatives near the island are taken together; when
    their union (gaps narrower than ``reach`` closed) covers the island
    without being its outline, the hole is drawn as several traces, and its
    pieces are the negatives the covering needs: those without which the rest
    no longer covers the island. A negative drawn twice counts once for that,
    so a duplicated piece is still a piece.

        Params:
            island: the island's polygon
            negatives (list): the negatives' polygons (None for one with no
                area, which is never a piece of a hole)
            reach (float): how far a piece can be from the island, or from
                the next piece, and still count
        Returns:
            (list): ascending indices into negatives
    """
    if island is None:
        return []
    near = [
        j for j, poly in enumerate(negatives)
        if poly is not None and not _boxesApart(island, poly, reach)
    ]
    alone = [j for j in near if _covers(negatives[j], island)]
    if alone or len(near) < 2:
        return alone

    # a quick no: the pieces' boxes must hold the island's box, and their
    # areas must add up to at least its area
    bounds = [negatives[j].bounds for j in near]
    joint = (
        min(b[0] for b in bounds), min(b[1] for b in bounds),
        max(b[2] for b in bounds), max(b[3] for b in bounds),
    )
    if not _boxAround(joint, island.bounds):
        return []
    if sum(negatives[j].area for j in near) < island.area:
        return []
    if not _around(_joined([negatives[j] for j in near], reach), island):
        return []

    # the same outline drawn twice is one piece
    groups : list[list[int]] = []
    for j in near:
        for group in groups:
            try:
                same = negatives[group[0]].equals(negatives[j])
            except Exception:
                same = False
            if same:
                group.append(j)
                break
        else:
            groups.append([j])
    pieces = []
    for group in groups:
        rest = [negatives[j] for other in groups if other is not group for j in other]
        if not rest or not _around(_joined(rest, reach), island):
            pieces.extend(group)
    return sorted(pieces)


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

    An island is a positive trace inside a negative trace (a hole), or
    inside several negatives that abut and together cover it (a hole drawn
    as several traces). Drawing every positive and then every negative
    clears it with the hole, so the caller fills each island back in
    afterward, less the voxels of the negatives listed with it: every
    negative that touches it or comes within ``reach`` of it, except the
    pieces of the hole around it. Each island is filled back
    on its own, so one island's holes never clear another island, and the
    island loses the voxels it would lose with no hole around it. A section
    with no island comes back empty and draws exactly as before.

        Params:
            pos (list): the point lists of the positive traces
            neg (list): the point lists of the negative traces
            reach (float): how far a negative can be from an island and still
                round onto the island's voxels, and how far apart two pieces
                of one hole can be; the diagonal of one voxel when the
                caller rounds the points to a grid
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

    near = _pairs(pos_polys, neg_shapes, reach)
    found = []
    for i in sorted(near):
        island = pos_polys[i]
        candidates = near[i]
        pieces = _holeAround(island, [neg_polys[j] for j in candidates], reach)
        if not pieces:
            continue
        hole = {candidates[k] for k in pieces}
        found.append((pos[i], [
            neg[j] for j in candidates
            if j not in hole and _reaches(island, neg_shapes[j], reach)
        ]))
    return found
