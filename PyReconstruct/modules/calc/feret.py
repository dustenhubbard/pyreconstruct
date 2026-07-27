"""Calculate Feret diameters.

The convex hull and the rotating-calipers walk over antipodal hull pairs are
sourced from:
http://code.activestate.com/recipes/117225-convex-hull-and-diameter-of-2d-point-sets/

The maximum Feret diameter is the diameter of the point set: the greatest
distance between any two of its points. The calipers walk finds it, because the
farthest pair is always an antipodal pair of hull vertices.

The minimum Feret diameter is a different measurement. It is the minimum width:
the smallest distance between two parallel lines that support the set. That
minimum is always attained with one of the two lines flush against an edge of
the convex hull, so it is the smallest, over all hull edges, of the extent of
the set along that edge's normal.

The minimum width is not the smallest distance between a pair of antipodal hull
vertices, which is what the recipe above yields and what this module used to
report. Two parallel supporting lines through a pair of vertices are in general
not perpendicular to the segment joining those vertices, so a vertex-pair
distance overstates the width. For the triangle (0,0), (10,0), (5,1) the closest
antipodal pair is 5.0990 apart while the true width, its shortest altitude, is
1.0. Only shapes whose narrowest direction happens to run vertex to vertex at a
right angle, rectangles above all, agree by coincidence.
"""

from math import hypot, inf, sqrt


def orientation(p,q,r):
    """Return positive if p-q-r are clockwise, neg if ccw, zero if colinear."""

    return (q[1]-p[1])*(r[0]-p[0]) - (q[0]-p[0])*(r[1]-p[1])


def hulls(Points):
    """Graham scan to find upper and lower convex hulls of a set of 2d points.

    Both chains run left to right and share their first and last vertex. The
    caller's list is not reordered: callers hand in point lists they still own.
    """
    U = []
    L = []

    for p in sorted(Points):

        while len(U) > 1 and orientation(U[-2],U[-1],p) <= 0: U.pop()
        while len(L) > 1 and orientation(L[-2],L[-1],p) >= 0: L.pop()
        U.append(p)
        L.append(p)

    return U, L


def hullRing(U, L):
    """Join upper and lower hull chains into one closed ring of hull vertices.

    The chains overlap at the leftmost and rightmost points, so the upper chain
    contributes only its interior vertices, walked back from right to left. The
    ring is implicitly closed: its last vertex joins its first.
    """
    return L + U[-2:0:-1]


def calipers(U, L):
    """Given the upper and lower convex hulls of a set of 2d points, finds all
ways of sandwiching the points between two parallel lines that touch one point
each, and yields the sequence of pairs of points touched by each pair of lines."""
    i = 0
    j = len(L) - 1

    while i < len(U) - 1 or j > 0:

        yield U[i],L[j]

        # if all the way through one side of hull, advance the other side
        if i == len(U) - 1:

            j -= 1

        elif j == 0:

            i += 1

        # still points left on both lists, compare slopes of next hull edges
        # being careful to avoid divide-by-zero in slope calculation
        elif (U[i+1][1]-U[i][1])*(L[j][0]-L[j-1][0]) > \
                (L[j][1]-L[j-1][1])*(U[i+1][0]-U[i][0]):

            i += 1

        else: j -= 1


def rotatingCalipers(Points):
    """Given a list of 2d points, finds all ways of sandwiching the points
between two parallel lines that touch one point each, and yields the sequence
of pairs of points touched by each pair of lines."""
    return calipers(*hulls(Points))


def minWidth(ring):
    """Given a closed ring of convex hull vertices, returns the minimum width of
the hull: the smallest distance between two parallel lines that support it.

The width in the direction of a hull edge is the extent of the hull along that
edge's normal, and the narrowest of the two supporting lines is always flush
with some edge, so the minimum over the edges is the minimum width. Projecting
only the hull vertices is exact, because in any direction the extreme hull
vertex is also the extreme point of the set the hull encloses."""
    n = len(ring)

    if n < 2:  # a single point, or nothing at all, has no width
        return 0.0

    narrowest = inf

    for i in range(n):

        # the edge ending at vertex i; at i == 0 this is the closing edge
        ax, ay = ring[i-1]
        bx, by = ring[i]
        ex, ey = bx - ax, by - ay
        edge_len = hypot(ex, ey)

        if edge_len == 0.0:  # a repeated hull vertex defines no direction
            continue

        nx, ny = -ey/edge_len, ex/edge_len  # unit normal to the edge

        lo = hi = ring[0][0]*nx + ring[0][1]*ny

        for px, py in ring:

            d = px*nx + py*ny

            if d < lo: lo = d
            elif d > hi: hi = d

        if hi - lo < narrowest: narrowest = hi - lo

    if narrowest == inf:  # every edge degenerate: all vertices coincident
        return 0.0

    return narrowest


def feret(Points):
    """Given a list of 2d points, returns the minimum and maximum feret diameters."""
    U, L = hulls(Points)
    sq_dists = [(p[0]-q[0])**2 + (p[1]-q[1])**2 for p, q in calipers(U, L)]
    if not sq_dists:
        # Degenerate point set (empty or a single point) collapses the convex
        # hull so the calipers walk yields nothing. Such a trace has no extent,
        # so its feret diameters are 0.
        return 0.0, 0.0
    return minWidth(hullRing(U, L)), sqrt(max(sq_dists))
