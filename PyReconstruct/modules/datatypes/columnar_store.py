"""A columnar store for one section's traces, behind the Qt-free core seam.

Phase 1 of the columnar-sections work. This module is a **parallel
representation with no consumers**: nothing in the application reads it, no call
site is rewired, `Trace`/`Contour`/`Section` are untouched, and no byte of any
`.jser` changes. What it buys today is a thing the parity tests can point at, so
the layout, the tracking and the identity plumbing can be argued about against
running code instead of against prose.

WHAT PARITY MEANS HERE, AND WHICH SIDE OF THE ROUNDING THIS SITS ON
-------------------------------------------------------------------
`Trace.getList` writes coordinates as `round(p[0], 7)`, while `trace.points`
in memory is unrounded. Every parity argument that compares a store against a
`getList` round-trip is therefore comparing two lossy things and can pass while
proving nothing.

**This store holds the unrounded in-memory float64 value.** It is on the
in-memory side of the rounding, not the serialized side, and the parity tests
are written against `trace.points` rather than against `trace.getList()`. A
consequence worth stating because it is easy to read the wrong way round: a
store built from a section and then materialized back is bit-identical to the
section, while a section written through `getList` and read back through
`fromList` is not.

LAYOUT, AND WHAT IS DELIBERATELY NOT DECIDED
--------------------------------------------
Attribute rows are **append-only** and a contour is a **per-contour index of row
numbers**, not a slice. That is the behavior-preserving shape: `addTrace` is an
append today and stays one, so nothing here performs a mid-array insert. Row
numbers are never reused; a removed row is tombstoned and its index retires with
it, which is what lets the index and any future op log refer to a row by number.
Within-contour order is preserved, because it is semantically significant:
`Contour.importTraces` walks `self[i]` against `other[i]` positionally and stops
at the first non-overlap, so a layout that reordered a contour would change
import behavior on real data.

**Whether coordinates live in one array per section or one array per trace is
not decided here, and this module is written so that it does not have to be.**
Both are implemented, both satisfy the same three-method backing interface, and
the store does not know which it has:

* `SegmentedCoordinates` -- one `(n, 2)` float64 array per row. Insert and
  delete are O(1), a row's array is its own, and nothing aliases.
* `PackedCoordinates` -- one `(N, 2)` float64 array per section with a per-row
  extent, appended to and never inserted into. A row whose length changes is
  appended fresh and its old extent tombstoned, so `addTrace` and a reshape are
  both appends. `deadRows` and `deadPoints` report the slack a compaction pass
  would reclaim, and there is no compaction pass here, because compaction
  reorders rows and row order is load-bearing above.

The default is `SegmentedCoordinates`, because it is the one that preserves
today's complexity on every path. Choosing between them is a measurement that
has not been taken. Nothing outside a backing depends on the answer, and the
parity suite runs against both, which is what keeps the question open.

Coordinates are **float64**, not float32. float32 carries about 7 significant
decimal digits in total while `getList` promises 7 decimal *places*, so a
coordinate with more than one digit before the point cannot survive the round
trip, and the dtype would become format-adjacent.

Attribute strings are **not interned**. Object names are already shared per
section today, because `Section.__init__` passes one dict key object to every
`Trace.fromList` in a contour, so interning names would buy approximately
nothing over the status quo; and the distinct-name and distinct-tag counts that
would justify a table for tags do not exist yet. `name` and `tags` therefore stay
Python objects in object-dtype columns.

Two attribute columns are numeric anyway, and one of them needs a fallback:

* `color` is a `uint8` `(rows, 3)` array.
* `fill_mode` is a `uint8` code over `FILL_MODE_CODES`, the nine pairs
  `convertMode` produces. A `.jser` can carry a pair outside that vocabulary,
  because `Trace.fromList` assigns `fill_mode` verbatim from the file, so an
  unknown pair goes into `_fill_mode_overflow` under its row number instead of
  raising a `KeyError` on open. Nothing is lost and nothing throws.

THE GENERATION COUNTER IS AN ADDITION, NOT A REPLACEMENT
--------------------------------------------------------
`Section.added_traces` / `removed_traces` / `modified_contours` have five
distinct consumer roles and four of them need **which names changed**, not
whether anything changed: the table manager's `updateObjects`, `series_data`,
dirty/save detection, `gui/table/section.py`'s `updateObjects` call, and
`SectionStates.addState`, which uses `section.getAllModifiedNames()` as the
**scope of the undo snapshot**. A scalar cannot answer any of those. So this
store carries the counter *beside* equivalent name tracking, and
`getAllModifiedNames()` is reproduced with the same contract.

The counter's lifetime is the part that is easy to get wrong, and getting it
wrong reproduces an existing bug in a new costume. The current stale-render
family exists because two mechanisms have different lifetimes: the tracking
lists, which the table manager empties through `clearTracking()`, and the render
cache, which does not know that happened. So:

**`clearTracking()` empties the name sets and does NOT touch the counter.** The
counter is monotonic and is never reset by anything. A cache stores the value it
was built at and compares.

A transform change bumps the counter, through `noteTransformChange()`. This is
not optional: an alignment change rewrites every trace's rendered geometry while
every section file stays byte-identical, and a generation counter that did not
move on it would reproduce a measured bug class in a new place.

MUTATION ENTRY POINTS
---------------------
Enumerated here so that an operation log can be attached at these points later
without a second call-site sweep. There are six, and they are the only methods
that bump the generation:

    appendRow(...)              a trace enters the section
    removeRow(row)              a trace leaves it
    setCoordinates(row, points) its geometry is replaced
    setAttribute(row, ...)      one of its scalar attributes is replaced
    setTags(row, tags)          its tag set is replaced
    noteTransformChange()       the section's alignment moved

IDENTITY, AND THE TWO CARRY RULES THAT ARE NOT IMPLEMENTED
----------------------------------------------------------
Each row has an `id` column, **in memory only**. The issuer is injected rather
than imported, so this module has no opinion about how an id is minted:
`datatypes/trace_id.py` is the intended production issuer (a frozen `tid-v1`
derivation for traces that already exist, opaque 64-bit random ids from a
series-global index for traces created afterward), and a test can pass a
deterministic stub instead.

The carry rules are implemented as two store operations, deliberately named for
the question they answer rather than for the object-model method they correspond
to, because no object-model method is being changed:

* `copyRow(row)` **keeps** the id. This is the `editTraceAttributes` shape:
  remove, copy, mutate an attribute, add. It is how an attribute edit and a
  rename are implemented, and the result is the same trace.
* `duplicateRow(row)` **issues** a new id. This is the duplicate-object and
  copy-traces-to-sections shape: a new annotation that happens to start as a
  copy of an old one.

`copy()` keeping and `duplicate()` issuing is the asymmetry that matters: a
missed duplication site under this arrangement produces a **collision**, which
an issuer's index can refuse and report, while the alternative (drop on copy,
re-attach explicitly) makes a missed site produce a trace with **no** id, which a
merge cannot place and nothing detects.

**Two rows of the carry table are not implemented, on purpose.** Split-object
traces, where one drawn geometry is redistributed under new `_{n}` names, and
palette traces, which are templates rather than annotations and may want no id at
all, are semantics rather than mechanics. They are held for the maintainer, and
`copyRow` / `duplicateRow` do not cover them: a caller reaching for either case
finds nothing here rather than an invented answer.
"""

