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

**Coordinates live in one array per trace.** The backing is
`SegmentedCoordinates` -- one `(n, 2)` float64 array per row, insert and delete
O(1), a row's array is its own, and nothing aliases. It is the pole that
preserves today's complexity on every path, and it is now the decided one
rather than a default: the design's open question (one array per section
versus one per trace) was settled after the paired undo-snapshot measurement
found the per-section `PackedCoordinates` backing 0.32% dearer on the workload
it was hypothesized to win (its per-row header amortization needs several rows
per store, and ~90% of undo snapshots hold one), and after the A1 open-pass
split (geometry 68%, construction 15.4%) came in on the side the design doc
itself names for that shape. The losing backing was deleted rather than kept
as an option -- carrying it was unreleased scope (review-246 F06) -- and the
store stays layout-blind behind the same five-method backing interface
(`append` / `get` / `set` / `release` / `freeze`), so a future whole-section
layout, if a measurement ever earns one, arrives as a new backing rather than a
rewrite. The interface was six methods until `totalPoints` went with the class
that consumed it: `PackedCoordinates.deadPoints` was its only call site
anywhere in the tree, and applying the unreleased-scope principle to one and
not the other is the inconsistency review-248 F02 recorded.

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
without a second call-site sweep. There are seven, and they are the only methods
that bump the generation:

    appendRow(...)              a trace enters the section
    removeRow(row)              a trace leaves it
    setCoordinates(row, points) its geometry is replaced
    setAttribute(row, ...)      one of its scalar attributes is replaced
    setTags(row, tags)          its tag set is replaced
    reorderContour(name, rows)  one contour's rows are put in a new order
    noteTransformChange()       the section's alignment moved

The seventh is the newest and is the only one that changes **no row at all**.
It exists because the order it rearranges was already rearrangeable, and by an
accident rather than by a decision: `setAttribute(row, "name", ...)` appends the
row at the end of its destination contour, so renaming a row away to a scratch
name and back is a move-to-end primitive, and n-1 of those realize any
permutation with no row renumbered, no row tombstoned and no held `TraceView`
invalidated. What that round trip could not do is stay quiet: the scratch name
landed in `_modified_contours` and came back out of `getAllModifiedNames()`,
which is the scope of an undo snapshot and, since the dual write went always-on,
is read in production. `reorderContour` is the same capability expressed
directly, so the tracking sets see one real contour name and nothing else.

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

THE ONE VIEW IN THIS MODULE, AND WHAT IT DELIBERATELY IS NOT
------------------------------------------------------------
`TraceView` reads and writes one row through a `Trace`-shaped surface: the
eight fields `Trace.__init__` assigns, each getter a direct call into the row
readers above and each setter a direct call into one of the three per-row
mutation entry points listed under MUTATION ENTRY POINTS. It adds no entry
point of its own, so the counter, the modified-name tracking and the rename
reindex all happen exactly once, in the store, on the path they already took.

It is **not** §5(A)'s cached identity-stable shim. It has no identity map and
no invalidation, because whether the shim should cache is still open and a view
that quietly cached would answer it by accident. The write path does not change
that: a view still holds no value, so a write through one view is visible to
every other view of the row on the next read, with nothing to invalidate.

It lives here, beside the store, rather than in a module of its own so that it
carries no import of anything and stays inside the graph
`test_datatypes_import_graph_is_qt_free` proves Qt-free -- which a module
nothing imports would sit outside of, the gap `trace_id.py`'s export note
records. Nothing in the application references it; the parity suite is its
only caller.

