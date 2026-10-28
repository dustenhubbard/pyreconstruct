"""Math formulae."""


import math
import cv2
import numpy as np
from typing import List


def area(pts : list) -> float:
    """Find the area of a closed contour.
    
        Params:
            pts (list): list of points describing a closed contour
        Returns:
            (float) the area of the closed contour
    """
    if len(pts) <= 2:
        return 0
    
    if pts[0] != pts[-1]:
        pts = pts + pts[:1]
    # Sum relative to the first point. Each cross product in raw coordinates
    # is on the order of x*y, so a small trace far from the origin loses its
    # area to rounding in the difference; measured from a point on the trace,
    # the terms are on the order of the trace's own size. centroid() and
    # traceGeometry() use the same reference.
    x0, y0 = pts[0]
    x = [ c[0] - x0 for c in pts ]
    y = [ c[1] - y0 for c in pts ]
    s = 0
    for i in range(len(pts) - 1):
        s += x[i]*y[i+1] - x[i+1]*y[i]
    return abs(s/2)


def centroid(pts : list) -> tuple:
    """Find the location of centroid.
    
        Params:
            pts (list): points describing a contour
        Returns:
            (tuple) coordinate pair of the centroid
    """
    a = area(pts)
    # if area is greater than 0
    if abs(a) > 1e-6:
        if pts[0] != pts[-1]:
            pts = pts + pts[:1]
        if not ccwpoly(pts):
            pts = pts[::-1]
        # relative to the first point, as in area(); the ring is closed, so
        # reversing it leaves that point first
        x0, y0 = pts[0]
        x = [ c[0] - x0 for c in pts ]
        y = [ c[1] - y0 for c in pts ]
        sx = sy = 0
        for i in range(len(pts) - 1):
            sx += (x[i] + x[i+1])*(x[i]*y[i+1] - x[i+1]*y[i])
            sy += (y[i] + y[i+1])*(x[i]*y[i+1] - x[i+1]*y[i])
        return (round(x0 + sx/(6*a), 6), round(y0 + sy/(6*a), 6))
    # if area is 0: return average of points
    else:
        x_avg = sum([p[0] for p in pts])/len(pts)
        y_avg = sum([p[1] for p in pts])/len(pts)
        return round(x_avg, 6), round(y_avg, 6)


def distance(x1 : float, y1 : float, x2 : float, y2 : float) -> float:
    """Calculate Euclidean distance between two points in 2D space.
    
        Params:
            x1 (float): x-value of first point
            y1 (float): y-value of first point
            x2 (float): x-value of second point
            y2 (float): y-value of second point
        Returns:
            (float) the distance between the two points
    """
    dist = ((x1-x2)**2 + (y1-y2)**2) ** 0.5
    return dist


def euclidean_distance(p1: tuple, p2: tuple):
    """Calculate Euclidean distance between two points."""

    return np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)


def distance3D(x1 : float, y1 : float, z1 : float, x2 : float, y2 : float, z2 : float) -> float:
    """Calculate Euclidean distance between two points in 3D space.
    
        Params:
            x1 (float): x-value of first point
            y1 (float): y-value of first point
            z1 (float): z-value of fist point
            x2 (float): x-value of second point
            y2 (float): y-value of second point
            z2 (float): z-value of second point
        Returns:
            (float) the distance between the two points
    """
    dist = ((x1-x2)**2 + (y1-y2)**2 + (z2-z1)**2) ** 0.5
    return dist


def lineDistance(pts : list, closed=True) -> float:
    """Calculate distance along multi-vertex line.

        Params:
            pts (list): a list describing a contour
            closed (bool): whether or not the contour is closed
        Return:
            (float) the length of the contour
    """
    if len(pts) <= 1:
        return 0
    
    # x and y represent a list of x- and y-coordinates.
    x = [ c[0] for c in pts ]
    y = [ c[1] for c in pts ]
    dist = 0.0
    n = len(x) - 1
    for i in range(n):
        point_dist = distance(x[i], y[i], x[i+1], y[i+1])
        dist += point_dist
    if closed:  # if closed make one more calculation
        point_dist = distance(x[-1], y[-1], x[0], y[0])
        dist += point_dist
    return round(dist, 7)


