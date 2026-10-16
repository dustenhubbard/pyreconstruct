import math

import numpy as np

import shapely
from shapely.geometry import Polygon
from skimage.draw import polygon
import trimesh

from PyReconstruct.modules.calc import centroid
from PyReconstruct.modules.datatypes import Trace, Transform, Series
from PyReconstruct.modules.datatypes.transform import alignment_tform
from PyReconstruct.modules.calc.nesting import (  # noqa: F401 (tests import them from here)
    _covers,
    _traceLine,
    _tracePolygon,
    islandCuts,
)


def exportMesh(tm, output_file, export_type):
    """Export trimesh obj to a file."""
    with open(output_file, "w") as fp:
            
        if export_type == "obj":
            
            with open(output_file, "w") as fp:
                fp.write(trimesh.exchange.obj.export_obj(tm))
                
        elif export_type == "off":
            
            with open(output_file, "w") as fp:
                fp.write(trimesh.exchange.off.export_off(tm))
                
        elif export_type == "ply":
            
            with open(output_file, "wb") as fp:
                fp.write(trimesh.exchange.ply.export_ply(tm))
                
        elif export_type == "stl":
            
            with open(output_file, "wb") as fp:
                fp.write(trimesh.exchange.stl.export_stl(tm))
                
        elif export_type == "dae":
            
            with open(output_file, "wb") as fp:
                fp.write(trimesh.exchange.dae.export_collada(tm))
                    

def mapTracePoints(points : list, tform : Transform = None) -> list:
    """Apply a transform to a trace's points, returning a list of (x, y) tuples.

    Batched through Transform.mapPointsArray: one numpy affine over the whole
    trace instead of a QTransform.map() call per point. mapPointsArray is
    bit-for-bit identical to map() for the affine transforms used here, so the
    resulting mesh is unchanged.

    With no transform the coordinates are passed through untouched -- integer
    trace coordinates must stay integers, since the callers round them.

        Params:
            points (list): the trace points
            tform (Transform): the transform to apply, or None
        Returns:
            (list) the mapped points as (x, y) tuples
    """
    if tform:
        return [(x, y) for x, y in tform.mapPointsArray(points).tolist()]
    else:
        return [(x, y) for x, y in points]


def _outlineVoxels(xs : np.ndarray, ys : np.ndarray) -> tuple:
    """Return the voxels a closed outline passes through, as x and y indices.

    The points are in voxel units, voxel i spanning i to i + 1. Each edge is
    cut at every grid line it crosses and the voxel holding each piece is
    taken, so the voxels of an edge are 4-connected: every voxel it passes
    through and no other. A Bresenham line steps diagonally, and marching
    cubes joins two voxels only across a shared face, so a diagonal step would
    leave the surface in two pieces.

        Params:
            xs (np.ndarray): the x coordinates, in voxel units
            ys (np.ndarray): the y coordinates, in voxel units
        Returns:
            (tuple) the x and y voxel indices, with repeats
    """
    n = len(xs)
    empty = np.zeros(0, dtype=np.intp)
    if n == 0:
        return empty, empty
    x1, y1 = np.roll(xs, -1), np.roll(ys, -1)
    dx, dy = x1 - xs, y1 - ys
    segments = [np.repeat(np.arange(n), 2)]
    times = [np.tile(np.array([0.0, 1.0]), n)]
    for p0, p1, d in ((xs, x1, dx), (ys, y1, dy)):
        # the grid lines each edge crosses, as the fraction of the edge
        # where it crosses them
        first = np.ceil(np.minimum(p0, p1))
        last = np.floor(np.maximum(p0, p1))
        counts = np.where(d != 0, np.maximum(last - first + 1, 0), 0).astype(np.intp)
        seg = np.repeat(np.arange(n), counts)
        starts = np.repeat(np.cumsum(counts) - counts, counts)
        lines = np.repeat(first, counts) + (np.arange(counts.sum()) - starts)
        segments.append(seg)
        times.append((lines - p0[seg]) / d[seg])
    seg = np.concatenate(segments)
    t = np.clip(np.concatenate(times), 0.0, 1.0)
    order = np.lexsort((t, seg))
    seg, t = seg[order], t[order]
    # the middle of each piece between two crossings sits inside one voxel
    same = seg[:-1] == seg[1:]
    piece = same & (t[1:] - t[:-1] > 1e-9)
    mid = (t[:-1] + t[1:])[piece] / 2
    vx = np.floor(xs[seg[:-1][piece]] + mid * dx[seg[:-1][piece]])
    vy = np.floor(ys[seg[:-1][piece]] + mid * dy[seg[:-1][piece]])
    # a piece with no length is a grid corner the edge passes through, where
    # it steps diagonally; the four voxels around the corner keep the band
    # 4-connected (the caller drops the ones the trace does not reach into)
    touch = same & ~piece
    px = xs[seg[:-1][touch]] + t[:-1][touch] * dx[seg[:-1][touch]]
    py = ys[seg[:-1][touch]] + t[:-1][touch] * dy[seg[:-1][touch]]
    rx, ry = np.round(px), np.round(py)
    corner = (np.abs(px - rx) < 1e-9) & (np.abs(py - ry) < 1e-9)
    rx, ry = rx[corner], ry[corner]
    vx = np.concatenate([vx, rx - 1, rx - 1, rx, rx])
    vy = np.concatenate([vy, ry - 1, ry, ry - 1, ry])
    return vx.astype(np.intp), vy.astype(np.intp)


