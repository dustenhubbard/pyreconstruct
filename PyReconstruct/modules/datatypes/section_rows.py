"""A section file read for the series data, with no `Section` built.

A series open (first open and resume) used to build every section through
`Section.__init__` only to hand it to `SeriesData.updateSection` and drop it.
The series data needs much less: the decoded rows after `Section.updateJSON`,
the transforms, flags and a few scalars. `SectionRows` holds just that, and
`SeriesData.addOpenedSection` measures its rows into the same numbers.

The trace ids are registered as `Section.__init__` registers them
(`Section.issueLoadedTraceIDs`, same inputs, same order), so the issuer ends
the open in the same state, and a later `Series.loadSection` of an unchanged
file gets the same ids back.

A section with any row that `Trace.fromList` or the columnar store reads in
its own way (`plainCoordinates`) is built as a `Section`, as before. That is
decided before the issuer is touched, so each section's ids are registered
once, by one path.
"""

import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from typing import Optional, Union

import numpy as np

from PyReconstruct.modules.calc import traceGeometries
from PyReconstruct.modules.constants import fast_loads

from .columnar_store import coordinatesFromRow
from .flag import Flag
from .section import Section, TransformsDict
from .trace import normalizeObjectName
from .trace_id import canonicalJSON, firstDerivedID, sectionFileDigest
from .transform import Transform


class SectionRows():
    """The parts of a section file the series data reads, after `updateJSON`.

    Carries the attribute names `SeriesData.updateSection` reads off a
    `Section` for the section's entry (thickness, calgrid, align_locked,
    bc_profiles, src, mag, flags, tforms), built the way `Section.__init__`
    builds them.
    """

    def __init__(self, n : int, section_data : dict, coordinates : dict):
        """
            Params:
                n (int): the section number
                section_data (dict): the decoded file after `updateJSON`
                coordinates (dict): name -> one (n, 2) array per row
                    (`plainCoordinates`)
        """
        self.n = n
        self.src = Section.imageName(section_data["src"])
        self.bc_profiles = section_data["brightness_contrast_profiles"]
        self.mag = section_data["mag"]
        self.align_locked = section_data["align_locked"]
        self.tforms = TransformsDict()
        for a in section_data["tforms"]:
            self.tforms[a] = Transform(section_data["tforms"][a])
        self.thickness = section_data["thickness"]
        ## name -> rows, in the file's (sorted) order
        self.contours = section_data["contours"]
        self.coordinates = coordinates
        self.flags = [Flag.fromList(l, n) for l in section_data["flags"]]
        self.calgrid = section_data["calgrid"]
        ## From a worker process of a large series' open (readFileRows):
        ## (name -> each row's closed flag, alignment -> name -> each row's
        ## geometry with that alignment's transform), or None. Its rows' x
        ## and y and `coordinates` are then None.
        self.measured = None


def fileRowClosed(coordinates, row) -> bool:
    """Whether a plain row's trace is closed: `Section.__init__` opens a
    two-point trace."""
    return False if len(coordinates) == 2 else bool(row[3])


def measureGeometries(coordinates : list, closed : list, tform : Transform) -> list:
    """traceGeometries of the traces' points mapped with `tform`."""
    points = tform.mapPointsArray(np.concatenate(coordinates))
    return traceGeometries(points, [len(c) for c in coordinates], closed)


def plainCoordinates(contours : dict) -> Optional[dict]:
    """Each row's points as an (n, 2) array, or None if any row is not plain.

    A plain row is one whose numbers in the series data do not depend on how
    `Trace.fromList` and the columnar store read it, so reading the row's
    fields directly gives the same values:

      * its contour name is already normalized (`Trace.fromList` strips it
        and the store normalizes it; `SeriesData._storeRows` then adds those
        traces one at a time under the new name);
      * it has 8 fields (a 9-field row names its own trace);
      * `coordinatesFromRow` reads its x and y, with more than one point
        (`Section.__init__` drops a shorter row);
      * its color is three ints from 0 to 255 (the store keeps `uint8`);
      * its fill mode is a list of strings and its tags a list.

        Params:
            contours (dict): name -> rows, after `updateJSON`
        Returns:
            (dict): name -> list of arrays, or None
    """
    coordinates = {}
    for name, rows in contours.items():
        if name != normalizeObjectName(name):
            return None
        arrays = []
        for row in rows:
            if type(row) is not list or len(row) != 8:
                return None
            x, y, color, _, _, _, fill_mode, tags = row
            array = coordinatesFromRow(x, y)
            if array is None or len(array) < 2:
                return None
            if type(color) is not list or len(color) != 3:
                return None
            for c in color:
                if type(c) is not int or not 0 <= c <= 255:
                    return None
            if type(fill_mode) is not list or any(type(m) is not str for m in fill_mode):
                return None
            if type(tags) is not list:
                return None
            arrays.append(array)
        coordinates[name] = arrays
    return coordinates