import numpy as np

from .contour import Contour
from .trace import Trace, normalizeObjectName


## The nine `fill_mode` pairs `convertMode` produces, frozen as a code table so
## the column can be a `uint8`. A pair outside this table is not an error: see
## `_fill_mode_overflow` and the module docstring.
FILL_MODE_STYLES = ("none", "solid", "transparent")
FILL_MODE_CONDITIONS = ("none", "selected", "unselected")
FILL_MODE_CODES = {
    (style, condition): i * len(FILL_MODE_CONDITIONS) + j
    for i, style in enumerate(FILL_MODE_STYLES)
    for j, condition in enumerate(FILL_MODE_CONDITIONS)
}
FILL_MODE_BY_CODE = {code: pair for pair, code in FILL_MODE_CODES.items()}

## The code a row carries when its `fill_mode` is not in the table above. The
## pair itself is kept in `_fill_mode_overflow`.
FILL_MODE_OVERFLOW = 255

## The scalar attributes a row holds, in the order `Trace.getList` writes them.
## `locked` is deliberately absent: it is not a `Trace` attribute at all but a
## per-object-name series attribute read as `series.getAttr(name, "locked")`, so a
## column here would be a denormalized copy of series state with no source of
## truth. `negative` is deliberately present: it is a real per-trace attribute
## and is serialized, so a column set without it could not round-trip a file.
BOOL_ATTRIBUTES = ("closed", "negative", "hidden")


