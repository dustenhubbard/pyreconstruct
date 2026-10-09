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


def _closes_at_the_end(series, save_first=False):
    """Close the series at the last progress update of its next pass.

    The last update is the only one at 100%: the others report the share of
    sections done before the next one loads. save_first saves the .jser at
    the switch, as answering Yes to the save prompt does.
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
