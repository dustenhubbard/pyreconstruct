"""Independent measurement checks for the upstream reference tests.

Standard library only, so the generator and the tests share one copy and
neither imports PyReconstruct for it. Every value here comes from the trace's
points and transform by a route that does not reuse the fork's or upstream's
measurement code:

* mapping, area and centroid use exact rational arithmetic (`Fraction` of
  each float), so the only rounding is the one the measurement itself defines;
* length is a correctly rounded sum (`math.fsum`) of the segment lengths;
* the Feret diameters come from an exact-orientation convex hull, with the
  minimum width taken over every hull edge and the maximum over every pair of
  hull vertices.
"""

import hashlib
import json
import math
from fractions import Fraction


## Absolute tolerances, all with rel=0. Each is the largest difference that
## two correct computations of the same quantity can show on this data.
TOLERANCES = {
    ## Both sides round the length to 7 decimals. A different summation order
    ## can move a value that sits on a rounding boundary by one step.
    "length": 1e-7,
    ## Area is not rounded. Its float summation error is at most about
    ## n * eps * max|x| * max|y|: 600 points * 2.2e-16 * 40 * 40 ~ 2e-10 for
    ## the largest traces of class_series.jser. 1e-9 covers that and is 100
    ## times below the export's 7-decimal step.
    "area": 1e-9,
    ## The radius is a maximum of float distances from the same rounded
    ## centroid, so it only carries the mapped points' last-bit rounding.
    "radius": 1e-9,
    ## Both sides round the centroid to 6 decimals, at different points of
    ## the calculation. A centroid with no recorded difference must match to
    ## the last bits; recorded differences are bounded by `centroidBound`.
    "centroid": 1e-12,
    ## The diameters are square roots of float hull distances.
    "feret_max": 1e-9,
    "feret_min": 1e-9,
}

## A value this close to a rounding midpoint can round either way in float.
NEAR_TIE = 1e-11

MEASURES = ("length", "area", "radius", "cx", "cy", "feret_min", "feret_max")


def tolerance(measure : str) -> float:
    """The `TOLERANCES` entry for a measure name (cx and cy share one)."""
    return TOLERANCES["centroid" if measure in ("cx", "cy") else measure]


def centroidBound(tform : list) -> tuple:
    """The largest centroid difference the two rounding orders allow.

    Upstream rounds the raw centroid to 6 decimals and maps it; the fork maps
    the points and rounds the result. Each rounding is off by at most 5e-7,
    and the transform scales upstream's by its row sums.

        Params:
            tform (list): a, b, c, d, e, f
        Returns:
            (tuple): the bound on x and on y
    """
    a, b, _, d, e, _ = tform
    return (5e-7 * (1 + abs(a) + abs(b)) + NEAR_TIE,
            5e-7 * (1 + abs(d) + abs(e)) + NEAR_TIE)


