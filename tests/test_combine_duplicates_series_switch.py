"""A Duplicates combine on series A leaves alone a series B opened during it.

The combine runs under a progress dialog, and the dialog runs the event loop on
each update, so a .jser opened from the Finder reaches the window there. B
opens and A closes. When the combine returned, the field refreshed the object
tables and the canvas and marked the series modified, and by then the series
open was B. The list's own guard (MalformedContoursDialog._forOpenSeries) only
stops it pruning rows afterwards.

B opens at the first, a middle or the last progress update, and is either a
copy of A or A's own .jser opened again, which unpacks into the working folder
A used. Before the last update the pass still has a section of A to combine,
and it stops there with SeriesClosedError: it writes, so it says it stopped
part-way (see SeriesIterator.__next__).

What is pinned here:

  * B is not marked modified
  * B's traces are what its .jser holds, on every section of the combine
  * B's object table is not refreshed
  * the combine says it stopped when there was still a section to combine,
    and says nothing when B opened at the end
  * a combine that B opens under asks to save A first: the sections it
    combined were in A's working folder, and closing A deleted them unasked
    when A had been saved just before
  * answering that prompt, Yes or Cancel, keeps every section the combine
    wrote combined, also the section shown and the flickered-away one: the
    save writes the field's loaded copies of those, and copies loaded before
    the combine put the duplicates back
  * a section the combine wrote is in its undo step even when refreshing
    the field's copy of it raised
"""
import shutil

import pytest

from tests.test_cleanup_lists_series_switch import (  # noqa: F401  (fixture)
    SCAN_UPDATES,
    SQUARE,
    _counts,
    _open_copy,
    confirmed,
    finder,
)

pytestmark = pytest.mark.gui


def _plant_on_two_sections(window, name, snums=None):
    """Add two copies of one trace to two sections and save the series.

    snums names the sections, the first two by default. Returns them.
    """
    from PyReconstruct.modules.datatypes.trace import Trace
    window.saveAllData()
    if snums is None:
        snums = sorted(window.series.sections)[:2]
    for snum in snums:
        section = window.series.loadSection(snum)
        for _ in range(2):
            trace = Trace(name, (255, 0, 0), closed=True)
            trace.points = list(SQUARE)
            section.addTrace(trace, log_event=False)
        section.save()
    window.field.reload()
    window.series.saveJser()
    return snums


def _reopen_from_finder(window, qtbot):
    """Open the current series' own .jser again, as the Finder sends it."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent
    from PySide6.QtWidgets import QApplication
    first = window.series
    app = QApplication.instance()
    app.sendEvent(app, QFileOpenEvent(QUrl.fromLocalFile(first.jser_fp)))
    assert window.series is not first
    assert window.series.jser_fp == first.jser_fp
    qtbot.wait(10)


OPENS = {
    "a copy": lambda window, tmp_path, qtbot: _open_copy(
        window, tmp_path, qtbot, from_finder=True
    ),
    "the same file": lambda window, tmp_path, qtbot: _reopen_from_finder(
        window, qtbot
    ),
}


def _b_opens_during_the_combine(window, tmp_path, qtbot, update, opens):
    """Open B from the Finder at one progress update of A's next pass.

    update names the update (see SCAN_UPDATES), opens what B is (see OPENS)
    or is the function that opens it. Opens it once: saving A on the way out
    reports progress too. Returns the progress values A reported.
    """
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    reported = []
    due = SCAN_UPDATES[update]
    opened = []

    class OpensB(NullProgressReporter):
        def set_progress(self, percent):
            if opened:
                return
            reported.append(percent)
            if due(percent):
                opened.append(percent)
                OPENS.get(opens, opens)(window, tmp_path, qtbot)

    window.series.setProgressReporter(OpensB)
    return reported


def _scan(window, main_window_dialogs, name):
    """Run the Duplicates scan; returns its list, with a row for name."""
    main_window_dialogs.responses = [
        ([0.95, [("check locked traces", False)]], True)
    ]
    window.reviewDuplicateTraces()
    dialog = window.duplicate_traces_dialog
    assert sum(g["names"] == [name] for g, _keep in dialog.choices()) == 2
    return dialog


@pytest.mark.parametrize("opens", list(OPENS))
@pytest.mark.parametrize("update", list(SCAN_UPDATES))
def test_a_combine_b_opens_under_leaves_b_alone(
    update, opens, main_window, main_window_dialogs, monkeypatch, tmp_path,
    qtbot, confirmed, finder,  # noqa: F811
):
    from PyReconstruct.modules.backend.table.manager import TableManager
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    window = main_window
    snums = _plant_on_two_sections(window, "SWITCH_DUP")
    dialog = _scan(window, main_window_dialogs, "SWITCH_DUP")
    first = window.series
    saved = [_counts(first, snum) for snum in snums]
    assert [counts["SWITCH_DUP"] for counts in saved] == [2, 2]
    reported = _b_opens_during_the_combine(
        window, tmp_path, qtbot, update, opens
    )
    # the field builds a new table manager for B, so watch the class
    refreshed = []
    monkeypatch.setattr(
        TableManager, "updateObjects",
        lambda manager, *a, **k: refreshed.append(manager.series),
    )

    if update == "last":
        dialog.combineAll()
    else:
        with pytest.raises(SeriesClosedError, match="part-way"):
            dialog.combineAll()

    assert any(SCAN_UPDATES[update](p) for p in reported)
    assert window.series is not first
    assert [_counts(window.series, snum) for snum in snums] == saved
    assert not window.series.modified
    assert window.series not in refreshed


@pytest.mark.parametrize("update", ["middle", "last"])
def test_a_combine_b_opens_under_asks_to_save_a(
    update, main_window, main_window_dialogs, tmp_path, qtbot,
    confirmed, finder,  # noqa: F811
):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    window = main_window
    snums = _plant_on_two_sections(window, "SWITCH_DUP")
    dialog = _scan(window, main_window_dialogs, "SWITCH_DUP")
    first = window.series
    # just saved, as File > Save leaves it
    window.seriesModified(False)
    _b_opens_during_the_combine(window, tmp_path, qtbot, update, "a copy")
    main_window_dialogs.save_response = "yes"

    try:
        dialog.combineAll()
    except FileNotFoundError:
        assert update == "middle"

    assert window.series is not first
    assert main_window_dialogs.save_prompts == 1
    combined = 1 if update == "middle" else 2
    a = Series.openJser(first.jser_fp, progress=NullProgressReporter)
    try:
        assert [_counts(a, snum)["SWITCH_DUP"] for snum in snums] == (
            [1] * combined + [2] * (2 - combined)
        )
    finally:
        a.close()


def _plant_where_the_field_holds(window, name, held):
    """Plant duplicates on two sections the field holds loaded copies of.

    held "shown": the first is the section shown. held "flickered": the
    first is the flickered-away section (b_section) and the second is shown.
    Returns the section numbers, in the order the combine writes them.
    """
    snums = sorted(window.series.sections)
    shown = window.series.current_section
    pair = [shown, snums[snums.index(shown) + 1]]
    _plant_on_two_sections(window, name, pair)
    if held == "flickered":
        window.changeSection(pair[1])
        assert window.field.b_section.n == pair[0]
    assert window.field.section.n == pair[held == "flickered"]
    return pair


def _offer_copy_from_finder(window, tmp_path, qtbot):
    """Send a copy of the series from the Finder; the save prompt decides."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent
    from PySide6.QtWidgets import QApplication
    copy_fp = tmp_path / "series_b" / "series_b.jser"
    copy_fp.parent.mkdir()
    shutil.copyfile(window.series.jser_fp, copy_fp)
    app = QApplication.instance()
    app.sendEvent(app, QFileOpenEvent(QUrl.fromLocalFile(str(copy_fp))))
    qtbot.wait(10)


