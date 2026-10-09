"""A section pass stops once its series is closed under it.

Every pass that shows a progress dialog runs the event loop on each update,
and another series can open there (a .jser opened from the Finder reaches the
window during any of them). Opening it closes this series and deletes its
working files, and the pass then failed on the next section it read, with a
FileNotFoundError and the app's error window.

What is pinned here:

  * a pass whose series closes at a progress update reads no further section
    and raises SeriesClosedError, which is still a FileNotFoundError
  * the progress dialog is finished on the way out
  * a series closed with leave_open set (its files kept for a series opened
    into the same folder) stops the same way
  * a write pass stopped that way is not quiet: the app's exception hook
    shows and logs it, naming the series (only the read-only clean-up scans
    end without a word; see test_cleanup_lists_series_switch.py)
  * a close that fails part-way (a locked working file) leaves the series
    open, and a pass over it reads every section
  * the last progress update (100%) runs the event loop too, after the last
    section: a pass that still writes series data then (the copy's and the
    split's object attributes, an import's groups, hosts and alignment, and
    its series file) stops there the same way, while a pass that has nothing
    left to write ends as it was
  * so do the passes that only log after their sections, the z-trace made
    from an object, a rename of an object with no traces, and a series undo
    (its series attributes): a log or attribute written then is lost with
    the closed series, and the pass would end as if it had finished
  * Calibrate and Edit all image sources write through the window after
    their pass, and the window then holds the series opened in its place:
    stopped, they leave that series alone
"""
import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter


@pytest.fixture
def series(series_jser):
    from PyReconstruct.modules.datatypes.series import Series
    opened = Series.openJser(str(series_jser), progress=NullProgressReporter)
    yield opened
    opened.leave_open = False
    opened.close()


def _closes_at(series, update, leave_open=False):
    """Close the series at the given progress update of its next pass.

    Returns the progress values reported and whether the pass finished it.
    """
    seen = {"reported": [], "finished": False}

    class Closes(NullProgressReporter):
        def set_progress(self, percent):
            seen["reported"].append(percent)
            if len(seen["reported"]) == update:
                series.leave_open = leave_open
                series.close()

        def finish(self):
            seen["finished"] = True

    series.setProgressReporter(Closes)
    return seen


@pytest.mark.parametrize("leave_open", [False, True])
def test_a_pass_stops_before_reading_a_closed_series(
    series, monkeypatch, leave_open
):
    from PyReconstruct.modules.datatypes.series import (
        Series,
        SeriesClosedError,
    )
    assert len(series.sections) > 2
    loaded = []
    load = Series.loadSection
    monkeypatch.setattr(
        Series, "loadSection",
        lambda self, n: loaded.append(n) or load(self, n),
    )
    seen = _closes_at(series, update=2, leave_open=leave_open)

    visited = []
    with pytest.raises(SeriesClosedError) as raised:
        for snum, _section in series.enumerateSections(message="Scanning..."):
            visited.append(snum)

    assert isinstance(raised.value, FileNotFoundError)
    assert visited == loaded == sorted(series.sections)[:1]
    assert seen["finished"]


def test_a_write_pass_stopped_part_way_is_reported(
    series, monkeypatch, tmp_path
):
    import sys
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    from PyReconstruct.modules.gui.utils import errors
    shown, printed = [], []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda summary, report, *a, **k: shown.append(report) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    log = tmp_path / "log.txt"
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: str(log))
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: printed.append(a))
    # an object on several sections, so the copy saves some and not others
    name = "d03p14"
    assert len(series.getObjectSections([name])) > 2
    # leave_open keeps the working files, so the saved part of the copy stays
    _closes_at(series, update=2, leave_open=True)

    try:
        series.copyObjects([name])
    except SeriesClosedError:
        errors.customExcepthook(*sys.exc_info())
    else:
        pytest.fail("the copy ran on after its series closed")

    assert len(shown) == 1 and len(printed) == 1
    assert series.name in shown[0] and "part-way" in shown[0]
    assert log.exists() and "SeriesClosedError" in log.read_text()


