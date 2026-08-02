import re
from typing import Union

import numpy as np

from .transform import Transform
from .points import Points

from PyReconstruct.modules.calc import centroid, distance, feret
from PyReconstruct.modules.constants import blank_palette_contour
from PyReconstruct.modules.calc import point_list_2_pix

from PyReconstruct.modules.datatypes_legacy import (
    Contour as XMLContour,
    Transform as XMLTransform
)


def normalizeObjectName(value : str) -> str:
    """Return ``value`` with whitespace and commas collapsed to underscores.

    Object names are written into the log as its fourth comma-space-delimited
    field (``Log.__str__`` / ``Log.fromStr``), so a comma in a name shifts every
    field after it and the entry no longer parses. That is what this exists to
    prevent. ``Section.updateJSON`` applies the same rule to the contour keys of
    a file written before the rule existed, so the two must agree; they are one
    function so they cannot drift.
    """
    value = value.strip()
    return "_".join(value.split()).replace(",", "_")


class Trace():

    def __init__(self, name : str, color : tuple, closed=True):
        """Create a Trace object.
        
            Params:
                name (str): the name of the trace
                color (tuple): the color of the trace: (R, G, B) 0-255
                closed (bool): True if trace is closed
        """
        self.name       = name
        self.color      = color
        self.closed     = closed
        self.negative   = False
        self.points     = []
        self.hidden     = False
        self.tags       = set()
        self.fill_mode  = ("none", "none")
    
    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        """Replace whitespace and commas with underscores."""
        
        assert (value is None or type(value) is str)

        if value is not None:

            value = normalizeObjectName(value)

        self._name = value
    
    def copy(self):
        """Create a copy of the trace object.
        
            Returns:
                (Trace): a copy of the object
        """
        
        copy_trace = Trace("", [0,0,0])
        copy_trace.__dict__ = self.__dict__.copy()
        copy_trace.points = self.points.copy()
        copy_trace.tags = self.tags.copy()

        return copy_trace
    
    def add(self, point : tuple):
        """Add a point to the trace.
        
            Params:
                point (tuple): a coordinate pair
        """
        self.points.append(point)
    
    def asPixels(self, mag: float, img_height: int, subpix: bool=False):
        """Return points as a list of (x, y) pixels on an image."""

        return point_list_2_pix(self.points, mag, img_height, subpix)

    def isSameTrace(self, other) -> bool:
        """Check if traces have the same name, color, and points.
        
            Params:
                other (Trace): the trace to compare
            Returns:
                (bool) whether or not the traces are the same
        """
        if self.name != other.name:
            return False
        if self.color != other.color:
            return False
        if self.points != other.points:
            return False
        return True

    ## How far apart, per axis, two corresponding points may sit and still count
    ## as the same point. Named because a caller that wants to skip a pair of
    ## traces cheaply has to allow for it: two traces can match point for point
    ## under this tolerance while their bounding boxes do not touch, so a
    ## bounding-box test that rules a pair out has to be slack by this much or it
    ## will rule out pairs that pointsMatch accepts. Real data has such pairs;
    ## see Series._duplicatePairs.
    POINTS_MATCH_TOLERANCE = 1e-2

    ## How far apart two *open* traces may sit and still count as the same curve.
    ## Open traces are compared curve-to-curve rather than by enclosed area (see
    ## getOverlapRatio), and that comparison needs a distance tolerance.
    ##
    ## The tolerance is a fraction of the shorter trace's arc length, BOUNDED AT
    ## BOTH ENDS by an absolute distance in image pixels. The fraction on its own
    ## has the right shape -- a longer structure is clicked more coarsely, so the
    ## discrepancy between two tracings of it grows with its length -- but it is
    ## unbounded in both directions, and both ends are wrong on real data. Both
    ## numbers below are from the reporting user's own series (mag 0.002045
    ## um/pixel, 3,974 open traces):
    ##
    ##   * Unbounded above, it stops being a tolerance. The 95th-percentile open
    ##     trace is 6,846 px long, so 2% of it is 137 px. At that tolerance two
    ##     unrelated structures 10 px apart lie within tolerance of each other
    ##     everywhere, the ratio saturates at exactly 1.0, and the pair is
    ##     collapsed at every threshold the import dialog can produce -- including
    ##     1.0, which ratioIsOverlap reads as "demand an exact match".
    ##   * Unbounded below, it misses the smallest duplicates. Her shortest
    ##     genuine duplicate pair is a 29 px arc whose two tracings differ by
    ##     0.72 px at worst. 2% of 29 px is 0.58 px, so the pair scored 0.
    ##
    ## So the bounds are absolute distances, in image pixels, converted through
    ## the section's magnification. Every production call site has a section in
    ## scope and passes it (see getOverlapRatio's ``mag`` parameter, and note that
    ## a call site which omits it raises rather than silently reverting to the
    ## unbounded fraction).
    OPEN_TRACE_MATCH_FRACTION = 0.02

    ## The floor. One image pixel: two tracings of one structure cannot
    ## meaningfully be closer than the image they were drawn on can resolve, so
    ## anything below a pixel is a tolerance of zero in disguise. This is what
    ## catches the 29 px pair above.
    OPEN_TRACE_MATCH_MIN_PIXELS = 1.0

    ## The ceiling. Five image pixels, which is deliberately the same distance
    ## POINTS_MATCH_TOLERANCE already stands for: 1e-2 series units is 4.89 px on
    ## her series, and that is the distance this codebase has always been willing
    ## to call "the same point". Two curves further apart than the tolerance under
    ## which two points count as identical should not count as one curve.
    ##
    ## Measured over the 594 distinct same-name same-section open pairs in her
    ## series (the complete population an import can ask about), split by a
    ## metric-independent ground truth -- the symmetric point-to-segment deviation
    ## between the two polylines -- at 2 px:
    ##
    ##   * all 264 pairs that are one annotation are detected at the import
    ##     default of 0.95, where origin/main detected 0 of them
    ##   * none of the 330 pairs that are different structures is collapsed, at
    ##     any threshold the import dialog can produce (0.90 through 0.999) or at
    ##     1.0
    ##
    ## Those two hold anywhere from a 2 px ceiling upward, so her real pairs do not
    ## pick the number out of that range on their own; what does is the two limits
    ## above. 5 px is the largest value that still refuses the constructed case --
    ## two different structures 10 px apart along a 6,846 px trace -- while
    ## staying at the point-match distance rather than below it, and it leaves the
    ## fraction in charge for every trace shorter than 250 px, which is 78% of the
    ## open traces in her series.
    OPEN_TRACE_MATCH_MAX_PIXELS = 5.0

    ## Ceiling on how many arc-length samples either open trace is reduced to in
    ## _openCurveRatio. The sampling it asks for is four per tolerance band, so the
    ## cap binds once a trace is longer than 256 tolerances -- about 1,280 px at
    ## the 5 px ceiling, which is the top few percent of real traces. It bounds the
    ## cost of the distance comparison there, and it is not a sensitive number:
    ## measured over the 1,188 real open pairs in the reporting user's series,
    ## every verdict is identical from a cap of 256 up to 16,384 and no ratio moves
    ## by more than 0.0032, while the scan time varies from 103 ms to 186 ms.
    _OPEN_CURVE_MAX_SAMPLES = 1024

    def pointsMatch(self, other) -> bool:
        """Check if two traces are the same point sequence, within a tolerance.

        The cheap half of overlaps(): equal point counts and every pair of
        corresponding points within POINTS_MATCH_TOLERANCE in both axes. Settled
        without measuring any area, which is what lets overlaps() answer for
        shapes that have no area to measure (see getOverlapRatio's zero-area
        note).

            Params:
                other (Trace): the trace to compare
            Returns:
                (bool): whether the two point sequences coincide
        """
        if len(self.points) != len(other.points):
            return False
        tol = self.POINTS_MATCH_TOLERANCE
        for (x1, y1), (x2, y2) in zip(self.points, other.points):
            if abs(x1-x2) > tol or abs(y1-y2) > tol:
                return False
        return True

    @staticmethod
    def ratioIsOverlap(r : float, threshold : float) -> bool:
        """Apply the overlap threshold to an already-measured overlap ratio.

        Split out of overlaps() so a caller that needs the ratio itself (to
        report it, say) can measure once and still reach the same verdict
        overlaps() would. The threshold is exclusive below 1, and a threshold of
        exactly 1 demands an exact ratio of 1.

            Params:
                r (float): an overlap ratio, as returned by getOverlapRatio
                threshold (float): the threshold overlap ratio (exclusive)
            Returns:
                (bool): whether that ratio counts as overlapping
        """
        ## bool(), not the comparison itself: getOverlapRatio divides two
        ## numpy sums, so the comparison yields numpy.bool_ and callers that
        ## assert `is True` would fail on it. overlaps() has always returned a
        ## plain bool here and tests hold it to that.
        if threshold < 1:
            return bool(r > threshold)
        return bool(threshold == r == 1)

    def overlaps(self, other, threshold=0.99, mag=None, open_curve=True):
        """Check if trace points overlap.

        ``mag`` and ``open_curve`` are passed straight through to
        getOverlapRatio. See there: ``mag`` is required for a pair of open traces
        and ignored otherwise, and ``open_curve=False`` measures an open pair by
        enclosed area instead, which needs no ``mag``.

            Params:
                other (Trace): the trace to compare
                threshold (float): the threshold overlap ratio to define overlapping (exclusive)
                mag (float): the section's magnification (Section.mag); required
                    if both traces are open and open_curve is True
                open_curve (bool): whether an open pair is compared
                    curve-to-curve; False asks for the area comparison instead
            Returns:
                (bool): whether or not trace traces overlap
        """
        if self.closed != other.closed:
            return False

        # compare points directly
        if self.pointsMatch(other):
            return True

        # compare amount of overlap
        return self.ratioIsOverlap(
            self.getOverlapRatio(other, mag, open_curve), threshold
        )

    def setHidden(self, hidden=True):
        """Set whether the trace is hidden.
        
            Params:
                hidden (bool): whether the trace is hidden
        """
        self.hidden = hidden
    
    def addTag(self, tag : str):
        """Set the tag for the trace:
            
            Params:
                tag (str): the tag for the trace
        """
        self.tags.add(tag)

    def getList(self, include_name=True) -> list:
        """Return the trace data as a list.

            Params:
                include_name (bool): True if name should be included in the list
            Returns:
                (list) list containing the trace data
        """
        x, y = [], []
        for p in self.points:
            x.append(round(p[0], 7))
            y.append(round(p[1], 7))
        
        l = []
        if include_name:
            l.append(self.name)
        
        l += [
            x, 
            y, 
            self.color,
            self.closed,
            self.negative,
            self.hidden,
            self.fill_mode,
            # tags is a set in memory: sort it so identical content serializes
            # to identical bytes across processes (canonical ordering)
            sorted(self.tags, key=str)
        ]

        return l
    
    def getXMLObj(self, xml_image_tform : XMLTransform = None, legacy_format : bool = False):
        """Returns the trace data as an XML object.
            Params:
                xml_image_tform (XMLTransform): the xml image transform object
            Returns:
                (XMLContour) the trace as an xml contour object or (Str)
        """
        border_color = list(self.color)
        for i in range(len(border_color)):
            border_color[i] /= 255

        # reverse point order if negative trace
        if self.negative:
            points = self.points[::-1]
        else:
            points = self.points

        xml_contour = XMLContour(
            name = self.name,
            comment = "",
            hidden = self.hidden,
            closed = self.closed,
            simplified = False,
            mode = convertMode(self.fill_mode),
            border = border_color,
            fill = border_color,
            points = points,
            transform = xml_image_tform
        )

        if legacy_format:

            # get scaling to modify the radius of the trace (for palette traces)
            r_scaling = getLegacyRadius(self) / self.getRadius()
            
            xml_text = blank_palette_contour

            border = list(map(lambda x: round(x, 3), xml_contour.border))
            border = f'{border[0]} {border[1]} {border[2]}'

            fill = list(map(lambda x: round(x, 3), xml_contour.fill))
            fill = f'{fill[0]} {fill[1]} {fill[2]}'

            xml_points = ''
            for pt in xml_contour.points:
                x, y = pt[0] * r_scaling, pt[1] * r_scaling  # modify radius for palette trace
                formatted_point = f'{x} {y}, '
                xml_points += formatted_point

            ## Deal with brackets in trace palette names (not allowable in legacy Reconstruct)
            if re.search(r"<|\{", xml_contour.name):
                xml_contour.name = re.sub(r"[<>{}]", "", xml_contour.name)
            
            xml_text = xml_text.replace("[NAME]", xml_contour.name)
            xml_text = xml_text.replace("[CLOSED]", str(xml_contour.closed))
            xml_text = xml_text.replace("[BORDER]", border)
            xml_text = xml_text.replace("[FILL]", fill)
            xml_text = xml_text.replace("[MODE]", str(xml_contour.mode))
            xml_text = xml_text.replace("[POINTS]", xml_points)
            
            return xml_text
        
        else:
            
            return xml_contour
    
    @staticmethod
    def fromList(l : list, name : str = None):
        """Create a trace object from a list.

        Two row shapes are accepted, told apart by length, because the two
        places traces are stored on disk differ in whether the name is part of
        the row:

          * **8 fields** -- ``getList(include_name=False)``. Section contours
            are stored keyed by contour name, so the name is not repeated in
            every row; the caller must supply ``name``.
          * **9 fields** -- ``getList(include_name=True)``, name first. Palette
            traces and undo-state baselines are stored as flat lists, so each
            row carries its own name.

        A 9-field row is self-naming even when ``name`` is passed. That is
        deliberate and load-bearing: ``FieldState.getContours`` reads
        name-bearing rows while also passing the contour name it keyed them
        under, and the embedded name is the authoritative one.

            Params:
                l (list): the list trace data, 8 or 9 fields as above
                name (str): the name of the trace; required for an 8-field row,
                            ignored for a 9-field one
            Returns:
                (Trace) a Trace object constructed from the list data
        """

        # Read the name without consuming it. This used to be `l.pop(0)`,
        # which mutated the caller's list: a 9-field row handed in twice
        # raised ValueError the second time, because the first call had left
        # it 8 fields long with `x` where the name belonged. One call site had
        # already grown a defensive `.copy()` to work around it:
        # `Series.getDefaultPaletteTraces`, which iterates the module-level
        # `default_traces` constant and would otherwise destroy it on first
        # use, permanently, for the rest of the process. Parsing a row is a
        # read; callers should not have to know that it wasn't.
        if not name or len(l) == 9:
            name, *fields = l
        else:
            fields = l

        (
            x,
            y,
            color,
            closed,
            negative,
            hidden,
            fill_mode,
            tags
        ) = tuple(fields)

        new_trace = Trace(name.strip(), color, closed)  # strip trace name
        new_trace.negative = negative
        new_trace.points = list(zip(x, y))
        new_trace.hidden = hidden
        new_trace.fill_mode = fill_mode
        new_trace.tags = set(tags)

        return new_trace
    
    @staticmethod
    def fromXMLObj(xml_trace : XMLContour, xml_image_tform : XMLTransform = None):
        """Create a trace from an xml contour object.
        
            Params:
                xml_trace (XMLContour): the xml contour object
                xml_image_tform (XMLTransform): the xml image transform object
            Returns:
                (Trace) the trace object
        """
        # get basic attributes
        name = xml_trace.name
        color = list(xml_trace.border)
        for i in range(len(color)):
            color[i] = int(color[i] * 255)
        closed = xml_trace.closed
        points = xml_trace.points.copy()
        negative = xml_trace.isNegative()
        if negative:
            points = points[::-1]
        new_trace = Trace(name, color, closed)

        # get the transform
        if xml_trace.transform is not None:
            points = xml_trace.transform.transformPoints(xml_trace.points)
        if xml_image_tform is not None:
            points = xml_image_tform.inverseTransformPoints(points)
        
        new_trace.points = points
        new_trace.fill_mode = convertMode(xml_trace.mode)
        new_trace.negative = negative
        
        return new_trace

    def getBounds(self, tform : Transform = None) -> tuple:
        """Get the most extreme coordinates for the trace.
        
            Params:
                tform (Transform): optional parameter to find extremeties of transformed trace
            Returns:
                (float) min x value
                (float) min y value
                (float) max x value
                (float) max y value
        """
        if tform is not None:
            points = tform.map(self.points)
        else:
            points = self.points.copy()

        xmin = xmax = points[0][0]  # BUG: Should this be 'points' and not 'self.points'?
        ymin = ymax = points[0][1]
        
        for x, y in points[1:]:
            if x < xmin: xmin = x
            elif x > xmax: xmax = x
            if y < ymin: ymin = y
            elif y > ymax: ymax = y
        
        return xmin, ymin, xmax, ymax
    
    def getMidpoint(self, tform : Transform = None) -> tuple:
        """Get the midpoint of the trace (avg of extremes).
        
            Params:
                tform (Transform): transform to apply to calculation
            Returns:
                (tuple) x, y of midpoint
        """
        xmin, ymin, xmax, ymax = self.getBounds(tform)
        return (xmin + xmax) / 2, (ymin + ymax) / 2

    def getCentroid(self, tform : Transform = None) -> tuple:
        """Get the centroid of the trace.
        
            Params:
                tform (Transform)"""
        c = centroid(self.points)
        if tform:
            return tform.map(*c)
        else:
            return c
    
    def getRadius(self, tform : Transform = None) -> float:
        """Get the distance from the centroid of the trace to its farthest point.
        
            Params:
                tform (Transform): the transform to apply to the points
            Returns:
                (float): the radius of the trace
        """
        points = self.points.copy()
        if tform:
            points = tform.map(points)
        cx, cy = centroid(points)
        r = max([distance(cx, cy, x, y) for x, y in points])
        return r

    def getFeret(self, tform : Transform = None) -> tuple:
        """Get min and max Feret diameters.

            Params:
                tform (Transform): the transform to apply to the points
            Returns:
                (tuple): the min and max Feret diameters (0, 0 if not closed)
        """

        if not self.closed:  # no feret diameter for open traces
            
            return (0,0)

        else:
        
            points = self.points.copy()
        
            if tform:
                points = tform.map(points)
            
            return feret(points)

    def centerAtOrigin(self):
        """Centers the trace at the origin (ignores transformations)."""
        cx, cy = centroid(self.points)
        self.points = [(x-cx, y-cy) for x,y in self.points]

    def resize(self, new_radius : float, tform : Transform = None):
        """Resize a trace beased on its radius
        
            Params:
                new_radius (float): the new radius for the trace
                tform (Transform): the transform to apply to the radius
        """
        points = self.points.copy()

        # apply the forward transform if applicable
        if tform:
            points = tform.map(points)
        
        # calculate constants
        cx, cy = centroid(points)
        r = max([distance(cx, cy, x, y) for x, y in points])
        scale_factor = new_radius / r

        # center trace at origin and apply scale factor
        points = [
            (
                scale_factor*(x-cx) + cx, 
                scale_factor*(y-cy) + cy
            )
            for x, y in points
        ]

        # apply the reverse transform if applicable
        if tform:
            points = tform.map(points, inverted=True)
                
        self.points = points

    def reshape(self, new_points : float, tform : Transform = None):
        """Resize a trace beased on its radius
        
            Params:
                new_points (float): the new points for the trace
                tform (Transform): the transform to apply the shape
        """
        r = self.getRadius(tform)
        xc, yc = self.getCentroid()

        self.points = new_points
        self.resize(r)
        # apply reverse transform if applicable
        if tform:
            self.points = tform.getLinear().map(self.points, inverted=True)

        self.points = [(x + xc, y + yc) for x, y in self.points]
    
    def getStretched(self, w : float, h : float):
        """Get the trace stretched to a specific w and h.
        
            Params:
                w (float): the width of the resulting trace
                h (float): the height of the resulting trace
            Returns:
                (Trace): the resulting trace
        """
        new_trace = self.copy()

        # get constants
        cx, cy = centroid(new_trace.points)
        xmin, ymin, xmax, ymax = self.getBounds()

        # get scale factors
        scale_x = w / (xmax - xmin)
        scale_y = h / (ymax - ymin)

        # center trace at origin and apply scale factor
        new_trace.points = [
            (
                scale_x*(x-cx) + cx, 
                scale_y*(y-cy) + cy
            )
            for x, y in new_trace.points
        ]
        
        return new_trace
    
    def magScale(self, prev_mag : float, new_mag : float):
        """Scale the trace to magnification changes.
        
            Params:
                prev_mag (float): the previous magnification
                new_mag (float): the new magnification
        """
        for i, p in enumerate(self.points):
            x, y = p
            x *= new_mag / prev_mag
            y *= new_mag / prev_mag
            self.points[i] = (x, y)

    def mergeTags(self, other):
        """Merge the tags of two traces.
        
            Params:
                other (Trace): the trace to merge tags with
        """
        self.tags = self.tags.union(other.tags)
    
    @staticmethod
    def openCurveTolerance(mag, len_a, len_b, fraction=None):
        """The distance two open curves may sit apart and still count as one.

        ``OPEN_TRACE_MATCH_FRACTION`` of the shorter arc length, clamped to
        between ``OPEN_TRACE_MATCH_MIN_PIXELS`` and
        ``OPEN_TRACE_MATCH_MAX_PIXELS`` image pixels. See the comments on those
        three constants for why each of the three parts is there and what the
        numbers were measured against.

        Split out of _openCurveRatio so a caller reporting to a human can say
        what tolerance a ratio was measured at, and so a test can assert the
        clamp directly rather than inferring it from a ratio.

            Params:
                mag (float): the section's magnification, series units per image
                    pixel (Section.mag)
                len_a (float): the first curve's arc length, in series units
                len_b (float): the second curve's arc length, in series units
                fraction (float): override for OPEN_TRACE_MATCH_FRACTION
            Returns:
                (float): the tolerance, in series units
        """
        if fraction is None:
            fraction = Trace.OPEN_TRACE_MATCH_FRACTION
        d = fraction * min(len_a, len_b)
        floor = Trace.OPEN_TRACE_MATCH_MIN_PIXELS * mag
        ceiling = Trace.OPEN_TRACE_MATCH_MAX_PIXELS * mag
        ## min() first: a series whose pixels are so coarse that the floor is
        ## above the ceiling is a contradiction in the constants, not in the
        ## data, and clamping in this order keeps the floor authoritative.
        return max(min(d, ceiling), floor)

    @staticmethod
    def _openCurveRatio(pts1, pts2, mag, fraction=None):
        """How much of two open polylines lie on top of each other, in [0, 1].

        The open-trace half of getOverlapRatio. Both polylines are resampled at
        uniform arc-length spacing, and each resampled point is measured against
        the *segments* of the other polyline, so the answer depends on where the
        curves lie and not on how many points were clicked along them. Returns

            min(fraction of A within d of B, fraction of B within d of A)

        with ``d = openCurveTolerance(mag, arc length A, arc length B)``.

        The min of the two directions makes it symmetric and conservative: a
        short trace lying along part of a long one scores about the length ratio
        rather than 1, so a trace covering half of another is not called a
        duplicate of it. Because it compares point sets and not paired-up points,
        it is also indifferent to which direction each trace was drawn in, and a
        trace redrawn end-to-start still reads as a duplicate.

        **Two open traces that merely touch or cross score a small nonzero
        ratio**, about ``d`` over the shorter arc length, because the tolerance is
        a disc of radius d around each curve and a transversal crossing passes
        through it. That is far below any threshold the import dialog can ask for
        (0.9 at the lowest), but a caller passing ``threshold=0`` -- meaning "do
        these overlap at all" -- would read it as an overlap where the area metric
        read a crossing pair of open traces as no overlap whatever. Bounding d
        shrinks that ratio and cannot make it zero: no coverage measure taken at a
        positive tolerance can. **That is why the two call sites which do pass zero
        opt out of this measure entirely** (Section.tracesWithoutCounterpart and
        the keep_below loop in Section.importTraces, via ``open_curve=False``): the
        question they ask is not the one this measure answers. It is also why
        degenerate two-point traces no longer score exactly 0 for the callers that
        do use it, the way the area path made them (#167).

            Params:
                pts1 (list): the first trace's points
                pts2 (list): the second trace's points
                mag (float): the section's magnification, which sets the absolute
                    bounds on the tolerance (see openCurveTolerance)
                fraction (float): tolerance as a fraction of the shorter arc
                    length, before the bounds are applied; defaults to
                    OPEN_TRACE_MATCH_FRACTION
            Returns:
                (float): the overlap ratio, in [0, 1]
        """
        a = np.asarray(pts1, dtype=float)
        b = np.asarray(pts2, dtype=float)

        ## A single point has no curve to compare. As with the zero-area case
        ## below, identical traces are already settled by pointsMatch in
        ## overlaps(), which never asks for a ratio.
        if len(a) < 2 or len(b) < 2:
            return 0

        def arc_length(p):
            return float(np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1])).sum())

        len_a, len_b = arc_length(a), arc_length(b)

        ## Every point in the same place: no length to take a fraction of, so no
        ## tolerance to measure against. Mirrors the zero-area guard.
        if len_a <= 0 or len_b <= 0:
            return 0

        d = Trace.openCurveTolerance(mag, len_a, len_b, fraction)

        def resample(p, spacing):
            """Points at uniform arc-length spacing along the polyline p."""
            steps = np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1]))
            travelled = np.concatenate([[0.0], np.cumsum(steps)])
            total = travelled[-1]
            ## Capped so a pair of wildly mismatched lengths cannot blow up the
            ## comparison. Hitting the cap coarsens the sampling of the longer
            ## trace, which can only lower its measured fraction -- and a pair
            ## that far apart in length is not a duplicate at any threshold.
            count = int(min(
                Trace._OPEN_CURVE_MAX_SAMPLES,
                max(2, int(np.ceil(total / spacing)) + 1),
            ))
            at = np.linspace(0.0, total, count)
            return np.column_stack([
                np.interp(at, travelled, p[:, 0]),
                np.interp(at, travelled, p[:, 1]),
            ])

        def fraction_within(samples, polyline):
            """Fraction of `samples` within d of any segment of `polyline`."""
            starts = polyline[:-1]
            ends = polyline[1:]
            seg = ends - starts                          # (S, 2)
            rel = samples[:, None, :] - starts[None, :, :]   # (N, S, 2)
            seg_sq = np.einsum("sj,sj->s", seg, seg)     # (S,)
            along = np.einsum("nsj,sj->ns", rel, seg)    # (N, S)
            ## Zero-length segments (repeated points) project to their start
            ## point, which is the right answer and avoids dividing by zero.
            safe = np.where(seg_sq > 0, seg_sq, 1.0)
            t = np.clip(np.where(seg_sq > 0, along / safe, 0.0), 0.0, 1.0)
            offset = rel - t[:, :, None] * seg[None, :, :]
            nearest = np.sqrt(np.einsum("nsj,nsj->ns", offset, offset)).min(axis=1)
            return float(np.mean(nearest <= d))

        ## Sampled finer than the tolerance so that a curve cannot slip between
        ## samples: the gap contributes at most a quarter of d to the distance.
        spacing = d / 4
        return min(
            fraction_within(resample(a, spacing), b),
            fraction_within(resample(b, spacing), a),
        )

    def getOverlapRatio(self, other, mag=None, open_curve=True):
        """Get the amount of intersection between two traces.

        Closed traces are compared by area: both are rasterized and the ratio is
        the intersection over the union.

        Open traces cannot be, and comparing them that way is what made
        duplicate open lines undetectable. Rasterizing an open trace fills the
        region between the polyline and the straight chord from its last point
        back to its first, so the shape being measured is a sliver whose form is
        governed by the trace's own wiggle rather than by where the curve
        actually lies. Two independent tracings of one structure have independent
        wiggle, so their slivers disagree even when the curves sit on top of each
        other: two near-straight profiles differing by 0.08% in length measured
        an area ratio of 0.19. Lowering the threshold cannot fix that, because
        the quantity being measured is not the one the user is asking about. Open
        traces are therefore compared curve-to-curve by _openCurveRatio, which
        returns the same 0-to-1 ratio, so the user-facing overlap threshold keeps
        its meaning and ratioIsOverlap is unchanged.

        A pair with one open and one closed trace keeps the area comparison.
        Trace.overlaps and Series._duplicatePairs both refuse such a pair before
        asking for a ratio, so this only affects a direct caller.

        ``mag`` is the section's magnification and is **required for an open
        pair**: it converts the bounds on the curve tolerance from image pixels
        into series units (see OPEN_TRACE_MATCH_FRACTION). It is not optional in
        any meaningful sense -- omitting it raises rather than falling back to an
        unbounded tolerance, because an unbounded tolerance saturates at 1.0 for
        long traces and collapses unrelated structures at every threshold, which
        is precisely the failure the bounds exist to prevent. Closed pairs never
        look at it. Every production caller has a section in scope:
        Section.importTraces passes ``self.mag`` down through
        Contour.importTraces and tracesWithoutCounterpart (and reconciles the two
        series' magnifications with Trace.magScale before it does), and both
        series-level scans (Series.deleteDuplicateTraces and
        Series.findDifferentlyNamedDuplicates) pass ``section.mag`` from the
        section they are walking.

        ``open_curve=False`` sends an open pair down the area path instead, byte
        for byte as it was before the curve metric existed, and needs no ``mag``.
        It is not a fallback and not a preference: it exists because two callers
        ask ``overlaps(threshold=0)``, which is the question "do these two traces
        overlap at all" rather than "are these two traces the same trace". The
        curve metric was designed and measured for the second question, at the
        import dialog's own thresholds, and ``ratioIsOverlap(r, 0)`` reduces to
        ``r > 0``, which accepts the small positive ratio any two curves that meet
        produce. Both those callers can delete a trace on the answer, so they keep
        the answer they have always given. The reasoning is written out at
        Section.tracesWithoutCounterpart, which is one of them.

            Params:
                other (Trace): the trace to compare against
                mag (float): the section's magnification, series units per image
                    pixel; required if both traces are open and open_curve is True
                open_curve (bool): whether an open pair is compared
                    curve-to-curve; False asks for the area comparison instead
            Returns:
                (float): the overlap ratio, in [0, 1]
        """
        if open_curve and not self.closed and not other.closed:
            if mag is None:
                raise ValueError(
                    "getOverlapRatio needs the section's mag to compare two "
                    "open traces: the curve tolerance is bounded in image "
                    "pixels. Pass mag=section.mag."
                )
            return self._openCurveRatio(self.points, other.points, mag)

        xmin1, ymin1, xmax1, ymax1 = self.getBounds()
        xmin2, ymin2, xmax2, ymax2 = other.getBounds()

        # if the shapes don't remotely intersect, ignore
        if (
            xmax1 < xmin2 or xmax2 < xmin1 or
            ymax1 < ymin2 or ymax2 < ymin1):
            return 0
        
        pts1 = np.array(self.points)
        pts2 = np.array(other.points)
        
        # calculate a scaling factor
        xmin, xmax = min(xmin1, xmin2), max(xmax1, xmax2)
        ymin, ymax = min(ymin1, ymin2), max(ymax1, ymax2)
        initial_area = (xmax-xmin) * (ymax-ymin)

        # The combined bounding box collapses when both traces sit on the same
        # vertical or the same horizontal line: a single point and a vertical
        # run through it, two collinear segments, and so on. Traces like this
        # are real -- smooth() already skips sub-three-point "pixel dust" --
        # and there is no box to rasterize into, so no area to compare. Two
        # such traces cannot overlap by area, and identical ones are already
        # settled by the point-by-point comparison in overlaps(), which never
        # asks for a ratio. Answer 0 rather than dividing by zero.
        if initial_area == 0:
            return 0

        scale_factor = (1e4 / initial_area) ** 0.5

        # scale the points
        pts1 = np.round(pts1 * scale_factor).astype(int)
        pts2 = np.round(pts2 * scale_factor).astype(int)
        xmin = round(xmin * scale_factor)
        xmax = round(xmax * scale_factor)
        ymin = round(ymin * scale_factor)
        ymax = round(ymax * scale_factor)

        # translate the points
        pts1[:,0] -= xmin
        pts1[:,1] -= ymin
        pts2[:,0] -= xmin
        pts2[:,1] -= ymin

        # generate the polygons
        from skimage.draw import polygon  # deferred: skimage is slow to import
        r1, c1 = polygon(pts1[:,1], pts1[:,0])
        r2, c2 = polygon(pts2[:,1], pts2[:,0])
        mask1 = np.zeros(shape=(ymax-ymin+1, xmax-xmin+1), dtype=bool)
        mask2 = np.zeros(shape=(ymax-ymin+1, xmax-xmin+1), dtype=bool)
        mask1[r1, c1] = True
        mask2[r2, c2] = True

        # get the union and intersect areas
        union_area = np.sum(np.logical_or(mask1, mask2))
        intersect_area = np.sum(np.logical_and(mask1, mask2))

        return intersect_area / union_area

    def smooth(self, window: int, spacing: Union[int, float]) -> bool:
        """Smooth trace in place.

        Malformed traces with too few points to smooth (e.g. "pixel dust"
        artifacts) are left untouched.

            Returns:
                (bool): True if the trace was smoothed, False if it was
                    skipped for having too few points
        """

        if len(self.points) < 3:

            return False

        unsmoothed = Points(self.points, self.closed)

        smoothed = unsmoothed.interp_rolling_average(
            spacing, window, as_int=False
        )

        if not smoothed:

            return False

        if smoothed[0] == smoothed[-1]:

            smoothed = smoothed[:-1]

        if not smoothed:

            return False

        self.points = smoothed

        return True

    @staticmethod
    def get_scale_bar():
        """Return a scale bar trace object."""

        ## Initialize trace
        scale_bar_trace = Trace("scale_bar", color=(0, 0, 0))

        ## Add attrs
        scale_bar_trace.points = [
            (0, 0), (0, 0.2), (2, 0.2), (2, 0)
        ]
        scale_bar_trace.fill_mode = ("solid", "always")

        return scale_bar_trace


