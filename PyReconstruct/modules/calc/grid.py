import cv2
import numpy as np

from .polygon import cut_closed_traces, cut_open_traces


class Grid():

    def __init__(self, traces):
        """Create a grid object.

            Params:
                traces (list): a list of traces, each one being a list of points
        """
        self.traces = [np.array(trace) for trace in traces]
        self._generateGrid()
    
    def _generateGrid(self):
        """Draw all the traces on the grid."""
        # get the boundaries of the trace
        xvals = [trace[:,0] for trace in self.traces]
        yvals = [trace[:,1] for trace in self.traces]
        xmin = min([x.min() for x in xvals])
        ymin = min([y.min() for y in yvals])
        xmax = max([x.max() for x in xvals])
        ymax = max([y.max() for y in yvals])

        # create an empty grid
        self.grid = np.array(
            np.zeros((ymax-ymin+2, xmax-xmin+2)),
            dtype="int"
        )

        # draw the trace(s) on the grid (ASSUMES CLOSED)
        for trace in self.traces:
            for i in range(len(trace)):
                x1, y1 = trace[i-1]
                x2, y2 = trace[i]
                x1 -= xmin
                y1 -= ymin
                x2 -= xmin
                y2 -= ymin
                self._drawGridLine(x1, y1, x2, y2)
        
        # save grid information
        self.grid_shift = xmin, ymin

        # invalidate the cached anchor mask (see _anchorMask)
        self._anchor_mask = None

    # DDA algorithm
    # Source: https://www.tutorialspoint.com/computer_graphics/line_generation_algorithm.htm
    def _drawGridLine(self, x0 : int, y0 : int, x1 : int, y1 : int):
        """Draw a line on self.grid.

        Every drawn cell is incremented, so a cell's value is the number of
        trace segments crossing it (1 for a plain edge, >1 where traces touch
        or overlap) -- which is what isAnchorPoint() keys off of.

            Params:
                x0 (int): x value of start point
                y0 (int): y value of start point
                x1 (int): x value of end point
                y1 (int): y value of end point
        """
        if (x0 == x1 and y0 == y1):
            return
        dx = x1 - x0
        dy = y1 - y0
        if (abs(dx) > abs(dy)):
            steps = abs(dx)
        else:
            steps = abs(dy)    
        x_increment = dx / steps
        y_increment = dy / steps
        x, y = x0, y0
        h, w = self.grid.shape
        if 0 <= x < w and 0 <= y < h:
            self.grid[y, x] += 1
        last_x, last_y = x, y
        for _ in range(steps):
            x += x_increment
            y += y_increment
            rx = round(x)
            ry = round(y)
            if (rx != last_x or ry != last_y):
                if 0 <= rx < w and 0 <= ry < h:
                    self.grid[ry, rx] += 1
                last_x, last_y = rx, ry

    def printGrid(self):
        """Print the grid to the console.
        
        For debugging purposes.
        """
        for r in range(len(self.grid)):
            for c in range(len(self.grid[r])):
                if self.grid[r,c]: print(self.grid[r,c], end="")
                else: print(" ", end="")
            print()
    
    def isAnchorPoint(self, x : int, y : int) -> bool:
        """Check if a grid point should be included in the final trace points.
        
            Params:
                x (int): the x-coord of the point to check
                y (int): the y-coord of the point to check
            Returns:
                (bool) whether or not the point is important to the trace
        """
        if self.grid[y, x] > 1: # point is automatically included if it is greater than 1
            return True
        else: # otherwise, check surrounding points
            cc_list = [(1,0), (1,1), (0,1), (-1,1), (-1,0), (-1,-1), (0,-1), (1,-1)]
            total = 0
            for dx, dy in cc_list:
                if self.grid[y + dy, x + dx] > 0:
                    total += 1
            if total >= 3: # if the point as three or more nonzero neighbors, include it
                return True
            else:
                return False

    def _anchorMask(self) -> np.ndarray:
        """Return a boolean mask of the anchor points of the whole grid.

        This is the batched form of isAnchorPoint(): a cell is an anchor if its
        value is > 1, or if at least 3 of its 8 neighbours are nonzero.  The
        neighbour count is a 3x3 correlation with a hollow kernel.

        isAnchorPoint() indexes self.grid[y + dy, x + dx] with no bounds check,
        so a neighbour at index -1 wraps around to the opposite edge.  Contours
        found on the grid really do include points on row 0 / column 0, so the
        grid is padded with mode="wrap" to reproduce that wrap-around exactly
        rather than treating out-of-bounds as zero.

        The result is computed once and cached: the grid is only written by
        _generateGrid/_drawGridLine during construction, and getExterior() asks
        for the mask once per contour.
        """
        if getattr(self, "_anchor_mask", None) is None:
            nonzero = np.pad((self.grid > 0).astype(np.uint8), 1, mode="wrap")
            kernel = np.ones((3, 3), np.uint8)
            kernel[1, 1] = 0
            neighbors = cv2.filter2D(
                nonzero,
                cv2.CV_16S,
                kernel,
                borderType=cv2.BORDER_CONSTANT
            )[1:-1, 1:-1]
            self._anchor_mask = (self.grid > 1) | (neighbors >= 3)
        return self._anchor_mask

    def getAnchorTrace(self, trace : np.ndarray) -> np.ndarray:
        """Get the "anchor" trace from a numpy cv2 trace.

        Often run after cv2.findContours is run on the grid.

            Params:
                trace (np.ndarray): the trace returned by cv2.findContours
            Returns:
                (np.ndarray) the anchor points of the trace
        """
        trace = np.asarray(trace)
        if trace.size:
            keep = self._anchorMask()[trace[:, 1], trace[:, 0]]
        else:
            keep = np.zeros(0, dtype=bool)
        if not keep.any():
            # preserve the historical empty result: np.array([]) of an empty
            # list, i.e. shape (0,) rather than shape (0, 2)
            return np.array([])
        return trace[keep]

    def getExterior(self) -> list:
        """Get the exterior of the trace(s) on the grid.

        A contour that keeps no anchor points contributes no exterior. That is
        the only case skipped here: getAnchorTrace returns a shape-(0,) array
        for it, which cannot be broadcast against the 2-element grid_shift, and
        an empty exterior would fail in reducePoints anyway -- every caller
        feeds each exterior straight into it, and cv2.approxPolyDP rejects an
        empty array. An isolated single pixel is such a contour: its value is 1
        and it has no nonzero neighbours, so neither anchor rule fires.

            Returns:
                (list) the exterior of the trace(s) (also represented as lists)
        """

        cv_traces, hierarchy = cv2.findContours(
            self.grid.astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_NONE
        )

        traces = []

        for trace in cv_traces:
            new_trace = self.getAnchorTrace(trace[:,0,:])
            if not new_trace.size:
                continue
            new_trace += self.grid_shift
            traces.append(new_trace.tolist())

        return traces