def test_a_failed_close_leaves_the_series_usable(series, monkeypatch):
    import os
    removed = []

    def locked(path):
        removed.append(path)
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(os, "remove", locked)
    with pytest.raises(PermissionError):
        series.close()
    monkeypatch.undo()

    assert len(removed) == 1 and os.path.isdir(series.hidden_dir)
    assert not series.closed
    visited = [
        snum for snum, _section
        in series.enumerateSections(message="Scanning...")
    ]
    assert visited == sorted(series.sections)


def _closes_at_the_end(series, save_first=False, then=None):
    """Close the series at the last progress update of its next pass.

    The last update is the only one at 100%: the others report the share of
    sections done before the next one loads. save_first saves the .jser at
    the switch, as answering Yes to the save prompt does. then runs after the
    close, as the rest of opening another series does.
    """
    seen = {"reported": [], "switched": False}

    class Closes(NullProgressReporter):
        def set_progress(self, percent):
            seen["reported"].append(percent)
            # once: the save reports its own progress here
            if percent == 100 and not seen["switched"]:
                seen["switched"] = True
                if save_first:
                    series.saveJser()
                series.close()
                if then is not None:
                    then()

    series.setProgressReporter(Closes)
    return seen


def _open_other(tmp_path):
    import shutil
    from PyReconstruct.modules.datatypes.series import Series
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_fp = other_dir / "other.jser"
    shutil.copyfile(tmp_path / "series.jser", other_fp)
    return Series.openJser(str(other_fp), progress=NullProgressReporter)


def _write_tforms(series, path):
    with open(path, "w") as f:
        for snum in sorted(series.sections):
            f.write(f"{snum} 1 0 5 0 1 7\n")
    return str(path)


def _write_swift(series, path):
    import json
    cafm = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    level = {"swim_settings": {"img_size": [100, 100]}, "alt_cafm": cafm}
    stack = [{"levels": {"s1": level}} for _ in series.sections]
    with open(path, "w") as f:
        json.dump({"level_data": {"s1": {}}, "stack": stack}, f)
    return str(path)


def _copy(series, tmp_path):
    return series.copyObjects(["d03p14"])


def _split(series, tmp_path):
    return series.splitObject("d03p14")


def _import_traces(series, tmp_path):
    other = _open_other(tmp_path)
    try:
        return series.importTraces(other)
    finally:
        other.close()


def _import_alignments(series, tmp_path):
    other = _open_other(tmp_path)
    try:
        alignment = sorted(other.alignments)[0]
        return series.importTransforms(other, [(alignment, "imported")])
    finally:
        other.close()


def _import_bc(series, tmp_path):
    other = _open_other(tmp_path)
    try:
        profile = sorted(other.bc_profiles)[0]
        return series.importBC(other, [(profile, "imported")])
    finally:
        other.close()


def _import_tforms_file(series, tmp_path):
    from PyReconstruct.modules.backend.func import importTransforms
    return importTransforms(series, _write_tforms(series, tmp_path / "t.txt"))


def _import_swift(series, tmp_path):
    from PyReconstruct.modules.backend.func import importSwiftTransforms
    return importSwiftTransforms(
        series, _write_swift(series, tmp_path / "p.json")
    )


WRITES_AFTER = {
    "copy": _copy,
    "split": _split,
    "import traces": _import_traces,
    "import alignments": _import_alignments,
    "import brightness": _import_bc,
    "import transforms file": _import_tforms_file,
    "import SWiFT": _import_swift,
}


@pytest.mark.parametrize("leave_open", [False, True])
@pytest.mark.parametrize("run", list(WRITES_AFTER.values()),
                         ids=list(WRITES_AFTER))
def test_a_pass_that_writes_after_its_sections_stops_at_the_last_update(
    series, tmp_path, run, leave_open
):
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    series.leave_open = leave_open
    seen = _closes_at_the_end(series)

    with pytest.raises(SeriesClosedError, match="part-way"):
        run(series, tmp_path)

    # only the last update reports 100: every section was done first
    assert seen["switched"] and series.closed