class SegmentedCoordinates():
    """One `(n, 2)` float64 array per row.

    Insert and delete are O(1) and a row's coordinates are its own, so nothing
    aliases and no caller can write into another row's memory. This is the
    default backing.
    """

    def __init__(self):
        self._arrays = []

    def __len__(self):
        return len(self._arrays)

    def append(self, points) -> int:
        """Store a new row's coordinates and return its row number."""
        self._arrays.append(_asCoordinateArray(points))
        return len(self._arrays) - 1

    def get(self, row: int) -> np.ndarray:
        """The row's `(n, 2)` float64 array. A view, not a copy."""
        array = self._arrays[row]
        if array is None:
            raise IndexError(f"row {row} has been removed")
        return array

    def set(self, row: int, points):
        """Replace the row's coordinates, at any length."""
        if self._arrays[row] is None:
            raise IndexError(f"row {row} has been removed")
        self._arrays[row] = _asCoordinateArray(points)

    def release(self, row: int):
        """Drop the row's coordinates. The row number is not reused."""
        self._arrays[row] = None

    @property
    def totalPoints(self) -> int:
        return sum(len(a) for a in self._arrays if a is not None)

    def freeze(self):
        """Nothing to release: each row's array is allocated at its exact size."""
        return


class PackedCoordinates():
    """One `(N, 2)` float64 array per section, appended to and never inserted.

    A row is an extent into the shared array. A row whose coordinates are
    replaced at a different length gets a fresh extent at the end and its old one
    is tombstoned, so every write is an append and `addTrace` never shifts
    anything. `deadPoints` is the slack a compaction pass would reclaim; there is
    no compaction pass, because compaction reorders rows and row order is
    load-bearing.
    """

    ## Points the array grows by when it is full. Growth is amortized doubling
    ## with this as a floor.
    INITIAL_CAPACITY = 256

    def __init__(self):
        self._array = np.empty((self.INITIAL_CAPACITY, 2), dtype=np.float64)
        self._used = 0
        self._extents = []   # row -> (start, length), or None once released

    def __len__(self):
        return len(self._extents)

    def _reserve(self, n: int) -> int:
        if self._used + n > len(self._array):
            capacity = max(len(self._array) * 2, self._used + n)
            grown = np.empty((capacity, 2), dtype=np.float64)
            grown[:self._used] = self._array[:self._used]
            self._array = grown
        start = self._used
        self._used += n
        return start

    def append(self, points) -> int:
        array = _asCoordinateArray(points)
        start = self._reserve(len(array))
        self._array[start:start + len(array)] = array
        self._extents.append((start, len(array)))
        return len(self._extents) - 1

    def get(self, row: int) -> np.ndarray:
        extent = self._extents[row]
        if extent is None:
            raise IndexError(f"row {row} has been removed")
        start, length = extent
        return self._array[start:start + length]

    def set(self, row: int, points):
        extent = self._extents[row]
        if extent is None:
            raise IndexError(f"row {row} has been removed")
        array = _asCoordinateArray(points)
        start, length = extent
        if len(array) == length:
            self._array[start:start + length] = array
            return
        # A different length: append a fresh extent rather than shift the array.
        # The old extent is dead space until something compacts, which nothing
        # here does.
        new_start = self._reserve(len(array))
        self._array[new_start:new_start + len(array)] = array
        self._extents[row] = (new_start, len(array))

    def release(self, row: int):
        self._extents[row] = None

    @property
    def totalPoints(self) -> int:
        return sum(length for e in self._extents if e for length in (e[1],))

    @property
    def deadRows(self) -> int:
        """Rows whose extent has been released."""
        return sum(1 for e in self._extents if e is None)

    @property
    def deadPoints(self) -> int:
        """Points a compaction pass would reclaim: released rows plus stranded
        extents left by a length-changing write."""
        return self._used - self.totalPoints

    def freeze(self):
        """Release the capacity beyond `_used`. See `SectionColumns.freeze`.

        Trims the tail only. Dead extents left inside `_used` by a length-changing
        write are NOT reclaimed, because reclaiming them means moving rows and row
        order is load-bearing. A store built by appends alone, which is what a
        snapshot is, has none.
        """
        if self._used != len(self._array):
            self._array = self._array[:self._used].copy()


