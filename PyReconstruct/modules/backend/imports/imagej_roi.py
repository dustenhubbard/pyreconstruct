"""ImageJ .roi file."""

from typing import List, Tuple

import numpy as np

from .mod_imports import modules_available


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
        self.closed = self.trace_closed_p()

    def trace_closed_p(self) -> bool:
        """Return true if trace closed else false.

        LINE (3) and POINT (10) are NOT in the closed set: they were, and a
        point ROI crashed on the closure check while a two-point line was
        force-closed and then crashed the cubic spline (found 2026-08-28).
        """

        roi_closed_types = [0, 1, 2, 7, 9]

        if self.roi.roitype in roi_closed_types:
            return True
        else:
            return False

    def get_field_coordinates(self, img_height: int, mag: float) -> List[Tuple[float]]:
        """Return field coordinates of roi trace."""

        coords = self.roi.coordinates().tolist()

        # first against LAST: comparing the first two points closed nothing
        # (an already-closed list got a redundant duplicate, a degenerate one
        # never closed) and crashed outright on a one-point ROI
        if self.closed and len(coords) > 1 and coords[0] != coords[-1]:
            coords.append(coords[0])

        x = np.array([p[0] for p in coords])
        y = np.array([img_height - p[1] for p in coords])

        # A spline needs more points than its degree, and FITPACK wants
        # slack beyond that; a point or short line ROI has nothing to smooth
        # anyway, so it imports as its own points instead of raising from
        # inside FITPACK.
        if len(coords) < 4:
            return [(px * mag, py * mag) for px, py in zip(x, y)]
        k = min(3, len(coords) - 1)

        # Exact interpolation (s=0). Periodic ONLY for a closed outline:
        # per=1 wraps the fitted curve back to the start and ignores the
        # final input point, so an open polyline came back bent into a loop
        # with its true endpoint lost (found 2026-08-28).
        from scipy.interpolate import splprep, splev  # deferred: scipy is slow to import
        tck, u = splprep([x, y], s=0, per=1 if self.closed else 0, k=k)

        # Evaluate the spline at more points
        u_new = np.linspace(0, 1, 100)
        smooth_x, smooth_y = splev(u_new, tck)

        smooth_x = [x * mag for x in smooth_x]
        smooth_y = [y * mag for y in smooth_y]

        return list(zip(smooth_x, smooth_y))