def readSectionRows(n : int, series) -> Optional[SectionRows]:
    """Read a section file and register its trace ids, as `Section.__init__`
    does, or return None (and touch nothing) if a row is not plain.

        Params:
            n (int): the section number
            series (Series): the series
    """
    # hidden trace file, filled first if it is a stub (lazy_sections.py)
    with open(series.presentSection(n), "rb") as f:
        raw = f.read()
    section_data = fast_loads(raw)
    stored_ids : dict = {}
    Section.updateJSON(section_data, n, stored_ids=stored_ids)
    coordinates = plainCoordinates(section_data["contours"])
    if coordinates is None:
        return None
    Section.issueLoadedTraceIDs(n, series, raw, section_data["contours"], stored_ids)
    return SectionRows(n, section_data, coordinates)


def loadForOpen(series, n : int) -> Union[SectionRows, Section]:
    """A section as a series open reads it: its rows, or the `Section` when a
    row is not plain (`readSectionRows`)."""
    rows = readSectionRows(n, series)
    if rows is None:
        return series.loadSection(n)
    return rows


## A series whose section files add up to less than this is read in this
## process: below it, starting the workers costs about what they save.
PARALLEL_MIN_BYTES = 64 * 1024 * 1024
## At most this many worker processes; each holds a section's decoded rows
## (about 280 MB at peak on DW09)
PARALLEL_MAX_WORKERS = 4
## A script that opens a series only under `if __name__ == "__main__":` may
## set this, so its opens can use workers (see mainSafeForWorkers)
MAIN_GUARDED = False


def mainSafeForWorkers() -> bool:
    """Whether a worker process can start without running the program's
    main script again.

    A spawned worker imports the main script as `__mp_main__` before it
    takes any work, so a script that opens a series at its top level, with
    no `__main__` guard, would open it again, and do whatever else it does,
    in every worker. Safe: PyReconstruct's own run.py (from source its body
    is guarded; frozen, the worker stops in `freeze_support` first), a
    package run with `-m`, an interactive session, or a script that set
    `MAIN_GUARDED`.
    """
    main = sys.modules.get("__main__")
    if MAIN_GUARDED or getattr(main, "__file__", None) is None:
        return True
    spec = getattr(main, "__spec__", None)
    if spec is not None:
        return spec.name == "__main__" or spec.name.endswith(".__main__")
    ## run.py, which defines runPyReconstruct itself
    run = getattr(main, "runPyReconstruct", None)
    return getattr(run, "__module__", None) == "__main__"


def readFileRows(fp : str, n : int, alignments):
    """A section file read for a series open, in a worker process.

    The work `readSectionRows` does that needs no series: the decode and
    `updateJSON`, `plainCoordinates`, each row's canonicalJSON and
    `firstDerivedID` (in `TraceIDIssuer.deriveForSection`'s walk order), and
    each row's geometry with each of `alignments` the section has. The rows
    go back without their x and y, which only the measuring reads. None if a
    row is not plain.
    """
    with open(fp, "rb") as f:
        raw = f.read()
    section_data = fast_loads(raw)
    stored_ids : dict = {}
    Section.updateJSON(section_data, n, stored_ids=stored_ids)
    contours = section_data["contours"]
    coordinates = plainCoordinates(contours)
    if coordinates is None:
        return None
    row_jsons, first_ids = [], []
    for cname in sorted(contours, key=str):
        for row in contours[cname]:
            row_json = canonicalJSON(row)
            row_jsons.append(row_json)
            first_ids.append(firstDerivedID(n, cname, row_json))
    closed = {
        name: [fileRowClosed(c, r) for c, r in zip(coordinates[name], rows)]
        for name, rows in contours.items()
    }
    arrays = [c for name in contours for c in coordinates[name]]
    flat_closed = [c for name in contours for c in closed[name]]
    tforms = SectionRows(n, section_data, None).tforms
    geometries = {}
    for alignment in alignments:
        if arrays and alignment in tforms:
            flat = measureGeometries(arrays, flat_closed, tforms[alignment])
            geometries[alignment] = by_name = {}
            k = 0
            for name, rows in contours.items():
                by_name[name] = flat[k:k + len(rows)]
                k += len(rows)
    for rows in contours.values():
        for row in rows:
            row[0] = row[1] = None
    return (sectionFileDigest(raw), section_data, stored_ids,
            row_jsons, first_ids, (closed, geometries))