def test_a_copy_closed_at_the_last_update_is_not_a_success(series, tmp_path):
    """The .jser saved at the switch has the copied traces and not the
    copy's alignment, groups and hosts, so the copy must not end as if it
    had finished."""
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import (
        Series,
        SeriesClosedError,
    )
    name = "d03p14"
    series.setAttr(name, "alignment", "no-alignment")
    series.object_groups.add("kept", name)
    host = next(n for n in sorted(series.data["objects"]) if n != name)
    series.setObjHosts([name], [host])
    _closes_at_the_end(series, save_first=True)

    with pytest.raises(SeriesClosedError, match="part-way"):
        series.copyObjects([name])

    saved = Series.openJser(series.jser_fp, progress=NullProgressReporter)
    try:
        assert saved.data.getCount(f"{name}_copy")
        assert not saved.object_groups.getObjectGroups(f"{name}_copy")
    finally:
        saved.close()


def test_a_pass_with_nothing_left_to_write_ends_at_the_last_update(series):
    seen = _closes_at_the_end(series)

    visited = [
        snum for snum, _section
        in series.enumerateSections(message="Scanning...")
    ]

    assert visited == sorted(series.sections)
    assert seen["switched"] and series.closed


OBJ = "d03p14"


def _events(series):
    return [log.event for log in series.log_set.all_logs]


def _remove_tags(series, tmp_path):
    return series.removeAllTraceTags([OBJ])


def _recolor(series, tmp_path):
    return series.reapplyAutosegColors([OBJ])


def _hide(series, tmp_path):
    return series.hideObjects([OBJ])


def _restore_visibility(series, tmp_path):
    snapshot = series.snapshotObjectVisibility([OBJ])
    flipped = {
        name: {snum: [not h for h in flags] for snum, flags in by.items()}
        for name, by in snapshot.items()
    }
    return series.restoreObjectVisibility(flipped)


def _hide_all(series, tmp_path):
    return series.hideAllTraces()


def _modify_alignments(series, tmp_path):
    alignments = {a: a for a in series.alignments}
    alignments["renamed"] = sorted(series.alignments)[0]
    return series.modifyAlignments(alignments)


def _modify_bc(series, tmp_path):
    profiles = {p: p for p in series.bc_profiles}
    profiles["renamed"] = sorted(series.bc_profiles)[0]
    return series.modifyBCProfiles(profiles)


def _import_flags(series, tmp_path):
    other = _open_other(tmp_path)
    try:
        return series.importFlags(other, (min(other.sections), max(other.sections) + 1))
    finally:
        other.close()


def _ztrace_midpoints(series, tmp_path):
    return series.createZtrace(OBJ, cross_sectioned=True)


def _ztrace_per_trace(series, tmp_path):
    return series.createZtrace(OBJ, cross_sectioned=False)


def _rename_traceless(series, tmp_path):
    series.setAttr("traceless", "comment", "kept")
    # its log comes before the pass; the attributes move after it
    return series.editObjectAttributes(
        ["traceless"], name="renamed", log_event=False
    )


LOGS_OR_WRITES_AFTER = {
    "remove trace tags": _remove_tags,
    "reapply colors": _recolor,
    "hide objects": _hide,
    "restore visibility": _restore_visibility,
    "hide all traces": _hide_all,
    "modify alignments": _modify_alignments,
    "modify brightness profiles": _modify_bc,
    "import flags": _import_flags,
    "ztrace from midpoints": _ztrace_midpoints,
    "ztrace from every trace": _ztrace_per_trace,
    "rename an object with no traces": _rename_traceless,
}


@pytest.mark.parametrize("leave_open", [False, True])
@pytest.mark.parametrize("run", list(LOGS_OR_WRITES_AFTER.values()),
                         ids=list(LOGS_OR_WRITES_AFTER))
