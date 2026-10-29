"""Collect data to pass to table manager."""

import contextlib
from typing import Optional, Union

from PyReconstruct.modules.calc import traceGeometry
from PyReconstruct.modules.constants import EXPORT_ERRORS

from .columnar_store import TraceView
from .object_ids import ObjectIds
from .section import Section
from .section_rows import SectionRows, fileRowClosed, measureGeometries, openLoader
from .transform import Transform
from .trace import Trace


class TraceData():

    def __init__(self, trace : Trace, index : int, tform : Transform, points=None):
        """Create a trace table item.
        
            Params:
                trace (Trace): the trace object for the trace, or a `TraceView`
                    of its row in the section's columnar store
                tform (Transform): the transform applied to the trace
                points: the trace's points, if not `trace.points`. The store
                    passes its own (n, 2) float64 array, so no list of tuples
                    is built and then converted back to an array.
        """
        self.index = index
        self.closed = trace.closed
        self.hidden = trace.hidden
        self.negative = trace.negative
        self.tags = trace.tags
        # A tuple so it hashes (color counting keys on it); None for a trace
        # with no color, which stays distinct from every real color.
        self.color = tuple(trace.color) if trace.color else None

        # Map the points through the tform ONCE, then compute length, area,
        # centroid, and radius together in a single vectorized NumPy pass
        # (traceGeometry). This replaces four separate Python loops over the
        # points -- lineDistance + area + centroid + a max-distance radius, each
        # re-walking the points and calling distance() -- which were the dominant
        # cost of a series refresh on large autoseg jsers (~27s of a 31s refresh
        # at 61k traces). traceGeometry is verified equivalent to those scalar
        # functions: length/area/centroid identical, radius within machine
        # epsilon. For affine tforms the centroid of the mapped points equals the
        # mapped centroid of the raw points (up to rounding).
        pts = tform.mapPointsArray(trace.points if points is None else points)
        if len(pts):
            length, trace_area, (cx, cy), radius = traceGeometry(pts, self.closed)
        else:
            length, trace_area, (cx, cy), radius = 0.0, 0.0, (0.0, 0.0), 0.0

        self.length = length
        if not self.closed:
            self.area = 0
        else:
            self.area = -trace_area if self.negative else trace_area
        self.centroid = (cx, cy)
        self.radius = radius

        # Defer the expensive convex-hull Feret diameter. It is only read by the
        # per-section trace table and CSV export, never by the object table, so
        # computing it for every trace up front (a third of the geometry cost)
        # is wasted on most series.
        #
        # Nothing is kept for it. Holding the mapped points until the Feret is
        # first read (which on most series is never) made this object the
        # largest per-trace allocation in a loaded series: 16 bytes per point
        # plus array overhead, retained for the lifetime of the series data,
        # ~1.3 KB per trace on autoseg contours. Both readers already hold the
        # section the trace is on, so getFeret() recomputes from the live trace
        # instead, then caches the two numbers.
        #
        # The transform is kept because it must be the one this data was built
        # with -- the object may pin a fixed alignment -- and it is a per-section
        # shared object already retained by the series data, so this costs one
        # pointer per trace.
        self._tform = tform
        self._feret = None if self.closed else (0, 0)

    @classmethod
    def fromGeometry(cls, index : int, closed : bool, hidden : bool, negative : bool,
                     tags : set, color, geometry : tuple, tform : Transform):
        """The TraceData `__init__` builds, from numbers already measured.

            Params:
                color (tuple): the trace's color, or None
                geometry (tuple): (length, area, (cx, cy), radius) from
                    traceGeometry of the trace's mapped points
            Other params are the trace's own fields, as `__init__` reads them.
        """
        self = cls.__new__(cls)
        self.index = index
        self.closed = closed
        self.hidden = hidden
        self.negative = negative
        self.tags = tags
        self.color = color
        length, trace_area, self.centroid, self.radius = geometry
        self.length = length
        if not closed:
            self.area = 0
        else:
            self.area = -trace_area if negative else trace_area
        self._tform = tform
        self._feret = None if closed else (0, 0)
        return self

    def getTags(self):
        return self.tags

    def getLength(self):
        return self.length
    
    def getArea(self):
        return self.area
    
    def getRadius(self):
        return self.radius

    def getCentroid(self):
        return self.centroid

    def getFeret(self, section : Section, name : str):
        """Get the min and max Feret diameters of the trace.

        Computed from the live trace on the given section, and cached. The
        section must be the one this data was built from: the trace is found by
        the index this data was built with, the same way the trace table already
        resolves a table row back to its trace.

            Params:
                section (Section): the section the trace is on
                name (str): the name of the object the trace belongs to
            Returns:
                (tuple): the min and max Feret diameters (0, 0 if not closed),
                    or None if the trace is not on the given section
        """
        if self._feret is None:

            contour = section.contours.get(name)

            if contour is None or self.index >= len(contour):

                ## A series-wide operation writes its sections and updates this
                ## data before the field reloads the section it is displaying,
                ## so a table row can briefly exist for a trace the displayed
                ## section does not have. Nothing to measure until the reload
                ## rebuilds the row against the section that does have it.
                return None

            trace = contour[self.index]

            ## a closed trace with no points has no hull and no extent
            self._feret = trace.getFeret(self._tform) if trace.points else (0, 0)

        return self._feret

    def __lt__(self, other):
        return self.index < other.index


