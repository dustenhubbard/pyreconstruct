import os
import sys
import json
from typing import Dict, List, Union

import numpy as np

from .contour import Contour
from .filters import passesFilters
from .trace import Trace, normalizeObjectName
from .flag import Flag
from .transform import Transform
from .log import LogSetPair

from PyReconstruct.modules.calc import (
    getDistanceFromTrace,
    distance,
    getImgDims
)

from PyReconstruct.modules.constants import (
    fast_loads,
    fast_dumps,
    canon_keys_inplace,
    SECTION_KEYS
)

from PyReconstruct.modules.backend.exports import export_svg, export_png


## --- the columnar dual-write ------------------------------------------------
##
## Slice 3 of the Phase 1 rewiring. Every `Section` carries a `SectionColumns`
## beside its own `self.contours` and mirrors every mutation into it, so that
## the columnar store is driven by real code on real data -- and checked against
## the object model -- before any call site is flipped to *read* from it.
##
## THE GATE IS GONE, DELIBERATELY, AND WHAT REPLACED IT
## ----------------------------------------------------
## This started life as a test harness behind an environment variable whose
## whole premise was that a real launch could not reach it. That premise was
## reversed on 2026-08-05: with the store built only under the gate,
## `self._columns` was `None` forever in a real session, so there was nothing for
## a production consumer to read from and the consumer-rewiring track could not
## start at all. The store is now built in every session, for every section, and
## the variable is gone rather than defaulted -- `tests/test_section_columnar_
## dual_write.py` scans the whole repository for its name so that a half-removed
## gate, which would give one machine a store and another none, cannot survive.
##
## What is NOT reversed, and is the safety property that replaces invisibility:
##
##   * **The object model is still authoritative.** `self.contours` owns
##     correctness. Nothing in this class reads an answer out of the store, and
##     `getDict`/`save` serialize the object model, never the columns. The store
##     is a shadow copy that is written and checked, not consulted.
##   * **The store is still never the source of a user-visible value.** A
##     consumer that reads it (Track C) is reading a copy that this class has
##     just checked against the thing that owns the value.
##   * **Divergence at a mutation is still loud.** Every dual-write hook still
##     raises `ColumnarDualWriteMismatch`, never logged and never swallowed.
##     What is no longer a raise is the WHOLE-SECTION check at `save()`; see
##     "REBUILD AT SAVE, NOT COMPARE" below, which is D11.
##
## WHAT THE CHECK COSTS, AND WHY ITS SCOPE NARROWED
## ------------------------------------------------
## Under the gate the consistency check materialized the *whole* section and
## compared it field by field after every single mutation. That was the right
## trade for a harness and is not a possible trade for production. Measured on
## `autoseg745` (745 MB, 636 sections, 323,534 traces, median section 503 traces
## and busiest 1,291):
##
##     addTrace, median section     0.0020 ms  ->  80.7 ms
##     addTrace, busiest section    0.0027 ms  -> 126.7 ms
##
## A drag translates the whole selection once per frame, and a translate is a
## remove/add pair per trace, so keeping that check would have made a real series
## unusable rather than slow.
##
## So the check now runs at two scopes instead of one:
##
##   * **Per mutation, targeted**: the row the mutation just wrote is compared
##     against the trace it mirrors, plus the store's live row count against the
##     section's trace count. O(1) in the section for the single-row paths,
##     O(section) only where the mutation itself already is. This catches every
##     routing bug -- a dropped write, a write that landed on the wrong value, a
##     write that carried seven of the eight columns -- at the mutation that
##     caused it, which is what the harness existed to do.
##   * **Whole section**: run at `save()`, which is already O(section) and is
##     not a per-frame path. That is where drift no per-row check can see is
##     dealt with: drift caused by something mutating a section's traces or
##     contours from OUTSIDE this class. `save()` no longer COMPARES there --
##     it REBUILDS; see the next section.
##
## `resyncColumnarStore()` is the public repair for that last case, and it is not
## hypothetical. Always-on turned every out-of-class mutation in the tree into a
## `ColumnarDualWriteMismatch` raised at the user, and there are **TWELVE**, on
## paths a user reaches constantly:
##
##     backend/func/state_manager.py    undoState, redoState  (contour rebind)
##     datatypes/series.py              deleteObjects         (contour rebind)
##     backend/autoseg/conversions.py   group deletion        (contour rebind)
##     datatypes/series.py              hideObjects           (in-place write)
##     datatypes/series.py              hideAllTraces         (in-place write)
##     datatypes/series.py              restoreObjectVisibility(in-place write)
##     datatypes/series.py              smoothObject          (in-place write)
##     datatypes/series.py              deleteDuplicateTraces (in-place write)
##     gui/main/field_widget_2_trace.py findFlag              (in-place write)
##     gui/main/field_widget_2_trace.py smoothTraces          (in-place write)
##     gui/main/field_widget_2_trace.py cutTrace's tag merge  (in-place write)
##
## (That is twelve sites across eleven rows: `state_manager.py` carries two.)
##
## Every one of them now calls the repair. The invariant this establishes is
## worth stating plainly because it is new and it is enforced by a raise: **a
## trace or contour mutated outside `Section` owes a `resyncColumnarStore()`
## before the section is saved.** That was free advice under the gate. It is a
## rule now, and the twelve sites above are what it caught.
##
## THE COUNT ABOVE HAS BEEN WRONG FOUR TIMES. READ IT AS A WARNING.
## ----------------------------------------------------------------
## It was "seven" when always-on landed, found by running the suite and watching
## it raise. A reviewer then read the source and found `findFlag` -- which hides
## every contour but one, in place, when the user clicks an `import-conflict_*`
## flag, on a path nothing in the suite clicked -- and it became "eight".
##
## The response to that was the right instinct: stop enumerating and scan for
## the shape instead. `tests/test_section_columnar_dual_write.py::
## test_no_module_outside_section_py_edits_a_store_backed_trace_column` fails on
## any function outside this module that reaches traces through a section and
## writes one of the eight store-backed columns without being on an explicit,
## reasoned allow-list.
##
## **The scan then missed two live sites of exactly the class it was built to
## close.** `Series.smoothObject` -- a shipped menu action -- and
## `Series.deleteDuplicateTraces` were both found by the next reviewer, reading
## the source, exactly as `findFlag` had been. The scan checked two of the nine
## `Trace` methods that write a store-backed column, so `Trace.smooth` and
## `Trace.mergeTags` walked straight through it. Widening it then exposed an
## eleventh, `smoothTraces`, which takes its traces as a parameter and names no
## section at all, so the reach predicate could not see it whatever it wrote;
## and a twelfth, `cutTrace`, hidden behind two further blind spots: the write
## was an in-place mutation of a column's own container, and the reach was
## `selected_traces` rather than `.contours`.
##
## The scan is now considerably harder to slip past -- its setter list is
## DERIVED from `Trace` by AST rather than hand-written, it knows four write
## routes instead of two, and three reach routes instead of one. But the honest
## summary is that four consecutive "complete" sets have been wrong, the third
## of them after the enumeration had been mechanised specifically to prevent
## that. Nothing about "twelve" is more trustworthy than "eight" was.
##
## REBUILD AT SAVE, NOT COMPARE -- D11, DECIDED, AND EXACTLY WHAT IT BUYS
## ----------------------------------------------------------------------
## Because the count kept being wrong, `save()` stopped asking whether the store
## already agrees with the object model and now simply REBUILDS it from the
## object model instead (`_rebuildColumnarStoreForSave`, called where the
## comparison used to run). The object model is authoritative; the store is
## derived from it; so there is nothing left to compare, and the store cannot be
## stale at `save()` time whenever a store can be built from the section at all.
##
## **What that removes, precisely:** an out-of-class edit can no longer leave a
## section unsaveable, and can no longer abort a multi-section operation partway
## through (`smoothObject` and `deleteDuplicateTraces` both call `save()` inside
## their own loop). The thirteenth site, whenever it is found, is not a crash in
## a user's session and not a data-loss risk. It is also cheaper: rebuilding the
## busiest section of `autoseg745` costs about half what comparing it did.
##
## **And that sentence needed a second pass to be true, which is worth keeping
## here because the first version of it read as settled.** Review of this change
## found a shape where the rebuild itself raised: the build indexes its rows by
## `trace.name` (`SectionColumns.fromSection`) and reads them back by contour
## key, so an out-of-class RENAME -- which leaves `Section.contours`'s key and
## `trace.name` disagreeing -- made the build fail its own arity check before
## any drift was computed. `save()` raised, exactly as before D11; and because
## the build assigns `self._columns` before filling `self._column_rows`, the
## failed save left the section with an empty row map, so every later hooked
## edit raised "holds no row for" as well. The save-time rebuild now restores
## the outgoing store and map on any failure and REPORTS rather than raises, so
## the claim above holds for that shape too. What it is NOT is a repair of the
## underlying disagreement: `resyncColumnarStore()` still raises on the same
## shape, because there the caller is asking for a store to be built and there
## is none to build. The claim is about `save()`, and only about `save()`.
##
## **What it does NOT remove, and this is the part it would be easy to overclaim
## -- the twelve repair calls above are still load-bearing and still there.**
## Rebuilding at `save()` fixes the store *at* `save()`. It does nothing for the
## window BETWEEN the out-of-class edit and the next save, and that window is
## where most of the twelve actually bit:
##
##   * a REBIND (undo, redo, `deleteObjects`, autoseg's group delete) leaves
##     `_column_rows` keyed on discarded `Trace` objects, so the next hooked
##     mutation touching a surviving trace goes through `_rowFor` and raises
##     "holds no row for" -- before any save runs.
##   * an IN-PLACE write (the eight `setHidden` / `smooth` / `mergeTags` /
##     `tags.add` sites) leaves one row's value stale, so the next hooked
##     mutation of that same trace runs `_assertRowMatchesTrace`, which compares
##     the whole row, and raises on the column that drifted.
##
## So the rule stands unchanged: **a trace or contour mutated outside `Section`
## owes a `resyncColumnarStore()`**, and the static scan that enforces it stays.
## What changed is the consequence of forgetting: it used to be an unsaveable
## section, and it is now a warning in the log plus a possible raise on the next
## edit. That is a strictly smaller blast radius, not an empty one.
##
## THE DISCIPLINE SIGNAL, KEPT AS A WARNING RATHER THAN LOST
## ---------------------------------------------------------
## A pure rebuild silently absorbs an out-of-class edit, and that signal is
## exactly how five of the twelve sites were found. So the rebuild is compared
## against the store it replaces -- store against store, not store against
## object model -- and any difference is PRINTED, never raised. `print` reaches
## a real place: `backend/func/logging_setup.py` tees stdout and stderr to a
## per-user log file the user can pull up from Help > View log file and paste
## into a bug report.
##
## The comparison is affordable because it is store-to-store: the four numeric
## columns compare as whole `numpy` arrays under one fancy index each, and only
## names, tags and coordinates need a per-row pass. Materializing a `Trace` per
## row -- what comparing against the object model requires -- is the expensive
## part, and it now runs only when something actually drifted, to write the
## message.
##
## It also pays for itself in a second way. A rebuild produces a NEW store with
## a higher generation, and a save happens on every section change; adopting one
## unconditionally would invalidate every generation-keyed cache on every
## mouse-wheel scroll. Because the comparison says when nothing moved, the
## common case keeps the store it already had, untouched, generation included.
##
## One thing that has NOT changed: the rebuild runs AFTER the write, for the
## same reason the comparison did. A fault in a shadow copy must never cost a
## user their valid bytes (see `save`).


class ColumnarDualWriteMismatch(AssertionError):
    """The columnar store and the object model disagree after a mutation.

    Raised, never logged and never swallowed. Catching store/object divergence
    is the entire purpose of the dual-write slice: a mismatch a test run
    survives is a mismatch that teaches nothing, and every later slice of the
    rewiring rests on the claim that the two representations agree.
    """


def _traceDifferences(stored : Trace, obj : Trace) -> list:
    """Every field on which a materialized row differs from a real trace.

    Compared against the **in-memory** trace, never against `getList()`: the
    store holds unrounded float64 while `getList` rounds to 7 decimal places, so
    a comparison through serialization is two lossy things agreeing and proves
    nothing about either. See the `columnar_store` module docstring, which puts
    the store on the unrounded side of that rounding on purpose.

    Container *types* are normalized on both sides before comparing, because
    they legitimately differ and a difference there is not a divergence: a
    file-loaded trace's `color` and `fill_mode` are `list`s while one built in
    memory carries `tuple`s, and the store's readers hand back `list`s by
    design.

        Params:
            stored (Trace): the trace `SectionColumns.materializeTrace` rebuilt
            obj (Trace): the trace the object model actually holds
        Returns:
            (list): one human-readable string per differing field; empty when
                the row and the trace agree
    """
    differences = []

    if stored.name != obj.name:
        differences.append(f"name: store {stored.name!r} != object {obj.name!r}")

    stored_points = [(float(x), float(y)) for x, y in stored.points]
    object_points = [(float(x), float(y)) for x, y in obj.points]
    if stored_points != object_points:
        if len(stored_points) != len(object_points):
            differences.append(
                f"points: store holds {len(stored_points)}, object holds "
                f"{len(object_points)}"
            )
        else:
            ## The first divergent point rather than both whole lists: a real
            ## trace runs to hundreds of points and dumping two of them buries
            ## the one pair that actually differs.
            for i, (s, o) in enumerate(zip(stored_points, object_points)):
                if s != o:
                    differences.append(f"points[{i}]: store {s!r} != object {o!r}")
                    break

    if list(stored.color) != list(obj.color):
        differences.append(
            f"color: store {list(stored.color)!r} != object {list(obj.color)!r}"
        )

    for attribute in ("closed", "negative", "hidden"):
        stored_flag = bool(getattr(stored, attribute))
        object_flag = bool(getattr(obj, attribute))
        if stored_flag != object_flag:
            differences.append(
                f"{attribute}: store {stored_flag!r} != object {object_flag!r}"
            )

    if list(stored.fill_mode) != list(obj.fill_mode):
        differences.append(
            f"fill_mode: store {list(stored.fill_mode)!r} != object "
            f"{list(obj.fill_mode)!r}"
        )

    if set(stored.tags) != set(obj.tags):
        differences.append(
            f"tags: store {sorted(stored.tags, key=str)!r} != object "
            f"{sorted(obj.tags, key=str)!r}"
        )

    return differences