def traceGeometry(points, closed=True):
    """Per-trace geometry in a single vectorized NumPy pass.

    Returns ``(length, area, (cx, cy), radius)`` -- the same quantities the hot
    per-trace path used to compute by calling lineDistance(), area(),
    centroid(), and a max-distance radius separately (each its own Python loop
    over the points, all calling distance()). Results match those scalar
    functions: ``area`` is unsigned, ``length`` is rounded to 7 and the centroid
    to 6. The scalar functions above remain the reference implementations, and
    all three sum relative to the trace's first point; this is purely a faster
    equivalent for the 60k+/refresh hot path.
    """
    n = len(points)
    if n == 0:
        return 0.0, 0.0, (0.0, 0.0), 0.0

    arr = np.asarray(points, dtype=float)
    x = arr[:, 0]
    y = arr[:, 1]

    # length (matches lineDistance)
    if n <= 1:
        length = 0.0
    else:
        d = float(np.hypot(x[1:] - x[:-1], y[1:] - y[:-1]).sum())
        if closed:
            d += math.hypot(x[0] - x[-1], y[0] - y[-1])
        length = round(d, 7)

    # area + centroid (matches area() / centroid())
    if n <= 2:
        a = 0.0
        cx = round(float(x.mean()), 6)
        cy = round(float(y.mean()), 6)
    else:
        # The sums run relative to the first point, the same reference area()
        # and centroid() use. In raw coordinates each cross product is on the
        # order of x*y, so a small trace far from the origin loses its area and
        # centroid to rounding; relative to a point on the trace, the terms are
        # on the order of the trace's own size.
        x0, y0 = arr[0].tolist()
        rel = arr - arr[0]
        rx = rel[:, 0]
        ry = rel[:, 1]

        # Consecutive-vertex pairs, built once. The shoelace cross products and
        # the midpoint sums are both functions of these same pairs, so the
        # slices are hoisted instead of being rebuilt per use.
        xa, xb = rx[:-1], rx[1:]
        ya, yb = ry[:-1], ry[1:]

        # The ring is closed by writing its wrap edge -- the one from the last
        # vertex back to the first -- straight into the last slot of the cross
        # array, rather than by appending a copy of the first point to x and y
        # and taking the cross products of the longer arrays. The two are the
        # same n cross products in the same order: appending x[0]/y[0] makes the
        # final pair (x[-1], y[-1]) -> (x[0], y[0]), whose cross product is
        # exactly the term assigned below. Measured from the first point, that
        # term is rx[-1]*0.0 - 0.0*ry[-1], which is 0.0 exactly, so it is
        # written as a constant. The same goes for a ring that already repeats
        # its first point at the end: its last edge adds 0.0 too, so it sums the
        # same as the ring without the repeat.
        cross = np.empty(n)
        cross[:-1] = xa * yb - xb * ya
        cross[-1] = 0.0
        signed2 = float(cross.sum())          # == 2 * signed area
        a = abs(signed2) / 2.0
        if a > 1e-6:
            # centroid via the signed area (orientation-independent), so no
            # explicit CCW reversal is needed; 6*signed_area == 3*signed2.
            sx = np.empty(n)
            sx[:-1] = xa + xb
            sx[-1] = rx[-1]                    # + rx[0], which is 0.0
            sy = np.empty(n)
            sy[:-1] = ya + yb
            sy[-1] = ry[-1]                    # + ry[0], which is 0.0
            cx = round(x0 + float((sx * cross).sum()) / (3.0 * signed2), 6)
            cy = round(y0 + float((sy * cross).sum()) / (3.0 * signed2), 6)
        else:
            cx = round(float(x.mean()), 6)
            cy = round(float(y.mean()), 6)

    # radius: max distance from centroid over the (unclosed) points
    radius = float(np.hypot(x - cx, y - cy).max())
    return length, a, (cx, cy), radius


