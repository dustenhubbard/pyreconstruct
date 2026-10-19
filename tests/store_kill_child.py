"""Child process for tests/test_store_kill_reopen.py: open, edit, Save, close, stop.

Run as ``python store_kill_child.py <jser> <kill point>`` with the local store
switched on in "store" mode (PYRECON_HYBRID_STORE=1, PYRECON_HYBRID_STORE_SAVE
=store, PYRECON_HYBRID_STORE_DIR set by the test). The first open keeps the
.jser in a new store (an import). The child makes the edits of
tests/save_kill_child.py, saves the way Save (Cmd+S, Ctrl+S on Windows/Linux)
does in "store" mode, which writes the store alone, and then closes the
series, which writes the .jser from the store.

At the named kill point it prints ``AT <point>`` and blocks, and the test
SIGKILLs it there. The points are reached by wrapping functions from this
script only, so no product code knows about the test. Every point but one is
a boundary in the product's own I/O, where the wrapper only waits:

  * during the import: with two sections written in its transaction, and
    after it committed, before the object-list numbers are stored;
  * during the store Save: with two sections written in its transaction, just
    before its COMMIT, and just after it;
  * during the close's write of the .jser: the new file complete and synced
    but not renamed, and renamed into place but not yet recorded by the store;
  * during the close's removal of the working folder, after two files.

``close-injected-jser-half-write`` is not a boundary: it forces half of the
write that carries section 3 onto disk, as in tests/save_kill_child.py.

``none`` runs to the end and prints ``SAVED``. A point that is never reached
also ends in ``SAVED``, and the test fails on it.

PySide6 cannot be imported here, so this process cannot reach the real
application settings (QSettings); the settings it reads come from memory.
"""

import os
import sys
import time


class _BlockPySide6:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 is blocked in the store kill child")
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
from PyReconstruct.modules.constants import jser_format  # noqa: E402
from PyReconstruct.modules.datatypes import Trace  # noqa: E402
from PyReconstruct.modules.datatypes import hybrid_store, store_open, store_save  # noqa: E402
from PyReconstruct.modules.datatypes.series import Series  # noqa: E402

#: Every kill point, in the order the child reaches them.
POINTS = (
    "import-between-sections",  # sections 0 and 1 written in the import's transaction
    "import-before-numbers",  # the import committed, its numbers not yet stored
    "store-save-between-sections",  # sections 0 and 2 written in the Save's transaction
    "store-save-before-commit",  # every row written, COMMIT not yet run
    "store-save-after-commit",  # the store holds the Save
    "close-injected-jser-half-write",  # half of section 3 forced into the temp .jser
    "close-jser-before-rename",  # the new .jser complete and synced, not renamed
    "close-jser-after-rename",  # the new .jser in place, not yet recorded by the store
    "close-remove",  # the .jser written; two files of the working folder removed
)

CONTROLS = ("none",)

#: Sections edited before the Save, and the one still open in the window.
EDITED = (0, 2, 4)
CURRENT = 3
OBJECT = "kill_test"

_saving = []  # non-empty while the store Save runs


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


def armImport(point):
    real_replace = hybrid_store.HybridStore._replaceSection

    def replace(self, snum, section_data):
        if point == "import-between-sections" and snum == 2:
            stop(point)
        return real_replace(self, snum, section_data)

    hybrid_store.HybridStore._replaceSection = replace

    real_stats = store_open._statsRow

    def stats(*args, **kwargs):
        if point == "import-before-numbers":
            stop(point)
        return real_stats(*args, **kwargs)

    store_open._statsRow = stats


def armSave(point):
    real_commit = store_save._commit

    def commit(*args, **kwargs):
        _saving.append(True)
        try:
            result = real_commit(*args, **kwargs)
        finally:
            _saving.clear()
        if point == "store-save-after-commit":
            stop(point)
        return result

    store_save._commit = commit

    real_pack = hybrid_store.packSection

    def pack(snum, section_data):
        if point == "store-save-between-sections" and _saving and snum == CURRENT:
            stop(point)
        return real_pack(snum, section_data)

    hybrid_store.packSection = pack

    real_exit = store_open._transaction.__exit__

    def exit_(self, exc_type, exc, tb):
        if point == "store-save-before-commit" and _saving and exc_type is None:
            stop(point)
        return real_exit(self, exc_type, exc, tb)

    store_open._transaction.__exit__ = exit_


def armClose(point, series):
    jser_fp = os.path.abspath(series.jser_fp)
    hidden = os.path.abspath(series.hidden_dir)

    real_replace = atomic_io.replace_with_retry

    def replace(src, dst, *args, **kwargs):
        at_jser = os.path.abspath(dst) == jser_fp
        if point == "close-jser-before-rename" and at_jser:
            stop(point)
        real_replace(src, dst, *args, **kwargs)
        if point == "close-jser-after-rename" and at_jser:
            stop(point)

    atomic_io.replace_with_retry = replace

    real_write_jser = jser_format.write_jser

    def write_jser(f, sections, tail, *args, **kwargs):
        if point != "close-injected-jser-half-write":
            return real_write_jser(f, sections, tail, *args, **kwargs)
        out = _StoppingFile(f, point)

        def counted():
            for i, s in enumerate(sections()):
                if i == CURRENT:
                    out.stop_in_next_write = True
                yield s

        return real_write_jser(out, counted, tail, *args, **kwargs)

    jser_format.write_jser = write_jser

    if point == "close-remove":
        # as tests/save_kill_child.py: after two removals, the series file last
        real_remove = os.remove
        removed = []

        def remove(path, *args, **kwargs):
            if os.path.dirname(os.path.abspath(path)) == hidden:
                if len(removed) == 2:
                    stop(point)
                removed.append(path)
            real_remove(path, *args, **kwargs)

        os.remove = os.unlink = remove
        real_listdir = os.listdir

        def listdir(path="."):
            names = real_listdir(path)
            if os.path.abspath(path) == hidden:
                names = sorted(names, key=lambda n: (n.endswith(".ser"), n))
            return names

        os.listdir = listdir


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
    if point not in CONTROLS and point not in POINTS:
        sys.exit(f"unknown kill point {point!r}")
    if not (store_open.enabled() and store_save.saveMode() == store_save.MODE_STORE):
        sys.exit("the store switch is not on in store mode")

    if point.startswith("import-"):
        armImport(point)
    series = Series.openJser(jser_fp, progress=NullProgressReporter, notifier=NullNotifier())
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    if store_save.heldStore(series) is None:
        sys.exit("the open did not keep the series in its store")

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
    if point.startswith("store-save-"):
        armSave(point)
    # What MainWindow.saveToJser does in store mode: saveAllData, then the store
    if current.isModified():
        current.save(update_series_data=False)
    if not series.saveToStore():
        sys.exit("the Save did not go to the store")
    print("STORED", flush=True)

    if point.startswith("close-"):
        armClose(point, series)
    series.close()
    print("SAVED", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
