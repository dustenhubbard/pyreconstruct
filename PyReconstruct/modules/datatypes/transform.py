"""Affine transforms for the core data model (Qt-free).

The six-number transform list is the whole contract: for
``[a, b, c, d, e, f]``,

    nx = a*x + b*y + c
    ny = d*x + e*y + f

which is `QTransform`'s row-vector convention (a=m11, b=m21, c=dx, d=m12,
e=m22, f=dy). The affine arithmetic below is plain Python/NumPy, so importing
this module -- and therefore `modules.datatypes` -- pulls in no Qt. Qt only
appears in the two adapter methods that exist to hand a `QTransform` to the
GUI (`getQTransform`, `fromQTransform`), which import PySide6 lazily.

Numerics: the operations replicate `QTransform`'s arithmetic (operand order,
inverse-by-reciprocal branches, and its fuzzy invertibility threshold), so
results are bit-for-bit identical to the previous QTransform-backed
implementation for every transform whose special-case structure is exact --
verified against QTransform in `tests/test_transform_qt_equivalence.py`
(fixtures, 550 random transforms, 3,600 composition pairs and 400k mapped
coordinates: zero mismatches). The one documented divergence: QTransform
classifies a matrix by type using a 1e-12 fuzz (`qFuzzyIsNull`), so it silently
drops a shear/scale/translation term whose magnitude is below that threshold;
the pure-Python affine keeps it, i.e. it is the mathematically exact result.
Deltas there are bounded by the threshold (~1e-13 absolute on the matrix
entries; see the characterization test). Note that `mapPointsArray` already
used the general formula for all transform types, so this also removes an
existing map()/mapPointsArray() disagreement in that corner.
"""

import numpy as np

# QTransform's qFuzzyIsNull() threshold, replicated so that a transform Qt
# reported as non-invertible still raises here rather than yielding huge
# numbers from a near-singular matrix.
_FUZZ = 1e-12


def _invert_list(t):
    """Invert a six-number affine the way ``QTransform.inverted()`` does.

    Returns ``(inverted_list, invertible)``. QTransform inverts by branching on
    the matrix type; the branches are reproduced here for matrices that are
    *exactly* identity/translation/scale (where Qt's reciprocal arithmetic
    differs from the general adjoint formula by an ULP), with the general
    adjoint-times-reciprocal path otherwise.
    """
    a, b, c, d, e, f = (float(v) for v in t)

    if b == 0.0 and d == 0.0:
        if a == 1.0 and e == 1.0:
            if c == 0.0 and f == 0.0:                       # identity (TxNone)
                return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0], True
            return [1.0, 0.0, -c, 0.0, 1.0, -f], True       # TxTranslate
        if abs(a) <= _FUZZ or abs(e) <= _FUZZ:              # TxScale
            return None, False
        inv_a = 1.0 / a
        inv_e = 1.0 / e
        return [inv_a, 0.0, -c * inv_a, 0.0, inv_e, -f * inv_e], True

    det = a * e - b * d                                     # general case
    if abs(det) <= _FUZZ:
        return None, False
    inv_det = 1.0 / det
    return [
        e * inv_det,
        (-b) * inv_det,
        (b * f - e * c) * inv_det,
        (-d) * inv_det,
        a * inv_det,
        (d * c - a * f) * inv_det,
    ], True


def _compose_lists(t1, t2):
    """Compose two six-number affines as ``QTransform(t1) * QTransform(t2)``.

    Row-vector convention: the result applies ``t1`` first, then ``t2``.
    """
    a1, b1, c1, d1, e1, f1 = (float(v) for v in t1)
    a2, b2, c2, d2, e2, f2 = (float(v) for v in t2)
    return [
        a1 * a2 + d1 * b2,
        b1 * a2 + e1 * b2,
        c1 * a2 + f1 * b2 + c2,
        a1 * d2 + d1 * e2,
        b1 * d2 + e1 * e2,
        c1 * d2 + f1 * e2 + f2,
    ]