def _asCoordinateArray(points) -> np.ndarray:
    """Coerce a point sequence to a fresh `(n, 2)` float64 array.

    float64 and not `float`, explicitly, so the dtype is a decision in the source
    rather than a platform default. An empty sequence gives a `(0, 2)` array
    rather than a `(0,)` one, so every row has the same shape contract.

    **Always a copy**, including when the input is already a float64 array. That
    costs a copy on every write and removes an entire failure class: `np.asarray`
    of an array returns the same memory, so a row copied from another row would
    share its coordinates, and a later in-place write to one would silently
    change the other. Silent aliasing between two owners of the same points is a
    data-loss shape, not a performance shape, so the copy is not negotiable here.
    """
    array = np.array(points, dtype=np.float64)
    if array.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(
            f"coordinates must be a sequence of (x, y) pairs, got shape "
            f"{array.shape}"
        )
    return array


class _NumericColumn():
    """One attribute column, grown by amortized doubling.

    `np.append` and `np.vstack` reallocate and copy the whole column on every
    call, so building a store row by row through either is O(rows**2) in the
    section's trace count. That is invisible on a small fixture and quadratic on
    a real autoseg section, which is the shape of defect a parity test on a
    200-trace series would never show. Capacity doubles instead.
    """

    INITIAL_CAPACITY = 64

    def __init__(self, dtype, width=None):
        self._width = width
        shape = (self.INITIAL_CAPACITY,) if width is None else (self.INITIAL_CAPACITY, width)
        self._array = np.empty(shape, dtype=dtype)
        self._used = 0

    def __len__(self):
        return self._used

    def append(self, value):
        if self._used == len(self._array):
            shape = list(self._array.shape)
            shape[0] *= 2
            grown = np.empty(tuple(shape), dtype=self._array.dtype)
            grown[:self._used] = self._array[:self._used]
            self._array = grown
        self._array[self._used] = value
        self._used += 1

    def __getitem__(self, row):
        if not 0 <= row < self._used:
            raise IndexError(f"row {row} is outside the column")
        return self._array[row]

    def __setitem__(self, row, value):
        if not 0 <= row < self._used:
            raise IndexError(f"row {row} is outside the column")
        self._array[row] = value

    @property
    def values(self) -> np.ndarray:
        """The live prefix of the column. A view, so the capacity slack behind
        `_used` is never visible to a caller."""
        return self._array[:self._used]

    def freeze(self):
        """Release the growth slack. See `SectionColumns.freeze`."""
        if self._used != len(self._array):
            self._array = self._array[:self._used].copy()