def traceGeometries(points, counts, closed) -> list:
    """traceGeometry for many traces at once, with the same results to the bit.

    The series-data build at open calls traceGeometry once per trace, and on a
    large series most of that time is NumPy call overhead on small arrays. This
    runs every element-wise step once over all the traces' points, and only
    the sums are taken per trace. A sum must add the same numbers in the same
    order as traceGeometry's, or the last bits change (`np.add.reduceat` does
    not, so it is not used). Two ways keep the order: a 1-D slice of the
    combined array, and, for traces with the same number of points, the rows
    of a 2-D block (one row per trace); NumPy adds up both as it adds up the
    trace's own array. Every other step is element-wise, or a maximum, and
    does not depend on how the points are grouped.

        Params:
            points: an (N, 2) array, the traces' points one after another
            counts (list): the number of points of each trace, in order
            closed (list): whether each trace is closed
        Returns:
            (list): one (length, area, (cx, cy), radius) per trace, as
                traceGeometry returns for that trace's points
    """
    k = len(counts)
    if k == 0:
        return []
    arr = np.asarray(points, dtype=float).reshape(-1, 2)
    counts = np.asarray(counts, dtype=np.intp)
    ends = np.cumsum(counts)
    starts = ends - counts
    x = arr[:, 0]
    y = arr[:, 1]

    # Each array below holds, at a trace's positions, what traceGeometry
    # builds from that trace alone. Positions where a step runs from one
    # trace into the next hold junk, and no sum reads them.
    step = np.hypot(x[1:] - x[:-1], y[1:] - y[:-1])
    nz = np.flatnonzero(counts > 0)
    rx = x - np.repeat(x[starts[nz]], counts[nz])
    ry = y - np.repeat(y[starts[nz]], counts[nz])
    cross = np.empty(len(arr))
    cross[:-1] = rx[:-1] * ry[1:] - rx[1:] * ry[:-1]
    sx = np.empty(len(arr))
    sx[:-1] = rx[:-1] + rx[1:]
    sy = np.empty(len(arr))
    sy[:-1] = ry[:-1] + ry[1:]
    last = ends[nz] - 1
    cross[last] = 0.0
    sx[last] = rx[last]
    sy[last] = ry[last]
    sxc = sx * cross
    syc = sy * cross

    # The per-trace sums: the step lengths, the cross products (twice the
    # signed area), the two centroid numerators, and x and y for a mean.
    add = np.add.reduce  # what ndarray.sum calls, without its wrapper
    sums = np.zeros((6, k))
    order = np.argsort(counts, kind="stable")
    sorted_counts = counts[order]
    cuts = np.flatnonzero(np.diff(sorted_counts)) + 1
    for members in np.split(order, cuts):
        n = int(counts[members[0]])
        if n == 0:
            continue
        if len(members) >= 8:
            idx = starts[members][:, None] + np.arange(n)
            if n > 1:
                sums[0, members] = add(step[idx[:, :-1]], axis=1)
            if n > 2:
                sums[1, members] = add(cross[idx], axis=1)
                sums[2, members] = add(sxc[idx], axis=1)
                sums[3, members] = add(syc[idx], axis=1)
            else:
                sums[4, members] = add(x[idx], axis=1)
                sums[5, members] = add(y[idx], axis=1)
            continue
        for i in members.tolist():
            s = int(starts[i])
            e = s + n
            if n > 1:
                sums[0, i] = add(step[s:e - 1])
            if n > 2:
                sums[1, i] = add(cross[s:e])
                sums[2, i] = add(sxc[s:e])
                sums[3, i] = add(syc[s:e])
            else:
                sums[4, i] = add(x[s:e])
                sums[5, i] = add(y[s:e])
    step_sums, cross_sums, sxc_sums, syc_sums, x_sums, y_sums = sums.tolist()

    x_first = x[starts[nz]].tolist()
    y_first = y[starts[nz]].tolist()
    x_last = x[last].tolist()
    y_last = y[last].tolist()

    results = [None] * k
    centers_x = []
    centers_y = []
    j = 0  # index into the traces that have points
    for i, (s, n, is_closed) in enumerate(zip(starts.tolist(), counts.tolist(), closed)):
        if n == 0:
            results[i] = (0.0, 0.0, (0.0, 0.0), 0.0)
            continue
        if n <= 1:
            length = 0.0
        else:
            d = step_sums[i]
            if is_closed:
                d += math.hypot(x_first[j] - x_last[j], y_first[j] - y_last[j])
            length = round(d, 7)
        if n <= 2:
            a = 0.0
            # x.mean(): ndarray.mean divides the sum by the count
            cx = round(x_sums[i] / n, 6)
            cy = round(y_sums[i] / n, 6)
        else:
            signed2 = cross_sums[i]
            a = abs(signed2) / 2.0
            if a > 1e-6:
                cx = round(x_first[j] + sxc_sums[i] / (3.0 * signed2), 6)
                cy = round(y_first[j] + syc_sums[i] / (3.0 * signed2), 6)
            else:
                cx = round(float(add(x[s:s + n])) / n, 6)
                cy = round(float(add(y[s:s + n])) / n, 6)
        results[i] = (length, a, (cx, cy))
        centers_x.append(cx)
        centers_y.append(cy)
        j += 1

    # radius: the largest distance from the centroid, per trace
    if nz.size:
        dist = np.hypot(
            x - np.repeat(np.asarray(centers_x), counts[nz]),
            y - np.repeat(np.asarray(centers_y), counts[nz]),
        )
        radii = np.maximum.reduceat(dist, starts[nz]).tolist()
        for j, i in enumerate(nz.tolist()):
            results[i] = results[i] + (radii[j],)
    return results