# METHODS (used to access the class functions)

def reducePoints(points : list, ep=0.80, iterations=1, closed=True, mag=None, array=False) -> list:
    """Reduce the number of points in a trace (uses cv2.approxPolyDP).
    
        Params:
            points (list): the list of points in the trace
            ep (float): the epsilon value for the approximation
            iterations (int): the number of times the approximation is run
            closed (bool): whether or not the trace is closed
            mag (float): magnifcation for the trace
            array (bool): True if returns as np.ndarray
        Returns:
            (list) the final points after the approximation
    """
    np_pts = np.array(points)
    if mag:
        np_pts *= mag
        np_pts = np_pts.astype(np.int32)

    for _ in range(iterations):
        reduced_points = cv2.approxPolyDP(np_pts, ep, closed=closed)
        # print(len(reduced_points) / len(points))
    
    if mag:
        reduced_points = reduced_points.astype(np.float64)
        reduced_points /= mag
    
    if array:
        return reduced_points[:,0,:]
    else:
        return reduced_points[:,0,:].tolist()

def getExterior(points : list) -> list:
    """Get the exterior of a single set of points.
    
        Params:
            points (list): points describing the trace
        Returns:
            (list) points describing trace exterior
    """
    grid = Grid([points])
    exteriors = grid.getExterior()
    if exteriors:
        new_points = grid.getExterior()[0]
        new_points = reducePoints(new_points)
        return new_points
    else:
        return []

def mergeTraces(trace_list : list) -> list:
    """Get the exterior(s) of a set of traces.
    
        Params:
            trace_list (list): set of traces
        Returns:
            (list) merged set of traces
    """
    grid = Grid(trace_list)
    new_traces = grid.getExterior()
    for i in range(len(new_traces)):
        new_traces[i] = reducePoints(new_traces[i])
    return new_traces

# A merge used to happen on the screen's pixel grid, so its result changed
# with the zoom (fork issue #423). It now happens on a grid tied to the image:
# MERGE_SUPERSAMPLE cells per image pixel, coarser only when the traces span
# more than MERGE_MAX_CELLS cells on an axis, so one huge object cannot ask
# for a grid that exhausts memory. Neither number looks at the view.
MERGE_SUPERSAMPLE = 4
MERGE_MAX_CELLS = 2500


def mergeCellSize(field_traces : list, mag : float) -> float:
    """Field units per grid cell for a zoom-independent merge.

        Params:
            field_traces (list): the traces to merge, points in field units
            mag (float): the section magnification, field units per image pixel
        Returns:
            (float): the cell size in field units
    """
    cell = mag / MERGE_SUPERSAMPLE
    xs = [x for trace in field_traces for x, _ in trace]
    ys = [y for trace in field_traces for _, y in trace]
    if xs and ys:
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        if span / cell > MERGE_MAX_CELLS:
            cell = span / MERGE_MAX_CELLS
    return cell


def _traceShape(trace : list):
    """The shapely geometry a closed trace covers, for the overlap test."""
    from shapely import make_valid
    from shapely.geometry import LineString, Point, Polygon

    points = [tuple(p) for p in trace]
    if len(set(points)) >= 3:
        return make_valid(Polygon(points))
    if len(set(points)) == 2:
        return LineString(points)
    if points:
        return Point(points[0])
    return Point()


