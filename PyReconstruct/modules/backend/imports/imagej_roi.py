"""ImageJ .roi file."""

from typing import List, Tuple

import numpy as np

from .mod_imports import modules_available


## ImageJ roi types (ij.gui.Roi, and roifile.ROI_TYPE). Areas are closed,
## lines are open, and POINT is a set of separate markers. TRACED is the
## wand tool's outline, an area; ANGLE is a 3-point line.
POLYGON, RECT, OVAL, LINE, FREELINE, POLYLINE = 0, 1, 2, 3, 4, 5
FREEHAND, TRACED, ANGLE, POINT = 7, 8, 9, 10
CLOSED_TYPES = (POLYGON, RECT, OVAL, FREEHAND, TRACED)

## ImageJ stores a spline-fitted roi as its control points plus this option
## bit, and fits the spline again when it opens the file.
SPLINE_FIT = 1

Points = List[Tuple[float, float]]


class Roi:

    def __init__(self, roi_fp):

        ## Raise, never half-construct: returning early left the instance
        ## with no roi/closed attributes, and the caller's next call crashed
        ## with an AttributeError right after the missing-package notice
        ## (found 2026-08-28). Callers check modules_available up front.
        if not modules_available("roifile"):
            raise ModuleNotFoundError("roifile is required to import .roi files")

        import roifile

        self.roi_fp = roi_fp
        self.roi = roifile.ImagejRoi.fromfile(roi_fp)
        self.composite = bool(getattr(self.roi, "composite", False))
        self.markers = self.roi.roitype == POINT and not self.composite
        self.spline_fit = bool(self.roi.options & SPLINE_FIT) and not self.markers
        self.closed = self.trace_closed_p()

    def trace_closed_p(self) -> bool:
        """Return true if trace closed else false.

        Every sub-path of a composite roi is an area, whatever roitype the
        file carries (a Combine is saved as RECT).
        """
        return self.composite or self.roi.roitype in CLOSED_TYPES

    def get_field_shapes(self, img_height: int, mag: float) -> List[Points]:
        """Return each outline, line, or marker of the roi in field coordinates.

        A composite roi gives one shape per sub-path, and a POINT roi one
        single-point shape per marker. Everything else keeps its own vertices;
        only a roi saved with ImageJ's spline fit is fitted again.
        """
        def to_field(pts):
            return [(x * mag, (img_height - y) * mag) for x, y in pts]

        shapes = []
        for path in self.roi.coordinates(multi=True):
            pts = [(float(x), float(y)) for x, y in np.asarray(path).tolist()]
            if self.markers:
                shapes.extend([p] for p in to_field(pts))
                continue
            # a repeated vertex is a zero-length segment: it adds nothing and
            # FITPACK refuses it
            pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
            if self.closed and len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if self.spline_fit:
                pts = fit_spline(pts, self.closed)
            if pts:
                shapes.append(to_field(pts))
        return shapes


def fit_spline(pts: Points, closed: bool) -> Points:
    """Fit a cubic spline through pixel points the way ImageJ does.

    ImageJ evaluates a fitted spline at one point per 2 pixels of length,
    and never fewer than 100 points.
    """
    if len(pts) < 4:
        return pts
    ring = pts + [pts[0]] if closed else pts
    x = np.array([p[0] for p in ring])
    y = np.array([p[1] for p in ring])
    length = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
    n = max(100, int(length / 2))

    from scipy.interpolate import splprep, splev  # deferred: scipy is slow to import
    try:
        # Periodic ONLY for a closed outline: per=1 wraps the curve back to
        # the start, so an open polyline came back bent into a loop with its
        # true endpoint lost (found 2026-08-28).
        tck, _ = splprep([x, y], s=0, per=1 if closed else 0, k=3)
    except ValueError:
        return pts
    u = np.linspace(0, 1, n, endpoint=not closed)
    sx, sy = splev(u, tck)
    return list(zip(map(float, sx), map(float, sy)))


def holes(shapes: List[Points]) -> List[bool]:
    """Return which outlines of a composite roi are holes.

    ImageJ fills a composite shape even-odd: an outline inside an odd number
    of the others is a hole. One vertex decides, since the sub-paths of a
    shape do not cross.
    """
    return [
        sum(inside(shape[0], other) for other in shapes if other is not shape) % 2 == 1
        for shape in shapes
    ]


def inside(point: Tuple[float, float], polygon: Points) -> bool:
    """Return true if the point is inside the closed polygon (ray casting)."""
    x, y = point
    result = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            result = not result
    return result