class TraceColumns():

    ## The fields, in the order `rows` hands them out
    FIELDS = (
        "snum", "index", "closed", "hidden", "negative", "tag", "color",
        "length", "area", "cx", "cy", "radius", "tform",
    )

    def __init__(self, arrays : dict, tags : list, colors : list, tforms : list):
        """The object-list numbers of many traces, one array per field.

        An open from the local store (store_open.py) fills one of these
        instead of building a TraceData per trace. Each object's rows are
        one run, in section order and then index order, the order an open
        appends TraceData in.

            Params:
                arrays (dict): field name -> numpy array, one entry per trace.
                    "tag", "color" and "tform" index the three lists below
                tags (list): the distinct tag values (frozensets)
                colors (list): the distinct colors (tuples, or None)
                tforms (list): the distinct transforms
        """
        self.arrays = arrays
        self.tags = tags
        self.colors = colors
        self.tforms = tforms
        self._lists : dict = {}

    def column(self, field : str) -> list:
        """One field for every trace, as Python values (built once, on first use)."""
        values = self._lists.get(field)
        if values is None:
            values = self._lists[field] = self.arrays[field].tolist()
        return values

    def rows(self, start : int, stop : int, *fields):
        """The given fields of the rows from start to stop, one tuple per row."""
        return zip(*(self.column(f)[start:stop] for f in fields))

    def traceData(self, start : int, stop : int):
        """(section number, TraceData) for each row, as an open from the store
        built them before the columns."""
        tags, colors, tforms = self.tags, self.colors, self.tforms
        for (snum, index, closed, hidden, negative, tag, color,
             length, area, cx, cy, radius, tform) in self.rows(start, stop, *self.FIELDS):
            td = TraceData.__new__(TraceData)
            td.index = index
            td.closed = closed
            td.hidden = hidden
            td.negative = negative
            # a fresh set, as a full open gives each TraceData (TraceView.tags)
            td.tags = set(tags[tag])
            td.color = colors[color]
            td.length = length
            # an open trace's area is the int 0, as TraceData.__init__ sets it
            # (the trace CSV writes it as "0", not "0.0")
            td.area = area if closed else 0
            td.centroid = (cx, cy)
            td.radius = radius
            td._tform = tforms[tform]
            td._feret = None if closed else (0, 0)
            yield snum, td


