"""A failed on-disk baseline still supports independent undo and redo."""

import errno
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.func import state_manager
from PyReconstruct.modules.backend.func.state_manager import FieldState, SeriesStates
from PyReconstruct.modules.datatypes import Contour, Trace


POINTS = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]


def draw(section):
    trace = Trace("axon", [10, 20, 30])
    trace.points = list(POINTS)
    section.addTrace(trace, log_event=False)
    return trace


def contour_points(contours):
    return {
        name: [list(trace.points) for trace in contour]
        for name, contour in contours.items() if len(contour)
    }


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_partial_baseline_write_falls_back_to_working_undo_redo(
    real_series, monkeypatch, cleanup_fails,
):
    series = real_series
    series.current_section = 0
    section = series.loadSection(0)
    trace = draw(section)
    section.save()
    section.clearTracking()
    baseline = Path(series.hidden_dir) / f"{series.sections[0]}.s0"

    def disk_full(source, destination):
        Path(destination).write_bytes(b'{"contours":')
        raise OSError(errno.ENOSPC, "simulated full disk")

    def refuse_cleanup(path):
        raise PermissionError(errno.EACCES, "simulated cleanup refusal")

    with monkeypatch.context() as patch:
        patch.setattr(state_manager.shutil, "copyfile", disk_full)
        if cleanup_fails:
            patch.setattr(state_manager.os, "remove", refuse_cleanup)
        states = SeriesStates(series)
        states[section]

    assert baseline.exists() is cleanup_fails
    if cleanup_fails:
        assert baseline.read_bytes() == b'{"contours":'

    section.removeTrace(trace, log_event=False)
    states.commitSection(section)
    assert contour_points(section.contours) == {}
    states.undoSection(section)
    assert contour_points(section.contours) == {"axon": [POINTS]}
    assert contour_points(section._columns.materializeContours()) == {"axon": [POINTS]}
    assert 0 in series.data["objects"]["axon"].traces

    states.undoSection(section, redo=True)
    assert contour_points(section.contours) == {}
    assert section._columns.contourNames() == []
    assert "axon" not in series.data["objects"]
    states.undoSection(section)
    section.save()
    reloaded = series.loadSection(0)
    assert contour_points(reloaded.contours) == {"axon": [POINTS]}
    assert contour_points(reloaded._columns.materializeContours()) == {"axon": [POINTS]}


def test_fallback_captures_deleted_names_and_copies_the_remaining_trace(
    tmp_path, monkeypatch,
):
    trace = Trace("axon", [10, 20, 30])
    trace.points = list(POINTS)
    contours = {"axon": Contour("axon", [trace])}

    def unavailable(source, destination):
        raise PermissionError(errno.EACCES, "simulated read-only baseline")

    monkeypatch.setattr(state_manager.shutil, "copyfile", unavailable)
    state = FieldState(
        contours, {}, {}, [],
        contours_fp=str(tmp_path / "baseline.s0"),
        updated_contours={"axon", "deleted"},
        src_fp=str(tmp_path / "section"),
    )

    trace.points[0] = (90.0, 91.0)
    restored = state.getContours()
    assert state.getModifiedContours() == {"axon", "deleted"}
    assert list(restored["axon"][0].points) == POINTS
    assert len(restored["deleted"]) == 0

    restored["axon"][0].points[1] = (80.0, 81.0)
    assert list(state.getContours()["axon"][0].points) == POINTS


def test_serialized_dirty_baseline_reads_back_independent_contours(tmp_path):
    trace = Trace("axon", [10, 20, 30])
    trace.points = list(POINTS)
    state = FieldState(
        {"axon": Contour("axon", [trace])}, {}, {}, [],
        contours_fp=str(tmp_path / "baseline.s0"),
    )

    trace.points[0] = (90.0, 91.0)
    assert state.getModifiedContours() == {"axon"}
    restored = state.getContours()
    assert contour_points(restored) == {"axon": [POINTS]}
    assert restored["axon"][0].color == [10, 20, 30]

    restored["axon"][0].points.clear()
    assert contour_points(state.getContours()) == {"axon": [POINTS]}