def convertMode(arg):
    """Translate between Reconstruct and PyReconstruct fill modes."""
    if type(arg) is int:
        fill_mode = [None, None]
        if abs(arg) == 11:
            fill_mode = ("none", "none")
        else:
            if abs(arg) == 13:
                fill_mode[0] = "solid"
            elif abs(arg) == 9 or abs(arg) == 15:
                fill_mode[0] = "transparent"
            if arg < 0:
                fill_mode[1] = "unselected"
            else:
                fill_mode[1] = "selected"
        return tuple(fill_mode)
    elif type(arg) is tuple or type(arg) is list:
        if arg[0] == "none":
            mode = 11
        else:
            if arg[0] == "transparent":
                mode = 9
            elif arg[0] == "solid":
                mode = 13
            if arg[1] == "unselected":
                mode *= -1
        return mode


def getLegacyRadius(trace : Trace):
    """Get the legacy radius for a palette trace."""
    legacy_radii = {
        "circle": 6.324555320336759,
        "star": 5.656854249492381,
        "triangle": 7.333333,
        "cross": 9.899494936611665,
        "square": 14.485601376004034,
        "diamond": 7,
        "curved_arrow": 12.952950706944307,
        "plus": 12.649110640673518,
        "straight_arrow": 16.646921637347848
    }
    l = len(trace.points)
    if l == 3:
        trace_type = "triangle"
    elif l == 4:
        trace_type = "diamond"
    elif l == 7:
        trace_type = "straight_arrow"
    elif l == 8:
        trace_type = "circle"
    elif l == 10:
        trace_type = "square"
    elif l == 16:
        trace_type = "star"
    elif l == 12:
        # three possibilities for length 12
        x, y = trace.points[0]
        if x < 0 and y > 0:
            if abs(abs(x) - abs(y) < 1e-6):
                trace_type = "cross"
            else:
                trace_type = "plus"
        else:
            trace_type = "curved_arrow"
    else:
        return 8
    
    return legacy_radii[trace_type]