class ObjectData():

    def __init__(self, columns : Optional[TraceColumns] = None, start : int = 0, stop : int = 0):
        """Create an object data object.

            Params:
                columns (TraceColumns): an open from the local store's
                    columns holding this object's traces, rows start to
                    stop. Its TraceData are built when something first
                    reads `traces`.
        """
        self._traces : dict = {}
        self._rows : Optional[tuple] = (columns, start, stop) if columns is not None else None

    @property
    def traces(self) -> dict:
        """Section number -> list of TraceData."""
        if self._rows is not None:
            columns, start, stop = self._rows
            self._rows = None
            for snum, td in columns.traceData(start, stop):
                self._traces.setdefault(snum, []).append(td)
        return self._traces

    @traces.setter
    def traces(self, value : dict):
        self._rows = None
        self._traces = value

    def columnRows(self):
        """(TraceColumns, start, stop) while the TraceData are not built, else None."""
        return self._rows

    def isEmpty(self) -> bool:
        """Return True of object data is empty."""
        if self._rows is not None:
            return self._rows[1] == self._rows[2]
        return not bool(self._traces)
    
    def addTrace(self, trace : Trace, section : Section, series, points=None):
        """Add a trace to the object data.
        
            Params:
                trace (Trace): the trace to add
                section (Section): the section containing the trace
                series (Series): the series containing the trace
                points: passed on to `TraceData`
        """
        if section.n not in self.traces:
            self.traces[section.n] = []

        tform = ObjectData.sectionTransform(trace.name, section, series)

        i = len(self.traces[section.n])
        
        self.traces[section.n].append(
            TraceData(trace, i, tform, points)
        )
    
    @staticmethod
    def sectionTransform(name : str, section : Section, series) -> Transform:
        """The transform an object's traces on a section are measured with.

        The object's own alignment, or the series alignment when it has none.
        An alignment the section lacks is cleared from the object first.
        """
        alignment = series.getAttr(name, "alignment")

        if alignment is None:

            alignment = series.alignment

        elif alignment not in section.tforms:

            series.setAttr(name, "alignment", None)
            alignment = series.alignment

        return section.tforms[alignment]

    def clearSection(self, snum : int):
        """Clear the traces on a specific section.
        
            Params:
                snum (int): the section number to clear
        """
        if snum in self.traces:
            del(self.traces[snum])


def traceDataForRows(store, rows : list, tform : Transform) -> list:
    """One TraceData per row of a section's columnar store, built together.

    Each is the TraceData `TraceData(TraceView(store, row), i, tform,
    store.getCoordinates(row))` builds, to the bit, with `index` set to its
    place in `rows`; the caller sets it when the rows are split.
    """
    # a list of int per row, as `getColor` gives it
    colors = store.colorColumn[rows].tolist()
    return measureTraceData(
        [store.getCoordinates(row) for row in rows],
        store.flagColumn("closed")[rows].tolist(),
        store.flagColumn("hidden")[rows].tolist(),
        store.flagColumn("negative")[rows].tolist(),
        [store.getTags(row) for row in rows],
        [tuple(c) if c else None for c in colors],
        tform,
    )


def traceDataForFileRows(items : list, tform : Transform) -> list:
    """One TraceData per (coordinates, row) of a section file's plain rows
    (section_rows.py), built together: the TraceData `traceDataForRows`
    gives for the same rows after `Section.__init__` and its store read them.
    """
    coordinates = [c for c, _ in items]
    rows = [r for _, r in items]
    return measureTraceData(
        coordinates,
        [fileRowClosed(c, r) for c, r in items],
        *_rowFields(rows),
        tform,
    )


def traceDataForMeasuredRows(items : list, tform : Transform, measured : tuple, tforms) -> list:
    """`traceDataForFileRows` for the (name, index, row) of rows a worker
    process measured (`SectionRows.measured`), from its numbers."""
    closed, geometries = measured
    for alignment, by_name in geometries.items():
        if tforms[alignment] is tform:
            break
    return measureTraceData(
        [],
        [closed[name][i] for name, i, _ in items],
        *_rowFields([r for _, _, r in items]),
        tform,
        [by_name[name][i] for name, i, _ in items],
    )


def _rowFields(rows : list) -> tuple[list, list, list, list]:
    """hidden, negative, tags and color of plain rows, as TraceData reads them."""
    return (
        [bool(r[5]) for r in rows],
        [bool(r[4]) for r in rows],
        [set(r[7]) for r in rows],
        # a plain row's color is three ints from 0 to 255
        [tuple(r[2]) for r in rows],
    )


def measureTraceData(coordinates : list, closed : list, hidden : list, negative : list,
                     tags : list, colors : list, tform : Transform, geometries=None) -> list:
    """One TraceData per trace, its points mapped and measured in one pass
    (or `geometries`, measured already, and `coordinates` is not read); the
    lists hold one entry per trace, `index` is left at 0."""
    if geometries is None:
        geometries = measureGeometries(coordinates, closed, tform)
    return [
        TraceData.fromGeometry(
            0, closed[k], hidden[k], negative[k], tags[k], colors[k], geometries[k], tform,
        )
        for k in range(len(closed))
    ]