def traceVoxels(points : list, xmin : float, ymin : float, vres : float, shape : tuple) -> tuple:
    """Return the x and y indices of the voxels a trace covers on its section.

    Voxel (i, j) spans xmin + i*vres to xmin + (i+1)*vres across and
    ymin + j*vres to ymin + (j+1)*vres up. A voxel is covered when the trace
    reaches into it: the voxels with their center inside the outline, which
    skimage's polygon finds, and the voxels the outline passes through. The
    second set is what keeps a trace thinner than a voxel whole. A synapse
    contour at the default XY resolution is often a fraction of a voxel wide,
    and filling only the voxels whose center fell inside its rounded outline
    left a dotted line, or nothing, on a section; stacked across sections the
    gaps became tunnels through the surface (found 2026-10-14). A trace with
    no area covers the voxels its outline runs through.

        Params:
            points (list): the trace's (x, y) points in field units
            xmin, ymin (float): the corner of the voxel grid
            vres (float): the voxel width
            shape (tuple): the grid size in x and y
        Returns:
            (tuple) the x and y voxel indices, each voxel once
    """
    empty = np.zeros(0, dtype=np.intp)
    if len(points) == 0:
        return empty, empty
    pts = np.asarray(points, dtype=float)
    xs = (pts[:, 0] - xmin) / vres
    ys = (pts[:, 1] - ymin) / vres
    # voxel i has its center at i + 0.5
    cx, cy = polygon(xs - 0.5, ys - 0.5, shape)
    ox, oy = _outlineVoxels(xs, ys)
    inside = (ox >= 0) & (ox < shape[0]) & (oy >= 0) & (oy < shape[1])
    ox, oy = ox[inside], oy[inside]
    # an outline running along a grid line passes through the voxels on both
    # sides of it; keep the ones the trace's area reaches into
    if len(ox):
        try:
            poly = Polygon(np.column_stack([xs, ys]))
            if poly.area > 0:
                shapely.prepare(poly)
                eps = 1e-9
                boxes = shapely.box(ox + eps, oy + eps, ox + 1 - eps, oy + 1 - eps)
                reached = shapely.intersects(poly, boxes)
                ox, oy = ox[reached], oy[reached]
        except Exception:
            pass  # an outline GEOS cannot test keeps every voxel it runs through
    flat = np.unique(np.concatenate([cx, ox]).astype(np.intp) * shape[1]
                     + np.concatenate([cy, oy]).astype(np.intp))
    return flat // shape[1], flat % shape[1]


class Object3D():

    def __init__(self, name, series : Series, color=None, alpha=None, tform=None):
        self.name = name
        self.series = series
        self.color = color
        self.alpha = alpha
        self.tform = tform
        self.extremes = []  # xmin, xmax, ymin, ymax, zmin, zmax
    
    def addToExtremes(self, x, y, s):
        """Keep track of the extreme values."""
        if not self.extremes:
            self.extremes = [x, x, y, y, s, s]
        else:
            if x < self.extremes[0]: self.extremes[0] = x
            if x > self.extremes[1]: self.extremes[1] = x
            if y < self.extremes[2]: self.extremes[2] = y
            if y > self.extremes[3]: self.extremes[3] = y
            if s < self.extremes[4]: self.extremes[4] = s
            if s > self.extremes[5]: self.extremes[5] = s

    def addPointsToExtremes(self, pts : list, s : int):
        """Fold a whole trace's points into the extreme values.

        Equivalent to calling addToExtremes() once per point: the extremes are
        six independent running min/max values, so feeding the trace's
        (min x, min y) and then its (max x, max y) yields the same six numbers.
        An empty trace is a no-op -- the per-point loop never ran for one, and
        seeding the extremes off it would be wrong.

            Params:
                pts (list): the trace's (x, y) points
                s (int): the section number
        """
        if not pts:
            return
        xs = [pt[0] for pt in pts]
        ys = [pt[1] for pt in pts]
        self.addToExtremes(min(xs), min(ys), s)
        self.addToExtremes(max(xs), max(ys), s)


