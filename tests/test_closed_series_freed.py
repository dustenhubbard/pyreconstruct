"""A closed series is freed when another one opens.

trimesh keeps the ImportError of each optional extra it lacks, tracebacks
included. Those tracebacks held every frame on the stack that first imported
trimesh, and on the first open that stack was MainWindow.openSeries building
the menus (the Collada label check imports the volume backend). The series in
those frames' locals stayed in memory after the next open: on DW09, RSS went
from 2.6 GB after one open to 5.2 GB after a second.
"""

import gc
import shutil
import subprocess
import sys
import weakref

import pytest


# A fresh interpreter, so this is the first trimesh import whatever ran before.
FIRST_IMPORT = """
import gc, weakref

class Held:
    pass

def caller():
    held = Held()
    import PyReconstruct.modules.backend.volume  # noqa: F401
    return weakref.ref(held)

ref = caller()
gc.collect()
print("freed" if ref() is None else "held")
"""


def test_first_volume_import_keeps_no_caller_frame():
    r = subprocess.run([sys.executable, "-c", FIRST_IMPORT],
                       check=True, capture_output=True, text=True)
    assert r.stdout.strip().splitlines()[-1] == "freed"


# The first attempt to find trimesh fails once; a retry would succeed.
FAIL_ONCE = """
import importlib.abc, sys

attempts = []

class FailOnce(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "trimesh":
            attempts.append(fullname)
            if len(attempts) == 1:
                raise RuntimeError("first attempt failed")

sys.meta_path.insert(0, FailOnce())
try:
    import PyReconstruct.modules.backend.volume  # noqa: F401
    print("imported", len(attempts))
except RuntimeError as e:
    print("raised", e, len(attempts))
"""


def test_failed_first_trimesh_import_reaches_caller_once():
    r = subprocess.run([sys.executable, "-c", FAIL_ONCE],
                       check=True, capture_output=True, text=True)
    assert r.stdout.strip().splitlines()[-1] == "raised first attempt failed 1"


@pytest.mark.gui
def test_first_series_is_freed_after_a_second_open(main_window, tmp_path):
    window = main_window
    other = tmp_path / "other" / "series.jser"
    other.parent.mkdir()
    shutil.copy(window.series.jser_fp, other)
    first = weakref.ref(window.series)

    window.seriesModified(False)
    window.openSeries(jser_fp=str(other))
    gc.collect()

    assert window.series.jser_fp == str(other)
    assert first() is None, "the first series is still reachable"