## How many drift complaints a single save is allowed to print. A whole-section
## drift -- an alignment change applied from outside this class, say -- produces
## one per trace, and the busiest section of the production corpus on record
## holds 1,291 of them. The log file this print lands in rotates at 2 MB, so an
## unbounded report would evict the history somebody is reading it for.
DRIFT_REPORT_LIMIT = 20


def _rowsAgree(before, before_rows, after, after_rows) -> bool:
    """Whether the paired rows carry the same eight columns. The fast path.

    Store against store, not store against object model, and that is what makes
    reporting drift affordable at all. Comparing against the object model means
    `materializeTrace` per row -- a whole `Trace` built, its coordinates
    rebuilt as a list of tuples, its tags rebuilt as a set -- which is the bulk
    of the 2.42x this change exists to remove. Two stores hold the same columns
    in the same encodings, so the four numeric ones compare as whole `numpy`
    arrays under one fancy index each, and only names, tags and coordinates
    need a Python-level pass.

    Answers yes/no and nothing else. When it says no, `_storeDrift` pays for
    the expensive per-row materialization once, to say what moved -- which is
    the right place for that cost, because drift is the rare case.

        Params:
            before: the store the section held
            before_rows (list): its row numbers, in canonical order
            after: the store just rebuilt from the object model
            after_rows (list): its row numbers, in the same canonical order
        Returns:
            (bool): True when every paired row agrees in all eight columns
    """
    from .columnar_store import FILL_MODE_OVERFLOW

    if not before_rows:
        return True

    count = len(before_rows)
    old = np.fromiter(before_rows, dtype=np.intp, count=count)
    new = np.fromiter(after_rows, dtype=np.intp, count=count)

    if not np.array_equal(before.colorColumn[old], after.colorColumn[new]):
        return False
    for attribute in ("closed", "negative", "hidden"):
        if not np.array_equal(
            before.flagColumn(attribute)[old], after.flagColumn(attribute)[new]
        ):
            return False

    old_fill = before.fillModeColumn[old]
    if not np.array_equal(old_fill, after.fillModeColumn[new]):
        return False
    ## Equal codes are equal pairs except for the overflow code, which means
    ## "this row's pair was outside the vocabulary and lives in a side map", so
    ## two overflow rows can carry different pairs under the same code. Rare
    ## enough to be worth a second pass only when one is actually present.
    if bool((old_fill == FILL_MODE_OVERFLOW).any()):
        for old_row, new_row in zip(before_rows, after_rows):
            if before.getFillMode(old_row) != after.getFillMode(new_row):
                return False

    for old_row, new_row in zip(before_rows, after_rows):
        if before.getName(old_row) != after.getName(new_row):
            return False
        if before.getTags(old_row) != after.getTags(new_row):
            return False
        old_points = before.getCoordinates(old_row)
        new_points = after.getCoordinates(new_row)
        if old_points.shape != new_points.shape:
            return False
        if not np.array_equal(old_points, new_points):
            return False

    return True


def _storeDrift(before, before_map, after, after_map) -> list:
    """Everything a save-time rebuild changed, as human-readable complaints.

    An empty list means the store the section already had was already correct,
    which is the case on every save that follows only hooked mutations. A
    non-empty one means something edited this section's traces or contours from
    outside `Section` without calling `resyncColumnarStore()`, and names what.

    Reported, never raised. The rebuild has already made the store correct by
    the time this runs, so there is nothing left to refuse; what is left is the
    discipline signal that the edit happened at all, which is how five of the
    twelve known out-of-class sites were found and is the one thing D11
    knowingly put at risk.

        Params:
            before: the store the section held before the rebuild
            before_map (dict): its `Trace` -> row map
            after: the store just rebuilt from the object model
            after_map (dict): its `Trace` -> row map
        Returns:
            (list): one complaint per difference, capped at
                `DRIFT_REPORT_LIMIT` plus a count of the rest
    """
    complaints = []

    stored_names = before.contourNames()
    object_names = after.contourNames()
    only_store = sorted(set(stored_names) - set(object_names), key=str)
    if only_store:
        complaints.append(f"contours only in the store: {only_store!r}")
    only_object = sorted(set(object_names) - set(stored_names), key=str)
    if only_object:
        complaints.append(f"contours only in the object model: {only_object!r}")

    ## Paired up across every shared contour first, so the numeric columns can
    ## be compared in one indexed pass over the whole section rather than one
    ## per contour.
    pairs = []
    before_rows = []
    after_rows = []
    for name in sorted(set(stored_names) & set(object_names), key=str):
        stored_contour = before.rowsForContour(name)
        object_contour = after.rowsForContour(name)
        if len(stored_contour) != len(object_contour):
            complaints.append(
                f"contour {name!r}: the store holds {len(stored_contour)} "
                f"traces, the object model holds {len(object_contour)}"
            )
            continue
        for index, (old_row, new_row) in enumerate(
            zip(stored_contour, object_contour)
        ):
            pairs.append((name, index, old_row, new_row))
            before_rows.append(old_row)
            after_rows.append(new_row)

    if not _rowsAgree(before, before_rows, after, after_rows):
        ## Only now, and only once: the expensive comparison, which exists to
        ## write the message rather than to reach the verdict.
        before_detail = len(complaints)
        for name, index, old_row, new_row in pairs:
            for difference in _traceDifferences(
                before.materializeTrace(old_row), after.materializeTrace(new_row)
            ):
                complaints.append(f"contour {name!r} trace {index}: {difference}")
            if len(complaints) > DRIFT_REPORT_LIMIT:
                break
        ## The two comparisons must not be able to disagree about WHETHER
        ## anything moved, only about how to describe it -- because the caller
        ## keeps the old store when this list comes back empty, and keeping a
        ## store the fast path has just called different would be the one way
        ## this mechanism could leave a section stale. They compare the same
        ## eight columns through different readers, so a disagreement is a bug
        ## in one of them; say so rather than resolving it silently.
        if len(complaints) == before_detail:
            complaints.append(
                "the columns differ but the field-by-field comparison found "
                "nothing to name, which means _rowsAgree and _traceDifferences "
                "disagree about the same eight columns; the rebuild was kept"
            )

    ## The identity half, which no value comparison can see: an undo restore
    ## rebinds `Section.contours` to equal-valued copies, so every column above
    ## matches while the old row map is keyed on `Trace` objects no contour
    ## holds any more. `after_map` is keyed on exactly the section's live
    ## traces, because the rebuild just built it from them.
    live = {id(trace) for trace in after_map}
    mapped = {id(trace) for trace in before_map}
    if live != mapped:
        complaints.append(
            f"the row map was stale: it held {len(mapped - live)} trace(s) no "
            f"contour on this section holds any more, and was missing "
            f"{len(live - mapped)} that it does"
        )

    if len(complaints) > DRIFT_REPORT_LIMIT:
        extra = len(complaints) - DRIFT_REPORT_LIMIT
        complaints = complaints[:DRIFT_REPORT_LIMIT]
        complaints.append(f"... and at least {extra} more")

    return complaints


def tracesWithoutCounterpart(donor : Contour, keeper : Contour) -> list:
    """Return the traces in donor that overlap nothing at all in keeper.

    This is the distinction an import needs before it discards a contour. A
    donor trace that overlaps a keeper trace -- at any ratio, however small --
    is plausibly an earlier or a later version of it, so resolving the two in
    the keeper's favour is a merge decision. A donor trace that overlaps
    *nothing* on the keeper side is not a version of anything there: it is
    independent annotation work, and discarding it destroys a trace a human drew
    and cannot get back.

    **``open_curve=False`` keeps this site on the area comparison, deliberately,
    so that the open-trace curve metric changes nothing here.** ``threshold=0``
    asks a categorically different question from the threshold the import dialog
    asks: "do these two traces overlap at all", not "are these two traces the same
    trace". The curve metric was designed and measured for the second one. On the
    import merge at 0.95 it is measured clean on real data -- 264 of 264 genuine
    duplicate open pairs detected, 0 different-structure collapses at every
    threshold the slider can reach. At ``threshold=0`` it was neither, and the
    predicate there reduces to ``r > 0``, which accepts any positive ratio at all:

      * Two open traces that merely cross or touch score a small positive ratio
        (0.0064 for a T junction), about the tolerance over the shorter arc
        length. Bounding the tolerance shrinks that number and cannot zero it; no
        coverage measure taken at a positive tolerance can.
      * On the reporting user's series that turned 487 of 979 donor open traces
        from orphans into counterparts, and an orphan is what makes the history
        shortcut in Section.importTraces back off. 618 of the 664 newly matched
        pairs were her fiducial and calibration marks (``SF1_Wh``, ``grid``,
        ``Wh*_Dim``), whose members genuinely intersect -- their mean deviation is
        1,118 px but their closest approach is 0.67 px at the median, and a
        tolerance tests the closest approach. **46 were biological objects across
        22 contours**, and losing orphan status is what lets the shortcut discard a
        whole donor contour with no flag and no log entry, so those 46 were a
        silent-loss risk.

    So the metric goes where it was validated and nowhere else. The alternatives
    considered were a positive floor on the ratio at this site, and a minimum
    contact length below which the curve metric reports 0; both are new rules
    invented for an untested question, where preserving the existing answer is a
    rule that already has years of use behind it. If the meaning of "overlaps at
    all" for a curve is ever worth revisiting, it should be revisited on its own
    evidence rather than inherited as a side effect of fixing duplicate detection.

    Note the area comparison is not a good answer to this question either -- it
    reports a pair of open traces whose closing chords cross as overlapping even
    when the curves run 49 px apart, which is a silent loss of its own. It is
    simply the answer this call site has always given, and the one the open-curve
    change is not entitled to alter.

        Params:
            donor (Contour): the contour whose traces are at risk
            keeper (Contour): the contour that would survive
        Returns:
            (list): the donor traces with no counterpart in keeper
    """
    if not len(donor):
        return []
    if not len(keeper):
        return donor.getTraces()  # nothing to overlap: all of it is independent

    return [
        d_trace for d_trace in donor
        if not any(
            d_trace.overlaps(k_trace, threshold=0, open_curve=False)
            for k_trace in keeper
        )
    ]