class Transform():

    def __init__(self, tform_list : list):
        """Create the transform object.

            Params:
                tform_list (list): the tform as a six-number list
        """
        self.tform = tform_list

    def _affine(self, inverted=False):
        """Return the six affine numbers to map with (inverted if requested).

        The forward case hands back `self.tform`'s numbers untouched (mapping
        coerces its results, so a list of ints still maps to floats exactly as
        QTransform did); the inverted case goes through `_invert_list`, which
        works in floats.

            Returns:
                (list): [a, b, c, d, e, f]
        """
        if inverted:
            t, invertible = _invert_list(self.tform)
            if not invertible:
                raise Exception("Matrix is not invertible.")
            return t
        return self.tform

    @property
    def qtform(self):
        """The transform as a QTransform (Qt adapter; requires PySide6).

        Kept for callers that reached for the old cached attribute; it is now
        built on demand so that a Transform holds no Qt object.
        """
        return self.getQTransform()

    def getQTransform(self):
        """Get the transform as a QTransform object.

            Returns:
                (QTransform): the QTransform object
        """
        from PySide6.QtGui import QTransform  # deferred: Qt adapter only
        t = self.tform
        return QTransform(t[0], t[3], t[1], t[4], t[2], t[5])

    # STATIC METHOD
    def fromQTransform(qtform):
        """Get a Transform object from a QTransform object."""
        return Transform([
            qtform.m11(),
            qtform.m21(),
            qtform.m31(),
            qtform.m12(),
            qtform.m22(),
            qtform.m32()
        ])

    def imageTransform(self):
        """Get the transform object as it should apply to images.
        
            Returns:
                (Transform): the image-style transform
        """
        t = self.tform
        return Transform([t[0], -t[1], 0, -t[3], t[4], 0])
    
    def map(self, *args, inverted=False):
        """Apply the transform to a single point or a list of points.
        
            Params:
                (tuple): an x, y coordinate pair to transform
                OR
                (list): a list of points to transform
            Returns:
                (tuple) OR (list): the transformed point or points
        """
        a, b, c, d, e, f = self._affine(inverted)
        if len(args) == 2:
            x, y = args
            return (float(a * x + b * y + c), float(d * x + e * y + f))
        elif len(args) == 1:
            return [
                (float(a * x + b * y + c), float(d * x + e * y + f))
                for x, y in args[0]
            ]

    def mapPointsArray(self, points, inverted=False):
        """Apply the transform to a list/array of points, returning an (N, 2)
        float ndarray.

        Numeric consumers (e.g. the per-trace geometry build) want an array, not
        a Python list of tuples. Going straight to an array avoids creating one
        tuple per point and then re-converting -- the dominant cost when mapping
        the points of tens of thousands of traces. Affine only; the result is
        bit-for-bit identical to map() and to QTransform.map -- verified on 5.9M
        real points, and pinned in tests/test_transform_qt_equivalence.py. Uses
        QTransform's convention: nx = m11*x + m21*y + dx,
        ny = m12*x + m22*y + dy.
        """
        a, b, c, d, e, f = self._affine(inverted)
        arr = np.asarray(points, dtype=float)
        if arr.size == 0:
            return np.empty((0, 2), dtype=float)
        x = arr[:, 0]
        y = arr[:, 1]
        out = np.empty((arr.shape[0], 2), dtype=float)
        out[:, 0] = a * x + b * y + c
        out[:, 1] = d * x + e * y + f
        return out
    
    def getList(self) -> list:
        """Get the tform list numbers.
        
            Returns:
                (list): the six-number transform
        """
        return self.tform.copy()
    
    def inverted(self):
        """Return the inverted transform.
        
            Returns:
                (Transform): the inverted transform
        """
        t, invertible = _invert_list(self.tform)
        if not invertible:
            raise Exception("Matrix is not invertible")
        return Transform(t)
    
    def copy(self):
        """Returns a copy of the transform."""
        return Transform(self.tform.copy())
    
    def __mul__(self, other):
        """Compose two transforms."""
        return Transform(_compose_lists(self.tform, other.tform))
    
    def magScale(self, prev_mag : float, new_mag : float):
        """Scale the transform to magnification changes.
        
            Params:
                prev_mag (float): the previous magnification
                new_mag (float): the new magnification
        """
        self.tform[2] *= new_mag / prev_mag
        self.tform[5] *= new_mag / prev_mag
    
    def estimateTform(pts1, pts2):
        """Estimate the transform that converts pts1 to pts2.
        
            Params:
                pts1 (list): the list of original points
                pts2 (list): the list of points to transform into
        """
        from skimage import transform as tf  # deferred: skimage is slow to import
        m = tf.estimate_transform("affine", np.array(pts1), np.array(pts2)).params

        tform = Transform([
            m[0,0], m[0,1], m[0,2],
            m[1,0], m[1,1], m[1,2]
        ])

        return tform

    @property
    def det(self):
        """The determinant (same value QTransform.determinant() returned)."""
        a, b, _, d, e, _ = self.tform
        return float(a * e - b * d)

    def equals(self, other):
        """Compare two transforms
        
            Params:
                other (Transform): the other transform
        """
        l1 = self.getList()
        l2 = other.getList()            
        for n1, n2 in zip(l1, l2):
            if abs(n1 - n2) > 1e-6:
                return False
        return True
    
    def getLinear(self):
        l = self.getList()
        l[2], l[5] = 0, 0
        return Transform(l)
    
    def identity():
        return Transform([1, 0, 0, 0, 1, 0])




def alignment_tform(series, snum : int, alignment : str = None):
    """The transform for an alignment on one section, degrading, never raising.

    ``alignment`` is a stored per-object or per-ztrace alignment name, or None
    to mean "use the series alignment". A name that no longer exists falls back
    to the series alignment, and then to ``no-alignment``, which the tform
    container always seeds with the identity transform.

    The fallback exists because a stored alignment name can outlive the
    alignment itself. ``Series.remapStoredAlignments`` now carries those
    attributes across a rename and clears them on a delete, but a series saved
    before that fix can already hold a dangling name, and a dangling name used
    to reach a bare tform lookup and raise ``KeyError`` from inside a table
    population. Reported against the z-trace list, which computes a distance for
    every row while the table is being built, so one z-trace with a dangling
    alignment made the whole list impossible to open.

    Nothing is written on a miss. The object path self-heals by clearing the
    attribute in ``SeriesData.addTrace``, but this runs while tables and 3D
    meshes are being built, and mutating series attributes from a read is how
    drawing a table turns into an unsaved change.

    A function taking ``series`` rather than a ``Series`` method, because the
    callers are datatypes that the suite exercises with lightweight series
    doubles: everything needed is ``series.data["sections"]`` and
    ``series.alignment``, so the existing doubles satisfy it unchanged.

        Params:
            series (Series): the series holding the section tform tables
            snum (int): the section to get the transform on
            alignment (str): the stored alignment name, or None
    """
    tforms = series.data["sections"][snum]["tforms"]
    if alignment in tforms:
        return tforms[alignment]
    if series.alignment in tforms:
        return tforms[series.alignment]
    return tforms["no-alignment"]