class Surface(Object3D):

    def __init__(self, *args):
        """Create a 3D Surface object."""
        super().__init__(*args)
        self.default_color = None
        self.traces = {}
    
    def addTrace(self, trace : Trace, snum : int, tform : Transform = None):
        """Add a trace to the surface data."""
        if self.default_color is None:
            self.default_color = trace.color
        
        if snum not in self.traces:
            self.traces[snum] = {}
            self.traces[snum]["pos"] = []
            self.traces[snum]["neg"] = []
        
        pts = mapTracePoints(trace.points, tform)
        self.addPointsToExtremes(pts, snum)

        if trace.negative:
            self.traces[snum]["neg"].append(pts)
        else:
            self.traces[snum]["pos"].append(pts)

    def generateVolume(self):
        """Fill the voxel volume the mesh is built from.

        Voxel (i, j) of a section spans xmin + i*vres to xmin + (i+1)*vres
        across and ymin + j*vres to ymin + (j+1)*vres up, and a trace covers
        every voxel it reaches into (see traceVoxels).

            Returns:
                (np.ndarray): the boolean volume, indexed x, y, section
                (float): the xy size of a voxel
        """
        # calculate the xy resolution for the volume
        vres_min = min(self.series.avg_mag, self.series.avg_thickness)
        vres_max = max(self.series.avg_mag, self.series.avg_thickness)
        vres_percent = self.series.getOption("3D_xy_res")
        vres = vres_min + (1 - vres_percent / 100) * (vres_max - vres_min)
        # calculate the dimensions of bounding box for empty array
        xmin, xmax, ymin, ymax, smin, smax = tuple(self.extremes)
        vshape = (
            round((xmax-xmin)/vres)+1,
            round((ymax-ymin)/vres)+1,
            smax-smin+1
        )

        # create empty numpy volume
        volume = np.zeros(vshape, dtype=bool)

        def voxels(trace):
            return traceVoxels(trace, xmin, ymin, vres, vshape[:2])

        # add the traces to the volume: positives fill and then negatives
        # clear; a positive inside a negative (an island in a hole) is then
        # filled back in, less the voxels of every negative that cuts it. A
        # negative within a voxel's diagonal of the island can reach into
        # its edge voxels, so it counts as cutting it.
        reach = math.hypot(vres, vres)
        for snum, trace_lists in self.traces.items():
            z = snum - smin
            for fill, key in ((True, "pos"), (False, "neg")):
                for trace in trace_lists[key]:
                    x_pos, y_pos = voxels(trace)
                    volume[x_pos, y_pos, z] = fill
            for island, cuts in islandCuts(
                trace_lists["pos"], trace_lists["neg"], reach
            ):
                xs, ys = voxels(island)
                if not len(xs):
                    continue
                x0, y0 = xs.min(), ys.min()
                keep = np.zeros((xs.max() - x0 + 1, ys.max() - y0 + 1), dtype=bool)
                keep[xs - x0, ys - y0] = True
                for trace in cuts:
                    cx, cy = voxels(trace)
                    inside = (
                        (cx >= x0) & (cx < x0 + keep.shape[0])
                        & (cy >= y0) & (cy < y0 + keep.shape[1])
                    )
                    keep[cx[inside] - x0, cy[inside] - y0] = False
                volume[x0:x0 + keep.shape[0], y0:y0 + keep.shape[1], z] |= keep

        return volume, vres

    def generateTrimesh(self):
        """Generate a trimesh object from traces."""
        xmin, xmax, ymin, ymax, smin, smax = tuple(self.extremes)
        volume, vres = self.generateVolume()

        # generate trimesh
        tm = trimesh.voxel.ops.matrix_to_marching_cubes(volume)
        tm : trimesh.base.Trimesh

        # add metadata
        tm.metadata["name"] = self.name
        tm.metadata["color"] = self.color if self.color else self.default_color
        tm.metadata["alpha"] = self.series.getAttr(self.name, "3D_opacity")

        smoothing = self.series.getOption("3D_smoothing")
        iterations = self.series.getOption("smoothing_iterations")

        # smooth trimesh
        if smoothing == "humphrey":
            trimesh.smoothing.filter_humphrey(tm, iterations=iterations)
        elif smoothing == "laplacian":
            trimesh.smoothing.filter_laplacian(tm, iterations=iterations)
        elif smoothing == "mut_dif_laplacian":
            trimesh.smoothing.filter_mut_dif_laplacian(tm, iterations=iterations)
        elif smoothing == "taubin":
            trimesh.smoothing.filter_taubin(tm, iterations=iterations)

        # provide real vertex locations
        # (i.e., normalize to real world dimensions)
        # voxel i spans xmin + i*vres to xmin + (i+1)*vres (see traceVoxels)
        tm.vertices[:,:2] += 0.5
        tm.vertices[:,:2] *= vres
        tm.vertices[:,0] += xmin
        tm.vertices[:,1] += ymin
        tm.vertices[:,2] += smin
        tm.vertices[:,2] *= self.series.avg_thickness

        return tm

    def measure(self):
        """Return the surface area and volume of the mesh."""

        tm = self.generateTrimesh()
        return tm.area, tm.volume

    def exportTrimesh(self, output_file, export_type):
        """Export trimesh object to file."""

        tm = self.generateTrimesh()
        exportMesh(tm, output_file, export_type)

    def generate3D(self):
        """Generate the openGL mesh for a surface object."""

        tm = self.generateTrimesh()

        mesh_data = {
            "name": self.name,
            "type": "object",
            "color": self.color if self.color else self.default_color,
            "alpha": self.alpha if self.alpha is not None else self.series.getAttr(self.name, "3D_opacity"),
            "vertices": tm.vertices,
            "faces": tm.faces,
            "tform": self.tform
        }

        return mesh_data


