"""The wording of the clean-up list headings and the Zarr converter window."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gui

from PyReconstruct.modules.gui.dialog import (
    DuplicateTracesDialog,
    MalformedContoursDialog,
    PixelDustDialog,
)

START_PROCESS = (
    Path(__file__).resolve().parents[1]
    / "PyReconstruct" / "assets" / "scripts" / "start_process.py"
)


def _record(**extra):
    record = {
        "name": "OBJ", "section": 1, "index": 0, "points": 2,
        "location": (0.0, 0.0), "reason": "Too few points",
        "match": {"color": [1, 2, 3], "points": [(0.0, 0.0)]},
    }
    record.update(extra)
    return record


def _group():
    members = [_record(name="A"), _record(name="B", index=1)]
    return {
        "section": 1, "members": members, "names": ["A", "B"], "count": 2,
        "ratio": 0.97, "location": (0.0, 0.0),
    }


def _heading(qtbot, dialog):
    qtbot.addWidget(dialog)
    return dialog.heading.text()


def test_the_smoothing_list_says_why_a_trace_is_skipped(qtbot):
    heading = _heading(qtbot, MalformedContoursDialog(None, [_record()]))
    assert (
        "A trace is skipped when it cannot be smoothed, usually because it "
        "has too few points"
    ) in heading


def test_the_pixel_dust_list_explains_the_area_column(qtbot):
    record = _record(name="DUST", reason="Area 3 px^2", area=1e-4,
                     area_px=3.0)
    heading = _heading(
        qtbot, PixelDustDialog(None, [record], delete=lambda recs: [])
    )
    assert (
        "The Area is shown in pixels (px^2), the same units as the "
        "threshold, with the physical area (um^2) next to it. Each "
        "section's magnification can differ, so"
    ) in heading
    assert (
        "Review the candidates below. Select a row and click “Go to trace” "
        "to inspect one, and deselect"
    ) in heading


def test_the_duplicates_heading_asks_for_one_name_per_row(qtbot):
    heading = _heading(
        qtbot, DuplicateTracesDialog(None, [_group()], combine=lambda c: [])
    )
    assert "Pick the name to keep in each row." in heading
    assert "A row with more than one is left alone until you pick one." in (
        heading
    )


@pytest.fixture
def start_process():
    spec = importlib.util.spec_from_file_location("start_process",
                                                  START_PROCESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def zarr_window(qtbot, start_process):
    window = start_process.MainWindow()
    qtbot.addWidget(window)
    return window


@pytest.fixture
def clock(monkeypatch, start_process):
    """A clock the test sets by hand, read by the window in place of the real one."""
    now = SimpleNamespace(value=1000.0)
    monkeypatch.setattr(
        start_process, "time", SimpleNamespace(monotonic=lambda: now.value)
    )
    return now


def test_the_zarr_window_shows_count_and_time_left(zarr_window, clock):
    zarr_window.update_progress("@@PROGRESS@@ TOTAL 4")
    assert zarr_window.eta.text() == "0 / 4, estimating time remaining…"

    # 10 s for the first of 4 steps leaves 3 more at the same pace
    clock.value += 10
    zarr_window.update_progress("@@PROGRESS@@ STEP 1 4")
    assert zarr_window.eta.text() == "1 / 4, ~30s remaining"

    # 60 s for 2 of 4 leaves another 60 s, shown in minutes
    clock.value += 50
    zarr_window.update_progress("@@PROGRESS@@ STEP 2 4")
    assert zarr_window.eta.text() == "2 / 4, ~1m 00s remaining"


def test_the_zarr_window_estimates_time_left_from_a_zero_start(zarr_window,
                                                              clock):
    # a clock that reads 0.0 at the first total is still a real start time
    clock.value = 0.0
    zarr_window.update_progress("@@PROGRESS@@ TOTAL 4")

    clock.value += 10
    zarr_window.update_progress("@@PROGRESS@@ STEP 1 4")
    assert zarr_window.eta.text() == "1 / 4, ~30s remaining"


def test_the_zarr_window_says_where_to_look_on_failure(zarr_window):
    zarr_window.process_finished(1)
    assert zarr_window.heading.text() == (
        "Zarr processing did not finish. See the messages below."
    )