class SectionColumns():
    """One section's traces as append-only rows with a per-contour index.

    Read the module docstring first: the layout choice this class does and does
    not make, what parity means, and why the generation counter sits beside the
    name tracking rather than replacing it.
    """

    def __init__(self, section_number: int, coordinates=None, id_issuer=None):
        """Create an empty store for one section.

            Params:
                section_number (int): the section these rows sit on
                coordinates: the coordinate backing. Defaults to
                    `SegmentedCoordinates`; `PackedCoordinates` satisfies the
                    same interface and the parity suite runs against both.
                id_issuer: anything with an `issue()` returning a fresh id.
                    `datatypes/trace_id.TraceIDIssuer` is the intended
                    production issuer. `None` means rows carry no id, which is
                    the state of every section in the shipped application.
        """
        self.section_number = section_number
        self._coordinates = coordinates if coordinates is not None else SegmentedCoordinates()
        self._id_issuer = id_issuer

        self._names = []
        self._colors = _NumericColumn(np.uint8, width=3)
        self._bools = {name: _NumericColumn(bool) for name in BOOL_ATTRIBUTES}
        self._fill_modes = _NumericColumn(np.uint8)
        self._fill_mode_overflow = {}
        self._tags = []
        self._ids = []
        self._live = []
        self._live_count = 0

        ## The per-contour index: name -> [row, ...] in within-contour order.
        self._index = {}

        self._generation = 0
        self.clearTracking()

    # --- construction from the object model ---------------------------------

    @classmethod
    def fromSection(cls, section, coordinates=None, id_issuer=None):
        """Build a store from a `Section`, in the section's own contour order.

        Duck-typed on `.n` and `.contours` rather than importing `Section`, which
        keeps this module out of that import cycle and lets a test hand over a
        stand-in. Contours are walked in `sorted(..., key=str)`, the canonical
        order `Section.getDict` writes, and each contour's traces in their own
        list order, which is semantically significant.

            Params:
                section: anything with `.n` and `.contours` (name -> iterable of
                    traces)
            Returns:
                (SectionColumns): a store holding every trace of the section
        """
        store = cls(section.n, coordinates=coordinates, id_issuer=id_issuer)
        for name in sorted(section.contours, key=str):
            for trace in section.contours[name]:
                store.appendRow(
                    name=trace.name,
                    points=trace.points,
                    color=trace.color,
                    closed=trace.closed,
                    negative=trace.negative,
                    hidden=trace.hidden,
                    fill_mode=trace.fill_mode,
                    tags=trace.tags,
                )
        store.clearTracking()
        return store

    # --- reading ------------------------------------------------------------

    def __len__(self):
        """The number of live rows."""
        return self._live_count

    @property
    def generation(self) -> int:
        """Monotonic, bumped by every mutation, never reset by anything."""
        return self._generation

    @property
    def rowCount(self) -> int:
        """Rows ever appended, live or tombstoned. Row numbers are never reused,
        so this is also the next row number."""
        return len(self._live)

    def isLive(self, row: int) -> bool:
        return bool(self._live[row])

    def contourNames(self) -> list:
        """Live contour names, in canonical sorted order."""
        return sorted(
            (name for name, rows in self._index.items() if rows), key=str
        )

    def rowsForContour(self, name: str) -> list:
        """The contour's row numbers, in within-contour order."""
        return list(self._index.get(normalizeObjectName(name), ()))

    def getName(self, row: int) -> str:
        return self._names[row]

    def getCoordinates(self, row: int) -> np.ndarray:
        """The row's `(n, 2)` float64 array of unrounded in-memory coordinates."""
        self._requireLive(row)
        return self._coordinates.get(row)

    def getPoints(self, row: int) -> list:
        """The row's coordinates as a list of `(x, y)` float tuples.

        The shape `Trace.points` has, so a caller comparing against the object
        model does not have to know the store holds an array.
        """
        return [(float(x), float(y)) for x, y in self.getCoordinates(row)]

    def getColor(self, row: int) -> list:
        """The row's color as a 3-element list of `int`.

        A list of `int` and not a tuple of `numpy.uint8`, deliberately: a
        file-loaded trace's `color` is a `list` of `int` (`Trace.fromList`
        assigns it verbatim from parsed JSON), and a `numpy` scalar is not
        JSON-serializable, so a tuple of `uint8` reaching `getList` would break a
        save.
        """
        self._requireLive(row)
        return [int(v) for v in self._colors[row]]

    def getFlag(self, row: int, attribute: str) -> bool:
        """One of `closed`, `negative`, `hidden`, as a Python `bool`.

        A Python `bool` and not a `numpy.bool_`: `numpy.bool_` compares equal but
        is not JSON-serializable, so one reaching `Trace.getList` would fail at
        `json.dump` rather than at the assignment.
        """
        self._requireLive(row)
        return bool(self._bools[attribute][row])

    def getFillMode(self, row: int) -> list:
        """The row's `fill_mode` as a 2-element list of `str`.

        A list, matching what a file-loaded trace carries: `Section.updateJSON`
        writes `["none", "none"]` and `Trace.fromList` assigns it verbatim.
        """
        self._requireLive(row)
        code = int(self._fill_modes[row])
        if code == FILL_MODE_OVERFLOW:
            return list(self._fill_mode_overflow[row])
        return list(FILL_MODE_BY_CODE[code])

    def getTags(self, row: int) -> set:
        """A fresh `set` of the row's tags.

        Fresh rather than the stored object, so nothing can mutate the column
        through a value it was handed. The column holds a `frozenset`.
        """
        self._requireLive(row)
        return set(self._tags[row])

    def getID(self, row: int):
        """The row's id, or `None` if the store was built without an issuer."""
        return self._ids[row]

    def freeze(self):
        """Release every column's growth slack. For a store that will not grow.

        The columns grow by amortized doubling, so a store holding two rows can
        hold buffers for sixty-four, and the coordinate backing's initial capacity
        is larger still. That slack is the right trade while a store is being
        built and the wrong one the moment a store is a **snapshot**: a snapshot is
        immutable after construction, and an undo state that over-allocated its
        columns five times over would be measured as costing five times what it
        costs.

        Found while adapting the undo-growth harness, where the slack would have
        dominated the figure the measurement exists to produce. Not a mutation: no
        value changes, so the generation counter does not move. Appending after a
        `freeze()` is allowed and simply grows the columns again.
        """
        self._colors.freeze()
        for column in self._bools.values():
            column.freeze()
        self._fill_modes.freeze()
        self._coordinates.freeze()

    # --- the columns themselves ----------------------------------------------
    #
    # Exposed because numeric columns are the point of the layout: a whole-section
    # pass over one attribute is what a per-trace attribute read cannot be. Views
    # over the live prefix, so the growth slack behind them is never visible.

    @property
    def colorColumn(self) -> np.ndarray:
        """The `(rows, 3)` `uint8` color column, tombstoned rows included."""
        return self._colors.values

    def flagColumn(self, attribute: str) -> np.ndarray:
        """One of the `bool` columns: `closed`, `negative` or `hidden`."""
        return self._bools[attribute].values

    @property
    def fillModeColumn(self) -> np.ndarray:
        """The `uint8` `fill_mode` code column. `FILL_MODE_OVERFLOW` marks a row
        whose pair was outside the vocabulary and is held in the overflow map."""
        return self._fill_modes.values

    @property
    def coordinateBacking(self):
        """The coordinate backing, so a caller can ask which one it got."""
        return self._coordinates

    # --- materialization back into the object model --------------------------

    def materializeTrace(self, row: int) -> Trace:
        """Build a real `Trace` from a row.

        Not a view. Wave B builds no views: a view's identity is load-bearing in
        the render path (three membership `set()`s of `Trace` objects and a
        `trace not in contour` staleness guard, all running on CPython object
        identity because `Trace` defines neither `__eq__` nor `__hash__`), and
        deciding what identity a view has is a separate question from whether the
        columns hold the right bytes. This method exists so the columns can be
        checked against the object model, not so that anything can be replaced.
        """
        self._requireLive(row)
        trace = Trace(self._names[row], self.getColor(row), self.getFlag(row, "closed"))
        trace.negative = self.getFlag(row, "negative")
        trace.points = self.getPoints(row)
        trace.hidden = self.getFlag(row, "hidden")
        trace.fill_mode = self.getFillMode(row)
        trace.tags = self.getTags(row)
        return trace

    def materializeContours(self) -> dict:
        """Rebuild `{name: Contour}`, the shape `Section.contours` has.

        Built through `Contour(name, traces)`, the checking constructor, so a
        name that did not survive the round trip fails here rather than later.
        """
        contours = {}
        for name in self.contourNames():
            traces = [self.materializeTrace(row) for row in self._index[name]]
            contours[name] = Contour(name, traces)
        return contours

    # --- the six mutation entry points --------------------------------------

    def appendRow(self, name: str, points, color, closed=True, negative=False,
                  hidden=False, fill_mode=("none", "none"), tags=(),
                  trace_id=None) -> int:
        """Add a trace's row. An append, never an insert.

            Params:
                name (str): the trace's name, which is also its contour's key.
                    Written through `normalizeObjectName`, the same function
                    `Trace.name`'s setter runs, so a name entering the store
                    cannot diverge from one entering a `Trace`.
                trace_id: an id to carry in. `None` asks the injected issuer for
                    one, and means no id when there is no issuer.
            Returns:
                (int): the new row number
        """
        name = normalizeObjectName(name)
        row = self._coordinates.append(points)
        assert row == len(self._names), (
            "the coordinate backing and the attribute columns have drifted out "
            f"of step: backing gave row {row}, columns hold {len(self._names)}"
        )
        self._names.append(name)
        self._colors.append(_asColorRow(color))
        for attribute, value in (("closed", closed), ("negative", negative),
                                 ("hidden", hidden)):
            self._bools[attribute].append(bool(value))
        self._fill_modes.append(self._encodeFillMode(row, fill_mode))
        self._tags.append(frozenset(tags))
        self._ids.append(self._resolveID(trace_id))
        self._live.append(True)
        self._live_count += 1

        self._index.setdefault(name, []).append(row)

        self._added_rows.append(row)
        self._bump()
        return row

    def removeRow(self, row: int):
        """Tombstone a row. Its row number retires with it and is not reused."""
        self._requireLive(row)
        name = self._names[row]
        self._index[name].remove(row)
        self._live[row] = False
        self._live_count -= 1
        self._coordinates.release(row)
        self._removed_rows.append(row)
        self._bump()

    def setCoordinates(self, row: int, points):
        """Replace a row's geometry, at any length."""
        self._requireLive(row)
        self._coordinates.set(row, points)
        self._modified_contours.add(self._names[row])
        self._bump()

    def setAttribute(self, row: int, attribute: str, value):
        """Replace one scalar attribute: `name`, `color`, `fill_mode`, or one of
        `closed` / `negative` / `hidden`.

        A rename moves the row between contour indices and keeps its position at
        the end of the destination, which is what `removeTrace` followed by
        `addTrace` does today.
        """
        self._requireLive(row)
        if attribute == "name":
            value = normalizeObjectName(value)
            old = self._names[row]
            if value != old:
                self._index[old].remove(row)
                self._index.setdefault(value, []).append(row)
                self._names[row] = value
                self._modified_contours.add(old)
                self._modified_contours.add(value)
            self._bump()
            return
        if attribute == "color":
            self._colors[row] = _asColorRow(value)
        elif attribute == "fill_mode":
            self._fill_modes[row] = self._encodeFillMode(row, value)
        elif attribute in BOOL_ATTRIBUTES:
            self._bools[attribute][row] = bool(value)
        else:
            raise KeyError(
                f"{attribute!r} is not a column. The columns are name, color, "
                f"fill_mode, tags and {', '.join(BOOL_ATTRIBUTES)}."
            )
        self._modified_contours.add(self._names[row])
        self._bump()

    def setTags(self, row: int, tags):
        """Replace a row's tag set."""
        self._requireLive(row)
        self._tags[row] = frozenset(tags)
        self._modified_contours.add(self._names[row])
        self._bump()

    def noteTransformChange(self):
        """Record that the section's alignment moved.

        Not optional and not cosmetic. An alignment change rewrites every
        trace's rendered geometry while every section file stays byte-identical,
        so a counter that did not move here would let a cache keyed on it serve
        stale geometry, which is a measured bug class rather than a hypothetical
        one. No row changes, so no name enters the modified set.
        """
        self._bump()

    # --- identity carry rules -----------------------------------------------

    def copyRow(self, row: int) -> int:
        """Append a copy of a row that **keeps** its id: the same trace, edited.

        This is the `Section.editTraceAttributes` shape, where an attribute edit
        or a rename is implemented as remove, copy, mutate, add. The result is
        the same annotation and must carry the same id.

        Split-object and palette traces are NOT this operation, and are not
        implemented anywhere in this module. See the module docstring.
        """
        return self._copy(row, trace_id=self._ids[row])

    def duplicateRow(self, row: int) -> int:
        """Append a copy of a row that **issues** a new id: a new trace.

        This is the duplicate-object and copy-traces-to-sections shape. A missed
        call site here produces an id collision, which the issuer's index refuses
        and reports; the alternative arrangement would produce a trace with no
        id, which nothing detects and a merge cannot place.
        """
        return self._copy(row, trace_id=None)

    def _copy(self, row: int, trace_id) -> int:
        self._requireLive(row)
        return self.appendRow(
            name=self._names[row],
            points=self.getCoordinates(row),
            color=self.getColor(row),
            closed=self.getFlag(row, "closed"),
            negative=self.getFlag(row, "negative"),
            hidden=self.getFlag(row, "hidden"),
            fill_mode=self.getFillMode(row),
            tags=self._tags[row],
            trace_id=trace_id,
        )

    # --- tracking, beside the counter ---------------------------------------

    @property
    def added_rows(self) -> list:
        return list(self._added_rows)

    @property
    def removed_rows(self) -> list:
        return list(self._removed_rows)

    @property
    def modified_contours(self) -> set:
        return set(self._modified_contours)

    def getAllModifiedNames(self) -> set:
        """The names of every trace added, removed or modified since the last
        `clearTracking()`.

        The same contract as `Section.getAllModifiedNames`, which four consumer
        roles need and a scalar counter cannot answer, including
        `SectionStates.addState`, which uses it as the scope of the undo
        snapshot.
        """
        names = {self._names[row] for row in self._added_rows}
        names |= {self._names[row] for row in self._removed_rows}
        names |= set(self._modified_contours)
        return names

    def clearTracking(self):
        """Empty the name tracking. **Does not touch the generation counter.**

        The counter's independence from this call is the point. The existing
        stale-render family is caused by exactly this asymmetry going unnoticed:
        the table manager empties the tracking lists and the render cache does
        not know it happened. A counter reset here would reproduce that bug in a
        new place.
        """
        self._added_rows = []
        self._removed_rows = []
        self._modified_contours = set()

    # --- internals -----------------------------------------------------------

    def _bump(self):
        self._generation += 1

    def _requireLive(self, row: int):
        if not self._live[row]:
            raise IndexError(f"row {row} has been removed")

    def _resolveID(self, trace_id):
        if trace_id is not None:
            return trace_id
        if self._id_issuer is None:
            return None
        return self._id_issuer.issue()

    def _encodeFillMode(self, row: int, fill_mode) -> int:
        pair = tuple(fill_mode)
        code = FILL_MODE_CODES.get(pair)
        if code is None:
            self._fill_mode_overflow[row] = pair
            return FILL_MODE_OVERFLOW
        self._fill_mode_overflow.pop(row, None)
        return code


def _asColorRow(color) -> np.ndarray:
    array = np.asarray(color, dtype=np.uint8)
    if array.shape != (3,):
        raise ValueError(f"a color is three 0-255 components, got {color!r}")
    return array
