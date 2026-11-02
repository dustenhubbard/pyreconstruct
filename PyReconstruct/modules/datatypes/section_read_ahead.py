"""One speculative section file, with no access to mutable series state."""

from dataclasses import dataclass
import os
import threading

from PyReconstruct.modules.constants import fast_loads

from .contour import Contour
from .trace import Trace
from .trace_id import sectionFileDigest


@dataclass
class PreparedSection:
    data: dict
    stored_ids: dict
    digest: bytes
    contours: dict
    coordinates: dict
    trace_keys: dict


def readSection(filepath, number, canceled=None):
    """Decode and build private traces; register no IDs and write no files."""
    from .columnar_store import coordinatesFromRow
    from .lazy_points import LazyPoints
    from .section import Section

    with open(filepath, "rb") as stream:
        raw = stream.read()
    if canceled is not None and canceled.is_set():
        return None
    data = fast_loads(raw)
    digest = sectionFileDigest(raw)
    del raw
    stored_ids = {}
    Section.updateJSON(data, number, stored_ids=stored_ids)
    contours, coordinates, trace_keys = {}, {}, {}
    for name, rows in data["contours"].items():
        if canceled is not None and canceled.is_set():
            return None
        traces = []
        for index, row in enumerate(rows):
            if canceled is not None and canceled.is_set():
                return None
            fields = row[1:] if len(row) == 9 else row
            array = coordinatesFromRow(fields[0], fields[1])
            points = LazyPoints.fromRow(fields[0], fields[1], array)
            trace = Trace.fromList(row, name, points=points)
            if len(trace.points) == 2:
                trace.closed = False
            if len(trace.points) > 1:
                traces.append(trace)
                trace_keys[trace] = (name, index)
                if array is not None:
                    coordinates[trace] = array
        contours[name] = Contour(name, traces)
    return PreparedSection(data, stored_ids, digest, contours, coordinates, trace_keys)


def _stamp(path):
    stat = os.stat(path)
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class SectionReadAhead:
    """One worker and one result, even while requests replace an active read.

    A take never waits. A late or failed read falls back to the normal loader.
    The worker owns only a path, number and cancellation event, never a Series.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._request = None
        self._result = None
        self._worker = None

    def start(self, owner, number, path):
        with self._lock:
            self._drop()
            self._request = (id(owner), number, path, threading.Event())
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="section-read-ahead", daemon=True,
                )
                self._worker.start()

    def _drop(self):
        if self._request is not None:
            self._request[3].set()
        self._request = None
        self._result = None

    def drop(self):
        with self._lock:
            self._drop()

    def stop(self):
        """Cancel and release the worker before moving or deleting working files.

        Called on the foreground thread, like start, drop and take. Paging
        uses drop or take instead, so it never waits for speculative work.
        """
        with self._lock:
            self._drop()
            worker = self._worker
        if worker is not None:
            worker.join()

    def take(self, owner, number, path):
        with self._lock:
            result = self._result
            matches = (self._request is not None and
                       self._request[:3] == (id(owner), number, path))
            self._drop()
        if matches and result is not None:
            stamp, prepared = result
            try:
                if _stamp(path) == stamp:
                    return prepared
            except OSError:
                pass
        return None

    def _run(self):
        while True:
            with self._lock:
                request = self._request
                if request is None:
                    self._worker = None
                    return
            _, number, path, canceled = request
            prepared = None
            try:
                stamp = _stamp(path)
                prepared = readSection(path, number, canceled)
                if canceled.is_set() or _stamp(path) != stamp:
                    prepared = None
            except Exception:
                # Speculation cannot surface an error. The requested load
                # retries normally and reports its own error if it still fails.
                prepared = None
            with self._lock:
                if self._request is request:
                    self._result = (stamp, prepared) if prepared is not None else None
                    prepared = None
                    self._worker = None
                    return
                # Release the old payload before starting another neighbor.
                prepared = None


READ_AHEAD = SectionReadAhead()