**Two rows of the carry table are not implemented, on purpose.** Split-object
traces, where one drawn geometry is redistributed under new `_{n}` names, and
palette traces, which are templates rather than annotations and may want no id at
all, are semantics rather than mechanics. They are held for the maintainer, and
`copyRow` / `duplicateRow` do not cover them: a caller reaching for either case
finds nothing here rather than an invented answer.
"""

import operator

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
    decided backing; the module docstring records how it was decided and what
    interface a future alternative would have to satisfy.
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

    def freeze(self):
        """Nothing to release: each row's array is allocated at its exact size."""
        return


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

    Read the module docstring first: the layout decision and how it was made,
    what parity means, and why the generation counter sits beside the name
    tracking rather than replacing it.
    """

    ## The object-dtype columns and the index, declared here rather than as
    ## annotated assignments in `__init__`. The reason is convention, not speed:
    ## none of the six has per-instance default logic for a type to hang off, so
    ## declaring them together puts the shape of a row in one block instead of
    ## scattering it down the constructor.
    ##
    ## An earlier version of this comment said the inline form pays an
    ## annotation evaluation on every instantiation and put a percentage on it.
    ## That was wrong. PEP 526 evaluates a complex-target annotation only in
    ## module or class scope, so `self.x : T = v` inside `__init__` never
    ## evaluates `T`; the two forms measure the same `SectionColumns(...)` cost.
    ## See `Trace.fill_mode` in `trace.py` for the same note.
    ##
    ## `_fill_mode_overflow` is deliberately not `dict[int, tuple[str, str]]`:
    ## the reason it exists is that the pair came out of a `.jser` unvalidated,
    ## so naming its element type would claim a check nothing performs.
    ## `_ids` is `None` where the store has no issuer, which is every section in
    ## the shipped application today; `TraceIDIssuer.issue` returns `str`.
    _names : list[str]
    _fill_mode_overflow : dict[int, tuple]
    _tags : list[frozenset[str]]
    _ids : list[str | None]
    _live : list[bool]
    _index : dict[str, list[int]]

    def __init__(self, section_number: int, coordinates=None, id_issuer=None,
                 generation: int = 0):
        """Create an empty store for one section.

            Params:
                section_number (int): the section these rows sit on
                coordinates: the coordinate backing. Defaults to
                    `SegmentedCoordinates`, the decided backing; anything
                    satisfying the same five-method interface may be injected.
                id_issuer: anything with an `issue()` returning a fresh id.
                    `datatypes/trace_id.TraceIDIssuer` is the intended
                    production issuer. `None` means rows carry no id, which is
                    the state of every section in the shipped application.
                generation (int): the count this store's monotonic generation
                    resumes from. Defaults to 0, a store with no history. The
                    one caller that passes anything else is
                    `Section.resyncColumnarStore`, which throws a store away and
                    builds a replacement -- an undo, a redo, an import, an
                    object deletion. The counter is documented above as
                    monotonic and never reset by anything, and a replacement
                    restarting at 0 would hand every cache a generation below
                    the one it already holds, so every cache would conclude it
                    was current: the stale-render bug class the counter exists
                    to prevent, arriving through the repair rather than the
                    fault. Under the test-only gate nothing rebuilt a store
                    outside a test and nothing read the counter at all, so this
                    could not bite; always-on plus a consumer makes it live.
        """
        self.section_number = section_number
        self._coordinates = coordinates if coordinates is not None else SegmentedCoordinates()
        self._id_issuer = id_issuer

        self._names = []
        self._colors = _NumericColumn(np.uint8, width=3)
        self._bools = {name: _NumericColumn(bool) for name in BOOL_ATTRIBUTES}
        self._fill_modes = _NumericColumn(np.uint8)
        ## row -> the pair the file carried, for a pair outside FILL_MODE_CODES.
        self._fill_mode_overflow = {}
        self._tags = []
        self._ids = []
        self._live = []
        self._live_count = 0

        ## The per-contour index: name -> [row, ...] in within-contour order.
        self._index = {}

        self._generation = generation
        self.clearTracking()

    # --- construction from the object model ---------------------------------

    @classmethod
    def fromSection(cls, section, coordinates=None, id_issuer=None,
                    generation: int = 0):
        """Build a store from a `Section`, in the section's own contour order.

        Duck-typed on `.n` and `.contours` rather than importing `Section`, which
        keeps this module out of that import cycle and lets a test hand over a
        stand-in. Contours are walked in `sorted(..., key=str)`, the canonical
        order `Section.getDict` writes, and each contour's traces in their own
        list order, which is semantically significant.

            Params:
                section: anything with `.n` and `.contours` (name -> iterable of
                    traces)
                generation (int): forwarded to `__init__`; see the note there on
                    why a rebuilt store must not restart the counter at 0
            Returns:
                (SectionColumns): a store holding every trace of the section
        """
        store = cls(section.n, coordinates=coordinates, id_issuer=id_issuer,
                    generation=generation)
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
        hold buffers for sixty-four. That slack is the right trade while a
        store is being built and the wrong one the moment a store is a
        **snapshot**: a snapshot is immutable after construction, and an undo
        state that over-allocated its columns five times over would be
        measured as costing five times what it costs.

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

    def reorderContour(self, name: str, rows):
        """Put one contour's rows in a new within-contour order.

        The clean reorder entry point (D9). Nothing is renumbered, nothing is
        tombstoned, no coordinate array moves and no held `TraceView` is
        touched: this rebinds one list of row numbers in the index, which is
        the only place within-contour order is held.

            Params:
                name (str): the contour to reorder. Normalized on the way in,
                    through the same `normalizeObjectName` `appendRow` and
                    `rowsForContour` run, so a caller cannot reorder `"a b"`
                    while the rows are indexed under `"a_b"`.
                rows: the contour's row numbers in the order it should now hold
                    them. Must be a permutation of exactly the rows it holds
                    now -- see below.
            Raises:
                ValueError: `rows` is not a permutation of the contour's
                    current rows, or holds an element that is not an integer
                    row number.

        WHY A WHOLE-ORDER ARGUMENT RATHER THAN A MOVE OR A SWAP
        -------------------------------------------------------
        The shape follows the consumer that asks for this. `Contour.importTraces`
        ends with `self.traces = traces`, where `traces` is built as [matched
        duplicates, positionally] + rem_s + rem_o -- a whole new order, computed
        in one pass and rebound in one statement. A `moveRowWithinContour(name,
        row, position)` would make that caller drive a loop of moves to
        reconstruct an order it already had in its hand, and each move would
        bump the generation, so the port's cost would scale with the
        permutation's distance from the identity rather than with the contour.
        The whole-order form is also the one the index can satisfy in a single
        rebind, because the index *is* a list of row numbers per contour: the
        argument and the representation are the same shape. A move or a swap
        remains one line on top of this for a caller that wants one, and neither
        is built here, because building the convenience before its caller exists
        is the unreleased scope this module has removed twice already.

        THE PERMUTATION CHECK IS NOT DEFENSIVE PADDING
        ----------------------------------------------
        Four ways to get it wrong, and each corrupts silently rather than
        loudly. A `rows` missing one of the contour's rows drops that row out of
        the index while leaving it **live** and named for this contour, so it
        vanishes from `contourNames()`'s contour and from every view, while
        `len(store)` still counts it and `save()` still holds it. A `rows`
        holding a row of a *different* contour puts that row in this contour's
        index without changing `_names[row]`, so the row would answer one name
        and be indexed under another -- and `removeRow`, which looks the row's
        name up to find the index to take it out of, would then fail to find it.
        A `rows` with a duplicate makes one row appear twice in a contour that
        holds it once. Those three are caught by comparing sorted row lists,
        which also settles liveness for free: `removeRow` takes a row out of the
        index as it tombstones it, so a row that is in the index is live, and a
        permutation of the index is a list of live rows.

        The fourth is the one a sorted comparison cannot catch, because it is a
        comparison of *values*: `2.0 == 2`, so a `rows` holding `float` or
        `numpy.float64` elements is a valid permutation by value and is stored
        verbatim. Nothing complains -- the contour is marked modified and the
        store reads as healthy -- until `materializeContours()` subscripts a
        list with a float and raises a bare `TypeError` naming neither this
        contour nor this call. numpy is a hard dependency here and an order
        computed through it can carry float dtype, so this is a reachable input
        rather than a contrived one. Each element is therefore coerced
        through `operator.index`, the integer-index protocol itself, which is
        the discriminator that gets this exactly right: `isinstance(row, int)`
        would reject `numpy.int64`, which every other row-number path in this
        store accepts and which must keep working.

        WHAT THE TRACKING DOES, AND WHY IT IS ONE NAME AND NOT NONE
        -----------------------------------------------------------
        A reorder marks the contour modified, and marks nothing else. It is
        tempting to argue that it should mark nothing at all, since no trace's
        attributes and no trace's geometry change, and every derived per-trace
        quantity is exactly what it was. That argument is wrong on the two
        consumers that matter. Within-contour order is **serialized**: a
        contour's traces are written in list order, so a reordered contour is a
        different section file and dirty/save detection has to see it. And
        `SectionStates.addState` takes `getAllModifiedNames()` as the **scope of
        the undo snapshot**, so a reorder outside that scope would be a change
        the user could not undo.

        The no-op case follows `setAttribute`'s own precedent rather than
        inventing a rule: a rename to the name a row already has bumps the
        generation and adds nothing to the tracking sets. So does a reorder to
        the order the contour already holds. The bump is unconditional because a
        caller reached a mutation entry point and a generation is cheap; the
        tracking is conditional because a name in the undo scope is not.
        """
        name = normalizeObjectName(name)
        current = self._index.get(name, [])
        ## Every element through the integer-index protocol, not a value or a
        ## type check. `operator.index` is the same discriminator a list
        ## subscript runs, so it accepts exactly what the index can hold --
        ## `int`, `bool` and `numpy.int64`/`numpy.uint8` -- and rejects `float`
        ## and `numpy.float64`, which a value comparison cannot do because
        ## `2.0 == 2`. It also normalizes: what lands in `_index` is an exact
        ## `int` whatever integral type the caller computed its order in.
        ordered = []
        for row in rows:
            try:
                ordered.append(operator.index(row))
            except TypeError as error:
                raise ValueError(
                    f"reorderContour needs integer row numbers for contour "
                    f"{name!r}: {row!r} is a {type(row).__name__}, which cannot "
                    f"index a contour's row list"
                ) from error
        if sorted(ordered) != sorted(current):
            raise ValueError(
                f"reorderContour needs a permutation of contour {name!r}'s own "
                f"rows: it holds {list(current)} and was given {ordered}"
            )
        ## A copy, not the caller's list: an index aliased to a list the caller
        ## still holds could be reordered again later without passing through
        ## this method at all, which is the entry point's whole point.
        if ordered != current:
            self._index[name] = ordered
            self._modified_contours.add(name)
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


class TraceView():
    """One row of a `SectionColumns`, read and written through a `Trace`-shaped
    surface.

    Uncached, and with no consumers. Each of the eight properties below is a
    direct call into the store's existing row readers on the way out and into
    one of its existing mutation entry points on the way in; nothing is
    remembered between calls. A `TraceView` is therefore free to construct,
    free to discard, and free to construct again for the same row.

    THE EIGHT FIELDS, AND WHY EXACTLY EIGHT
    ---------------------------------------
    `Trace.__init__` assigns eight attributes -- `name` (through the property
    that runs `normalizeObjectName`), `color`, `closed`, `negative`, `points`,
    `hidden`, `tags`, `fill_mode` -- and `SectionColumns` carries a column for
    each. Those eight are the whole surface here.

    `Trace`'s geometry methods (`getBounds`, `getMidpoint`, `getCentroid`,
    `getRadius`, `getFeret`, ...) are deliberately absent. They are a separate
    row of the rewiring plan's pattern table -- a batched whole-section pass
    over the coordinate column, which is the thing the layout exists for -- and
    reimplementing them one trace at a time here would prejudge that work by
    shipping the per-trace shape it is meant to replace.

    NO CACHE, AND THAT IS THE POINT RATHER THAN AN OMISSION
    ------------------------------------------------------
    The design's §5(A) shim is a *cached, identity-stable* view, and its own
    cost note ("exactly the object-per-trace cost the phase is removing") is
    still open. Nothing here presupposes an answer: this class has no identity
    map, no weak-value table and no generation-counter invalidation, because it
    holds no state that could go stale. Two views of one row are two objects
    that compare unequal under `is`. `ContourView.index` and `__contains__` ask
    a different question of them -- `row`, which is equal -- and that is exactly
    why they could be built without settling the caching one: a row number is
    stable whether or not any object is. Whatever the caching question is
    decided to be, it is decided against a view that already provably reads and
    writes the right bytes.

    The write path is what makes that absence worth restating rather than
    assuming. A *cached* view would have to answer "who invalidates the other
    views of this row?" the moment one of them was written through. This one
    does not have the question: a write lands in the column, and every other
    view of that row reads the column on its next access. Write-invalidation is
    therefore not deferred here, it is absent, in the same way and for the same
    reason read-invalidation is.

    THE WRITE PATH, AND WHY IT ADDS NO ENTRY POINT
    ----------------------------------------------
    Each of the eight setters is one call into a mutation entry point the store
    already had -- `setAttribute` for the six scalars, `setTags` for `tags`,
    `setCoordinates` for `points` -- and does nothing else. No validation, no
    coercion, no counter arithmetic, no tracking. That is the whole design:

      * the generation counter bumps exactly once per write, in the store,
        because the store is what bumps it;
      * `_modified_contours` records the write, because the store records it;
      * a rename reindexes the row between contours, because `setAttribute`
        reindexes it;
      * a write to a tombstoned row raises `IndexError`, because
        `_requireLive` raises it.

    A setter that did any of those itself would be a second implementation of a
    rule the store owns, and the two would drift. The same argument the liveness
    note below makes, applied to the write direction.

    Assignment is still the only way in. `__slots__` covers every name the eight
    properties do not, so `view.colour = ...` raises rather than landing as an
    instance attribute that would shadow the column and read back convincingly,
    and `row` stays read-only because a view that could be repointed at another
    row is a different object, not a written one.

    NAME VALIDATION IS THE STORE'S TOO, AND THE DIVERGENCE IS DELIBERATE
    -------------------------------------------------------------------
    `Trace.name`'s setter does two things: `assert (value is None or
    type(value) is str)`, then `normalizeObjectName(value)`. `setAttribute`
    does the second and not the first, so `view.name = ...` inherits exactly
    that. Measured, both sides:

        value              Trace.name =        view.name =
        " a,b "            "a_b"               "a_b"          <- agree
        None               None                AttributeError
        5                  AssertionError      AttributeError
        str subclass       AssertionError      "a_b"

    The row that matters agrees. Normalization is the half with a correctness
    consequence -- a comma in a name shifts every field of the log entry that
    carries it and the entry stops parsing -- and the store runs it, in
    `setAttribute` and in `appendRow` alike, through the same function
    `Trace.name` calls.

    The three disagreements are all in the `assert`, and it is not replicated
    here, for three reasons. It is a debug-time type guard that `python -O`
    strips, so a view that copied it would match `Trace` in some runs and not
    others -- a *conditionally* divergent answer, which is worse than a
    consistently delegated one. `None` is the only value `Trace` accepts and
    this refuses, and the refusal is not the view's to lift: `_names` is a list
    of `str` that `_index` keys on and `contourNames()` sorts, so the store has
    no representation for a nameless row, and an assert here permitting `None`
    would hand it to the same `AttributeError` one frame later. And the store
    being the sole authority on what a name may be is the property that keeps a
    name written through the store from diverging from one written through a
    `Trace`, which is what the whole normalization arrangement exists for.

    Pinned as a table in the parity suite, so it reads as a decision to revisit
    when a consumer needs `Trace`'s exact type-error behavior, not as an
    oversight.

    LIVENESS IS THE STORE'S, NOT THIS CLASS'S
    -----------------------------------------
    A view over a tombstoned row behaves exactly as the store's own readers do,
    which is not uniformly: `getName` answers for a dead row while the other
    seven raise `IndexError` through `_requireLive`. That asymmetry is
    `SectionColumns`', it is pinned by a test rather than papered over here, and
    a view that added a liveness check of its own would be a second, divergent
    answer to a question the store already answers.
    """

    ## Two slots, so a name the class has no property for cannot land as an
    ## instance attribute on a class whose whole contract is that it does not
    ## hold values. This matters MORE now that the eight fields accept writes,
    ## not less: `view.colour = ...` under a plain class would silently create
    ## an attribute and then read back convincingly, which is precisely the
    ## failure a write-through view must not have.
    __slots__ = ("_columns", "_row")

    def __init__(self, columns: SectionColumns, row: int):
        """View one row of one store.

        Neither argument is validated and the row is not required to be live:
        construction touches no column, so a view is as cheap as a tuple, and
        the store raises on the read rather than the constructor -- the same
        moment it would for a direct `getColor(row)` call.

            Params:
                columns (SectionColumns): the store holding the row
                row (int): the row number, which never changes and is never
                    reused once its row is removed
        """
        self._columns = columns
        self._row = row

    def __repr__(self) -> str:
        ## `getName` and not a live-row read: a repr that raised on a removed
        ## row would break a debugger session at the moment it was most needed.
        return f"<TraceView row {self._row} of {self._columns.getName(self._row)!r}>"

    @property
    def row(self) -> int:
        """The row this view reads. Not a `Trace` field; here because a view
        with no way to say which row it is cannot be usefully debugged."""
        return self._row

    # --- the eight fields ----------------------------------------------------
    #
    # Getter: one row reader. Setter: one mutation entry point. Six of the eight
    # are `setAttribute` under their own name, which is why they read as
    # repetition -- the store's dispatch is the single place that knows which
    # column an attribute lives in, and a per-field mapping here would be a
    # second copy of it.

    @property
    def name(self) -> str:
        return self._columns.getName(self._row)

    @name.setter
    def name(self, value):
        ## Normalization and the rename reindex are `setAttribute`'s; see the
        ## class docstring for why the `type(value) is str` assertion is not.
        self._columns.setAttribute(self._row, "name", value)

    @property
    def color(self) -> list:
        return self._columns.getColor(self._row)

    @color.setter
    def color(self, value):
        self._columns.setAttribute(self._row, "color", value)

    @property
    def closed(self) -> bool:
        return self._columns.getFlag(self._row, "closed")

    @closed.setter
    def closed(self, value):
        self._columns.setAttribute(self._row, "closed", value)

    @property
    def negative(self) -> bool:
        return self._columns.getFlag(self._row, "negative")

    @negative.setter
    def negative(self, value):
        self._columns.setAttribute(self._row, "negative", value)

    @property
    def points(self) -> list:
        return self._columns.getPoints(self._row)

    @points.setter
    def points(self, value):
        ## The one field whose write is not `setAttribute`: coordinates are a
        ## ragged backing, not a column, and `setCoordinates` is the entry point
        ## that owns replacing a row's geometry at any length.
        self._columns.setCoordinates(self._row, value)

    @property
    def hidden(self) -> bool:
        return self._columns.getFlag(self._row, "hidden")

    @hidden.setter
    def hidden(self, value):
        self._columns.setAttribute(self._row, "hidden", value)

    @property
    def tags(self) -> set:
        return self._columns.getTags(self._row)

    @tags.setter
    def tags(self, value):
        ## `setTags` and not `setAttribute`: the tag column holds a `frozenset`
        ## per row and `setAttribute` refuses `"tags"` by design, so the store
        ## has one place that does the freezing.
        self._columns.setTags(self._row, value)

    @property
    def fill_mode(self) -> list:
        return self._columns.getFillMode(self._row)

    @fill_mode.setter
    def fill_mode(self, value):
        self._columns.setAttribute(self._row, "fill_mode", value)


class ContourView():
    """One contour of a `SectionColumns`, read through a `Contour`-shaped
    surface. The **read half** only.

    A `Contour` is a thin wrapper around `list[Trace]` plus the name every trace
    in it shares. The store already holds both halves -- `rowsForContour(name)`
    is that list, in within-contour order, and the name is the key it is
    indexed under -- so this class is the container protocol over the index and
    nothing more. Each element it hands back is a `TraceView` over the
    corresponding row, so a walk over a contour is a walk over rows and no
    `Trace` is built anywhere on the path.

    Uncached and with no consumers, for the same reasons `TraceView` is: every
    method below is a fresh `rowsForContour` call, nothing is remembered
    between calls, and nothing in the application references this class.

    WHAT IS HERE, AND THE ONE PROPERTY THAT IS LOAD-BEARING FOR A LATER SLICE
    ------------------------------------------------------------------------
    `Contour` defines `__init__`, `__iter__`, `__getitem__`, `__len__`,
    `__add__`, and the methods `append`, `remove`, `index`, `isEmpty`,
    `getTraces`, `copy`, `getBounds`, `getMidpoint`, `importTraces`. Of those,
    six are read-only *and* buildable out of what the store and `TraceView`
    already expose: `__iter__`, `__getitem__`, `__len__`, `isEmpty`,
    `getTraces` and `index` -- the last of which arrived in 7b' and brought
    `__contains__` with it, since they are one question. They are what this
    class carries, plus `name`.

    `__getitem__` on a slice returns a **bare `list`**, exactly as
    `Contour.__getitem__` does -- it is `self.traces[index]` there, and
    `list.__getitem__` with a slice returns a `list`, never a `Contour` and
    never a view. That is not an incidental detail. `Contour.importTraces`
    takes `rem_s_traces = self[i:]` and then calls `.copy()`, `.pop(found_i)`
    and `.remove(o_trace)` on it and finally `+`-concatenates it, all of which
    require a real, mutable, independent `list`. A slice that returned another
    view would break the slice that ports `importTraces` in a way no type
    annotation would catch, so the parity suite pins `type(...) is list`
    against a real `Contour` rather than asserting a shape.

    Every index and type error is the row list's own: `__getitem__` indexes
    `rowsForContour`'s list first and wraps afterwards, so `view[10]` raises
    `IndexError` and `view["x"]` raises `TypeError` with the same messages
    `Contour` gives, without this class deciding what an index may be.

    IDENTITY IS ANSWERED BY ROW, WHICH NEEDS NO CACHE AND NO `__eq__`
    -----------------------------------------------------------------
    `Contour` defines no `__contains__` and no `__eq__`, so `trace in contour`
    and `contour.index(trace)` both fall through to `Trace`'s inherited `==`,
    which is CPython object identity. Every route to an element of a view builds
    a *fresh* `TraceView`, so no object a caller holds is ever `is`-equal to an
    element -- measured over all six access routes on every contour of the real
    fixture series, zero hits. Slice 7a read that as "identity has no answer
    here" and left both methods absent.

    That reading was too strong, and this is the correction. There is a third
    route, and it is mechanical: **match on the row**. `TraceView.row` is
    already public, already read-only, and is already the row's identity. Two
    views of one row of one store name the same trace whether or not they are
    `is`-equal, and that is what `index` and `__contains__` answer here. The
    route caches nothing, so it is not design §5(A)'s identity-stable view, and
    it defines no `__eq__` over trace ids, so it is not §5(B), which
    `DECISIONS.md` records as **rejected**. It is observationally what a cached
    view would give -- a cache handing out one object per row makes `is` mean
    exactly "same row of the same store" -- but with no live-view map, which is
    the cost D1 exists to weigh. **So this route needs no D1 answer: there is no
    cache for D1 to be about.**

    The divergence from `Contour` that this does *not* erase, and that the
    parity suite pins so it stays visible: **a materialized `Trace` is still
    never a member.** `materializeTrace` builds an object outside the store,
    holding no row, so it has no answer here and gets `False` / `ValueError`
    rather than a guess. Three more non-members, all deliberate and all pinned:
    a `TraceView` over a *different store*, one over a *different contour* of
    this store, and one over a row this contour has since removed.

    The `ValueError` message is this class's own (`"... is not in contour
    'axon'"`) rather than `list.index`'s `"... is not in list"`. Message parity
    is unattainable here for a reason that is not a shortcut: the repr in it is
    a `TraceView`'s, never the `Trace`'s that `Contour` would have printed, so a
    string copied from `list` would be a more misleading answer, not a more
    faithful one. `__getitem__`'s `IndexError` and `TypeError` still come from
    the row list verbatim, because those *can* be identical.

    WHAT IS DELIBERATELY ABSENT, AND WHY EACH ONE IS ABSENT
    ------------------------------------------------------
    *Mutation*, so `append` and `remove` are not here: this is the read half by
    construction, and the store's own entry points (`appendRow`, `removeRow`)
    are what a write half would route to.

    `remove` needs its own paragraph now, because the row route above makes it
    *mechanically* buildable -- `removeRow(row)` once the row is known is three
    lines -- and it is still not built. Two reasons, and the second is the
    load-bearing one.

    First, read-only is this class's shipped contract, not an accident of how
    far the last slice got, and widening it is the write half's call.

    Second, and independent of that: it would not be the same operation.
    `Contour.remove(trace)` *detaches* an object that stays alive and is often
    re-added a line later. Its only production callers are `Section.removeTrace`
    and `Section.importTraces`, and six of `removeTrace`'s own eleven callers --
    `Section.editTraceAttributes`, `Section.editTraceRadius`,
    `Section.editTraceShape`, `Section.makeNegative`, `Section.translateTraces`
    and `Series.splitObject` -- go on using the removed object afterwards
    (remove / mutate / add it back, or remove / `.copy()` / add the copy, as
    `splitObject` does). The other five mean the removal: `Section.deleteTraces`
    and, in `series.py`, `deleteObjects`, `deleteAllTraces`,
    `deleteMalformedTraces` and `deleteDuplicateTraces`. The count is
    package-wide -- `section.py` and `series.py` both -- and an AST walk in the
    tests holds it there. `removeRow` tombstones: the row number retires for
    good and every `TraceView` over it raises from then on, so the *mutate* step
    of that pattern would have nothing left to write through. A
    `ContourView.remove` would therefore be a differently-shaped
    operation wearing `Contour.remove`'s name, which is the failure this class
    exists to avoid. That is a finding for the write half to answer, and it is
    pinned by a test rather than left here as prose.

    *`__add__`*, because it builds a `Contour` holding both operands' trace
    lists, and a contour spanning two stores is not a thing the row index can
    represent. *`copy()`*, because it is the pattern table's separate
    whole-object-clone row and its callers are the undo snapshots, which are a
    later track's question.

    *`getBounds` and `getMidpoint`*, and this one is a genuine gap rather than
    a category exclusion. Both exist on `Contour` and both are called on real
    contours in production (`autoseg/conversions.py` for the bounds,
    `Series.createZtrace` for the midpoint). Both are implemented by delegating
    to `trace.getBounds(tform)` once per trace -- and `TraceView` deliberately
    does not carry `getBounds`, because the geometry family is a separate row
    of the rewiring plan's pattern table (a batched whole-section pass over the
    coordinate column) and reimplementing it one trace at a time would prejudge
    that work. Building them here would mean either adding geometry to
    `TraceView` or writing the same per-trace loop one class further out; both
    prejudge the same decision, so both wait for the slice that owns it.

    *The `traces` attribute itself*, because it is not a read-only surface. On a
    `Contour` it is the live list, and code that holds it can append to it --
    the census counts three rebinds of it. Handing out a fresh list under that
    name would make `contour.traces.append(...)` a silent no-op. `getTraces()`,
    which returns a copy on a `Contour` too and is what the production readers
    actually call, is here instead.

    SLICE 7b WAS ATTEMPTED. HALF OF IT SHIPPED; `importTraces` DID NOT
    -------------------------------------------------------------------
    7b was dispatched as "`importTraces` + identity ops on `ContourView`". The
    identity ops are above and are built. The import is not, and the reasons are
    each measured and each pinned by a test in
    `tests/test_columnar_store_parity.py` that fails the day its blocker lifts.

    A correction is recorded here rather than quietly dropped, because the
    earlier draft of this docstring asserted the opposite and would have been
    read as settled architecture. It claimed identity through a view "can never
    match", that the only two ways out were D1's cached views and the rejected
    equality-over-id, and that there was **no third option that is merely
    mechanical**. That was wrong: the row route above is the third option, it
    needs neither decision, and it was built and run against all 221 contours of
    the real fixture series before this slice took it (review-274 F1). The blocker below is what survives of that claim.

      1. *A `Trace` a caller holds is still not a member, and `remove` is still
         absent.* Identity by row answers for `TraceView`s (above) and answers
         `False` for everything else, which is the honest answer and is pinned
         on every contour of the real series rather than assumed. What is not
         built is `remove`, for the two reasons in the mutation paragraph above
         -- the read-only contract, and the fact that `Contour.remove` detaches
         while `removeRow` tombstones.

      2. *`Contour.importTraces` calls `overlaps` and `mergeTags` on its
         elements.* `TraceView` carries neither, each for a reason older than
         this slice: `overlaps` is the geometry family, deferred to the batched
         coordinate pass, and `mergeTags` is outside the eight fields
         `Trace.__init__` assigns.

      3. ~~*The store can express the reordered list `importTraces` rebinds,
         but not cleanly.*~~ **No longer a blocker. Answered by D9 and built:
         `SectionColumns.reorderContour(name, rows)`.** `importTraces` ends
         `self.traces = traces`, where `traces` is in a **different order** from
         the contour it replaces, and the store had no purpose-built way to say
         so: `appendRow` is "an append, never an insert" and `removeRow` retires
         the row number for good. It could nonetheless express the reorder, by
         an accident of `setAttribute(row, "name", ...)` appending a renamed row
         at the **end** of its destination -- so a rename away to a scratch name
         and back was a move-to-end primitive, and n−1 of those realized any
         permutation, with no row renumbered, no row tombstoned and no held
         `TraceView` invalidated. The residue was smaller and dirtier than a
         capability gap: the scratch name **leaked into `modified_contours` and
         `getAllModifiedNames`**, which the dual write consumes as the scope of
         an undo snapshot. D9 answered that with an entry point rather than with
         a tolerance, and **the round trip is retired rather than kept beside
         it**: it survives in the parity suite only as the measurement that says
         the two routes reach the same order and only one of them stays quiet.
         What still blocks the port is 2 and 4 below, not the rebind.

      4. *The rebound list may hold the other contour's own `Trace` objects*,
         and in production `other` is a contour of a different section of a
         different series with a different store. `Section.importTraces` then
         calls `Contour.remove` on exactly those objects, by identity. Adopting
         a foreign trace into this store is design §10's id-carry question, not
         an append: `_resolveID` takes a carried-in id verbatim **without
         registering it with the issuer**, so a foreign id can later collide
         with one the local issuer hands out.

    ON D1, AND ONE INCONSISTENCY WORTH FLAGGING RATHER THAN INHERITING
    ------------------------------------------------------------------
    `specs/phase1-rewiring-slices-2026-08-04.md` heads Track B with "needs D1
    confirmed", so citing D1 as a precondition for shim work is defensible. Two
    things temper it, and neither is settled precedent. Slices 4, 6 and 7a all
    shipped under the identical unconfirmed D1, so treating it as *blocking* is
    new with 7b rather than established. And D1's own recorded text asks whether
    the cache is permanent or scaffolded -- not whether identity may be
    expressed at all. The row route above needs no answer to either question,
    because it builds no cache; if D1 is worth splitting when it is answered,
    the split is "is the cache permanent" from "may the shim express identity in
    store terms", and only the first is still open.

    What also ports is the container mechanics, and they are now pinned rather
    than inherited from slice 7a's word: the bare `list` a slice returns, its
    iterator type, and its `IndexError`/`TypeError` message strings, all
    re-verified against real `Contour`s on the real series.
    """

    ## Same two-slot discipline as `TraceView`, and for the same reason: a
    ## class whose contract is that it holds no values must not let a
    ## misspelled name land as an instance attribute and read back
    ## convincingly.
    __slots__ = ("_columns", "_name")

    def __init__(self, columns: SectionColumns, name: str):
        """View one contour of one store.

        The name is normalized on the way in, through the same
        `normalizeObjectName` that `appendRow` runs and that `Trace.name`'s
        setter runs. Not validation -- normalization -- and it closes a trap
        rather than adding a rule: `rowsForContour` normalizes its argument
        anyway, so a view that kept the raw name would look up rows under
        `"a_b"` while reporting its own name as `"a b"`. For the intended
        construction, from a name `contourNames()` handed out, it is a no-op.

        Nothing else is validated and the contour is not required to exist: a
        name with no rows behaves exactly as an empty `Contour` does, which is
        also what the store has to say about it, since a contour with no rows
        has no entry in the index.

            Params:
                columns (SectionColumns): the store holding the rows
                name (str): the contour's name, which is also its index key
        """
        self._columns = columns
        self._name = normalizeObjectName(name)

    def __repr__(self) -> str:
        return f"<ContourView {self._name!r} of {len(self)} row(s)>"

    @property
    def name(self) -> str:
        """The contour's name. Read-only: a view that could be renamed would be
        pointed at a different contour, not a written one -- the same reason
        `TraceView.row` is read-only."""
        return self._name

    def __iter__(self):
        """Iterate the contour's rows, as `TraceView`s, in within-contour order.

        A `list_iterator`, matching `Contour.__iter__`'s own return type
        exactly, over a snapshot of the row list. The snapshot is not a choice
        this class makes: `rowsForContour` already returns a fresh list, so
        there is no live sequence to iterate lazily over.
        """
        return iter([TraceView(self._columns, row)
                     for row in self._columns.rowsForContour(self._name)])

    def __getitem__(self, index):
        """Index or slice the contour.

        An `int` gives one `TraceView`; a slice gives a **bare `list`** of them,
        which is what `Contour.__getitem__` gives and what `importTraces` needs.
        See the class docstring.
        """
        ## Index the row list first, so every IndexError and TypeError is the
        ## list's own and this class decides nothing about what an index is.
        selected = self._columns.rowsForContour(self._name)[index]
        if isinstance(index, slice):
            return [TraceView(self._columns, row) for row in selected]
        return TraceView(self._columns, selected)

    def __len__(self):
        """The number of rows the contour holds."""
        return len(self._columns.rowsForContour(self._name))

    # --- identity, by row ----------------------------------------------------
    #
    # See the class docstring for why the row is the right question and why
    # object identity is the wrong one. The two methods are one question asked
    # twice, so they share `_rowOf` rather than one calling the other: `index`
    # needs the row list it matched against anyway, and building it twice would
    # be two `rowsForContour` calls where one is honest.

    def __contains__(self, candidate) -> bool:
        """True when `candidate` views a row this contour holds.

        `Contour` has no `__contains__` at all, so `trace in contour` falls back
        to `__iter__` plus `==` -- which, `Trace` defining no `__eq__`, is object
        identity. This answers the same question the only way a view can: by row.
        Anything that is not a `TraceView` over this store gets `False`,
        including a `Trace` this store materialized.
        """
        rows = self._columns.rowsForContour(self._name)
        return self._rowOf(candidate, rows) is not None

    def index(self, candidate) -> int:
        """The within-contour position of the row `candidate` views.

        `Contour.index` is `list.index`, so it raises `ValueError` for a trace it
        does not hold; so does this, with a message naming the contour rather
        than "list" (the class docstring says why exact message parity is the
        wrong target here, unlike for `__getitem__`).
        """
        rows = self._columns.rowsForContour(self._name)
        row = self._rowOf(candidate, rows)
        if row is None:
            raise ValueError(
                f"{candidate!r} is not in contour {self._name!r}"
            )
        return rows.index(row)

    def _rowOf(self, candidate, rows):
        """The row `candidate` names in THIS contour of THIS store, or `None`.

        Four ways to get `None`, and each is a real case rather than defensive
        padding: not a `TraceView` at all (a materialized `Trace`, most often),
        a view over a different store, a view over a different contour of this
        store, and a view over a row this contour no longer holds -- which
        covers a removed row, since `removeRow` takes the row out of the index.
        """
        if not isinstance(candidate, TraceView):
            return None
        if candidate._columns is not self._columns:
            return None
        row = candidate.row
        return row if row in rows else None

    def isEmpty(self) -> bool:
        """True when the contour holds no rows."""
        return not self._columns.rowsForContour(self._name)

    def getTraces(self) -> list:
        """The contour's rows as a fresh `list` of `TraceView`s.

        A copy, as `Contour.getTraces` returns `self.traces.copy()`, so a caller
        that mutates the list it was handed does not reach the index behind it.
        """
        return [TraceView(self._columns, row)
                for row in self._columns.rowsForContour(self._name)]


def _asColorRow(color) -> np.ndarray:
    array = np.asarray(color, dtype=np.uint8)
    if array.shape != (3,):
        raise ValueError(f"a color is three 0-255 components, got {color!r}")
    return array