def mergeGroups(field_traces : list) -> list:
    """Split the traces into groups that touch, overlap or nest.

        Params:
            field_traces (list): the traces to merge, points in field units
        Returns:
            (list): lists of indices into field_traces, one per group, in the
                order each group's first trace appears
    """
    from shapely import STRtree

    shapes = [_traceShape(trace) for trace in field_traces]
    parent = list(range(len(shapes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    if shapes:
        left, right = STRtree(shapes).query(shapes, predicate="intersects")
        for i, j in zip(left.tolist(), right.tolist()):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)

    groups : dict[int, list[int]] = {}
    for i in range(len(shapes)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def mergeTracesInField(field_traces : list, mag : float) -> list:
    """Merge closed traces given in field units, at a resolution set by the
    image rather than the screen.

    Traces that do not touch are merged apart, each group on a grid sized to
    that group alone. One shared grid sized to the whole selection let a long
    trace coarsen the cells until a small separate trace rounded onto a single
    grid point and vanished from the result.

        Params:
            field_traces (list): the traces to merge, points in field units
            mag (float): the section magnification, field units per image pixel
        Returns:
            (list): the merged trace(s), points in field units; empty if any
                group of traces leaves no outline, so a caller that keeps its
                traces on an empty result never loses one the result left out
    """
    result = []
    for group in mergeGroups(field_traces):
        traces = [field_traces[i] for i in group]
        cell = mergeCellSize(traces, mag)
        grid_traces = [
            [(int(round(x / cell)), int(round(y / cell))) for x, y in trace]
            for trace in traces
        ]
        merged = mergeTraces(grid_traces)
        # a speck straddling a cell edge comes back as a two-point line,
        # which is no closed outline either
        if not any(len(trace) >= 3 for trace in merged):
            return []
        result += [[(x * cell, y * cell) for x, y in trace] for trace in merged]
    return result


def cutTraces(trace_list, cut_trace, del_threshold=0.0, closed=True):
    """Cut a set of traces using polygon operations.
    
    Args:
        trace_list (list): List of traces, each a list of points
        cut_trace (list): A single curve representing the cut line
        del_threshold (float): Deletion threshold as percentage
        closed (bool): Whether traces are closed polygons
        
    Returns:
        list: The newly cut traces
    """
    # A usable cut line needs at least two points; a degenerate empty or
    # single-point cut (e.g. a knife single-click) would raise in shapely's
    # LineString, so treat it as a no-op.
    if not trace_list or not cut_trace or len(cut_trace) < 2:
        return trace_list
        
    if closed:
        new_traces = cut_closed_traces(trace_list, cut_trace, del_threshold)

    else:
        new_traces = cut_open_traces(trace_list, cut_trace, del_threshold)

    return new_traces


# Function to check if two line segments intersect
def intersection(line1, line2):
    (x1, y1), (x2, y2) = tuple(line1)
    (x3, y3), (x4, y4) = tuple(line2)

    # Calculate the slopes of the lines
    m1 = (y2 - y1) / (x2 - x1) if x2 - x1 != 0 else float('inf')
    m2 = (y4 - y3) / (x4 - x3) if x4 - x3 != 0 else float('inf')

    # Check if the lines are parallel
    if m1 == m2:
        return None  # The lines do not intersect

    # Calculate the intersection point
    if m1 == float('inf'):  # Line1 is vertical
        x_intersection = x1
        y_intersection = m2 * (x1 - x3) + y3
    elif m2 == float('inf'):  # Line2 is vertical
        x_intersection = x3
        y_intersection = m1 * (x3 - x1) + y1
    else:
        x_intersection = (m1 * x1 - y1 - m2 * x3 + y3) / (m1 - m2)
        y_intersection = m1 * (x_intersection - x1) + y1

    # Check if the intersection point is within the line segments
    if (
        min(x1, x2) <= x_intersection <= max(x1, x2)
        and min(x3, x4) <= x_intersection <= max(x3, x4)
        and min(y1, y2) <= y_intersection <= max(y1, y2)
        and min(y3, y4) <= y_intersection <= max(y3, y4)
    ):
        return (x_intersection, y_intersection)
    else:
        return None  # The lines do not intersect within the line segments

def cutOpenTrace(trace : list, cut_trace : list):
    """Cut an open trace.
    
        Params:
            trace (list): the trace to cut
            cut_trace (list): the trace used to cut
    """
    # insert interect points into trace
    new_trace = []
    cut_indexes = []
    for i in range(len(trace) - 1):
        new_trace.append(trace[i])
        for j in range(len(cut_trace) - 1):
            line1 = [trace[i], trace[i+1]]
            line2 = [cut_trace[j], cut_trace[j+1]]
            pt = intersection(line1, line2)
            if pt:
                cut_indexes.append(len(new_trace))
                new_trace.append(pt)
    new_trace.append(trace[-1])
    
    # split up the trace
    last_i = 0
    traces = []
    for i in cut_indexes:
        traces.append(new_trace[last_i : i+1])
        last_i = i
    traces.append(new_trace[last_i:])

    return traces
        

