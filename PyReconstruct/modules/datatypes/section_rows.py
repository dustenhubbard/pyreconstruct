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
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
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

    def __init__(self, n : int, section_data : dict, coordinates : Optional[dict]):
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
## A cancelled or failed open gives its running workers this many seconds
## to finish, then terminates them
PARALLEL_STOP_GRACE = 0.5
## A wait for a worker checks for a cancel this often, in seconds
PARALLEL_POLL = 0.1


class OpenCanceled(Exception):
    """Raised by a `ParallelLoader` cancelled while it waits for a worker."""


def _executorParts(executor):
    """The worker processes, manager thread and result queue of a
    `ProcessPoolExecutor`, read before `shutdown` drops them.

    The executor has no public way to stop a running worker before Python
    3.14 (terminate_workers), and none at all to end its manager thread
    once a worker died partway through sending a result: that thread then
    waits in `recv` for the rest, and this process still holds the queue's
    writer, so no end of file comes. The same attributes in 3.11 to 3.13.
    """
    return (
        list((executor._processes or {}).values()),
        executor._executor_manager_thread,
        executor._result_queue,
    )


def stopWorkers(executor, grace : float = PARALLEL_STOP_GRACE):
    """Stop a `ProcessPoolExecutor` without waiting on a stalled worker.

    Sections not started are dropped, and a worker still running after
    `grace` seconds is terminated. Returns once every worker process has
    exited, so none still has a section file open, and the executor's
    manager thread has ended, so Python can exit.
    """
    processes, manager, results = _executorParts(executor)
    executor.shutdown(wait=False, cancel_futures=True)
    deadline = time.monotonic() + grace
    for process in processes:
        process.join(max(0.0, deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
    ## no worker can write now: closing this process's writer ends a
    ## result one stopped partway through, and the manager reads that as a
    ## broken pool and exits (_executorParts)
    if results is not None:
        results._writer.close()
    if manager is not None:
        manager.join(5)
        if manager.is_alive():
            print("The open's worker manager did not stop", file=sys.stderr)


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


def readFileRows(fp : Union[str, bytes], n : int, alignments):
    """A section file read for a series open, in a worker process. `fp` is
    the file's path, or on a first open its bytes (UnpackFeeder).

    The work `readSectionRows` does that needs no series: the decode and
    `updateJSON`, `plainCoordinates`, each row's canonicalJSON and
    `firstDerivedID` (in `TraceIDIssuer.deriveForSection`'s walk order), and
    each row's geometry with each of `alignments` the section has. The rows
    go back without their x and y, which only the measuring reads. None if a
    row is not plain.
    """
    if isinstance(fp, bytes):
        raw = fp
    else:
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
    geometries : dict = {}
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
    ## pickled here, so this process receives one block of bytes while a
    ## first open is still unpacking, and decodes it when the pass takes it
    return pickle.dumps((sectionFileDigest(raw), section_data, stored_ids,
                         row_jsons, first_ids, (closed, geometries)),
                        protocol=pickle.HIGHEST_PROTOCOL)


def _rowsFromWorker(n : int, series, result) -> Optional[SectionRows]:
    """The SectionRows of a `readFileRows` result, its ids registered as
    `readSectionRows` registers them, or None (and the issuer untouched) if
    an object would be measured with an alignment the worker did not use."""
    digest, section_data, stored_ids, row_jsons, first_ids, measured = pickle.loads(result)
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

    def __init__(self, executor, alignments, canceled=None):
        self.executor = executor
        self.alignments = alignments
        self.canceled = canceled or (lambda: False)
        ## the sections not yet taken by the pass: a result is dropped once
        ## taken, so the open never holds one it has already built
        self.futures = {}
        self.failed = False
        self.closed = False

    def submit(self, n : int, fp : Union[str, bytes]):
        """Read section n's file (its path or its bytes) in a worker."""
        future = self.executor.submit(readFileRows, fp, n, self.alignments)
        self.futures[n] = future

    @staticmethod
    def workerCount(section_count : int) -> int:
        return min(PARALLEL_MAX_WORKERS, (os.cpu_count() or 1) - 1, section_count)

    @staticmethod
    def seriesAlignments(alignment : str, obj_attrs : dict) -> set:
        """Every alignment an object can be measured with: an object's own
        is only ever cleared during the open, never set."""
        return {alignment} | {
            attrs["alignment"] for attrs in obj_attrs.values()
            if attrs.get("alignment") is not None
        }

    @classmethod
    def launch(cls, workers : int, alignments : set, sections, canceled=None) -> Optional["ParallelLoader"]:
        """A loader with `workers` processes reading `sections`, (n, path or
        bytes) pairs, or None if the workers do not start."""
        executor = None
        try:
            executor = ProcessPoolExecutor(
                workers, mp_context=multiprocessing.get_context("spawn"),
            )
            loader = cls(executor, alignments, canceled)
            for n, fp in sections:
                loader.submit(n, fp)
            return loader
        except Exception as e:
            ## a worker started before the failure may be reading a section:
            ## it stops before the open goes on in this process
            if executor is not None:
                stopWorkers(executor)
            print(f"Opening in one process: the workers failed ({e!r})", file=sys.stderr)
            return None

    @classmethod
    def start(cls, series, canceled=None) -> Optional["ParallelLoader"]:
        """A loader for the series, or None to read it in this process: a
        series under `PARALLEL_MIN_BYTES`, one with sections not yet in its
        working folder (lazy_sections.py), a machine with one core, a
        program whose main script a worker would run again
        (mainSafeForWorkers), or workers that do not start.

        `canceled()` is checked while the loader waits for a worker."""
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
        workers = cls.workerCount(len(section_numbers))
        if size < PARALLEL_MIN_BYTES or workers < 1:
            return None
        return cls.launch(
            workers, cls.seriesAlignments(series.alignment, series.obj_attrs),
            [(n, series.presentSection(n)) for n in section_numbers], canceled,
        )

    def __call__(self, series, n : int) -> Union[SectionRows, Section]:
        future = self.futures.get(n)
        if future is None:
            return loadForOpen(series, n)
        try:
            result = self._wait(future)
        except OpenCanceled:
            raise  # its future stays, so close stops the worker
        except Exception as e:
            del self.futures[n]
            if not self.failed:
                self.failed = True
                print(f"Section {n} read in this process: its worker failed ({e!r})", file=sys.stderr)
            return loadForOpen(series, n)
        del self.futures[n]
        if result is None:
            return series.loadSection(n)
        rows = _rowsFromWorker(n, series, result)
        return loadForOpen(series, n) if rows is None else rows

    def _wait(self, future):
        """`future.result()`, raising OpenCanceled on a cancel."""
        while True:
            try:
                return future.result(timeout=PARALLEL_POLL)
            except FutureTimeout:
                if future.done():  # the worker's own TimeoutError
                    raise
                if self.canceled():
                    raise OpenCanceled() from None

    def close(self):
        """Stop the workers, dropping any sections they did not start.

        Returns once every worker has exited: a cancelled or failed open
        removes the working folder next, and on Windows a file a worker
        still has open would stay behind. A worker still reading is given
        `PARALLEL_STOP_GRACE`, then terminated (stopWorkers).
        """
        if self.closed:
            return
        self.closed = True
        if all(future.done() for future in self.futures.values()):
            self.executor.shutdown(wait=True)
        else:
            stopWorkers(self.executor)


class UnpackFeeder():
    """A first open's section files read in worker processes as its unpack
    writes them, so the reads overlap the unpack.

    The workers get each file's bytes, not its path: the unpack moves its
    folder into place once every file is written, and on Windows a file a
    worker has open cannot be moved. They start once the files written add
    up to `PARALLEL_MIN_BYTES`, so a series takes them exactly when
    `ParallelLoader.start` would. The build pass then uses `loader`
    (openLoader). Workers that fail to start or to take a section are
    stopped, and the open goes on in this process. `close` must run before
    the unpack removes its folder on a cancel or failure.
    """

    def __init__(self, section_count : int, series_data : dict, canceled=None):
        self.workers = ParallelLoader.workerCount(section_count) if mainSafeForWorkers() else 0
        self.series_data = series_data
        self.canceled = canceled
        self.loader = None
        self.feeding = self.workers >= 1
        self.written = []  # (n, bytes) written before the workers start
        self.size = 0

    def wrote(self, n : int, data):
        """The unpack wrote section n's file, `data` its bytes."""
        if not self.feeding:
            return
        data = bytes(data)  # a memoryview cannot go to a worker
        if self.loader is not None:
            try:
                self.loader.submit(n, data)
            except Exception as e:
                self.feeding = False
                loader, self.loader = self.loader, None
                stopWorkers(loader.executor)
                print(f"Opening in one process: the workers failed ({e!r})", file=sys.stderr)
            return
        self.written.append((n, data))
        self.size += len(data)
        if self.size < PARALLEL_MIN_BYTES:
            return
        ## the alignment and obj_attrs the open builds the series with:
        ## Series.updateJSON changes neither
        alignments = ParallelLoader.seriesAlignments(
            self.series_data.get("alignment"), self.series_data.get("obj_attrs", {}),
        )
        written, self.written = self.written, None
        self.loader = ParallelLoader.launch(self.workers, alignments, written, self.canceled)
        self.feeding = self.loader is not None

    def close(self):
        self.feeding = False
        self.written = None
        if self.loader is not None:
            self.loader.close()


@contextmanager
def openLoader(series, canceled=None, feeder : Optional[UnpackFeeder] = None):
    """The `load` a series open passes `enumerateSections`: a
    `ParallelLoader` for a large series, else `loadForOpen`. With
    `canceled`, a load that waits for a worker raises OpenCanceled once
    `canceled()` is true. A first open passes its `feeder`, whose workers
    already have the sections."""
    if feeder is not None:
        loader = feeder.loader
    else:
        loader = ParallelLoader.start(series, canceled)
    if loader is None:
        yield loadForOpen
        return
    try:
        yield loader
    finally:
        loader.close()