def test_a_pass_that_logs_after_its_sections_stops_at_the_last_update(
    series, tmp_path, run, leave_open
):
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    series.leave_open = leave_open
    logged = _events(series)
    ztraces = set(series.ztraces)
    seen = _closes_at_the_end(series)

    with pytest.raises(SeriesClosedError, match="part-way"):
        run(series, tmp_path)

    assert seen["switched"] and series.closed
    # nothing went into the closed series after its last section
    assert _events(series) == logged
    assert set(series.ztraces) == ztraces
    assert "renamed" not in series.obj_attrs


def test_a_pass_with_logging_off_ends_at_the_last_update(series):
    seen = _closes_at_the_end(series)

    series.hideAllTraces(log_event=False)

    assert seen["switched"] and series.closed


def test_a_rename_with_traces_ends_at_the_last_update(series):
    """The rename moves the object's attributes on the first section, so
    nothing is left to write after the last one."""
    seen = _closes_at_the_end(series)

    series.editObjectAttributes([OBJ], name="renamed")

    assert seen["switched"] and series.closed
    assert "renamed" in series.obj_attrs


class _Field:
    """The parts of the field that setMag touches. The window reuses its
    field for the series it opens next, so self.series changes under a
    pass."""

    def __init__(self, series):
        from PyReconstruct.modules.backend.func.state_manager import (
            SeriesStates,
        )
        from PyReconstruct.modules.gui.main.field_widget_4_data import (
            FieldWidgetData,
        )
        self.series = series
        self.series_states = SeriesStates(series)
        self.reloaded = False
        self.table_manager = type(
            "Tables", (), {"recreateTables": lambda *a, **k: None}
        )()
        self.setMag = FieldWidgetData.setMag.__get__(self)

    def reload(self, clear_states=False):
        self.reloaded = True


def test_a_calibration_closed_at_the_last_update_leaves_the_next_series_alone(
    series, tmp_path
):
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    field = _Field(series)
    other = _open_other(tmp_path)
    try:
        logged = _events(other)
        mag = series.loadSection(min(series.sections)).mag
        _closes_at_the_end(series, then=lambda: setattr(field, "series", other))

        with pytest.raises(SeriesClosedError, match="part-way"):
            field.setMag(mag * 1.5)

        assert _events(other) == logged
        assert not field.reloaded
    finally:
        other.close()


def test_edit_all_image_sources_closed_at_the_last_update_leaves_the_next_series_alone(
    series, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    from PyReconstruct.modules.gui.table import section as section_mod
    from PyReconstruct.modules.gui.table.section import SectionTableWidget
    for snum in series.sections:
        series.data["sections"][snum]["locked"] = False
    monkeypatch.setattr(
        section_mod.QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("img_#.tif", True)),
    )
    marked = []
    window = SimpleNamespace(
        saveAllData=lambda: None,
        seriesModified=marked.append,
        field=SimpleNamespace(reload=lambda: None, reloadImage=lambda: None),
    )
    table = SimpleNamespace(
        series=series, mainwindow=window,
        manager=SimpleNamespace(updateSections=lambda snums: None),
    )
    logged = _events(series)
    _closes_at_the_end(series)

    with pytest.raises(SeriesClosedError, match="part-way"):
        SectionTableWidget.modifyAllSrc(table)

    # marking the window modified would mark the series opened in its place
    assert marked == []
    assert _events(series) == logged


def test_a_series_undo_closed_at_the_last_update_is_not_a_success(series):
    """The undo's series attributes come after its sections, so it stops
    there with an error and its step stays where it was."""
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    field = _Field(series)
    field.setMag(series.loadSection(min(series.sections)).mag * 1.5)
    states = field.series_states
    assert states.canUndo()[0]
    undos = list(states.undos)
    _closes_at_the_end(series)

    with pytest.raises(SeriesClosedError, match="part-way"):
        states.undoState()

    assert states.undos == undos and not states.redos
