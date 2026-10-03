"""Calibrate and Set magnification are one undo across the series.

`FieldWidget.setMag` rewrites every section: the mag, every trace, the tforms,
the flags and the z-traces. It recorded no undo state, so Ctrl+Z after a
calibration did nothing and the only way back was a second calibration.

The tests compare the section files byte for byte: after an undo they must
match the files before the change, and after a redo the files right after it.
"""

import json
import os

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Flag, Series, Ztrace
from PyReconstruct.modules.gui.main.field_widget_4_data import FieldWidgetData


class _Tables:
    def recreateTables(self, refresh_data=False):
        pass


class _Field:
    """The parts of the field that setMag touches."""

    def __init__(self, series):
        self.series = series
        self.series_states = SeriesStates(series)
        self.table_manager = _Tables()

    def reload(self, clear_states=False):
        pass

    setMag = FieldWidgetData.setMag


def _files(series):
    """section number -> the bytes of its file on disk."""
    out = {}
    for snum, fname in series.sections.items():
        with open(os.path.join(series.hidden_dir, fname), "rb") as f:
            out[snum] = f.read()
    return out


def _ztraces(series):
    return {
        name: [tuple(p) for p in z.points]
        for name, z in series.ztraces.items()
    }


@pytest.fixture
def series(series_jser):
    """The fixture series with a shifted tform, a flag and a z-trace, so the
    change reaches every kind of data it scales. Every section is saved once
    first, so the files compared are in this version's format."""
    series = Series.openJser(str(series_jser))
    series.setProgressReporter(NullProgressReporter)
    snums = sorted(series.sections)
    for i, snum in enumerate(snums):
        section = series.loadSection(snum)
        if i == 1:
            tform = section.tform
            tform.tform[2] += 1.2345678
            tform.tform[5] -= 0.7654321
            section.tform = tform
        if i == 2:
            section.flags.append(Flag("calibrate-flag", 1.1111111, 2.2222222, snum, (255, 0, 0)))
        section.save()
    series.ztraces["calibrate-z"] = Ztrace(
        "calibrate-z", (255, 0, 0), [(1.5, 2.5, snums[0]), (3.25, 4.75, snums[-1])]
    )
    series.save()
    yield series
    series.close()


def test_calibrate_undo_and_redo_restore_every_file_exactly(series):
    field = _Field(series)
    snums = sorted(series.sections)
    old_mags = {snum: series.loadSection(snum).mag for snum in snums}
    files_before = _files(series)
    z_before = _ztraces(series)

    new_mag = old_mags[snums[0]] * 1.37
    field.setMag(new_mag)

    files_after = _files(series)
    z_after = _ztraces(series)
    assert all(series.loadSection(n).mag == new_mag for n in snums)
    assert files_after != files_before
    assert z_after != z_before

    can_3D, _, _ = field.series_states.canUndo()
    assert can_3D, "a mag change must leave a series undo"

    field.series_states.undoState()
    assert {n: series.loadSection(n).mag for n in snums} == old_mags
    assert _files(series) == files_before, "undo must restore every section file"
    assert _ztraces(series) == z_before

    field.series_states.undoState(redo=True)
    assert all(series.loadSection(n).mag == new_mag for n in snums)
    assert _files(series) == files_after, "redo must restore the changed files"
    assert _ztraces(series) == z_after

    # and a second round trip lands in the same place
    field.series_states.undoState()
    assert _files(series) == files_before
    field.series_states.undoState(redo=True)
    assert _files(series) == files_after


def test_calibrate_undo_restores_trace_points(series):
    """The same check on the trace values themselves, as a reader sees them."""
    field = _Field(series)
    snums = sorted(series.sections)

    def points():
        return {
            n: [
                (t.name, [tuple(p) for p in t.points])
                for t in series.loadSection(n).tracesAsList()
            ]
            for n in snums
        }

    before = points()
    assert any(before.values()), "the fixture must have traces to scale"
    field.setMag(series.loadSection(snums[0]).mag / 3)
    after = points()
    assert after != before

    field.series_states.undoState()
    assert points() == before
    field.series_states.undoState(redo=True)
    assert points() == after


def test_calibrate_undo_cannot_split_by_section(series):
    """One section cannot step back alone: it would sit at the old mag while
    the rest of the series stays at the new one."""
    field = _Field(series)
    snum = sorted(series.sections)[0]
    field.setMag(series.loadSection(snum).mag * 2)

    section = series.loadSection(snum)
    _, can_2D, _ = field.series_states.canUndo(snum)
    assert not can_2D
    field.series_states.undoSection(section)
    assert section.mag == series.loadSection(snum).mag


def test_calibrate_undo_keeps_the_series_data_in_step(series):
    """The object list reads areas from the series data, not the files."""
    field = _Field(series)
    names = sorted(series.data["objects"])
    assert names
    areas = {n: series.data.getFlatArea(n) for n in names}

    field.setMag(series.loadSection(sorted(series.sections)[0]).mag * 2)
    assert any(
        series.data.getFlatArea(n) != pytest.approx(areas[n]) for n in names
    )

    field.series_states.undoState()
    for n in names:
        assert series.data.getFlatArea(n) == pytest.approx(areas[n])