def _rowsFromWorker(n : int, series, result) -> Optional[SectionRows]:
    """The SectionRows of a `readFileRows` result, its ids registered as
    `readSectionRows` registers them, or None (and the issuer untouched) if
    an object would be measured with an alignment the worker did not use."""
    digest, section_data, stored_ids, row_jsons, first_ids, measured = result
    rows = SectionRows(n, section_data, None)
    geometries = measured[1]
    for name, contour_rows in rows.contours.items():
        if not contour_rows:
            continue
        ## the alignment `ObjectData.sectionTransform` measures it with
        alignment = series.getAttr(name, "alignment")
        if alignment is None or alignment not in rows.tforms:
            alignment = series.alignment
        if alignment not in geometries:
            return None
    Section.issueLoadedTraceIDs(
        n, series, None, rows.contours, stored_ids,
        digest=digest, row_jsons=row_jsons, first_ids=first_ids,
    )
    rows.measured = measured
    return rows


class ParallelLoader():
    """`loadForOpen` for a large series, with the files read in worker
    processes (`readFileRows`) ahead of the pass.

    The series open still takes the sections one at a time in section order,
    and the ids are registered here, in that order, so the issuer, the ids and
    the object list are the ones `loadForOpen` gives. A section whose worker
    failed, for any reason, is read in this process instead, so an open never
    fails because a worker did.
    """

    def __init__(self, series, executor, section_numbers):
        self.executor = executor
        ## every alignment an object can be measured with: an object's own
        ## is only ever cleared during the open, never set
        alignments = {series.alignment} | {
            attrs["alignment"] for attrs in series.obj_attrs.values()
            if attrs.get("alignment") is not None
        }
        self.futures = {
            n: executor.submit(readFileRows, series.presentSection(n), n, alignments)
            for n in section_numbers
        }
        self.failed = False

    @classmethod
    def start(cls, series) -> Optional["ParallelLoader"]:
        """A loader for the series, or None to read it in this process: a
        series under `PARALLEL_MIN_BYTES`, one with sections not yet in its
        working folder (lazy_sections.py), a machine with one core, a
        program whose main script a worker would run again
        (mainSafeForWorkers), or workers that do not start."""
        if series._lazy or not mainSafeForWorkers():
            return None
        section_numbers = sorted(series.sections)
        try:
            size = sum(
                os.path.getsize(os.path.join(series.getwdir(), series.sections[n]))
                for n in section_numbers
            )
        except OSError:
            return None
        workers = min(PARALLEL_MAX_WORKERS, (os.cpu_count() or 1) - 1, len(section_numbers))
        if size < PARALLEL_MIN_BYTES or workers < 1:
            return None
        executor = None
        try:
            executor = ProcessPoolExecutor(
                workers, mp_context=multiprocessing.get_context("spawn"),
            )
            return cls(series, executor, section_numbers)
        except Exception as e:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            print(f"Opening in one process: the workers did not start ({e!r})", file=sys.stderr)
            return None

    def __call__(self, series, n : int) -> Union[SectionRows, Section]:
        future = self.futures.pop(n, None)
        if future is None:
            return loadForOpen(series, n)
        try:
            result = future.result()
        except Exception as e:
            if not self.failed:
                self.failed = True
                print(f"Section {n} read in this process: its worker failed ({e!r})", file=sys.stderr)
            return loadForOpen(series, n)
        if result is None:
            return series.loadSection(n)
        rows = _rowsFromWorker(n, series, result)
        return loadForOpen(series, n) if rows is None else rows

    def close(self):
        """Stop the workers, with any sections they did not read."""
        self.executor.shutdown(wait=False, cancel_futures=True)


@contextmanager
def openLoader(series):
    """The `load` a series open passes `enumerateSections`: a
    `ParallelLoader` for a large series, else `loadForOpen`."""
    loader = ParallelLoader.start(series)
    if loader is None:
        yield loadForOpen
        return
    try:
        yield loader
    finally:
        loader.close()