class Section():

    ## Class-level defaults for the dual write. `__init__` assigns instance
    ## attributes over both, so these exist for one case: a `Section` built
    ## through `Section.__new__` without running `__init__`, which a dozen test
    ## modules do to drive one method against a handful of hand-set attributes.
    ## Without these, adding a hook to a mutator would break every one of them.
    ##
    ## They are the reason `_columns is None` is still a state this class has to
    ## tolerate even though every constructed `Section` now has a store: a bare
    ## `__new__` instance has no section number, no series and no contours to
    ## build one from, and inventing one for it would turn a deliberate test
    ## shortcut into a construction error.
    ##
    ## The shared dict is never written. Every path that puts a row into it
    ## runs only when `_columns is not None`, and the only thing that sets
    ## `_columns` is `resyncColumnarStore`, which rebinds an instance dict
    ## first.
    _columns = None
    _column_rows : dict = {}

    def __init__(self, n : int, series):
        """Load the section file.
        
            Params:
                n (int): the section number
                series (Series): the series that contains the section
        """
        self.n = n
        self.series = series

        ## Declared here, before anything can fail, so that `self._columns is
        ## None` is true of a half-constructed Section rather than an
        ## AttributeError. The real store is built at the bottom of this method,
        ## once there are contours to build it from.
        self._columns = None
        self._column_rows : dict = {}

        self.filepath = os.path.join(  # hidden trace file
            self.series.getwdir(),
            self.series.sections[n]
        )

        self.selected_traces : list[Trace] = []
        self.selected_ztraces = []
        self.selected_flags = []

        self.temp_hide = []          # traces to temp hide
        self.traces_group_hide = []  # traces to hide by group viz

        with open(self.filepath, "rb") as f:
            section_data = fast_loads(f.read())
        
        Section.updateJSON(section_data, n)  # update any missing attributes

        self.src = os.path.basename(section_data["src"])
        self.bc_profiles = section_data["brightness_contrast_profiles"]
        self.mag = section_data["mag"]
        self.align_locked = section_data["align_locked"]

        self.tforms = TransformsDict()
        
        for a in section_data["tforms"]:
            self.tforms[a] = Transform(section_data["tforms"][a])
        
        self.thickness = section_data["thickness"]
        self.contours : dict[str, Contour] = {}

        for name in section_data["contours"]:
            
            trace_list = []
            
            for trace_data in section_data["contours"][name]:
                trace = Trace.fromList(trace_data, name)
                # screen for defective traces. `updateJSON` above now applies
                # both screens to the stored data as well, so on this path the
                # two lines below are a no-op; they are kept because callers
                # that build a Section from data that has not been through
                # `updateJSON` still need them, and because the in-memory value
                # is the one the rest of the program reads.
                l = len(trace.points)
                if l == 2:
                    trace.closed = False
                if l > 1:
                    trace_list.append(trace)
                    
            self.contours[name] = Contour(
                name,
                trace_list
            )
        
        ## Build the parallel store. Unconditional as of 2026-08-05: every
        ## section in every session carries one.
        ##
        ## EAGER, NOT LAZY, AND THIS WAS MEASURED RATHER THAN ASSUMED
        ## ----------------------------------------------------------
        ## Building here taxes every section load, including the read-only ones,
        ## and the obvious alternative is to build on first touch so that a user
        ## who only reads a series never pays. The tax is real and is stated
        ## exactly in the PR: on `autoseg745` a section load goes from 0.0111 s
        ## to 0.0319 s (2.86x) and a full-series pass from 11.6 s to 25.1 s
        ## (2.16x), with the whole cost being `SectionColumns.fromSection`
        ## walking the section's traces once.
        ##
        ## It is still the right place, for a reason about correctness rather
        ## than speed: a lazily built store is built from whatever the object
        ## model holds at first touch, so every mutation before that point is one
        ## the store never saw and the check never compared. The dual write's
        ## entire claim is that the two representations have agreed continuously
        ## since construction, and a store that starts life mid-history cannot
        ## make it -- which matters precisely because the next slice is a
        ## consumer reading the store instead of the object model. Deferring also
        ## moves the cost rather than removing it: the first touch is a consumer
        ## read, so the tax lands inside a render or an export instead of inside
        ## a load, where it is less predictable and harder to attribute.
        self.resyncColumnarStore()

        self.flags = [Flag.fromList(l, self.n) for l in section_data["flags"]]

        self.calgrid = section_data["calgrid"]

        ## Modify temp_hide based on group visibility
        self.setGroupVisibility(series.groups_visibility)
        
        ## For GUI use
        self.clearTracking()
    
    @property
    def tform(self):
        return self.tforms[self.series.alignment]
    @tform.setter
    def tform(self, new_tform):
        if self.series.alignment != "no-alignment":
            self.tforms[self.series.alignment] = new_tform
            self._dualWriteTransformChange()  # test-only

    @property
    def brightness(self):
        return self.bc_profiles[self.series.bc_profile][0]
    @brightness.setter
    def brightness(self, b):
        c = self.contrast
        self.bc_profiles[self.series.bc_profile] = (b, c)
    
    @property
    def contrast(self):
        return self.bc_profiles[self.series.bc_profile][1]
    @contrast.setter
    def contrast(self, c):
        b = self.brightness
        self.bc_profiles[self.series.bc_profile] = (b, c)
    
    @property
    def src_fp(self):
        if self.series.src_dir.endswith("zarr"):
            scales = self.zarr_scales
            return os.path.join(
                self.series.src_dir,
                f"scale_{min(scales)}",
                self.src
            )
        else:
            return os.path.join(
                self.series.src_dir,
                self.src
            )

    @property
    def img_dims(self):
        return getImgDims(self.src_fp)
    
    @property
    def zarr_scales(self):
        if self.series.src_dir.endswith("zarr"):
            return [
                int(s.split("_")[1])
                for s in os.listdir(self.series.src_dir)
                if (
                    s.startswith("scale_") and 
                    s.split("_")[1].isnumeric() and 
                    self.src in os.listdir(os.path.join(self.series.src_dir, s))
                )
            ]

    @staticmethod
    def updateJSON(section_data, n):
        """Add missing attributes to section JSON.

        (Updates the dictionary in place)

            Params:
                section_data (dict): the JSON data to update
                n (int): the section number
            Returns:
                (dict): the contour renames this call performed, old name -> new
                    name. Empty for a section whose names already satisfy
                    ``normalizeObjectName``, which is every section written by a
                    build that has the rule. The caller needs this because the
                    rename is only half done here: a series keeps an object's
                    groups, comment, curation, user columns and hosts under the
                    object *name*, in the series file, which this function does
                    not see. ``Series.openJser`` repoints them.
        """
        renamed = {}

        # Recorded BEFORE the back-fill loop below inserts the key, because the
        # legacy brightness/contrast migration needs to know whether the *file*
        # carried a profiles dict -- a fact that is unrecoverable once the
        # default has been back-filled.
        had_bc_profiles = isinstance(
            section_data.get("brightness_contrast_profiles"), dict
        )

        empty_section = Section.getEmptyDict()
        for key in empty_section:
            if key not in section_data:
                section_data[key] = empty_section[key]

        # modify brightness/contrast
        if "brightness" in section_data and "contrast" in section_data:
            # fix exact numbers from an older version
            if abs(section_data["brightness"]) > 100:
                section_data["brightness"] = 0
            section_data["contrast"] = int(section_data["contrast"])

            # Move into profiles by MERGING. This used to assign a fresh
            # single-key dict, which discarded every other named profile the
            # section had. getDict() never writes the legacy scalars back, so
            # they vanish on the first save -- meaning the migration ran on
            # every open until that save, and the save then made the loss of
            # the other profiles permanent.
            profiles = section_data["brightness_contrast_profiles"]
            if not isinstance(profiles, dict):
                # Not mergeable, and would fail on load. Treat it as absent,
                # which is what the old wholesale assignment did in effect.
                profiles = {}
                section_data["brightness_contrast_profiles"] = profiles
                had_bc_profiles = False

            # Whether the scalars override an existing "default" is decided by
            # whether the file carried a profiles dict at all -- NOT by
            # comparing values, which cannot tell a deliberate (0, 0) default
            # from the back-filled placeholder:
            #   no profiles key  -> a pre-profiles file; the scalars ARE its
            #                       only brightness/contrast, so they become
            #                       "default"
            #   profiles present -> already profiles-aware, so that dict is
            #                       authoritative. It is what the profiles UI
            #                       has been showing and editing, while the
            #                       scalars are a stale leftover of an older
            #                       schema. Nothing is overwritten.
            if not had_bc_profiles or "default" not in profiles:
                profiles["default"] = (
                    section_data["brightness"], section_data["contrast"]
                )

        # scan contours
        flagged_contours = []
        for cname in section_data["contours"]:
            flagged_traces = []
            for i, trace in enumerate(section_data["contours"][cname]):
                # convert trace to list format if needed
                if type(trace) is dict:
                    trace = [
                        trace["x"],
                        trace["y"],
                        trace["color"],
                        trace["closed"],
                        trace["negative"],
                        trace["hidden"],
                        trace["mode"],
                        trace["tags"]
                    ]
                    section_data["contours"][cname][i] = trace
                # remove history from trace if it exists
                elif len(trace) == 9:
                    trace.pop()
                # check for trace mode
                if type(trace[6]) is not list:
                    trace[6] = ["none", "none"]
                # canonical tag order. Trace.getList sorts tags, but that only
                # runs for a section that goes back through the model: saveJser
                # reads the hidden dir verbatim, so a section the user never
                # touched kept whatever order its source file had and the
                # writer's "tags are sorted" guarantee did not hold for it.
                if type(trace[7]) is list and len(trace[7]) > 1:
                    trace[7] = sorted(trace[7], key=str)
                # check for empty/defective traces
                if len(trace[0]) < 2:
                    flagged_traces.append(i)
                # Two points enclose no area, so every reader forces such a
                # trace open in memory (`Section.__init__` below, the undo
                # baseline in `state_manager.getContours`, and `addTrace`).
                # Correct the stored flag as well, for the same reason the tag
                # sort above lives here: `saveJser` copies the hidden dir
                # verbatim, so the in-memory coercion reached the file only for
                # sections the user happened to open AND save. That is the
                # worst of the three possible behaviors -- the flag flipped
                # from true to false at some unpredictable later save rather
                # than never, so byte-diffing a .jser showed a change no edit
                # accounts for. Doing it here makes the correction happen once,
                # on unpack, for every section alike.
                #
                # The divergent row is not hypothetical and does not require a
                # hand-edited file: a Reconstruct XML import writes
                # `trace.getList()` straight into the section file with no
                # arity check (`xml_json_conversions.py`), so a two-point
                # closed contour keeps `closed: true` across the import.
                elif len(trace[0]) == 2:
                    trace[3] = False
            # remove the flagged defective traces
            for i in sorted(flagged_traces, reverse=True):
                section_data["contours"][cname].pop(i)
            # check if the contour is empty
            if not section_data["contours"][cname]:
                flagged_contours.append(cname)
        # remove flagged contours
        for cname in flagged_contours:
            del(section_data["contours"][cname])
        
        # remove no-alignment if present
        if "no-alignment" in section_data["tforms"]:
            del(section_data["tforms"]["no-alignment"])
        
        # iterate through flags and add resolved status or section number and ID.
        # The ID is DERIVED from the flag's own content, not generated: this
        # migration runs on every unpack of a .jser whose flags predate the ID
        # field, and a random ID there gave the same flag a different identity
        # on every open. Flag.equals compares IDs and nothing else, so
        # Series.importFlags deduplicated on an identity that did not survive
        # the trip and duplicated every legacy flag it was asked to merge.
        # See Flag.deriveID.
        taken = set(
            flag[0] for flag in section_data["flags"]
            if len(flag) == 7 and isinstance(flag[0], str)
        )
        for flag in section_data["flags"]:
            if len(flag) == 5:
                flag.append(False)
            if len(flag) == 6:
                id = Flag.deriveID([n] + flag, taken)
                taken.add(id)
                flag.insert(0, id)

        # iterate through contours and remove whitespace
        for cname in tuple(section_data["contours"].keys()):

            ## print(f"'{cname}'")
            updated_cname = normalizeObjectName(cname)

            if cname != updated_cname:

                if updated_cname not in section_data["contours"]:
                    section_data["contours"][updated_cname] = []

                section_data["contours"][updated_cname] += section_data["contours"][cname]

                del(section_data["contours"][cname])

                renamed[cname] = updated_cname

        # Canonical key order. The back-fill loop at the top of this function
        # appends any missing key at the tail, so two sections with identical
        # content but different provenance differed byte-wise. Rebuild in the
        # writer's order; keys this build has no concept of (e.g. the legacy
        # scalar brightness/contrast pair) are preserved, sorted, after the
        # documented nine. Rebuilt in place: the caller holds this dict.
        canon_keys_inplace(section_data, SECTION_KEYS)

        # Canonical contour order, so an object added later in a session lands in
        # the same place as one that was there from the start.
        contours = section_data["contours"]
        if isinstance(contours, dict) and list(contours) != sorted(contours, key=str):
            ordered = {name: contours[name] for name in sorted(contours, key=str)}
            contours.clear()
            contours.update(ordered)

        return renamed

    def getDict(self) -> dict:
        """Convert section object into a dictionary.
        
            Returns:
                (dict) all of the compiled section data
        """
        d = {}
        d["src"] = self.src
        d["brightness_contrast_profiles"] = self.bc_profiles
        d["mag"] = self.mag
        d["align_locked"] = self.align_locked

        # save tforms
        d["tforms"] = {}
        for a in self.tforms:
            if a != "no-alignment":  # not needed to save the no-alignment option
                d["tforms"][a] = self.tforms[a].getList()

        d["thickness"] = self.thickness

        # save contours (sorted: canonical ordering)
        d["contours"] = {}
        for contour_name in sorted(self.contours, key=str):
            if not self.contours[contour_name].isEmpty():
                d["contours"][contour_name] = [
                    trace.getList(include_name=False) for trace in self.contours[contour_name]
                ]
        
        d["flags"] = [f.getList() for f in self.flags]

        d["calgrid"] = self.calgrid

        return d
    
    @staticmethod
    def getEmptyDict() -> dict:
        """Returns a dict representing an empty section."""
        section_data = {}
        section_data["src"] = ""  # image location
        section_data["brightness_contrast_profiles"] = {
            "default": (0, 0)
        }
        section_data["mag"] = 0.00254  # microns per pixel
        section_data["align_locked"] = True
        section_data["thickness"] = 0.05  # section thickness
        section_data["tforms"] = {}  
        section_data["tforms"]["default"]= Transform.identity().getList() # identity matrix default
        section_data["contours"] = {}
        section_data["flags"] = []
        section_data["calgrid"] = False

        return section_data
    
    @staticmethod
    def new(series_name : str, snum : int, image_location : str, mag : float, thickness : float, wdir : str):
        """Create a new blank section file.
        
            Params:
                series_name (str): the name for the series
                snum (int): the section number
                image_location (str): the file path for the image
                mag (float): microns per pixel for the section
                thickness (float): the section thickness in microns
                wdir (str): the working directory for the sections
            Returns:
                (Section): the newly created section object
        """
        section_data = Section.getEmptyDict()
        section_data["src"] = os.path.basename(image_location)  # image location
        section_data["mag"] = mag  # microns per pixel
        section_data["thickness"] = thickness  # section thickness

        section_fp = os.path.join(wdir, series_name + "." + str(snum))
        with open(section_fp, "w") as section_file:
            section_file.write(json.dumps(section_data, indent=2))
   
    def save(self, update_series_data=True):
        """Save file into json.
        
            Params:
                update_series_data (bool): True if series data object should be updated
        """
        if self.series.isWelcomeSeries():
            return

        # A section the series no longer has is not written back. self.filepath
        # was resolved from series.sections at construction, so a Section object
        # outlives its entry in the index and keeps pointing at the file that
        # deleteSections removed: the field holds the deleted section in
        # b_section (changeSection -> swapABsections), and MainWindow.saveAllData
        # saves b_section on every save, recreateTables included, which put the
        # file straight back and resurrected the section on the next open. There
        # is nothing to persist for a section that is not part of the series, so
        # this is a no-op and not a refusal.
        if self.n not in self.series.sections:
            return

        # update the series data
        if update_series_data:
            self.series.data.updateSection(self, update_traces=True)
    
        d = self.getDict()
        # write atomically: a crash or ENOSPC mid-write must never leave the
        # section file truncated, so write a sibling temp file and rename it
        # over the original (os.replace is atomic on POSIX/Windows). We do NOT
        # fsync here: this internal working file is re-saved on every section
        # change (mouse-wheel scroll), so fsyncing each scroll would turn the
        # gesture into a synchronous disk flush. The .jser master copy is the
        # durable one; os.replace already prevents a truncated file on crash.
        tmp_fp = self.filepath + ".tmp"
        try:
            with open(tmp_fp, "wb") as f:
                # internal hidden working file -- write compact bytes to cut
                # serialization cost and the bytes re-read on every saveJser
                f.write(fast_dumps(d))
            # a save fires on scroll / section switch; retry a transiently-locked
            # replace (Windows AV/indexer/sync) so it doesn't fail spuriously
            from PyReconstruct.modules.backend.func.atomic_io import replace_with_retry
            replace_with_retry(tmp_fp, self.filepath)
        except OSError:
            # leave the original file untouched; clean up the partial temp
            try:
                os.remove(tmp_fp)
            except OSError:
                pass
            raise

        # The whole-section reconciliation, at the one non-per-frame point that
        # is already O(section). Per-mutation checking is targeted at the row
        # that moved (see `_assertRowMatchesTrace`), which cannot see drift
        # caused by something replacing contours from outside this class.
        #
        # REBUILT, NOT COMPARED -- D11
        # -----------------------------
        # This used to be `_assertColumnsMatchObjectModel("save")`, which asked
        # whether the store already agreed with the object model and raised at
        # the user when it did not. The enumeration of edit sites that check
        # existed to police was wrong four review rounds running, so the
        # question is no longer asked: the store is rebuilt from the object
        # model, which owns every value, and cannot then be stale whenever a
        # store can be built from the section at all. The module header sets
        # out what that removes, what it does not, and the one shape (an
        # out-of-class rename) where no store can be built and the section
        # keeps the one it had with a warning in the log instead.
        #
        # AFTER THE WRITE, NOT BEFORE, AND THAT ORDERING IS STILL THE POINT
        # ------------------------------------------------------------------
        # The comparison ran before the write until review, on the reasoning
        # that a section whose store disagrees with its object model should
        # raise rather than be written and then raise. That is exactly
        # backwards for what the two representations are. The object model is
        # authoritative and `getDict()` above serialized it; the store is a
        # shadow copy that NOTHING reads. So a fault in the shadow copy's
        # bookkeeping was vetoing the persistence of the model that owns every
        # value, and the refusal recurred on every later save, leaving the
        # section unsaveable for the rest of the session.
        #
        # The rebuild inherits that ordering rather than making it unnecessary.
        # It reports by printing rather than raising -- both drift and a
        # rebuild that could not be built at all -- so it cannot veto a save.
        # `resyncColumnarStore` CAN still raise on the build's arity check, and
        # the first version of this comment called that "a genuine
        # store-construction bug"; review showed the attribution was wrong. The
        # check also fires on a healthy store when the OBJECT MODEL is
        # self-contradictory -- an out-of-class rename leaves the contour key
        # and `trace.name` disagreeing -- which is why the save path reports it
        # instead of raising, and why the ordering still matters: the bytes
        # above were written from the object model and were already correct.
        # `test_a_shadow_mismatch_no_longer_costs_the_save` and
        # `test_a_rebuild_that_cannot_be_built_leaves_the_section_usable`
        # pin the two halves.
        self._rebuildColumnarStoreForSave()

    def tracesAsList(self) -> list[Trace]:
        """Return the trace dictionary as a list. Does NOT copy traces.
        
            Returns:
                (list): a list of traces
        """
        trace_list = []
        for contour_name in self.contours:
            for trace in self.contours[contour_name]:
                trace_list.append(trace)
        return trace_list
    
    def setAlignLocked(self, align_locked : bool):
        """Set the alignment locked status of the section.
        
            Params:
                align_locked (bool): the new locked status
        """
        self.align_locked = align_locked
    
    def getAllModifiedNames(self) -> set:
        """Return the names of all the modified traces."""
        trace_names = set([t.name for t in self.added_traces])
        trace_names = trace_names.union(set([t.name for t in self.removed_traces]))
        trace_names = trace_names.union(self.modified_contours)
        return trace_names
    
    def tformsModified(self, scaling_only=False):
        if len(self.tforms_values_copy) != len(self.tforms):
            return True
        for t1, t2 in zip(self.tforms_values_copy, self.tforms.values()):
            if scaling_only:
                if abs(t1.det - t2.det) > 1e-6:
                    return True
            else:
                if not t1.equals(t2):
                    return True
        return False
    
    def clearTracking(self):
        """Clear the added_traces and removed_traces lists."""
        self.added_traces = []
        self.removed_traces = []
        self.modified_contours = set()
        self.tforms_values_copy = [t.copy() for t in self.tforms.values()]
        self.flags_modified = False

    # --- the columnar dual write ---------------------------------------------
    #
    # Read the module-level comment first: it says why this runs in every
    # session, what the object model still owns, and why the check runs at two
    # scopes. Every method in this block still returns on its first line when
    # `self._columns` is None, which is now only true of a `Section` built
    # through `__new__` without an `__init__`.
    #
    # WHICH MUTATION PATHS ARE MODELLED, AND WHY THERE ARE FEWER HOOKS THAN
    # THIS CLASS HAS MUTATORS
    # -----------------------------------------------------------------------
    # The design proposal named four paths to route: `addTrace`, `removeTrace`,
    # `editTraceAttributes` and `translateTraces`. Reading the class says the
    # last two are not separate paths at all. `editTraceAttributes`,
    # `translateTraces`, `editTraceRadius`, `editTraceShape`, `makeNegative` and
    # `deleteTraces` are each *composed* of `removeTrace` / mutate / `addTrace`,
    # so hooking the two primitives covers all six and hooking them on their own
    # account as well would double-write. That composition is load-bearing for
    # this harness and is pinned by its tests rather than left as a reading.
    #
    # What the two primitives do NOT cover is the mutators that write a trace
    # attribute in place and never leave the contour: `hideTraces`,
    # `hideOtherTraces`, `unhideAllTraces` and `closeTraces` -- one
    # `setAttribute` each -- and `setMag`, which rewrites every trace's
    # coordinates through `Trace.magScale`, one `setCoordinates` each plus a
    # transform change, checked once for the batch because a whole-section
    # rewrite is one mutation. Those get their own hooks. The `tform` setter
    # reports a transform change, which changes no row and only moves the
    # generation counter; the store's own docstring says why that must not be
    # skipped even though nothing this slice does reads the counter.
    #
    # `importTraces` is the one method here that replaces whole contour trace
    # *lists* rather than going through any of the above: `Contour.importTraces`
    # rebinds `self.traces` outright, and the history shortcut swaps one Contour
    # object for another. There is no sequence of per-row mutations to mirror, so
    # the store is rebuilt from the object model at the end of it instead of
    # pretending to have tracked it. That is honest but limited, and the limit is
    # worth stating plainly: the consistency check proves nothing about the
    # inside of an import. Modelling an import as store operations is later work.
    #
    # Paths that edit a section's traces or contours from OUTSIDE this class are
    # the reason always-on was more than deleting an `if`. Under the gate they
    # were unreachable with a store present, and the comment here said only that
    # they "owe the resync". **There are TWELVE**, they are all on hot user
    # paths, and with a store always present every one of them was a
    # `ColumnarDualWriteMismatch` raised in a real session -- undo, redo,
    # deleting an object, autoseg's group deletion, the three hide paths,
    # smoothing an object, de-duplicating traces, clicking an import-conflict
    # flag, smoothing a selection, and cutting one. They now call
    # `resyncColumnarStore()`:
    #
    #   backend/func/state_manager.py    SectionStates.undoState / .redoState
    #   datatypes/series.py              Series.deleteObjects
    #   backend/autoseg/conversions.py   seriesToLabels
    #   datatypes/series.py              Series.hideObjects
    #   datatypes/series.py              Series.hideAllTraces
    #   datatypes/series.py              Series.restoreObjectVisibility
    #   datatypes/series.py              Series.smoothObject
    #   datatypes/series.py              Series.deleteDuplicateTraces
    #   gui/main/field_widget_2_trace.py FieldWidgetTrace.findFlag
    #   gui/main/field_widget_2_trace.py FieldWidgetTrace.smoothTraces
    #   gui/main/field_widget_2_trace.py FieldWidgetTrace.cutTrace
    #
    # (Eleven rows, twelve sites: the `state_manager.py` row carries two.)
    #
    # Two shapes, and the second is the one that keeps being missed: a *rebind*
    # (the contour dict or a key is replaced) and an *in-place write* (a trace
    # the section still holds has one of the eight columns written on it). The
    # first three rows are rebinds -- four sites, since `state_manager.py`
    # carries two -- and the last eight rows are in-place writes.
    #
    # That is a real limit on this design, not a fixed bug: a thirteenth such site
    # added later fails the same way. What it costs is smaller since D11, and
    # the smaller amount is the honest number rather than zero. It used to make
    # the section UNSAVEABLE for the rest of the session, because `save()`
    # compared and raised and nothing on that path repaired anything. `save()`
    # now rebuilds, so it does not raise -- not for drift, and not for a
    # rebuild that cannot be built at all -- and reports in the log instead.
    # (The second half of that is the review fix: an out-of-class RENAME makes
    # the build fail its own arity check, and the first version of this change
    # both raised and emptied the row map on that path. See the module header.)
    # But the window BETWEEN the out-of-class edit and that save is
    # untouched, and it is where these sites actually bit: a rebind sends the
    # next mutation of a surviving trace through `_rowFor`, which raises "holds
    # no row for", and an in-place write sends it through
    # `_assertRowMatchesTrace`, which raises on the drifted column. Both still
    # happen, both before any save.
    #
    # So the repair calls are still load-bearing and the scan that finds sites
    # needing them is still worth running.
    # `tests/test_section_columnar_dual_write.py` scans the source for the edit
    # shape so that such a site is a red test rather than a user's crash -- but
    # see the header of this module before trusting that: the scan was added
    # after `findFlag` was missed, and then missed two live sites itself. It is
    # much stronger now (its `Trace` setter list is derived by AST, and it knows
    # four write routes and three reach routes), and it is still a scan for
    # shapes somebody thought of.
    #
    # Forgetting the resync used to fail SILENTLY. It no longer does. An
    # undo restore rebinds `self.contours` to `Contour.copy()` products, which
    # are equal field for field to the traces the store was built from -- so the
    # value comparison in `_assertColumnsMatchObjectModel` saw nothing wrong,
    # while `_column_rows` stayed keyed on the traces that had just been thrown
    # away. The run then died several mutations later on a "holds no row for"
    # naming a trace that was plainly still in its contour. Both whole-section
    # mechanisms -- `_assertColumnsMatchObjectModel` and the drift report the
    # save-time rebuild writes -- compare the row map's identity domain against
    # the section's live traces as well as the columns' values, and the
    # per-mutation check compares their sizes, so a rebind is named where it
    # happened.

    def resyncColumnarStore(self):
        """Build (or rebuild) the parallel store from the object model.

        The public repair for a section whose traces or contours were edited
        from outside this class, and the only way a store is ever created.
        `__init__` calls it once per section, and the import path and the
        twelve out-of-class edit sites call it after they are done.

        The work itself is `_rebuildColumnarStore`, which this delegates to and
        which `save()` reaches independently since D11. The split is not
        decoration: this name means "an out-of-class edit happened and is being
        repaired", and `save()`'s rebuild does not mean that. Anything that
        intercepts the repair -- the tests that revert one call site to show it
        is load-bearing -- must not silently disable `save()` as well.

        THE GENERATION COUNTER IS CARRIED FORWARD, NOT RESET
        ----------------------------------------------------
        `SectionColumns`' docstring is explicit that the counter "is monotonic
        and is never reset by anything", because a cache stores the value it was
        built at and compares. A rebuild produces a *new* store, whose counter
        would otherwise start at 0 -- so an undo that rebuilt the store would
        hand every cache a generation lower than the one it holds, and every
        cache would conclude it was current. That is precisely the stale-render
        bug class the counter exists to prevent, reintroduced by the repair.
        Under the gate this could not bite, because nothing outside a test ever
        rebuilt a store and nothing at all read the counter; always-on plus a
        Track C consumer makes it live, so the new store resumes above the old
        one's count.

        The row map is keyed on the `Trace` object itself. `Trace` defines
        neither `__eq__` nor `__hash__`, so that dict is an identity map -- the
        same identity `Contour.remove` already runs on through `list.remove`, so
        the store's notion of "this trace" and the object model's cannot come
        apart. It is a strong reference and it keeps traces alive: a trace
        dropped from its contour by anything other than `removeTrace` stays
        reachable through the row map until the next resync, which is a real
        cost of the row map being an identity map and is why the out-of-class
        sites resync rather than being left to leak.
        """
        self._rebuildColumnarStore()

    def _rebuildColumnarStore(self):
        """Throw the store away and build a new one from the object model.

        The work behind `resyncColumnarStore` (the public repair) and behind
        `_rebuildColumnarStoreForSave` (D11's save-time rebuild). Read
        `resyncColumnarStore`'s docstring for the generation-counter and
        identity-map reasoning, which belongs to this method and is documented
        there because that is the name callers use.

        THE REBUILD CARRIES THE IDS AND THE ISSUER. D10.
        -------------------------------------------------
        This method used to call `SectionColumns.fromSection(self, ...)` with
        neither, and both halves of that were lossy. Dropping the ISSUER meant
        the replacement store had none, so every row's id came back `None` and
        the series' id index went with the store it was attached to. Dropping
        the IDS -- which is what happened at the `fromSection` layer whenever
        an issuer WAS passed -- meant every trace on the section was
        re-identified. Either way a birth certificate was reissued for a trace
        that had not changed, and this method is reached from all fourteen
        `resyncColumnarStore()` call sites plus, since D11, every `save()`.

        The correlation is the outgoing row map, and it has to be, because
        `Trace` carries no id attribute of any kind: there is no id to read off
        the object being re-appended. The only place a trace's existing id
        lives is the OUTGOING store, found by the row the OUTGOING map holds
        for that `Trace`. So both are read before either is replaced.

        A trace the outgoing map does not hold is a trace this store has never
        seen -- genuinely new, or arrived through an import -- and it falls
        through to the issuer, which is the pre-D10 behavior and stays right.
        A section with no outgoing store at all (`Section.__init__`, the first
        build) has nothing to carry and passes nothing.
        """
        from .columnar_store import SectionColumns

        ## `+ 1`, not `previous`. `fromSection` bumps once per appended row, so
        ## seeding with `previous` relies on the rebuild having at least one row
        ## to move the counter past the value a cache may already hold. A resync
        ## that produces ZERO rows does not advance at all -- and
        ## `Series.deleteObjects` reaches exactly that shape, deleting every
        ## contour key on a section and then calling the repair. A cache holding
        ## the old generation would conclude it was current against a store that
        ## had just been emptied, which is the stale-render bug the counter
        ## exists to prevent. Seeding one above the outgoing count makes the
        ## rebuild itself the advance, whatever it rebuilds into.
        outgoing = self._columns
        previous = outgoing.generation if outgoing is not None else 0

        ## Read the outgoing ids BEFORE `self._columns` is rebound, through the
        ## outgoing row map, which is the only correlation between a `Trace`
        ## and an id. `getID` is deliberately not liveness-checked, so a map
        ## entry left pointing at a tombstoned row still answers; such a trace
        ## is not in `self.contours` any more, so `fromSection` never asks for
        ## it and the entry is simply dropped with the map.
        carried_ids = None
        issuer = outgoing.id_issuer if outgoing is not None else None
        if issuer is not None:
            carried_ids = {}
            for trace, row in self._column_rows.items():
                trace_id = outgoing.getID(row)
                if trace_id is not None:
                    carried_ids[trace] = trace_id

        self._columns = SectionColumns.fromSection(
            self, id_issuer=issuer, generation=previous + 1,
            carried_ids=carried_ids,
        )
        self._column_rows = {}

        ## `fromSection` walks `sorted(contours, key=str)` and each contour's
        ## traces in list order, so the rows it appended for a contour line up
        ## one-for-one with that contour's traces. Read back through the store's
        ## public index rather than assuming row numbers, and check the arity, so
        ## that a change in the store's construction order fails here instead of
        ## silently mis-mapping every trace.
        for name in sorted(self.contours, key=str):
            traces = self.contours[name].getTraces()
            rows = self._columns.rowsForContour(name)
            if len(traces) != len(rows):
                raise ColumnarDualWriteMismatch(
                    f"building the store for section {self.n} gave "
                    f"{len(rows)} rows for contour {name!r}, which holds "
                    f"{len(traces)} traces"
                )
            for trace, row in zip(traces, rows):
                self._column_rows[trace] = row

        ## The whole-section VALUE comparison used to run here too, and was
        ## removed when this became a production path -- deliberately, and it is
        ## the second of the two places this change narrowed the check, so it is
        ## called out rather than buried.
        ##
        ## Measured on `autoseg745`: it costs about 81 ms on that series' median
        ## section and 127 ms on its busiest, and a store is built at every
        ## section load, so keeping it made loading one section 0.0111 s ->
        ## 0.1264 s (11.4x) and a full-series pass 11.6 s -> 90.8 s (7.8x). A
        ## user scrolls sections with the mouse wheel; 126 ms per scroll step is
        ## a different application.
        ##
        ## What it bought does not justify that, which is the part that makes
        ## this a narrowing and not a loss. A build copies values straight out of
        ## the object model, so the only divergence it can find is a bug in the
        ## store's own encode/decode -- `fill_mode` codes, the `uint8` colour
        ## row, the tag frozenset. That is a property of `SectionColumns` and not
        ## of any particular section, it does not vary from one section to the
        ## next, and `tests/test_columnar_store_parity.py` already tests it
        ## against both fixture series including the synthetic one carrying the
        ## tagged, negative and hidden traces the real one has none of. Running
        ## it again on each of 636 sections re-answers the same question 636
        ## times.
        ##
        ## The arity comparison above stays, because it is O(contours) and it
        ## does answer a per-section question: it fails if the store's
        ## construction order ever stops matching the object model's, which would
        ## silently mis-map every trace on the section.
        ##
        ## `save()` no longer compares in full either, since D11: it calls this
        ## method and then checks the result against the store it replaced,
        ## store to store, which is the same set of columns without a `Trace`
        ## rebuilt per row. `_storeDrift` is that comparison.

    def _rebuildColumnarStoreForSave(self):
        """Make the store correct at `save()` by rebuilding it, and report drift.

        D11. This replaced `_assertColumnsMatchObjectModel("save")`, and the
        difference is the whole point: the old call asked whether the store
        already agreed with the object model and raised at the user when it did
        not, which made a missed out-of-class edit site into an unsaveable
        section. This one does not ask. The object model owns every value, the
        store is derived from it, so rebuilding makes the store correct
        whenever a store can be built -- and a thirteenth edit site, whenever
        it turns up, cannot cost anybody a save.

        **"Cannot cost a save" is a claim about this method not raising, and
        it took two goes to be true.** Review of this change found the shape
        that falsified the first version: an out-of-class rename leaves
        `Section.contours`'s key and `trace.name` disagreeing, and the rebuild
        then raised out of its own arity check before any drift was computed --
        so the save still raised, and worse, the half-built row map it left
        behind made every later hooked edit raise too. Both halves are handled
        below, and pinned by
        `test_a_rebuild_that_cannot_be_built_leaves_the_section_usable`. So the
        sentence above is now about the rebuild being tolerant of BOTH
        outcomes, not only of drift.

        **THE REBUILD IS DISCARDED WHEN IT CHANGES NOTHING, AND THAT IS NOT AN
        OPTIMIZATION.** A rebuild produces a new store with a higher generation
        counter, and a save fires on every section change -- a mouse-wheel
        scroll included. Adopting a new store unconditionally would therefore
        hand every generation-keyed cache a fresh number several times a second
        and make the counter useless for the thing it exists for. So the
        rebuild is compared against the store it would replace, and when they
        agree the section keeps the store it already had, generation, tracking
        and row numbers untouched. The cost is the build, which is paid either
        way; what is saved is the churn.

        It has a third consequence, worth naming because it is load-bearing for
        work in flight: `SectionColumns` carries an `id` column, and until D10
        `fromSection` issued rather than carried ids. Nothing in the
        application injects an id issuer today, so every id is `None` and there
        is nothing to lose -- but the day one is wired, a save that adopted a
        rebuild unconditionally would have re-identified every trace on the
        section. Keeping the existing store when nothing drifted means an
        ordinary save does not, and
        `test_a_save_does_not_re_identify_the_traces_it_saves` pins that.

        **The residue this paragraph used to record is closed.** A save that
        DOES find drift adopts the rebuild, and that used to lose the ids with
        it -- exactly as the fourteen `resyncColumnarStore()` call sites did --
        which was left as the rebuild-carries-ids scope call in
        `specs/phase1-foreign-trace-id-acquisition-2026-08-05.md` §5. D10 made
        that call: `_rebuildColumnarStore` now carries both the issuer and the
        outgoing ids into the replacement, so a drifted save keeps every id it
        can correlate through the outgoing row map. The two mechanisms are
        complementary rather than redundant, and both are still wanted: this
        one avoids the rebuild entirely when nothing drifted, which also
        spares the generation counter, while D10's carry is what makes the
        rebuild non-destructive on the occasions it IS adopted.

        Drift is PRINTED, never raised. See `_storeDrift`. So is a rebuild that
        cannot be built at all: see the `except` below, which is the reason
        this method can honestly say `save()` does not raise for an
        out-of-class edit. It is not enough for the rebuild to be tolerant of
        drift, because the build has an arity check of its own that an
        out-of-class RENAME trips before any drift is computed.

        **WHAT IT STILL DOES NOT FIX, and the honest limit on the sentence
        above.** When the rebuild cannot be built, the section keeps the store
        it had rather than getting a corrected one, so the underlying
        disagreement is reported and survives. `resyncColumnarStore()`, the
        documented public repair, still raises on the same shape -- it is the
        caller asking for a store to be built, and there is no store to build.
        The claim this method makes is about `save()` alone: an out-of-class
        edit cannot cost a save and cannot cost the session, not that every
        out-of-class edit is repairable.
        """
        if self._columns is None:
            return

        before = self._columns
        before_map = self._column_rows
        ## `_rebuildColumnarStore`, not `resyncColumnarStore`, and the
        ## difference matters to more than style. `resyncColumnarStore` is the
        ## PUBLIC REPAIR, the thing an out-of-class edit site owes; this is
        ## internal machinery that happens to do the same work. Routing through
        ## the public name would make the two indistinguishable to anything
        ## that intercepts it -- including the tests that revert one repair
        ## call to show it is load-bearing, which would silently disable
        ## `save()`'s rebuild as well and report no drift for the wrong reason.
        ##
        ## THE REBUILD CAN FAIL, AND FAILING MUST NOT COST THE SECTION ITS ROW
        ## MAP. `_rebuildColumnarStore` assigns `self._columns` first and then
        ## fills `self._column_rows` contour by contour, so a raise partway
        ## through leaves the section holding a new store and a half-built map
        ## -- and since it raises on the FIRST contour whose arity disagrees,
        ## "half-built" is usually "empty". Every later hooked mutation then
        ## goes through `_rowFor` and raises "holds no row for", which turns a
        ## save that could not rebuild into a section nobody can edit for the
        ## rest of the session. That is strictly worse than what this method
        ## replaced, and it lands on the one path D11 exists to make safe, so
        ## the outgoing store and map are put back whatever happens.
        try:
            self._rebuildColumnarStore()
        except ColumnarDualWriteMismatch as unbuildable:
            ## The store the section already had is intact and is what
            ## `getDict()` just wrote from, so keeping it is not a fallback so
            ## much as declining to trade it for a store that does not exist.
            self._columns = before
            self._column_rows = before_map
            ## REPORTED, NOT RAISED -- the same rule as drift, for the same
            ## reason, and this is the case that used to break it. The build's
            ## arity check is a statement about the object model as much as
            ## about the store: an out-of-class RENAME leaves
            ## `Section.contours`'s key and `trace.name` disagreeing, and since
            ## `SectionColumns.fromSection` indexes rows by `trace.name` while
            ## the readback asks for them by contour key, a perfectly healthy
            ## store cannot be rebuilt at all. Raising here would refuse
            ## nothing (the bytes are already on disk, written from the object
            ## model, under the contour key -- which is the name the file
            ## round-trips) while costing the user the rest of the session.
            ##
            ## The check itself is NOT weakened: `resyncColumnarStore`, the
            ## import path and every section load still raise on it, and
            ## `test_building_a_store_still_checks_the_row_arity` still pins
            ## that. What changed is only that `save()` stopped being one of
            ## the places it can crash.
            self._warnAboutTheStore(
                f"the columnar store for section {self.n} could not be rebuilt "
                f"at save and the store it already had was kept. No data was "
                f"lost -- the object model is authoritative and it is what was "
                f"written -- but something has left this section's traces or "
                f"contours in a shape a store cannot be built from, most "
                f"likely an edit made outside Section:\n  {unbuildable}"
            )
            return
        except BaseException:
            ## Anything else is unexpected and still deserves to reach the
            ## caller; it just must not reach them through a bricked section.
            self._columns = before
            self._column_rows = before_map
            raise

        drift = _storeDrift(before, before_map, self._columns, self._column_rows)
        if not drift:
            self._columns = before
            self._column_rows = before_map
            return

        self._warnAboutTheStore(
            f"the columnar store for section {self.n} had drifted "
            f"from the object model and was rebuilt at save. No data was lost "
            f"-- the object model is authoritative and it is what was written "
            f"-- but something edited this section's traces or contours "
            f"outside Section without calling resyncColumnarStore():\n  "
            + "\n  ".join(drift)
        )

    def _warnAboutTheStore(self, message : str):
        """Report a save-time store problem where a user can retrieve it.

        stderr rather than stdout, and `print` rather than a logger because
        this tree has no logging framework: `backend/func/logging_setup.py`
        tees both standard streams into a per-user log file, which is what
        Help > View log file shows and what a bug report carries. A warning
        nobody can retrieve would not be a signal.
        """
        print(f"WARNING: {message}", file=sys.stderr)

    def _dualWriteResync(self):
        """Rebuild the store, if there is one.

        The `__new__`-tolerant form. `resyncColumnarStore` is the one callers
        outside this class use, because a caller that has a real `Section` in
        its hand wants a rebuild rather than a silent skip.
        """
        if self._columns is None:
            return
        self.resyncColumnarStore()

    def _rowFor(self, trace : Trace, operation : str) -> int:
        """The store row mirroring `trace`, or raise saying it has none."""
        row = self._column_rows.get(trace)
        if row is None:
            raise ColumnarDualWriteMismatch(
                f"{operation} on section {self.n} touched a trace the store "
                f"holds no row for: {trace.name!r}, {len(trace.points)} points. "
                f"Either it never entered the section through addTrace, or its "
                f"row has already been retired by removeTrace."
            )
        return row

    def _dualWriteAppend(self, trace : Trace):
        """Mirror an `addTrace` into the store, then check the row it wrote."""
        if self._columns is None:
            return
        self._column_rows[trace] = self._columns.appendRow(
            name=trace.name,
            points=trace.points,
            color=trace.color,
            closed=trace.closed,
            negative=trace.negative,
            hidden=trace.hidden,
            fill_mode=trace.fill_mode,
            tags=trace.tags,
        )
        self._assertRowMatchesTrace(trace, "addTrace")
        self._assertLiveCountMatches("addTrace")

    def _dualWriteRemove(self, trace : Trace):
        """Mirror a `removeTrace` into the store, then check the row it retired."""
        if self._columns is None:
            return
        row = self._rowFor(trace, "removeTrace")
        self._columns.removeRow(row)
        del self._column_rows[trace]
        ## The row has to be gone, not merely written to. A `removeRow` that did
        ## nothing leaves a live row for a trace no contour holds, and the value
        ## comparison cannot see that because there is no longer a trace to
        ## compare it against.
        if self._columns.isLive(row):
            raise ColumnarDualWriteMismatch(
                f"the columnar store diverged from the object model after "
                f"removeTrace on section {self.n}:\n  row {row} is still live "
                f"in the store, holding {self._columns.getName(row)!r}, after "
                f"the trace it mirrors left the section"
            )
        self._assertLiveCountMatches("removeTrace")

    def _dualWriteAttribute(self, trace : Trace, attribute : str, value):
        """Mirror an in-place scalar attribute write into the store."""
        if self._columns is None:
            return
        operation = f"a {attribute} write"
        self._columns.setAttribute(self._rowFor(trace, operation), attribute, value)
        self._assertRowMatchesTrace(trace, operation)

    def _dualWriteAllCoordinates(self, operation : str):
        """Mirror a geometry rewrite that touched every trace on the section.

        The rows are written first and checked afterwards, in two passes rather
        than one, which is a correctness requirement and not an ordering
        preference: checking a row inside the write loop compares a section
        whose object model has already moved everywhere against a store that has
        only moved as far as the loop has reached. A batch mutation is one
        mutation as far as the invariant is concerned.

        O(section), which is what the mutation it mirrors already is.
        """
        if self._columns is None:
            return
        traces = self.tracesAsList()
        for trace in traces:
            self._columns.setCoordinates(self._rowFor(trace, operation), trace.points)
        for trace in traces:
            self._assertRowMatchesTrace(trace, operation)

    def _dualWriteTransformChange(self):
        """Tell the store the section's alignment moved."""
        if self._columns is None:
            return
        before = self._columns.generation
        rows = self._columns.rowCount
        self._columns.noteTransformChange()
        ## No row changes here, so there is nothing for a value comparison to
        ## catch. Check the claim that is actually being made instead -- the
        ## counter moved and no row did -- because an unchecked claim is the
        ## shape of defect the store's docstring says the counter exists to
        ## prevent.
        if self._columns.generation <= before or self._columns.rowCount != rows:
            raise ColumnarDualWriteMismatch(
                f"the columnar store diverged from the object model after "
                f"a transform change on section {self.n}:\n  the generation "
                f"went {before} -> {self._columns.generation} and the row count "
                f"went {rows} -> {self._columns.rowCount}; a transform change "
                f"must move the first and not the second"
            )

    def _assertRowMatchesTrace(self, trace : Trace, operation : str):
        """Check the one row mirroring `trace`. O(1) in the size of the section.

        The per-mutation half of the consistency check. Every routing bug this
        class can have -- a dropped store write, a write that landed on the
        wrong value, a write that carried seven of the eight columns -- shows up
        in the row the mutation just touched, so comparing that row catches it
        at the mutation that caused it, which is what the whole-section
        comparison was doing and the only part of it a per-frame path can
        afford. What it deliberately does NOT catch is drift somewhere else on
        the section; `_assertColumnsMatchObjectModel` is still the net for that,
        and runs at every `save()`.

            Params:
                trace (Trace): the trace whose row is checked
                operation (str): what was just done, for the message
            Raises:
                ColumnarDualWriteMismatch: on any difference at all
        """
        row = self._rowFor(trace, operation)
        differences = _traceDifferences(self._columns.materializeTrace(row), trace)
        if differences:
            raise ColumnarDualWriteMismatch(
                f"the columnar store diverged from the object model after "
                f"{operation} on section {self.n}:\n  row {row} ({trace.name!r}): "
                + "\n  ".join(differences)
            )

    def _assertLiveCountMatches(self, operation : str):
        """The store holds one live row per trace on the section, and no more.

        O(contours) rather than O(traces), and the cheapest thing that can
        notice a row appearing or vanishing on either side. It cannot see a
        *replacement* -- an undo restore swaps every trace for an equal-valued
        copy and the count is unchanged -- which is the case
        `_assertColumnsMatchObjectModel`'s identity comparison exists for.
        """
        traces = sum(len(contour) for contour in self.contours.values())
        if len(self._columns) != traces or len(self._column_rows) != traces:
            raise ColumnarDualWriteMismatch(
                f"the columnar store diverged from the object model after "
                f"{operation} on section {self.n}:\n  the store holds "
                f"{len(self._columns)} live row(s) and the row map holds "
                f"{len(self._column_rows)}, against {traces} trace(s) on the "
                f"section"
            )

    def _assertColumnsMatchObjectModel(self, operation : str):
        """Raise unless the store and `self.contours` hold the same thing.

        Reads the store back through `materializeContours`, which exists for
        exactly this comparison and is explicitly not a view, and compares it
        contour by contour, trace by trace, field by field against the object
        model. Every mismatch found is reported, not just the first, because a
        single mutation that went wrong usually goes wrong in more than one
        column and the second one is the informative one.

        **THIS NO LONGER RUNS ON THE PRODUCTION PATH AT ALL. D11.** It is
        O(section) with a large constant: it rebuilds every trace on the
        section and compares every field. Under the test-only gate it ran after
        every single mutation, which was the right trade for a harness; when
        the store went always-on it was narrowed to `save()` alone, at a
        measured **2.42x on the busiest section of `autoseg745` (90.6 ms ->
        219.6 ms)** and 2.29x on the median (60.9 -> 139.6). D11 then removed
        it from `save()` as well, in favor of rebuilding the store there --
        because the point of comparing was to catch out-of-class edit sites,
        the enumeration of those was wrong four review rounds running, and a
        rebuild does not need the enumeration to be right.

        What survives is this method, unchanged in scope and still exact, kept
        for two consumers:

          * **the tests**, which call it directly throughout
            `test_section_columnar_dual_write.py` -- it is the precise
            instrument for "did this operation leave the two representations
            in agreement", and answering that is most of that file, and
          * **any future caller** that wants the question asked rather than the
            answer imposed.

        `save()` reaches `_rebuildColumnarStoreForSave` instead, which rebuilds
        and then compares the new store against the old one -- store to store,
        which needs no `materializeTrace` per row and is where the cost went.

        The per-mutation net is unchanged: `_assertRowMatchesTrace` and
        `_assertLiveCountMatches` still raise, still on every hooked mutation.

        **Empty contours are skipped on the object side.** `Section.contours`
        keeps a key whose `Contour` has been emptied -- `removeTrace` never
        deletes the key, and `importTraces` creates empty ones outright --
        while the store's `contourNames()` reports only names with live rows.
        That is the same asymmetry `getDict()` already has, where an empty
        contour is not written to the file, so it is a difference in how the two
        represent nothing rather than a divergence.

            Params:
                operation (str): what was just done, for the message
            Raises:
                ColumnarDualWriteMismatch: on any difference at all
        """
        if self._columns is None:
            return

        materialized = self._columns.materializeContours()
        expected = {
            name: contour.getTraces()
            for name, contour in self.contours.items()
            if not contour.isEmpty()
        }

        complaints = []

        only_store = sorted(set(materialized) - set(expected), key=str)
        if only_store:
            complaints.append(f"contours only in the store: {only_store!r}")
        only_object = sorted(set(expected) - set(materialized), key=str)
        if only_object:
            complaints.append(f"contours only in the object model: {only_object!r}")

        for name in sorted(set(materialized) & set(expected), key=str):
            stored_traces = materialized[name].getTraces()
            object_traces = expected[name]
            if len(stored_traces) != len(object_traces):
                complaints.append(
                    f"contour {name!r}: the store holds {len(stored_traces)} "
                    f"traces, the object model holds {len(object_traces)}"
                )
                continue
            for i, (stored, obj) in enumerate(zip(stored_traces, object_traces)):
                for difference in _traceDifferences(stored, obj):
                    complaints.append(f"contour {name!r} trace {i}: {difference}")

        ## The comparison above reads *values* out of the store, so it is
        ## structurally incapable of seeing a stale row map. A whole-dict rebind
        ## of `self.contours` to equal-valued copies -- which is exactly the
        ## shape of an undo restore -- leaves every field matching and every key
        ## in `_column_rows` pointing at a `Trace` no contour holds any more.
        ## The check passed, and the next `removeTrace` then failed with "holds
        ## no row for" naming a trace that is plainly in the contour. So compare
        ## the map's identity domain too, and the failure lands here, on the
        ## first hooked mutation after the rebind, saying what actually went
        ## wrong instead of surfacing later as a puzzle.
        ##
        ## Identity and not equality, for the same reason the map itself is an
        ## identity map: `Trace` defines no `__eq__`. Sets and not multisets, so
        ## the same `Trace` object appended twice -- which no application path
        ## does -- is left to the arity comparison above rather than newly
        ## rejected here. Both hooks that write the map do so *after* the object
        ## model has already been updated, so this holds at every call site.
        live = {id(trace) for trace in self.tracesAsList()}
        mapped = {id(trace) for trace in self._column_rows}
        if live != mapped:
            complaints.append(
                f"the row map is stale: it holds {len(mapped - live)} trace(s) "
                f"no contour on this section holds any more and is missing "
                f"{len(live - mapped)} that it does. Something replaced this "
                f"section's contours or traces from outside Section without "
                f"calling resyncColumnarStore() afterwards"
            )

        if complaints:
            raise ColumnarDualWriteMismatch(
                f"the columnar store diverged from the object model after "
                f"{operation} on section {self.n}:\n  " + "\n  ".join(complaints)
            )

    def setMag(self, new_mag : float):
        """Set the magnification for the section.
        
            Params:
                new_mag (float): the new magnification for the section
        """
        # modify the translation component of the transformation
        for tform in self.tforms.values():
            tform.magScale(self.mag, new_mag)
        
        # modify the traces
        for trace in self.tracesAsList():
            trace.magScale(self.mag, new_mag)
        
        # modify the ztraces
        for ztrace in self.series.ztraces.values():
            ztrace.magScale(self.n, self.mag, new_mag)
        
        # modify the flags
        for flag in self.flags:
            flag.magScale(self.mag, new_mag)

        self.mag = new_mag

        # mirror into the test-only store: every trace's geometry was rewritten
        # in place above, and every tform with it
        self._dualWriteAllCoordinates("setMag")
        self._dualWriteTransformChange()

    def addTrace(self, trace : Trace, log_event=True):
        """Add a trace to the trace dictionary.
        
            Params:
                trace (Trace): the trace to add
                log_event (bool): true if the event should be logged
        """        
        # do not add trace if less than two points
        if len(trace.points) < 2:
            return
        # force trace to be open if only two points
        elif len(trace.points) == 2:
            trace.closed = False
        # add to log
        if log_event:
            self.series.addLog(trace.name, self.n, "Create trace(s)")

        if trace.name in self.contours:
            self.contours[trace.name].append(trace)
        else:
            self.contours[trace.name] = Contour(trace.name, [trace])

        self.added_traces.append(trace)

        self._dualWriteAppend(trace)  # test-only; a no-op in every shipped launch

    def removeTrace(self, trace : Trace, log_event=True):
        """Remove a trace from the trace dictionary.
        
            Params:
                trace (Trace): the trace to remove from the traces dictionary
                log_event (bool): true if the event should be logged
        """
        if trace.name in self.contours:
            self.contours[trace.name].remove(trace)
            self.removed_traces.append(trace)
            self._dualWriteRemove(trace)  # test-only; see the harness block above
        if log_event:
            self.series.addLog(trace.name, self.n, "Delete trace(s)")
    
    def addFlag(self, flag : Flag, log_event=True):
        """Add a flag to the section.
        
            Params:
                flag (Flag): the flag to add to the section
                log_event (bool): true if the event should be logged
        """
        self.flags.append(flag)
        self.flags_modified = True
        if log_event:
            self.series.addLog(None, self.n, "Create flag(s)")
    
    def removeFlag(self, flag : Flag, log_event=True):
        """Remove a flag from the section.
        
            Params:
                flag (Flag): the flag to remove from the section
                log_event (bool): true if the event should be logged
        """
        if flag in self.flags:
            self.flags.remove(flag)
            self.flags_modified = True
            if log_event:
                self.series.addLog(None, self.n, "Delete flag(s)")

    def editTraceAttributes(self, traces : list[Trace], name : str, color : tuple, tags : set, mode : tuple, add_tags=False, log_event=True):
        """Change the name and/or color of a trace or set of traces.
        
            Params:
                traces (list): the list of traces to modify
                name (str): the new name
                color (tuple): the new color
                tags (set): the new set of tags. None leaves each trace's own
                    tags untouched (as for name/color/mode); an empty set
                    REPLACES them with no tags, which is how
                    Series.removeAllTraceTags clears them. The set is copied
                    per trace, so the caller's set is never adopted and no two
                    traces share one.
                mode (tuple): the new fill mode for the traces
                add_tags (bool): True if tags should be added (rather than replaced)
                log_event (bool): true if the event should be logged
        """
        for trace in traces.copy():
            # check if trace was highlighted
            if trace in self.selected_traces:
                self.selected_traces.remove(trace)
                selected = True
            else:
                selected = False
            
            # remove the trace and modify
            self.removeTrace(trace, log_event=False)
            new_trace = trace.copy()
            if name is not None:
                new_trace.name = name
            if color is not None:
                new_trace.color = color
            if tags is not None:
                if add_tags:
                    for tag in tags:
                        new_trace.tags.add(tag)
                else:
                    # copy per trace: a bare assignment would hand the same set
                    # object to every trace in the loop (and to the caller, whose
                    # set it is), so a later in-place tags.add on one trace would
                    # appear on all of them. Trace.copy() copies tags for the
                    # same reason.
                    new_trace.tags = set(tags)
            fill_mode = list(new_trace.fill_mode)
            if mode is not None:
                style, condition = mode
                if style is not None:
                    fill_mode[0] = style
                if condition is not None:
                    fill_mode[1] = condition
                new_trace.fill_mode = tuple(fill_mode)
            
            # log the event
            if log_event:
                if trace.name != new_trace.name:
                    self.series.addLog(trace.name, self.n, f"Rename to {new_trace.name}")
                    self.series.addLog(new_trace.name, self.n, f"Create trace(s) from {trace.name}")
                else:
                    self.series.addLog(new_trace.name, self.n, f"Modify trace(s)")
            
            # add trace back to scene and highlight if needed
            self.addTrace(new_trace, log_event=False)
            if selected:
                self.addSelectedTrace(new_trace)
    
    def editTraceRadius(self, traces : list[Trace], new_rad : float, log_event=True):
        """Change the radius of a trace or set of traces.
        
            Params:
                traces (list): the list of traces to change
                new_rad (float): the new radius for the trace(s)
                log_event (bool): true if the event should be logged
        """
        for trace in traces:
            a = self.series.getAttr(trace.name, "alignment")
            if not a: a = self.series.alignment
            tform = self.tforms[a]
            self.removeTrace(trace, log_event=False)
            trace.resize(new_rad, tform)
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify radius")
    
    def editTraceShape(self, traces : list[Trace], new_shape : list, log_event=True):
        """Change the shape of a trace or set of traces.
        
            Params:
                traces (list): the list of traces to change
                new_shape (list): the new shape for the trace(s)
                log_event (bool): true if the event should be logged
        """
        for trace in traces:
            self.removeTrace(trace, log_event=False)
            trace.reshape(new_shape, self.tform)
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify shape")
    
    def findClosest(
            self,
            field_x : float,
            field_y : float,
            radius=0.5,
            traces_in_view : list[Trace] = None,
            include_hidden=False):
        """Find closest trace/ztrace to field coordinates in a given radius.
        
        (Only meant for GUI use.)
        
            Params:
                field_x (float): x coordinate of search center
                field_y (float): y coordinate of search center
                radius (float): 1/2 of the side length of search square
                traces_in_view (list): the traces in the window viewed by the user
                include_hidden (bool): True if hidden traces can be returned
            Returns:
                (tuple): the object closest to the point and the type
                None if no trace points are found within the radius
        """
        min_distance = -1
        closest = None
        closest_type = None
        min_interior_distance = -1
        closest_trace_interior = None
        tform = self.tform

        # only check the traces within the view if provided
        if traces_in_view:
            traces = traces_in_view
        else:
            traces = self.tracesAsList()

        # Bbox rejection (hot path: this method runs on every buttonless
        # mouse move for every trace in view). Build the search square in
        # field space -- padded by the radius plus a couple of mag units,
        # since getDistanceFromTrace quantizes coordinates to the mag grid --
        # and inverse-map its corners into trace space. The axis-aligned bbox
        # of those corners is a conservative search window: any trace whose
        # own bbox misses it cannot pass the radius check or contain the
        # point, so it is skipped before any numpy mapping or cv2 test.
        margin = radius + 2 * self.mag
        try:
            search_corners = tform.map(
                [
                    (field_x - margin, field_y - margin),
                    (field_x + margin, field_y - margin),
                    (field_x + margin, field_y + margin),
                    (field_x - margin, field_y + margin),
                ],
                inverted=True,
            )
            sxs = [p[0] for p in search_corners]
            sys_ = [p[1] for p in search_corners]
            s_xmin, s_xmax = min(sxs), max(sxs)
            s_ymin, s_ymax = min(sys_), max(sys_)
        except Exception:
            # a degenerate/non-invertible section transform cannot be
            # inverse-mapped. Fall back to an unbounded search window so no
            # trace is bbox-rejected: every trace is still forward-mapped and
            # distance-tested in the loop below, exactly as the old forward-map
            # loop did. Hover (a buttonless mouse move) must never crash here.
            s_xmin = s_ymin = float("-inf")
            s_xmax = s_ymax = float("inf")

        # iterate through all traces to get closest
        for trace in traces:
            # skip hidden traces
            if not include_hidden and trace.hidden:
                continue
            if not trace.points:
                continue

            # bbox-reject in trace space (cheap C-level min/max)
            xs, ys = zip(*trace.points)
            if (
                max(xs) < s_xmin or min(xs) > s_xmax or
                max(ys) < s_ymin or min(ys) > s_ymax
            ):
                continue

            # map every surviving trace's points in one vectorized call
            points = tform.mapPointsArray(trace.points)

            # find the distance of the point from each trace
            dist = getDistanceFromTrace(
                field_x,
                field_y,
                points,
                factor=1/self.mag,
                absolute=False
            )
            if closest is None or abs(dist) < min_distance:
                min_distance = abs(dist)
                closest = trace
                closest_type = "trace"
            
            # check if the point is inside any filled trace
            if (
                trace.fill_mode[0] != "none" and
                dist > 0 and 
                (closest_trace_interior is None or dist < min_interior_distance)
            ):
                min_interior_distance = dist
                closest_trace_interior = trace
        
        # check for ztrace points close by
        if self.series.getOption("show_ztraces"):
            for ztrace in self.series.ztraces.values():
                for i, pt in enumerate(ztrace.points):
                    if pt[2] == self.n:
                        x, y = tform.map(*pt[:2])
                        dist = distance(field_x, field_y, x, y)
                        if closest is None or dist < min_distance:
                            min_distance = dist
                            closest = (ztrace, i)
                            closest_type = "ztrace_pt"
        
        # check for flags close by
        show_flags = self.series.getOption("show_flags")
        if show_flags != "none":
            for flag in self.flags:
                if show_flags == "unresolved" and flag.resolved:
                    continue
                x, y = tform.map(flag.x, flag.y)
                dist = distance(field_x, field_y, x, y)
                if closest is None or dist < min_distance:
                    min_distance = dist
                    closest = flag
                    closest_type = "flag"
        
        # check for radius and if pointer is in interior
        if min_distance > radius:
            if closest_trace_interior:
                closest = closest_trace_interior
                closest_type = "trace"
            else:
                closest = None
                closest_type = None

        return closest, closest_type
    
    def deselectAllTraces(self):
        """Deselect all traces.
        
        (Only meant for GUI use.)
        """
        self.selected_traces : list[Trace] = []
        self.selected_ztraces = []
        self.selected_flags = []
    
    def selectAllTraces(self):
        """Select all traces.

        (Only meant for GUI use.)
        """
        self.deselectAllTraces()
        for trace in self.tracesAsList():
            self.addSelectedTrace(trace)

    def invertTraceSelection(self, include_hidden=False):
        """Invert the trace selection: deselect every selected trace and
        select every unselected trace.

        Only traces visible in the field can become selected: hidden and
        group-hidden traces are skipped unless include_hidden is True (the
        show-all-traces mode). A locked object's traces are selected like any
        other, which is what the object list's invert already does: lock guards
        edits, not selection. Selected ztrace points and flags are left
        untouched.

        (Only meant for GUI use.)

            Params:
                include_hidden (bool): True if hidden traces may be selected
        """
        selected = set(self.selected_traces)
        group_hidden = set(self.traces_group_hide)

        to_select = []
        for trace in self.tracesAsList():
            if trace in selected:
                continue
            if not include_hidden and (trace.hidden or trace in group_hidden):
                continue
            to_select.append(trace)

        self.selected_traces : list[Trace] = []
        for trace in to_select:
            self.addSelectedTrace(trace)

    def hideOtherTraces(self, keep : list = None, log_event=True):
        """Hide every trace on THIS section except the given ones (the selected
        traces by default).

        Locked traces in the complement are hidden too: locking guards edits and
        quantification, not visibility. Traces already hidden are left untouched.
        An empty keep set is a no-op, so this never blanks the section.

        (Only meant for GUI use.)

            Params:
                keep (list): the traces to keep visible (defaults to selection)
                log_event (bool): true if the event should be logged
            Returns:
                (bool): True if the section was modified
        """
        if keep is None:
            keep = self.selected_traces
        keep_set = set(keep)
        if not keep_set:  # never hide every trace on the section
            return False

        modified = False
        for trace in self.tracesAsList():
            if trace in keep_set or trace.hidden:
                continue
            modified = True
            trace.setHidden(True)
            self._dualWriteAttribute(trace, "hidden", True)  # test-only
            self.modified_contours.add(trace.name)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")

        # drop any traces that are now hidden from the selection
        self.selected_traces = [t for t in self.selected_traces if not t.hidden]

        return modified

    def hideTraces(self, traces : list = None, hide=True, log_event=True):
        """Hide traces.

        (Only meant for GUI use.)
        
            Params:
                traces (list): the traces to hide
                hide (bool): True if traces should be hidden
                log_event (bool): true if the event should be logged
        """
        modified = False

        if not traces:
            traces = self.selected_traces.copy()

        for trace in traces:
            modified = True
            trace.setHidden(hide)
            self._dualWriteAttribute(trace, "hidden", hide)  # test-only
            self.modified_contours.add(trace.name)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        self.selected_traces : list[Trace] = []

        return modified

    def setGroupVisibility(self, group_viz: Union[Dict[str, bool], None]=None) -> None:
        """Modify traces_group_hide based on group visibility.

            Params:
                group_viz (dict): group name -> True if the group is visible.
                                  Omitted, None, or empty means there is nothing
                                  to apply and traces_group_hide is left alone.
        """
        ## Nothing to apply: leave traces_group_hide as it is
        if not group_viz:

            return

        ## Get list of groups to hide
        hide_groups = [group for group, viz in group_viz.items() if not viz]

        if not hide_groups:

            return

        obj_groups = self.series.object_groups

        to_hide = set()
        
        for group in hide_groups:
            
            objs = obj_groups.getGroupObjects(group)
            to_hide = to_hide.union(objs)

        if not to_hide:

            return

        # only visit contours that are actually hidden (avoids scanning every
        # trace on the section and rebuilding a list per trace)
        for name in (to_hide & self.contours.keys()):

            self.traces_group_hide.extend(self.contours[name])

    def closeTraces(self, traces : list = None, closed=True, log_event=True):
        """Close or open traces.

        (Only meant for GUI use.)
        
            Params:
                traces (list): the traces to modify
                closed (bool): True if traces should be closed
                log_event (bool): true if the event should be logged
        """
        modified = False

        if not traces:
            traces = self.selected_traces

        for trace in traces:
            modified = True
            trace.closed = closed
            self._dualWriteAttribute(trace, "closed", closed)  # test-only
            self.modified_contours.add(trace.name)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        return modified
    
    def unhideAllTraces(self, log_event=True):
        """Unhide all traces on the section.

        (Only meant for GUI use.)
        
            Params:
                log_event (bool): true if the event should be logged
        """
        modified = False
        for trace in self.tracesAsList():
            hidden = trace.hidden
            if hidden:
                modified = True
                trace.setHidden(False)
                self._dualWriteAttribute(trace, "hidden", False)  # test-only
                self.modified_contours.add(trace.name)
                if log_event:
                    self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        return modified
    
    def makeNegative(self, traces : list = None, negative=True, log_event=True):
        """Make a set of traces negative.

        (Only meant for GUI use.)
        
            Params:
                traces (list): the traces to make negative
                negative (bool): the negative status of the traces to modify
                log_event (bool): true if the event should be logged
        """
        if traces is None:
            traces = self.selected_traces.copy()
        modified = False

        for trace in traces:
            self.removeTrace(trace, log_event=False)
            trace.negative = negative
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
            modified = True
        
        return modified
        
    def deleteTraces(self, traces : Union[List, None] = None, flags : Union[List, None] = None, log_event=True):
        """Delete selected traces and flags.
        
            Params:
                traces (list): a list of traces to delete (default is selected traces)
                flags (list): a list of flags to delete (defaults to selected
                    flags only when traces is also defaulted)
                log_event (bool): True if event should be logged
        """
        modified = False

        traces_defaulted = traces is None
        if traces_defaulted:
            traces = self.selected_traces.copy()

        for trace in traces:
            modified = True
            self.removeTrace(trace, log_event)
            if trace in self.selected_traces:
                self.selected_traces.remove(trace)

        if flags is None:
            # fall back to the selected flags only when the caller also
            # defaulted traces (i.e. "delete the selection"); callers that
            # pass an explicit trace list (cut/merge/scalpel/scissors) must
            # not delete selected flags as a side effect
            flags = self.selected_flags.copy() if traces_defaulted else []
        
        for flag in flags:
            modified = True
            self.removeFlag(flag, log_event)
            if flag in self.selected_flags:
                self.selected_flags.remove(flag)

        return modified
    
    def translateTraces(self, dx : float, dy : float, log_event=True):
        """Translate the selected traces.
        
            Params:
                dx (float): x-translate
                dy (float): y-translate
                log_event (bool): True if event should be logged
        """
        tform = self.tform

        for trace in self.selected_traces:
            self.removeTrace(trace, log_event=False)
            for i, p in enumerate(trace.points):
                # apply forward transform
                x, y = tform.map(*p)
                # apply translate
                x += dx
                y += dy
                # apply reverse transform
                x, y = tform.map(x, y, inverted=True)
                # replace point
                trace.points[i] = (x, y)
            self.addTrace(trace, log_event=False)
            if log_event:
                self.series.addLog(trace.name, self.n, "Modify trace(s)")
        
        for ztrace, i in self.selected_ztraces:
            x, y, snum = ztrace.points[i]
            # apply forward tform
            x, y = tform.map(x, y)
            # apply translate
            x += dx
            y += dy
            # apply reverse transform
            x, y = tform.map(x, y, inverted=True)
            # replace point
            ztrace.points[i] = (x, y, snum)
            # keep track of modified ztrace
            self.series.modified_ztraces.add(ztrace.name)
            if log_event:
                self.series.addLog(ztrace.name, self.n, "Modify ztrace")
        
        for flag in self.selected_flags:
            # apply forward tform
            x, y = tform.map(flag.x, flag.y)
            # apply translate
            x += dx
            y += dy
            # apply reverse tform
            x, y = tform.map(x, y, inverted=True)
            # replace point
            flag.x, flag.y = x, y
            # keep track of modified flag
            if log_event:
                self.series.addLog(None, self.n, "Modify flag")
    
    def addImportFlag(self, prefix : str, cname : str, trace : Trace, comment : str):
        """Flag a trace an import acted on, with a comment saying why.

            Params:
                prefix (str): the flag name prefix, e.g. "import-removed"
                cname (str): the name of the contour
                trace (Trace): the trace to flag (used for position and colour)
                comment (str): the explanation shown to the reviewer
        """
        x, y = trace.getCentroid()
        flag = Flag(f"{prefix}_{cname}", x, y, self.n, trace.color)
        flag.addComment(self.series.user, comment)
        self.flags.append(flag)

    def flagImportConflicts(self, cname : str, traces : list, reason : str):
        """Flag traces an import kept because it could not safely choose between them.

            Params:
                cname (str): the name of the contour
                traces (list): the traces to flag
                reason (str): the explanation shown to the reviewer
        """
        for trace in traces:
            self.addImportFlag("import-conflict", cname, trace, reason)

    def recordImportRemoval(self, cname : str, traces : list, reason : str):
        """Record traces that an import removed, as a flag and as a log entry.

        An import is only ever allowed to destroy annotation work that a human's
        own recorded action licenses, and never without leaving behind both a
        flag a reviewer can find and a log entry the next merge can see. This is
        deliberately NOT gated on the "flag conflicts" option: that option is
        about conflicts, where both versions survive and somebody has to choose.
        A record of destroyed work is not optional.

            Params:
                cname (str): the name of the contour
                traces (list): the traces that were removed
                reason (str): the explanation shown to the reviewer
        """
        if not traces:
            return

        for trace in traces:
            self.addImportFlag(
                "import-removed", cname, trace,
                f"Trace removed by an import: {reason}.",
            )

        self.series.addLog(cname, self.n, "Remove trace(s) during import")

    def importTraces(
            self,
            other,
            regex_filters: list=[],
            group_filters: list=[],
            threshold : float=0.95, 
            flag_conflicts : bool=True, 
            histories : LogSetPair=None, 
            keep_above : str="self",
            keep_below : str="",
            dt_str : str=None
    ):
        """Import the traces from another section.
        
            Params:
                other (Section): the section with traces to import
                regex_filters (list): regex filters for objects
                group_filters (list): group filters for objects
                threshold (float): the overlap threshold
                flag_conflicts (bool): True if conflicts should be flagged
                histories (LogSetPair): the self history and the other history
                keep_above (str): the series that is favored for functional duplicates (above the overlap threshold; "self", "other", or "")
                keep_below (str): the series that is favored in the case of a conflict (overlap not reaching the threshold; "self", "other", or "")
                dt_str (str): the datetime string for tagging purposes
        """

        all_contour_names = list(
            set(self.contours.keys()) | set(other.contours.keys())
        )

        if group_filters:

            other_groups = other.series.object_groups.getGroupDict()
        
        for cname in all_contour_names:

            if not passesFilters(cname, regex_filters):

                continue

            if group_filters:

                passes_filter = False

                for gf in group_filters:

                    if cname in other_groups[gf]:
                        passes_filter = True

                if not passes_filter:

                    continue

            ## Flag as modified
            self.modified_contours.add(cname)

            ## Create empty contour if does not exist
            if cname not in self.contours:
                self.contours[cname] = Contour(cname, [])
                
            if cname not in other.contours:
                other.contours[cname] = Contour(cname, [])
            
            ## Adjust contours in other series to match current series mag
            mags_match = abs(other.mag - self.mag) <= 1e-8

            if not mags_match:
                
                for trace in other.contours[cname]:
                    trace.magScale(other.mag, self.mag)

            # Check the histories to find which contour has been modified since
            # the two series diverged.
            #
            # The history gives one Boolean per side: "does this side's log
            # mention this contour after the divergence point?" A True is
            # positive evidence that somebody edited the contour. A False is
            # only SILENCE, and silence is not proof that a side is unchanged --
            # logs get trimmed, get rewritten when an object is deleted, and are
            # suppressed outright while an import runs, so anything a previous
            # merge brought in reads as untouched. Acting on a False therefore
            # used to destroy real annotation work: the (False, False) branch
            # discarded the other contour whole and the (False, True) branch
            # replaced ours with theirs, in both cases without comparing a
            # single point and without leaving a flag behind.
            #
            # So the shortcut is now checked against the data before it is
            # taken. It may discard a trace only if that trace overlaps
            # something on the surviving side (making it a version of it) or if
            # a log entry records it as deliberately removed -- and a discarded
            # trace always leaves a flag and a log entry. Anything else is
            # independent work, which means the history cannot decide this
            # contour: keep both sides and flag the disagreement.
            history_orphans = []

            if histories and not histories.complete_match and histories.last_shared_index >= 0:
                # determine which series have been modified since diverge
                modified_since_diverge = histories.getModifiedSinceDiverge(cname, self.n)

                # (True, True) is the case a merge exists for; fall through to
                # the geometric merge below. Everything else has a shortcut.
                if not all(modified_since_diverge):
                    # the shortcut keeps one contour and discards the other: the
                    # side the log says changed, or -- when the log mentions
                    # neither -- the current series', which the two contours are
                    # being assumed to already agree on
                    take_other = modified_since_diverge[1]
                    keeper = other.contours[cname] if take_other else self.contours[cname]
                    donor = self.contours[cname] if take_other else other.contours[cname]

                    # the traces the shortcut would destroy outright
                    orphans = tracesWithoutCounterpart(donor, keeper)

                    # only ask the log about a removal if something is at stake:
                    # the scan is linear in the log length
                    deliberate = bool(orphans) and histories.getRemovedSinceDiverge(
                        cname, self.n
                    )[1 if take_other else 0]

                    if orphans and not deliberate:
                        # The log claims one side is untouched, yet that side
                        # holds traces the other has nothing over at all, and
                        # nothing in the log says they were removed on purpose.
                        # Decline the shortcut: the geometric merge below keeps
                        # both sides, and these traces get flagged.
                        history_orphans = orphans
                    else:
                        if take_other:
                            self.contours[cname] = other.contours[cname]
                        if orphans:
                            # a removal recorded by a human is being propagated;
                            # it is allowed to destroy work, but never silently
                            self.recordImportRemoval(
                                cname,
                                orphans,
                                "the other series' history records it as deliberately removed"
                                if take_other else
                                "this series' history records it as deliberately removed",
                            )
                        if self.contours[cname].isEmpty(): del(self.contours[cname])  # remove contour from self if empty
                        continue

            # import the contour
            ## self.mag, not other.mag: the loop above has already brought the
            ## other series' traces onto this section's magnification with
            ## Trace.magScale, so the comparison happens entirely in these units.
            conflict_traces_s, conflict_traces_o = self.contours[cname].importTraces(
                other.contours[cname], threshold, keep_above, self.mag
            )

            # A history shortcut was declined above because it would have
            # destroyed traces with no counterpart on the surviving side. The
            # merge has kept them; flag them here, before the short-circuit
            # below, because one of the conflict pools is usually empty in this
            # situation and the flagging step at the bottom would skip them.
            if history_orphans and flag_conflicts:
                self.flagImportConflicts(
                    cname,
                    history_orphans,
                    "kept because the two series' histories disagree with their "
                    "traces: one history reports this contour unmodified, but "
                    "this trace has no counterpart in the other series",
                )

            # if one or both series have no conflicts, no need to flag them or check for favor below the threshold
            if not conflict_traces_s or not conflict_traces_o:
                if self.contours[cname].isEmpty(): del(self.contours[cname])  # remove contour from self if empty
                continue

            # iterate through conflict pool and favor the requested traces
            if keep_below in ("self", "other"):
                # set traces1 variable to be favored traces and traces2 to be unfavored traces
                if keep_below == "self":
                    traces1, traces2 = conflict_traces_s, conflict_traces_o
                elif keep_below == "other":
                    traces1, traces2 = conflict_traces_o, conflict_traces_s
                # iterate through traces and delete overlaps in unfavored series
                removed_by_policy = []
                for trace1 in traces1:
                    for trace2 in traces2.copy():
                        ## open_curve=False for the same reason as
                        ## tracesWithoutCounterpart above, which is written out
                        ## there: threshold=0 asks "do these overlap at all", the
                        ## curve metric was measured for "are these the same
                        ## trace", and this site deletes a trace on the answer.
                        if trace1.overlaps(trace2, threshold=0, open_curve=False):
                            traces2.remove(trace2)
                            self.contours[cname].remove(trace2)
                            removed_by_policy.append(trace2)
                # clear favored traces, as they will never be conflicts
                traces1.clear()
                # any traces left in unfavored traces will be flagged
                #
                # The two lines above are why this needs recording: the
                # unfavoured traces have been removed from the contour and the
                # favoured pool has been emptied, so the flagging step below has
                # nothing left to flag and the traces would simply be gone.
                if removed_by_policy:
                    favoured = (
                        "the current series"
                        if keep_below == "self" else "the importing series"
                    )
                    self.recordImportRemoval(
                        cname,
                        removed_by_policy,
                        "the import was asked to keep traces from "
                        f"{favoured} only where the overlap is below the threshold",
                    )

            # flag the remaining conflicts
            if flag_conflicts:                                     
                for trace in conflict_traces_s:
                    if dt_str:
                        trace.tags.add(f"{dt_str}-ic1")
                    x, y = trace.getCentroid()
                    self.flags.append(Flag(f"import-conflict_{trace.name}", x, y, self.n, trace.color))
                for trace in conflict_traces_o:
                    if dt_str:
                        trace.tags.add(f"{dt_str}-ic2")
                    x, y = trace.getCentroid()
                    self.flags.append(Flag(f"import-conflict_{trace.name}", x, y, self.n, trace.color))
            
            if self.contours[cname].isEmpty(): del(self.contours[cname])  # remove contour from self if empty

        # An import rebinds whole contour trace lists rather than going through
        # addTrace/removeTrace, so there is no sequence of row operations to
        # mirror. Rebuild the store from the result instead of pretending it was
        # tracked -- which is honest but limited, and the limit is worth stating
        # plainly: the consistency check proves nothing about the inside of an
        # import, only that the two agree once it returns. Modelling an import
        # as store operations is later work.
        #
        # `other` is rebuilt too, because the mag loop above rewrote ITS traces'
        # coordinates in place and the loop over `other.contours` above created
        # empty contours on it. `_dualWriteResync` on both rather than
        # `resyncColumnarStore`, because either side may be a `Section.__new__`
        # stand-in that never built a store, and inventing one here would turn a
        # deliberate test shortcut into a construction error.
        self._dualWriteResync()
        other._dualWriteResync()

        self.save()

    def addSelectedTrace(self, trace : Trace):
        """Add a trace to the selected trace list.

        Locking an object does not affect selection. Lock prevents mutations
        that change quantitative data (traces added, deleted or modified), and
        every field operation that does one of those carries its own check:
        `FieldWidgetTrace.refuseLockedTraces` for the six that read the
        selection directly, `trace_function` for the trace context menu and
        `object_function(update_objects=True)` for the object one.

        This used to refuse a locked object's trace, which made it the only
        thing standing between a locked object and those operations. It was
        also visible to the user as an inconsistency: the field's invert
        selection silently skipped locked objects while the object list
        selected locked rows freely.

            Params:
                trace (Trace): the trace to append to the list.
        """
        self.selected_traces.append(trace)

    def exportAsSVG(self, svg_fp):
        """Export untransformed section as svg."""

        return export_svg(self, svg_fp)

    def exportAsPNG(self, png_fp, scale: float=1.0):
        """Export untransformed section as png."""

        return export_png(self, png_fp, scale)
        

class TransformsDict(dict):
    
    def __init__(self):
        super().__init__()
        self["no-alignment"] = Transform.identity()
    
    def __setitem__(self, key, value) -> None:
        if key == "no-alignment" and not value.equals(Transform.identity()):
            raise Exception("Cannot change transform for 'no-alignment'.")
        else:
            return super().__setitem__(key, value)
    
    def __delitem__(self, key) -> None:
        if key == "no-alignment":
            raise Exception("Cannot delete transform for 'no-alignment'.")
        else:
            return super().__delitem__(key)