def sigfigRound(n : float, sf : int) -> float:
    """Round a float to a specified number of significant figures.
    
        Params:
            n (float): the number to be rounded
            sf (int): the number of significant figures to keep
        Returns:
            (float) the rounded number
    """
    if n == 0:
        return 0
    greatest_place = math.floor(math.log(abs(n))/math.log(10))
    return round(n, sf - (greatest_place+1))


def getDistanceFromTrace(x : float, y: float, trace : list, factor=1.0, absolute=True):
    """Find the distance a point is from a given trace (uses opencv).
    
        Params:
            x (float): the x-coord of the point
            y (float): the y-coord of the point
            trace (list): the trace to check against the point
        Returns:
            (float) the distance of the point from the trace
    """
    pp_test = cv2.pointPolygonTest((np.array(trace) * factor).astype(int), (x * factor, y * factor), measureDist=True)
    return abs(pp_test / factor) if absolute else pp_test / factor


def pointInPoly(x : float, y: float, trace : list) -> bool:
    """Find if a point is in a given trace (uses opencv).
    
        Params:
            x (float): the x-coord of the point
            y (float): the y-coord of the point
            trace (list): the trace to check against the point
        Returns:
            (bool): whether or not the point is in the trace
    """
    pp_test = cv2.pointPolygonTest(np.array(trace).astype(int), (x, y), measureDist=False)
    return pp_test >= 0


def ccwpoly(pts):
    s = 0
    for i in range(len(pts)):
        x1, y1 = pts[i-1]
        x2, y2 = pts[i]
        s += (x2 - x1) * (y2 + y1)
    return s < 0


# source: https://stackoverflow.com/questions/3838329/how-can-i-check-if-two-segments-intersect
def ccw(A,B,C):
    return (C[1]-A[1]) * (B[0]-A[0]) > (B[1]-A[1]) * (C[0]-A[0])


def linesIntersect(A, B, C, D):
    """Return true if line segments AB and CD intersect."""
    return ccw(A,C,D) != ccw(B,C,D) and ccw(A,B,C) != ccw(A,B,D)


def lineIntersectsContour(x1, y1, x2, y2, contour, closed=True):
    p1 = (x1, y1)
    p2 = (x2, y2)
    if closed:
        start = 0
    else:
        start = 1
    for i in range(start, len(contour)):
        p3 = contour[i-1]
        p4 = contour[i]
        if linesIntersect(p1, p2, p3, p4):
            return True
    return False