class SeriesData():

    def __init__(self, series):
        """Create a series data object.
        
            Params:
                series (Series): the series to keep track of data
        """
        self.series = series
        self.data = {
            "sections": {},
            "objects": {},
        }
        self.supress_logging = False
        # in-memory object ids, kept in step with the traces below
        self.object_ids = ObjectIds(series)
    
    def __getitem__(self, index):
        """Allow direct indexing of data dictionary."""
        return self.data[index]

    @property
    def objects(self):
        """Return all object data."""

        return self.data["objects"]

    @property
    def traces(self):
        """Return all trace data by object."""

        trace_data = {}

        for obj_name, obj_data in self.objects.items():

            trace_data[obj_name] = obj_data.traces

        return trace_data
    
    def refresh(self, message="Loading series data...", show_progress=True, from_rows=False):
        """Completely refresh the series data.

            Params:
                message (str): the progress text. `Series.__init__` names the
                    series it opens; a refresh of the open series keeps the
                    default.
                show_progress (bool): False to show no progress bar at all
                from_rows (bool): True to read each section's rows without
                    building a `Section` (`addOpenedSection`), as an open does
        """

        self.data = {
            "sections": {},
            "objects": {},
        }

        # No time estimate here: this is the pass behind the "Opening
        # <name>..." bar when a series opens, and an opening series must not
        # carry one (decided 2026-09-14). Every other operation bar does.
        with contextlib.ExitStack() as stack:
            load = stack.enter_context(openLoader(self.series)) if from_rows else None
            for snum, section in self.series.enumerateSections(
                show_progress=show_progress, message=message, eta=False, load=load,
            ):

                self.addOpenedSection(section)

        # the ids carry over: traces that are still there keep their ids
        # (a renumbering moved them already, Series.reorderSections)
        self.object_ids.reconcile(
            (snum, name)
            for name, obj_data in self.data["objects"].items()
            for snum in obj_data.traces
        )
    
    def updateSection(self, section : Section, update_traces=False, all_traces=True, log_events=True, read_store=False):
        """Update the existing section data.
        
            Params:
                section (Section): the section with data to update
                update_traces (bool): True if all traces should also be updated
                all_traces (bool): True if all traces on the section should be updated IF NO TRACES HAVE BEEN MARKED AS MODIFIED
                log_events (bool): True if events (creating and deleting objects) should be logged
                read_store (bool): True to read the traces from the section's
                    columnar store instead of `section.contours`. Only for a
                    section just loaded from its file, as the series-open pass
                    does, where the store was built from the contours a moment
                    earlier. `Section.save` reads the contours: an edit made
                    outside `Section` can make the store stale until the save
                    rebuilds it, and the save updates the series data first.
        """
        # create/update the data for a section
        if section.n not in self.data["sections"]:
            
            d = {
                "thickness": section.thickness,
                "calgrid": section.calgrid,
                "locked": section.align_locked,
                "bc_profiles": section.bc_profiles.copy(),
                "src": section.src,
                "mag": section.mag,
                "flags": [f.copy() for f in section.flags],
                "tforms": section.tforms.copy()
            }
            
            self.data["sections"][section.n] = d
            
        else:
            
            d = self.data["sections"][section.n]
            d["thickness"] = section.thickness
            d["locked"] = section.align_locked
            d["bc_profiles"] = section.bc_profiles.copy()
            d["src"] = section.src
            d["mag"] = section.mag
            d["flags"] = [f.copy() for f in section.flags]
            d["tforms"] = section.tforms.copy()
        
        if update_traces:
            
            ## Check if there are specific traces to be updated
            trace_names = section.getAllModifiedNames()

            if section.tformsModified(scaling_only=True) or (all_traces and not trace_names):
                trace_names = section.contours.keys()

            ## Keep track of objects that are newly created/destroyed
            added_objects = set()
            removed_objects = set()

            ## Only a Section built through `Section.__new__` has no store
            store = section._columns if read_store else None

            ## From the store, every trace on the section is measured in one
            ## pass after the clearing below (traceDataForRows)
            named_rows = self._storeRows(store, section, trace_names) if store is not None else None

            ## Clear existing trace data on this section
            for name in trace_names:
                
                ## Check if object is new
                if name in self.data["objects"]:
                    self.data["objects"][name].clearSection(section.n)
                    
                ## Add new trace data
                if named_rows is None and name in section.contours:
                    if store is not None:
                        traces = (
                            (TraceView(store, row), store.getCoordinates(row))
                            for row in store.rowsForContour(name)
                        )
                    else:
                        traces = ((trace, None) for trace in section.contours[name])
                    for trace, points in traces:
                        is_new_object = self.addTrace(trace, section, points)
                        if is_new_object:
                            added_objects.add(name)

            if named_rows is not None:
                added_objects.update(self._addStoreRows(store, section, named_rows))
            
            ## Check for removed objects
            for name in trace_names:
                if name in self.data["objects"]:
                    obj_data = self.data["objects"][name]
                    if obj_data.isEmpty():
                        del(self.data["objects"][name])
                        removed_objects.add(name)

            ## Keep the object ids in step (object_ids.py). An object emptied
            ## here is deleted (removeObjAttrs below) only when events are
            ## logged; otherwise (an import, a refresh) the host tree keeps
            ## its id, so it keeps its links, as the object keeps its
            ## attributes.
            ids = self.object_ids
            keep = not (log_events and not self.supress_logging)
            for name in trace_names:
                obj_data = self.data["objects"].get(name)
                if obj_data is not None and section.n in obj_data.traces:
                    ids.ensure(section.n, name)
                else:
                    ids.drop(section.n, name, keep=keep)

            ## Log newly created/destroyed objects
            if log_events and not self.supress_logging:

                for obj_name in added_objects:

                    self.series.addLog(obj_name, None, "Create object")
                    ## Set the fixed alignment of the object to creation,
                    ## unless it already has one (a renamed object brings its own)
                    if self.series.getAttr(obj_name, "alignment") is None:
                        self.series.setAttr(obj_name, "alignment", self.series.alignment)

                for obj_name in removed_objects:

                    self.series.addLog(obj_name, None, "Delete object")
                    ## Remove object from object attributes dicts
                    self.series.removeObjAttrs(obj_name)
    
    def addOpenedSection(self, section):
        """Add a section an open loaded (`loadForOpen`): a `Section`, or the
        `SectionRows` of a section not yet in the series data.

        From `SectionRows`, the same data `updateSection(section,
        update_traces=True, log_events=False, read_store=True)` gives for
        the `Section` built from the same file: the same section entry, the
        same objects created in the same order, the same TraceData, and the
        same object-id calls.
        """
        if not isinstance(section, SectionRows):
            self.updateSection(section, update_traces=True, log_events=False, read_store=True)
            return
        ## the section entry (updateSection reads the same attributes)
        self.updateSection(section)
        objects = self.data["objects"]
        named_rows = []
        measured = section.measured
        for name, rows in section.contours.items():
            if name in objects:
                objects[name].clearSection(section.n)
            if not rows:
                continue
            if measured is None:
                named_rows.append((name, list(zip(section.coordinates[name], rows))))
            else:
                named_rows.append((name, [(name, i, row) for i, row in enumerate(rows)]))
        if measured is None:
            self._addMeasured(section, named_rows, traceDataForFileRows)
        else:
            self._addMeasured(
                section, named_rows,
                lambda items, tform: traceDataForMeasuredRows(items, tform, measured, section.tforms),
            )
        ## a name with rows has traces now, so no object is emptied; the
        ## object ids as updateSection keeps them with log_events off
        ids = self.object_ids
        for name in section.contours:
            obj_data = objects.get(name)
            if obj_data is not None and section.n in obj_data.traces:
                ids.ensure(section.n, name)
            else:
                ids.drop(section.n, name, keep=True)

    def _storeRows(self, store, section : Section, trace_names) -> Optional[list]:
        """(name, rows) for each name with traces on the section, in order.

        None if a row carries a name other than its contour's: the traces then
        go one at a time, under the name each carries, as before.
        """
        named_rows = []
        for name in trace_names:
            if name not in section.contours:
                continue
            rows = store.rowsForContour(name)
            if not rows:
                continue
            for row in rows:
                if store.getName(row) != name:
                    return None
            named_rows.append((name, rows))
        return named_rows

    def _addStoreRows(self, store, section : Section, named_rows : list) -> list:
        """Add the TraceData of every (name, rows), measured together, and
        return the names of the objects this created.

        The same TraceData, in the same order, as adding the rows one at a
        time with addTrace. Rows measured with one transform are measured in
        one pass; an object with its own alignment can have another.
        """
        return self._addMeasured(
            section, named_rows, lambda rows, tform: traceDataForRows(store, rows, tform)
        )

    def _addMeasured(self, section, named_rows : list, measure) -> list:
        """`_addStoreRows`, with `measure(rows, tform)` giving the TraceData
        of a list of rows.

        Objects are created in the order of `named_rows`, not in the order
        their transforms are measured in: the series data's object order
        follows the section's contour order.
        """
        objects = self.data["objects"]
        by_tform : dict = {}
        for name, rows in named_rows:
            tform = ObjectData.sectionTransform(name, section, self.series)
            by_tform.setdefault(id(tform), (tform, []))[1].append((name, rows))
        built : dict = {}
        for tform, group in by_tform.values():
            trace_data = measure([r for _, rows in group for r in rows], tform)
            start = 0
            for name, rows in group:
                built[name] = trace_data[start:start + len(rows)]
                for i, td in enumerate(built[name]):
                    td.index = i
                start += len(rows)
        created = []
        for name, _ in named_rows:
            obj_data = objects.get(name)
            if obj_data is None:
                objects[name] = obj_data = ObjectData()
                created.append(name)
            obj_data.traces[section.n] = built[name]
        return created

    def addTrace(self, trace : Trace, section : Section, points=None):
        """Add trace data to the existing object.
        
            Params:
                trace (Trace): the trace to add
                section (Section): the section containing the trace
                points: passed on to `TraceData`
            Returns:
                (bool): True if a new object was just created
        """
        ## Create section data if not present
        if section.n not in self.data["sections"]:
            
            self.updateSection(section, update_traces=True)
            return ## Assume trace already on section
        
        ## Create object if not present
        object_data = self.data["objects"]

        if trace.name not in object_data:

            new_object = True
            object_data[trace.name] = ObjectData()

        else:

            new_object = False
        
        object_data[trace.name].addTrace(trace, section, self.series, points)

        return new_object
    
    def getStart(self, obj_name : str) -> int:
        """Get the first section of the object.
        
            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None or obj_data.isEmpty():
            return None
        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, _ = rows
            return columns.column("snum")[start]
        
        return min(obj_data.traces.keys())
        
    def getEnd(self, obj_name : str) -> int:
        """Get the last section of the object.
        
            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None or obj_data.isEmpty():
            return None
        rows = obj_data.columnRows()
        if rows is not None:
            columns, _, stop = rows
            return columns.column("snum")[stop - 1]
        
        return max(obj_data.traces.keys())
    
    def getCount(self, obj_name : str) -> int:
        """Get the number of traces associated with the object.
        
            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None:
            return None
        rows = obj_data.columnRows()
        if rows is not None:
            return rows[2] - rows[1]
        
        c = 0
        for trace_list in obj_data.traces.values():
            c += len(trace_list)
        return c
    
    def getFlatArea(self, obj_name : str) -> float:
        """Get the flat area of the object.
        
            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None:
            return None
        
        fa = 0
        rows = obj_data.columnRows()
        if rows is not None:
            ## the same additions in the same order as the loop below
            columns, start, stop = rows
            sections = self.data["sections"]
            for snum, closed, area, length in columns.rows(start, stop, "snum", "closed", "area", "length"):
                if closed:
                    fa += area
                else:
                    fa += length * sections[snum]["thickness"]
            return fa
        for snum, trace_list in obj_data.traces.items():
            for trace_data in trace_list:
                if trace_data.closed:
                    fa += trace_data.getArea()
                else:
                    fa += trace_data.getLength() * self.data["sections"][snum]["thickness"]
        return fa

    def getVolume(self, obj_name : str) -> float:
        """Get the volume of the object.
        
            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)

        if obj_data is None:
            return None
        
        v = 0
        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, stop = rows
            sections = self.data["sections"]
            for snum, closed, area in columns.rows(start, stop, "snum", "closed", "area"):
                v += (area if closed else 0) * sections[snum]["thickness"]
            return v
        
        for snum, trace_list in obj_data.traces.items():
            
            for trace_data in trace_list:
                v += trace_data.getArea() * self.data["sections"][snum]["thickness"]
        
        return v

    def getConfiguration(self, obj_name: str) -> Union[str, None]:
        """Get the configuration of the object.

            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)

        if obj_data is None:
            return None

        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, stop = rows
            closed = columns.column("closed")[start:stop]
        else:
            closed = []
            for _, trace_list in obj_data.traces.items():

                for trace_data in trace_list:
                    closed.append(trace_data.closed)

        if sum(closed) == 0:
            config = "open"
            
        elif sum(closed) == len(closed):
            config = "closed"
            
        else:
            config = "mixed"

        return config
    
    def getTags(self, obj_name : str) -> set:
        """Get the tags associated with an object.

        Always a set, empty for an unknown object. Every caller treats the
        result as a set (len, union, join); the None this used to return for
        an unknown name crashed the Object List's Trace tags column when a
        row was re-queried mid-removal, after the object's data was already
        gone (user report: TypeError, can only join an iterable).

            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None:
            return set()

        tags = set()
        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, stop = rows
            for tag in set(columns.column("tag")[start:stop]):
                tags = tags.union(columns.tags[tag])
            return tags
        for trace_list in obj_data.traces.values():
            for trace_data in trace_list:
                tags = tags.union(trace_data.getTags())
        return tags

    def usedTags(self) -> set:
        """Every tag on a trace anywhere in the series.

        Read from this cache, which the field updates after each edit, so no
        section file is opened.
        """
        tags = set()
        tag_ids : dict = {}
        for obj_data in self.data["objects"].values():
            rows = obj_data.columnRows()
            if rows is not None:
                columns, start, stop = rows
                tag_ids.setdefault(columns, set()).update(columns.column("tag")[start:stop])
                continue
            for trace_list in obj_data.traces.values():
                for trace_data in trace_list:
                    if trace_data.tags:
                        tags.update(trace_data.tags)
        for columns, ids in tag_ids.items():
            for tag in ids:
                tags.update(columns.tags[tag])
        return tags

    def getColorCounts(self, obj_name : str) -> dict:
        """Traces per color for an object, across every section it is on.

        A dict mapping each distinct trace color (an RGB tuple, or None for
        a trace with no color) to how many of the object's traces carry it;
        empty for an unknown object. One key means the object's color is
        unanimous; more than one is the discrepancy the object attributes
        dialog renders as a split swatch, wherever in the series the
        minority traces live.

            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None:
            return {}

        counts = {}
        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, stop = rows
            colors = columns.colors
            for color in columns.column("color")[start:stop]:
                color = colors[color]
                counts[color] = counts.get(color, 0) + 1
            return counts
        for trace_list in obj_data.traces.values():
            for trace_data in trace_list:
                color = trace_data.color
                counts[color] = counts.get(color, 0) + 1
        return counts

    def getAvgRadius(self, obj_name : str) -> float:
        """Get the average stamp radius of an object.
        
            Params:
                obj_name (str): the name of the object to retrieve data for
        """
        obj_data = self.data["objects"].get(obj_name)
        if obj_data is None:
            return None
        
        rows = obj_data.columnRows()
        if rows is not None:
            columns, start, stop = rows
            radii = columns.column("radius")[start:stop]
        else:
            radii = []
            for trace_list in obj_data.traces.values():
                for trace_data in trace_list:
                    radii.append(trace_data.getRadius())
        avg_radius = sum(radii) / len(radii)

        return avg_radius

    def getZtraceDist(self, ztrace_name : str) -> float:
        """Get the distance of a ztrace.
        
            Params:
                ztrace_name (str): the name of the ztrace to retrieve data for
        """
        return self.series.ztraces[ztrace_name].getDistance(self.series)

    def getZtraceStart(self, ztrace_name : str) -> int:
        """Get the first section of a ztrace.
        
            Params:
                ztrace_name (str): the name of the ztrace to retrieve data for
        """
        return self.series.ztraces[ztrace_name].getStart()
    
    def getZtraceEnd(self, ztrace_name : str) -> int:
        """Get the last section of a ztrace.
        
            Params:
                ztrace_name (str): the name of the ztrace to retrieve data for
        """
        return self.series.ztraces[ztrace_name].getEnd()
    
    def clearSection(self, snum : int):
        """Clear the object data for a speicified section.
        
            Params:
                snum (int): the section number
        """
        for obj_data in self.data["objects"].values():
            obj_data.clearSection(snum)
        
    def getTraceData(self, name : str, snum : int) -> list:
        """Get the list of trace data objects.
        
            Params:
                name (str): the name of the object/trace
                snum (int): the section number
            Returns:
                (list): the list of TraceData objects
        """
        if name in self.data["objects"] and snum in self.data["objects"][name].traces:
            return self.data["objects"][name].traces[snum]
        return None

    def getFlagCount(self) -> int:
        """Get the number of flags in the series."""
        c = 0
        for data in self.data["sections"].values():
            c += len(data["flags"])
        return c
    
    def exportTracesCSV(self, out_fp : str = None):
        """Export all trace data to a CSV file.
        
            Params:
                out_fp (str): filepath of exported CSV (str returned if no filepath provided)
        """
        out_rows = ["Name,Section,Index,Hidden,Closed,Tags,Length,Area,Radius,Centroid-x,Centroid-y,Feret-Max,Feret-Min"]

        ## Iterate through all traces
        objs = self.data["objects"]

        ## The Feret diameters are computed from the trace points, which live on
        ## the sections rather than in this data, so the rows are built section
        ## by section -- one load per section for the whole export -- and then
        ## emitted per object. Walking objects first would reload every section
        ## once per object that appears on it.
        traces_by_section = {}

        for name, obj_data in objs.items():

            for snum, trace_list in obj_data.traces.items():

                if not trace_list:

                    continue

                traces_by_section.setdefault(snum, []).append((name, trace_list))

        rows_by_name = dict((name, []) for name in objs)

        for snum, section in self.series.enumerateSections(
            message="Exporting trace data...",
            section_numbers=sorted(traces_by_section)
        ):

            for name, trace_list in traces_by_section[snum]:

                for i, t in enumerate(trace_list):

                    hidden     = "yes" if t.hidden else "no"
                    closed     = "yes" if t.closed else "no"
                    tags       = ' '.join(t.getTags())
                    length     = round(t.getLength(), 7)
                    xs_area    = round(t.getArea(), 7)
                    radius     = round(t.getRadius(), 7)

                    centroid   = t.getCentroid()
                    centroid_x = round(centroid[0], 7)
                    centroid_y = round(centroid[1], 7)

                    ## left blank rather than reported as zero if the section on
                    ## file somehow does not have the trace this data was built
                    ## from (the caller writes the sections out first)
                    diameters  = t.getFeret(section, name)
                    feret_max  = round(diameters[1], 7) if diameters else ""
                    feret_min  = round(diameters[0], 7) if diameters else ""

                    vals = [
                        name,
                        snum,
                        i,
                        hidden,
                        closed,
                        tags,
                        length,
                        xs_area,
                        radius,
                        centroid_x,
                        centroid_y,
                        feret_max,
                        feret_min
                    ]

                    vals = list(map(str, vals))

                    rows_by_name[name].append(','.join(vals))

        ## Objects in name order; within an object the rows are already in
        ## ascending section then ascending index order
        for name in sorted(objs):

            out_rows += rows_by_name[name]

        out_str = "\n".join(out_rows) + "\n"

        # export the csv file
        if out_fp:
            with open(out_fp, "w", errors=EXPORT_ERRORS) as f:
                f.write(out_str)
        else:
            return out_str
    
    def getAvgMag(self):
        """Return the average magnification of the series."""
        mags = []
        for sdata in self.data["sections"].values():
            mags.append(sdata["mag"])
        return sum(mags) / len(mags)

    def getAvgThickness(self):
        """Return the average thickness of the series."""
        thicknesses = []
        for sdata in self.data["sections"].values():
            thicknesses.append(sdata["thickness"])
        return sum(thicknesses) / len(thicknesses)

    
