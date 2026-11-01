"""A trace's points, built from the section file's x and y lists when first read.

A section file holds a trace's coordinates as two lists, x and y. Loading a
section built a tuple per point from them at once, `list(zip(x, y))`: about
550,000 tuples for a dense section, each a tracked object the collector walked
at every collection the load set off. Paging draws a section from the columnar
store's arrays, so most of those tuples were never read.

`LazyPoints` is a `list` that holds the x and y lists until something reads,
compares or changes it, and then fills itself with the same `zip` the load ran.
Every list operation fills first, so a caller cannot tell it from the plain
list the load used to give, except that `type(points) is list` is False.
`len()` and truth come from the x list without filling. `copy()`, `copy.copy`,
`copy.deepcopy` and pickling give a plain list.

`__array__` gives the `(n, 2)` float64 array the load read from the same lists
(`coordinatesFromRow`), so `np.asarray(trace.points, dtype=float)`, which the
per-trace draw, the hover and the bounds run, reads no tuple. The array is
kept until the first change to the points, and `loadedArray` hands it to the
store's rebuild while it is kept. With no dtype asked for, `np.array` infers
one from the points as it did before, so a trace of integers still gives an
integer array.
"""

import numpy as np


class LazyPoints(list):
    """A trace's points over the row's x and y lists; see the module docstring.

    `x` and `y` must be two lists of one length. `array` is their `(n, 2)`
    float64 array, or None; it is made read-only, as every array a trace's
    points are kept beside is.
    """

    __slots__ = ("_x", "_y", "_array")

    def __init__(self, x: list, y: list, array=None):
        list.__init__(self)
        if type(x) is not list or type(y) is not list or len(x) != len(y):
            raise ValueError("LazyPoints takes two lists of the same length")
        self._x = x
        self._y = y
        if array is not None:
            array.flags.writeable = False
        self._array = array

    @classmethod
    def fromRow(cls, x, y, array=None):
        """The points over a row's x and y, or None when they are not two
        lists of one length. The caller then builds `list(zip(x, y))`, which
        cuts the longer of two unequal lists, as the load always did."""
        if type(x) is list and type(y) is list and len(x) == len(y):
            return cls(x, y, array)
        return None

    @property
    def pending(self) -> bool:
        """True while the points have not been built."""
        return self._x is not None

    def loadedArray(self):
        """The `(n, 2)` float64 array of the points as loaded, read-only, while
        the points are unchanged; None after a change or when the load read
        none."""
        return self._array

    def _fill(self):
        if self._x is not None:
            list.extend(self, zip(self._x, self._y))
            self._x = self._y = None

    def _change(self):
        self._fill()
        self._array = None

    @staticmethod
    def _filled(other):
        """`other` with its points built, when it is a LazyPoints: `list`'s
        own comparison and concatenation read the other list's storage
        directly, not through its methods."""
        if type(other) is LazyPoints:
            other._fill()
        return other

    # --- reading --------------------------------------------------------

    def __len__(self):
        x = self._x
        return len(x) if x is not None else list.__len__(self)

    def __iter__(self):
        self._fill()
        return list.__iter__(self)

    def __reversed__(self):
        self._fill()
        return list.__reversed__(self)

    def __getitem__(self, index):
        self._fill()
        return list.__getitem__(self, index)

    def __contains__(self, point):
        self._fill()
        return list.__contains__(self, point)

    def __repr__(self):
        self._fill()
        return list.__repr__(self)

    def index(self, *args):
        self._fill()
        return list.index(self, *args)

    def count(self, point):
        self._fill()
        return list.count(self, point)

    def copy(self) -> list:
        """A plain list of the points."""
        self._fill()
        return list.copy(self)

    def __reduce__(self):
        return (list, (self.copy(),))

    def __array__(self, dtype=None, copy=None):
        if dtype is not None:
            dtype = np.dtype(dtype)
            array = self._array
            if array is not None:
                return array if dtype == array.dtype else array.astype(dtype)
        return np.array(self.copy(), dtype=dtype)

    # --- comparing ------------------------------------------------------

    __hash__ = None

    def __eq__(self, other):
        self._fill()
        return list.__eq__(self, self._filled(other))

    def __ne__(self, other):
        self._fill()
        return list.__ne__(self, self._filled(other))

    def __lt__(self, other):
        self._fill()
        return list.__lt__(self, self._filled(other))

    def __le__(self, other):
        self._fill()
        return list.__le__(self, self._filled(other))

    def __gt__(self, other):
        self._fill()
        return list.__gt__(self, self._filled(other))

    def __ge__(self, other):
        self._fill()
        return list.__ge__(self, self._filled(other))

    # --- new lists ------------------------------------------------------

    def __add__(self, other):
        self._fill()
        return list.__add__(self, self._filled(other))

    def __radd__(self, other):
        # Python asks a list subclass on the right before the left list's own
        # `+` and `+=`. Fill, then decline, so `list + points` builds a new
        # list and `target += points` extends `target` itself, as a plain
        # list on the right does.
        self._fill()
        return NotImplemented

    def __mul__(self, n):
        self._fill()
        return list.__mul__(self, n)

    __rmul__ = __mul__

    # --- changing -------------------------------------------------------

    def __setitem__(self, index, value):
        self._change()
        list.__setitem__(self, index, value)

    def __delitem__(self, index):
        self._change()
        list.__delitem__(self, index)

    def __iadd__(self, other):
        self._change()
        return list.__iadd__(self, other)

    def __imul__(self, n):
        self._change()
        return list.__imul__(self, n)

    def append(self, point):
        self._change()
        list.append(self, point)

    def extend(self, points):
        self._change()
        list.extend(self, points)

    def insert(self, index, point):
        self._change()
        list.insert(self, index, point)

    def pop(self, *args):
        self._change()
        return list.pop(self, *args)

    def remove(self, point):
        self._change()
        list.remove(self, point)

    def clear(self):
        self._change()
        list.clear(self)

    def reverse(self):
        self._change()
        list.reverse(self)

    def sort(self, *, key=None, reverse=False):
        self._change()
        list.sort(self, key=key, reverse=reverse)