def colorize(n):
    cn = (n % 156) ** 3
    c = [0, 0, 0]
    for i in range(3):
        c[i] = cn % 156 + 100
        cn //= 156
    return c


def ellipseFromPair(x1, y1, x2, y2, number=100):
    """Create an ellipse from two points in space."""
    center = (
        (x1 + x2) / 2,
        (y1 + y2) / 2
    )
    a = abs(x1 - center[0])
    b = abs(y1 - center[1])

    ellipse = []
    for i in range(number):
        ellipse.append((
            round(center[0] + a * math.cos((i / number) * 2 * math.pi)),
            round(center[1] + b * math.sin((i / number) * 2 * math.pi))
        ))
    
    return ellipse


def get_window_points(points, idx, max_size, edge_mode):
    """Get points for window centered at idx with given maximum size.
    
    Params:
        points (list): list of [x, y, snum] points
        idx (int): center index for the window
        max_size (int): maximum window size
        edge_mode (str): how to handle edges - "padded", "shrinking", or "circular"
        
    Returns:
        tuple: (window_x, window_y) lists of x and y coordinates
    """
    if edge_mode == "shrinking":
        
        ## Calculate growing window size from ends
        dist_from_start = idx
        dist_from_end = len(points) - 1 - idx
        dist_from_edge = min(dist_from_start, dist_from_end)

        ## Window size grows from 1 at edges to max_size in middle
        current_size = min(1 + 2 * dist_from_edge, max_size)
        half = current_size // 2
        start_idx = idx - half
        end_idx = idx + half + 1

        return (
            [p[0] for p in points[start_idx:end_idx]], 
            [p[1] for p in points[start_idx:end_idx]]
        )
        
    else:
        
        half = max_size // 2
        window_x = []
        window_y = []
        
        for i in range(-half, half + 1):
            
            if edge_mode == "circular":
                point_idx = (idx + i) % len(points)
                
            else:  # padded
                point_idx = max(0, min(idx + i, len(points) - 1))
            
            window_x.append(points[point_idx][0])
            window_y.append(points[point_idx][1])
            
        return window_x, window_y


def rolling_average(points, window=10, edge_mode="padded"):
    """Smooth z-trace with configurable edge handling.
    
    Params:
        series (Series): the series object (contains transform data)
        smooth (int): the smoothing factor
        edge_mode (str): how to handle edges - "padded", "shrinking", or "circular"
    """
    if edge_mode not in ["padded", "shrinking", "circular"]:
        raise ValueError("edge_mode must be 'padded', 'shrinking', or 'circular'")

    new_points = [None] * len(points)

    # Process each point
    for i in range(len(points)):
        
        ## Get window points
        window_x, window_y = get_window_points(points, i, window, edge_mode)
        
        ## Calculate moving average
        window_size = len(window_x)  # window len variable depending on edge mode
        xMA = sum(window_x) / window_size
        yMA = sum(window_y) / window_size
        
        ## Update point with smoothed values
        new_points[i] = (
            round(xMA, 4),
            round(yMA, 4)
        )

    return new_points


def interpolate_points(points: List[tuple], spacing=0.01):
    """Interpolate points around a path."""

    # a path needs at least two points to interpolate; fewer is a no-op
    if len(points) < 2:
        return []

    x, y = zip(*points)

    ## Calculate cumulative arc lengths (distances between consecutive points)
    distances = [0]
    
    for i in range(1, len(points)):
        
        distances.append(
            distances[-1] + euclidean_distance(points[i-1], points[i])
        )

    ## Total path length
    total_length = distances[-1]

    ## Interpolate curve using parametric functions
    from scipy.interpolate import interp1d  # deferred: scipy is slow to import
    interp_x = interp1d(distances, x)
    interp_y = interp1d(distances, y)

    # Generate new distances at equal intervals
    num_new_points = int(total_length / spacing)
    new_distances = np.linspace(0, total_length, num_new_points)

    # Interpolate new points at these distances
    x_new = [round(elem, 5) for elem in interp_x(new_distances)]
    y_new = [round(elem, 5) for elem in interp_y(new_distances)]

    return list(
        zip(x_new, y_new)
    )