def pointsDigest(points) -> str:
    """SHA-256 of the points as JSON pairs of float reprs."""
    text = json.dumps([[float(x), float(y)] for x, y in points], separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def outputDigest(value) -> str:
    """SHA-256 of a tool output in canonical JSON."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def exactMap(points, tform : list) -> list:
    """The points mapped by the transform, exactly, as Fractions.

    Uses QTransform's convention, as both trees do: x' = a*x + b*y + c,
    y' = d*x + e*y + f.
    """
    a, b, c, d, e, f = (Fraction(v) for v in tform)
    out = []
    for x, y in points:
        fx, fy = Fraction(x), Fraction(y)
        out.append((a * fx + b * fy + c, d * fx + e * fy + f))
    return out


def _exactAreaCentroid(pts : list) -> tuple:
    """Unsigned area and centroid of the ring, exactly (the ring closes itself)."""
    n = len(pts)
    s = sx = sy = Fraction(0)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        s += cross
        sx += (x0 + x1) * cross
        sy += (y0 + y1) * cross
    return s, sx, sy


def roundHalfEven(value : Fraction, places : int) -> Fraction:
    """`value` rounded to `places` decimals, ties to even, exactly."""
    scale = 10 ** places
    return Fraction(round(value * scale), scale)


def nearTie(value : Fraction, places : int) -> bool:
    """True if `value` is within NEAR_TIE of a midpoint between two steps."""
    scale = 10 ** places
    scaled = value * scale
    frac = scaled - math.floor(scaled)
    return abs(frac - Fraction(1, 2)) * Fraction(1, scale) < Fraction(NEAR_TIE)


def exactCentroid(pts : list) -> Fraction:
    """The centroid both trees define, exactly: the polygon centroid when the
    float area exceeds 1e-6, else the mean of the points."""
    if len(pts) > 2:
        s, sx, sy = _exactAreaCentroid(pts)
        a = abs(s) / 2
        if a > Fraction(1e-6):
            return sx / (3 * s), sy / (3 * s)
    n = len(pts)
    return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n


def _cross(o, p, q) -> Fraction:
    return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])


def convexHull(pts : list) -> list:
    """Andrew's monotone chain with exact orientation; collinear points dropped."""
    unique = sorted(set(pts))
    if len(unique) <= 2:
        return unique
    lower, upper = [], []
    for p in unique:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(unique):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def feretDiameters(float_pts : list) -> tuple:
    """(minimum width, diameter) of the points, in float.

    The minimum width of a convex set is attained with a supporting line flush
    against a hull edge, so it is the smallest, over the edges, of the largest
    distance from that edge's line to a hull vertex. The diameter is the
    largest distance between two hull vertices.
    """
    hull = convexHull([(Fraction(x), Fraction(y)) for x, y in float_pts])
    if len(hull) < 2:
        return 0.0, 0.0
    fh = [(float(x), float(y)) for x, y in hull]
    diameter = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p in fh for q in fh)
    if len(hull) == 2:
        return 0.0, diameter
    width = math.inf
    n = len(hull)
    for i in range(n):
        p, q = hull[i], hull[(i + 1) % n]
        edge = math.hypot(float(q[0] - p[0]), float(q[1] - p[1]))
        far = max(abs(_cross(p, q, r)) for r in hull)
        width = min(width, float(far) / edge)
    return width, diameter


def forkMeasures(points : list, tform : list, closed : bool, negative : bool) -> dict:
    """What the fork's TraceData should report, from the oracle.

        Params:
            points (list): the trace's raw (x, y) floats, as loaded
            tform (list): a, b, c, d, e, f
            closed (bool): the trace's effective closed flag
            negative (bool): the trace's negative flag
        Returns:
            (dict): each measure, plus "near_tie", the measures whose rounding
                lands within NEAR_TIE of a midpoint and may go either way
    """
    exact = exactMap(points, tform)
    mapped = [(float(x), float(y)) for x, y in exact]
    near = []

    if len(mapped) > 1:
        segments = [math.hypot(mapped[i + 1][0] - mapped[i][0], mapped[i + 1][1] - mapped[i][1])
                    for i in range(len(mapped) - 1)]
        if closed:
            segments.append(math.hypot(mapped[0][0] - mapped[-1][0], mapped[0][1] - mapped[-1][1]))
        raw_length = math.fsum(segments)
        length = round(raw_length, 7)
        if nearTie(Fraction(raw_length), 7):
            near.append("length")
    else:
        length = 0.0

    if closed and len(exact) > 2:
        s, _, _ = _exactAreaCentroid(exact)
        area = float(abs(s) / 2)
        if negative:
            area = -area
    else:
        area = 0.0

    ecx, ecy = exactCentroid(exact)
    cx = float(roundHalfEven(ecx, 6))
    cy = float(roundHalfEven(ecy, 6))
    if nearTie(ecx, 6):
        near.append("cx")
    if nearTie(ecy, 6):
        near.append("cy")
    radius = max(math.hypot(x - cx, y - cy) for x, y in mapped) if mapped else 0.0

    if closed and mapped:
        feret_min, feret_max = feretDiameters(mapped)
    else:
        feret_min, feret_max = 0.0, 0.0

    return {
        "length": length, "area": area, "radius": radius, "cx": cx, "cy": cy,
        "feret_min": feret_min, "feret_max": feret_max, "near_tie": near,
    }


def upstreamCentroidRule(points : list, tform : list) -> tuple:
    """Upstream's centroid, by its own rule: the raw points' centroid rounded
    to 6 decimals, then mapped (float arithmetic, as `Transform.map` does)."""
    ecx, ecy = exactCentroid([(Fraction(x), Fraction(y)) for x, y in points])
    rx, ry = float(roundHalfEven(ecx, 6)), float(roundHalfEven(ecy, 6))
    a, b, c, d, e, f = tform
    return a * rx + b * ry + c, d * rx + e * ry + f


def exportNumber(value : float) -> str:
    """A number as the trace CSV export writes it."""
    return str(round(value, 7))
