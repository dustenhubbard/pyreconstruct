"""Child process for tests/test_save_kill_reopen.py: edit a series, save, stop.

Run as ``python save_kill_child.py <jser> <kill point>``. It opens the series,
makes edits the way the window does (each section written to the working folder
as it is left, then the series file), and saves the way Save (Cmd+S, Ctrl+S on
Windows/Linux) does: the current section and the series file into the working
folder, then the .jser.

At the named kill point it prints ``AT <point>`` and blocks, and the test
SIGKILLs it there. The points are reached by wrapping functions from this script
only, so no product code knows about the test. Whatever the product wrote before
the point is on disk when ``AT`` is printed: the wrappers flush first, and a
flushed write is visible to the next process even without an fsync.

``none`` runs the whole save and prints ``SAVED``, which gives the test the state
a finished save leaves. A point that is never reached also ends in ``SAVED``, and
the test fails on it.

PySide6 cannot be imported here at all, so this process cannot reach the real
application settings (QSettings), and the settings it does read come from an
in-memory store.
"""

import os
import sys
import time


class _BlockPySide6:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 is blocked in the save kill child")
        return None


sys.meta_path.insert(0, _BlockPySide6())

from PyReconstruct.modules.backend.settings_store import (  # noqa: E402
    DictSettingsStore,
    set_default_settings_store,
)

set_default_settings_store(DictSettingsStore())

from PyReconstruct.modules.backend.func import atomic_io  # noqa: E402
from PyReconstruct.modules.backend.notifier import NullNotifier  # noqa: E402
from PyReconstruct.modules.backend.progress import NullProgressReporter  # noqa: E402
from PyReconstruct.modules.datatypes import Trace  # noqa: E402
from PyReconstruct.modules.datatypes import series as series_mod  # noqa: E402
from PyReconstruct.modules.datatypes.series import Series  # noqa: E402

#: Every kill point this script can stop at, in the order a save reaches them.
POINTS = (
    "section-replace",  # the current section's working file, before its rename
    "ser-replace",  # the working folder's series file, before its rename
    "jser-mid-write",  # partway through the bytes of one section in the .jser
    "jser-between-sections",  # after some sections are in the new .jser
    "jser-before-rename",  # the new .jser complete and synced, not renamed
    "jser-after-rename",  # the new .jser renamed into place
    "close-remove",  # Save and close: the working folder partly removed
)

#: Sections edited before the save, and the one still open in the window.
EDITED = (0, 2, 4)
CURRENT = 3
OBJECT = "kill_test"


def stop(point):
    """Report the point and wait to be killed."""
    print(f"AT {point}", flush=True)
    time.sleep(600)
    sys.exit(f"not killed at {point}")


def edit(section, tag):
    """Add one trace whose points say which section and edit it came from."""
    n = section.n
    trace = Trace(OBJECT, color=(10, 20, 30))
    trace.points = [(1.0 + n, 2.0 + tag), (3.0 + n, 2.0 + tag), (3.0 + n, 5.0 + tag)]
    section.addTrace(trace)


def arm(point, series):
    """Install the wrapper that stops the save at `point`."""
    jser_fp = series.jser_fp
    hidden = os.path.abspath(series.hidden_dir)

    real_replace = atomic_io.replace_with_retry

    def replace(src, dst, *args, **kwargs):
        dst_abs = os.path.abspath(dst)
        in_hidden = os.path.dirname(dst_abs) == hidden
        if point == "section-replace" and in_hidden and dst_abs.rsplit(".", 1)[-1].isdigit():
            stop(point)
        if point == "ser-replace" and in_hidden and dst_abs.endswith(".ser"):
            stop(point)
        if point == "jser-before-rename" and dst_abs == os.path.abspath(jser_fp):
            stop(point)
        real_replace(src, dst, *args, **kwargs)
        if point == "jser-after-rename" and dst_abs == os.path.abspath(jser_fp):
            stop(point)

    atomic_io.replace_with_retry = replace

    real_write_jser = series_mod.write_jser

    def write_jser(f, sections, tail, *args, **kwargs):
        if point not in ("jser-between-sections", "jser-mid-write"):
            return real_write_jser(f, sections, tail, *args, **kwargs)
        out = _StoppingFile(f, point)

        def counted():
            for i, s in enumerate(sections()):
                if i == CURRENT:
                    # sections 0 to 2 are in the file; 3, edited, is next
                    if point == "jser-between-sections":
                        f.flush()
                        stop(point)
                    out.stop_in_next_write = True
                yield s

        return real_write_jser(out, counted, tail, *args, **kwargs)

    series_mod.write_jser = write_jser

    if point == "close-remove":
        real_remove = os.remove
        removed = []

        def remove(path, *args, **kwargs):
            if os.path.dirname(os.path.abspath(path)) == hidden:
                ser_left = any(n.endswith(".ser") for n in os.listdir(hidden))
                if removed and ser_left and _is_section_file(path):
                    stop(point)
                if _is_section_file(path):
                    removed.append(path)
            real_remove(path, *args, **kwargs)

        os.remove = remove

        # The order close() removes files in is the folder listing's, which the
        # file system picks. Sorted is one real order, and the one that leaves
        # the series file for last.
        real_listdir = os.listdir

        def listdir(path="."):
            names = real_listdir(path)
            if os.path.abspath(path) == hidden:
                names = sorted(names, key=lambda n: n.endswith(".ser"))
            return names

        os.listdir = listdir


def _is_section_file(path):
    return os.path.basename(path).rsplit(".", 1)[-1].isdigit()


class _StoppingFile:
    """The .jser temp file, stopping halfway through one write when told to."""

    def __init__(self, f, point):
        self._f = f
        self._point = point
        self.stop_in_next_write = False

    def write(self, data):
        # the one-byte write is the comma before the section
        if self.stop_in_next_write and len(data) > 1:
            half = len(data) // 2
            self._f.write(memoryview(data)[:half])
            self._f.flush()
            stop(self._point)
        return self._f.write(data)

    def __getattr__(self, name):
        return getattr(self._f, name)


def main(jser_fp, point):
    if point != "none" and point not in POINTS:
        sys.exit(f"unknown kill point {point!r}")

    series = Series.openJser(jser_fp, progress=NullProgressReporter, notifier=NullNotifier())
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())

    # Edits, each section written to the working folder as it is left
    for snum in EDITED:
        section = series.loadSection(snum)
        edit(section, tag=0)
        section.save()
        series.save()
    series.setAttr(OBJECT, "comment", "edited before the save")
    series.save()

    # The section on screen, edited and not yet written
    current = series.loadSection(CURRENT)
    edit(current, tag=1)

    print("SAVING", flush=True)
    if point != "none":
        arm(point, series)

    # What MainWindow.saveToJser does: saveAllData, then the .jser
    current.save()
    series.save()
    series.saveJser(close=(point == "close-remove"))
    print("SAVED", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