class Spheres(Object3D):

    def __init__(self, *args):
        """Create a 3D Spheres object."""
        super().__init__(*args)
        self.colors = []
        self.centroids = []
        self.radii = []
    
    def addTrace(self, trace : Trace, snum : int, tform : Transform = None):
        """Add a trace to the spheres data."""
        self.colors.append(trace.color)

        x, y = centroid(trace.points)
        if tform:
            x, y = tform.map(x, y)
        self.centroids.append((x, y, snum))
        self.addToExtremes(x, y, snum)

        self.radii.append(trace.getRadius(tform))

    def generateTrimesh(self):
        """Generate trimesh object of spheres."""

        verts = []
        faces = []

        all_spheres = []
        
        for point, radius in zip(
            self.centroids,
            self.radii
        ):
            x, y, s = point
            z = s * self.series.avg_thickness
            sphere = trimesh.primitives.Sphere(radius=radius, center=(x,y,z), subdivisions=1)
            all_spheres.append(sphere)
            
            faces += (sphere.faces + len(verts)).tolist()
            verts += sphere.vertices.tolist()
        
        return trimesh.util.concatenate(all_spheres)

    def measure(self):
        """Return the summed surface area and volume of the spheres.

        Taken from the radii, not from the mesh. The mesh is an icosphere with
        one subdivision, which holds about 87% of a sphere's volume and 93% of
        its area. Only a single sphere measured exactly, because concatenating
        one primitive returns the primitive, whose area and volume are exact;
        two or more came back as a plain mesh (found 2026-09-30).
        """

        area = sum(4 * np.pi * r ** 2 for r in self.radii)
        volume = sum(4 / 3 * np.pi * r ** 3 for r in self.radii)
        return area, volume

    def exportTrimesh(self, output_file, export_type):
        """Export trimesh sphere(s) to file."""

        tm = self.generateTrimesh()
        exportMesh(tm, output_file, export_type)
            
    def generate3D(self):
        """Generate the openGL meshes for sphere objects."""

        tm = self.generateTrimesh()
        
        mesh_data = {
            "name": self.name,
            "type": "object",
            "color": self.color if self.color else self.colors[0],
            "alpha": self.alpha if self.alpha is not None else self.series.getAttr(self.name, "3D_opacity"),
            "vertices": np.array(tm.vertices),
            "faces": np.array(tm.faces),
            "tform": self.tform
        }
        
        return mesh_data