@pytest.mark.parametrize("unsaved", [False, True], ids=["saved", "unsaved"])
@pytest.mark.parametrize("answer", ["yes", "cancel"])
@pytest.mark.parametrize("held", ["shown", "flickered"])
@pytest.mark.parametrize("update", ["middle", "last"])
def test_saving_a_at_the_prompt_keeps_what_the_combine_wrote(
    update, held, answer, unsaved, main_window, main_window_dialogs,
    tmp_path, qtbot, confirmed, finder,  # noqa: F811
):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import (
        Series,
        SeriesClosedError,
    )
    window = main_window
    snums = _plant_where_the_field_holds(window, "SWITCH_DUP", held)
    dialog = _scan(window, main_window_dialogs, "SWITCH_DUP")
    first = window.series
    if not unsaved:
        # just saved, as File > Save leaves it
        window.seriesModified(False)
    assert first.modified == unsaved
    _b_opens_during_the_combine(
        window, tmp_path, qtbot, update, _offer_copy_from_finder
    )
    main_window_dialogs.save_response = answer

    try:
        dialog.combineAll()
    except (SeriesClosedError, FileNotFoundError):
        # Yes closed A with a section still to combine
        assert answer == "yes" and update == "middle"

    assert main_window_dialogs.save_prompts == 1
    if answer == "cancel":
        # A stays open and the combine finishes
        assert window.series is first
        assert [_counts(first, snum)["SWITCH_DUP"] for snum in snums] == [1, 1]
        assert len(window.field.section.contours["SWITCH_DUP"]) == 1
        return
    assert window.series is not first
    combined = 1 if update == "middle" else 2
    a = Series.openJser(first.jser_fp, progress=NullProgressReporter)
    try:
        assert [_counts(a, snum)["SWITCH_DUP"] for snum in snums] == (
            [1] * combined + [2] * (2 - combined)
        )
    finally:
        a.close()


def test_a_failed_field_refresh_leaves_the_written_section_undoable(
    main_window, main_window_dialogs, monkeypatch, confirmed,  # noqa: F811
):
    from PyReconstruct.modules.backend.table.manager import TableManager
    window = main_window
    snums = _plant_where_the_field_holds(window, "SWITCH_DUP", "shown")
    # the planting has no undo state: start the history after it
    window.field.clearStates()
    dialog = _scan(window, main_window_dialogs, "SWITCH_DUP")
    series = window.series
    change_section = TableManager.changeSection
    failed = []

    def fails_once(manager, section):
        if not failed:
            failed.append(section.n)
            raise RuntimeError("table refresh failed")
        return change_section(manager, section)

    monkeypatch.setattr(TableManager, "changeSection", fails_once)

    with pytest.raises(RuntimeError, match="table refresh failed"):
        dialog.combineAll()

    def counts():
        window.saveAllData()
        return [_counts(series, snum)["SWITCH_DUP"] for snum in snums]

    assert failed == [snums[0]]
    assert counts() == [1, 2]
    assert len(window.field.series_states[snums[0]].undo_states) == 1
    main_window_dialogs.linked_undo_responses = ["all", "all"]
    window.undo()
    assert counts() == [2, 2]
    window.undo(redo=True)
    assert counts() == [1, 2]
