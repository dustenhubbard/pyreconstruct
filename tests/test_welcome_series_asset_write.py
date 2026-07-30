"""The app must not write into its own bundled assets when it opens the welcome
series.

``MainWindow.openWelcomeSeries`` opens the welcome series **in place** from the
install tree: ``get_welcome_setup()`` hands back the path under
``PyReconstruct/assets/welcome_series/.welcome`` and ``Series.__init__`` sets
``hidden_dir`` to that file's own directory. Every other series gets a hidden
working dir freshly created next to the user's ``.jser``; the welcome series is
the one case where "the working dir" and "the installation" are the same place.

``SectionStates.initialize`` writes an undo baseline to
``<hidden_dir>/<section>.s0``, so for the welcome series that baseline landed on
the shipped ``welcome.0.s0``. Two observed consequences, both fixed here:

1. In a source checkout the file is tracked by git, and launching the app
   rewrote it from ``{}`` to a byte copy of ``welcome.0`` (a full section file:
   ``src``, ``brightness``, ``mag``, ``tforms``, ...), leaving the working tree
   dirty after simply starting the program.

2. Where the install's *files* are read-only but its *directory* is not, the
   write raised, and the ``OSError`` cleanup then removed the bundled
   ``welcome.0.s0`` outright -- deleting a shipped asset that the failed write
   had never touched.

Nothing about the welcome series is meant to persist: ``Series.save``,
``Section.save`` and ``Series.setOption`` all no-op for it and Save / Save As /
Backup are disabled in the menus. So its undo baseline is kept in memory and no
file path is ever computed for it. The section holds no contours, so the
file-copy optimization has nothing to save there anyway.

The tests below assert the invariant directly (the bundled tree is byte-identical
after an open) rather than asserting on the implementation, and separately pin
that a *real* series still gets its on-disk baseline -- the fix must not turn the
undo-init copy optimization off for everyone.
"""

import hashlib
import os
import shutil
import stat
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.func import SectionStates
from PyReconstruct.modules.constants import welcome_series_dir
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.utils import get_welcome_setup


WELCOME_TREE = Path(welcome_series_dir).parent  # assets/welcome_series


def _snapshot(root: Path) -> dict:
    """sha256 of every file under root, keyed by path relative to root.

    Catches content changes, deletions and additions in one comparison.
    """
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


def _open_welcome():
    """Open the welcome series exactly as MainWindow.openWelcomeSeries does."""
    w_ser, w_secs, w_src = get_welcome_setup()
    series = Series(w_ser, w_secs)
    series.src_dir = w_src
    return series


def test_opening_welcome_series_leaves_bundled_assets_byte_identical():
    """Opening the welcome series must not touch the shipped asset tree.

    This is the user-visible bug: `git status` was dirty after launching from a
    source checkout, with `welcome.0.s0` rewritten from `{}` to a copy of
    `welcome.0`. Before the fix this test fails on that file's hash.
    """
    before = _snapshot(WELCOME_TREE)
    assert os.path.join(".welcome", "welcome.0.s0") in before, (
        f"the bundled baseline is not where the test expects it, under {WELCOME_TREE}"
    )

    series = _open_welcome()
    section = series.loadSection(0)
    SectionStates(section, series)

    after = _snapshot(WELCOME_TREE)
    assert after == before, (
        "opening the welcome series modified the bundled assets: "
        f"{sorted(set(before) ^ set(after)) or [k for k in before if before[k] != after.get(k)]}"
    )


def test_welcome_series_baseline_is_held_in_memory_and_still_restorable():
    """No file path is computed for the welcome series, and undo still works.

    Keeping the baseline in memory is only acceptable if the state is still
    usable, so assert the two readers that the file path would have served.
    """
    series = _open_welcome()
    assert series.isWelcomeSeries()
    section = series.loadSection(0)

    states = SectionStates(section, series)
    state = states.current_state

    assert state.contours_fp is None, (
        "the welcome series' undo baseline must not target a file; it would "
        f"land inside the install tree at {state.contours_fp}"
    )
    # the in-memory baseline is a working baseline, not a stub
    assert state.getContours() == {}
    assert state.getModifiedContours() == set()
    assert states.initialized


def _tmp_series_copy(tmp_path: Path) -> Series:
    """A real (non-welcome) series in tmp_path, cloned from the welcome files.

    Same shape as the welcome series, but at a path `isWelcomeSeries()` does not
    match, so it takes the ordinary on-disk-baseline route.
    """
    hidden = tmp_path / ".welcome"
    shutil.copytree(welcome_series_dir, hidden)
    return Series(str(hidden / "welcome.ser"), {0: "welcome.0"})


def test_ordinary_series_still_gets_an_on_disk_baseline(tmp_path):
    """The fix must not disable the undo-init file copy for real series."""
    series = _tmp_series_copy(tmp_path)
    assert not series.isWelcomeSeries()
    section = series.loadSection(0)

    states = SectionStates(section, series)
    fp = states.current_state.contours_fp

    assert fp is not None, "a normal series must keep its on-disk undo baseline"
    assert os.path.isfile(fp)
    # the clean-section path copies the section file's bytes verbatim
    assert Path(fp).read_bytes() == Path(section.filepath).read_bytes()


def test_unwritable_preexisting_baseline_is_not_deleted(tmp_path):
    """A baseline the failed write never touched must survive the cleanup.

    Reproduces consequence (2): file read-only, directory writable. The write
    raises, and before the fix the `OSError` handler deleted the file it had
    just failed to open -- which, for the welcome series, is a shipped asset.
    """
    series = _tmp_series_copy(tmp_path)
    section = series.loadSection(0)
    baseline = Path(series.hidden_dir) / "welcome.0.s0"
    assert baseline.is_file(), "fixture must ship a pre-existing .s0"

    original = baseline.read_bytes()
    mode = stat.S_IMODE(baseline.stat().st_mode)
    baseline.chmod(0o444)  # unwritable file, writable parent
    try:
        if os.access(baseline, os.W_OK):
            pytest.skip("cannot make a file unwritable here (running as root?)")
        states = SectionStates(section, series)
    finally:
        if baseline.exists():
            baseline.chmod(mode)

    assert baseline.is_file(), (
        "the pre-existing baseline was deleted by the failed-write cleanup"
    )
    assert baseline.read_bytes() == original
    # and the state fell back to memory rather than raising
    assert states.current_state.contours_fp is None
    assert states.current_state.getContours() == {}