class Contours(Object3D):

    def __init__(self, *args):
        """Create a 3D Surface object."""
        super().__init__(*args)
        self.default_color = None
        self.traces = {}
    
    def addTrace(self, trace : Trace, snum : int, tform : Transform = None):
        """Add a trace to the surface data."""
        if self.default_color is None:
            self.default_color = trace.color
        
        if snum not in self.traces:
            self.traces[snum] = []
        
        pts = mapTracePoints(trace.points, tform)
        self.addPointsToExtremes(pts, snum)

        if trace.closed:
            pts.append(pts[0])
        
        self.traces[snum].append(pts)
    
    def generate3D(self):
        """Generate openGL meshes for trace slabs."""
        
        verts = []
        faces = []
        
        for snum in self.traces:
            # get the z values
            t = self.series.avg_thickness
            z1 = snum * t
            z2 = z1 + t/2
            for trace in self.traces[snum]:
                for i in range(len(trace)-1):
                    # get the xy coords of the points
                    x1, y1 = trace[i]
                    x2, y2 = trace[i+1]
                    # gather the four points to create the slab section
                    verts.append([x1, y1, z1])
                    verts.append([x2, y2, z1])
                    verts.append([x2, y2, z2])
                    verts.append([x1, y1, z2])
                    # create the faces
                    l = len(verts)
                    faces.append([l-4, l-3, l-2])
                    faces.append([l-4, l-2, l-1])
        
        mesh_data = {
            "name": self.name,
            "type": "object",
            "color": self.color if self.color else self.default_color,
            "alpha": self.alpha if self.alpha is not None else self.series.getAttr(self.name, "3D_opacity"),
            "vertices": np.array(verts),
            "faces": np.array(faces),
            "tform": self.tform
        }

        return mesh_data


class Ztrace3D(Object3D):
    
    def generate3D(self):
        """Generate the 3D object for the ztrace."""
        # ASSUME UNIFORM SECTION THICKNESS
        thickness = self.series.avg_thickness

        ztrace = self.series.ztraces[self.name]

        # get appropriate alignment (the same for every point of the ztrace)
        # a stored name that no longer exists degrades to the series alignment
        # rather than raising; see transform.alignment_tform
        alignment = self.series.getAttr(self.name, "alignment", ztrace=True)

        # NOTE: not batched through mapPointsArray -- every ztrace point carries
        # its own section, so the tform varies point to point and the batches
        # would be one point each (slower than a scalar map).
        pts = []
        for pt in ztrace.points:
            # get coords
            x, y, s = pt
            self.addToExtremes(x, y, s)

            # get real field coord point
            tform = alignment_tform(self.series, s, alignment)
            x, y = tform.map(x, y)
            z = s * thickness
            pts.append((x, y, z))
        
        d = ztrace.getDistance(self.series)
        color = ztrace.color

        verts, faces = createTube(pts, d/1000)

        ## The literal 1 fallback is not a stored value the way the object
        ## paths' is: SceneObject.setAlpha only writes 3D_opacity for
        ## type == "object", so a ztrace never has one, and Series.getAttr
        ## would return 1 for it anyway.
        mesh_data = {
            "name": self.name,
            "type": "ztrace",
            "color": self.color if self.color else color,
            "alpha": self.alpha if self.alpha is not None else 1,
            "vertices": verts,
            "faces": faces,
            "tform": self.tform
        }

        return mesh_data


def getCircleVertices(radius, segments):
    """
    Generate vertices for a circle in the XY plane.
    
    :param radius: Radius of the circle
    :param segments: Number of segments (vertices) to generate around the circle
    :return: Numpy array of shape (segments, 3) containing the circle vertices
    """
    angles = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    x = radius * np.cos(angles)
    y = radius * np.sin(angles)
    z = np.zeros(segments)
    return np.vstack((x, y, z)).T

def createTube(path_points, radius=0.1, segments=6):
    """Create a tube mesh.
    
        Params:
            path_points (list): the list of 3D points
            radius (float): the radius of the circle for the tube
            segments (int): the number of segments in the circle
    """
    # Generate the circular profile vertices
    circle_vertices = getCircleVertices(radius, segments)

    # Initialize lists to store vertices and faces
    vertices = []
    faces = []

    num_points = len(path_points)
    num_circle_vertices = len(circle_vertices)

    for i, point in enumerate(path_points):
        # Translate the circle profile to the current path point
        translated_vertices = circle_vertices + point
        vertices.extend(translated_vertices)

        if i > 0:
            # Connect the current profile with the previous profile
            for j in range(num_circle_vertices):
                next_j = (j + 1) % num_circle_vertices
                current_base = (i * num_circle_vertices) + j
                current_next = (i * num_circle_vertices) + next_j
                previous_base = ((i - 1) * num_circle_vertices) + j
                previous_next = ((i - 1) * num_circle_vertices) + next_j

                # Create two faces (a quad) between the profiles
                faces.append([previous_base, previous_next, current_next])
                faces.append([previous_base, current_next, current_base])

    # Convert lists to numpy arrays
    vertices = np.array(vertices)
    faces = np.array(faces)

    return vertices, faces

