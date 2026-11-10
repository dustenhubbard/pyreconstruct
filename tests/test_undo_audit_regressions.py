"""Undo and redo preserve complete edits without loading unrelated sections."""

from copy import deepcopy

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Flag, Trace, Ztrace


@pytest.fixture
def history(real_series):
    series = real_series
    series.setProgressReporter(NullProgressReporter)
    series.current_section = 0
    section = series.loadSection(0)
    states = SeriesStates(series)
    states[section]
    return series, section, states


def trace(name="undo_audit"):
    item = Trace(name, (255, 0, 0), True)
    item.points = [(1, 1), (2, 1), (2, 2)]
    return item


@pytest.mark.gui
def test_paste_is_one_undo_and_redo(main_window):
    field = main_window.field
    before = sum(len(c) for c in field.section.contours.values())
    field.clipboard = [trace("paste_a"), trace("paste_b")]
    assert field.paste()
    assert sum(len(c) for c in field.section.contours.values()) == before + 2
    main_window.undo()
    assert sum(len(c) for c in field.section.contours.values()) == before
    main_window.undo(True)
    assert sum(len(c) for c in field.section.contours.values()) == before + 2


@pytest.mark.parametrize("selected", [[0], [0, 2]])
@pytest.mark.parametrize("existing", [True, False])
@pytest.mark.parametrize("earlier_edit", [True, False])
def test_ztrace_move_after_creation_restores_latest_points(history, existing, earlier_edit, selected):
    series, section, states = history
    if existing:
        series.ztraces["regenerated"] = Ztrace(
            "regenerated", (0, 255, 0), [(1, 1, 0), (2, 2, 1)]
        )
        # Open history while the previous two-point z-trace exists.
        states[0].initialize(section, series)
    if earlier_edit:
        section.addTrace(trace(), log_event=False)
        states.commitSection(section)
    points = [(10, 10, 0), (20, 20, 1), (30, 30, 0)]
    series.createZtrace("regenerated", z_points=list(points), log_event=False)
    series.clearTracking()
    section.selected_ztraces = [(series.ztraces["regenerated"], i) for i in selected]
    section.translateTraces(5, 7, log_event=False)
    states.commitSection(section)
    # A later change on another section must survive this section's undo.
    series.ztraces["regenerated"].points[1] = (99, 99, 1)
    step = states.undoSection(section)
    assert step.ztraces == {"regenerated"}
    assert series.ztraces["regenerated"].points == [
        (10, 10, 0), (99, 99, 1), (30, 30, 0)
    ]
    states.undoSection(section, redo=True)
    assert series.ztraces["regenerated"].points == [
        (15, 17, 0), (99, 99, 1),
        (35, 37, 0) if 2 in selected else (30, 30, 0),
    ]


def test_ztrace_move_preserves_points_added_on_another_section(history):
    series, section, states = history
    series.createZtrace(
        "extended", z_points=[(10, 10, 0), (20, 20, 1)], log_event=False
    )
    series.clearTracking()
    section.selected_ztraces = [(series.ztraces["extended"], 0)]
    section.translateTraces(5, 7, log_event=False)
    states.commitSection(section)
    series.ztraces["extended"].points.append((60, 70, 1))

    states.undoSection(section)
    assert series.ztraces["extended"].points == [
        (10, 10, 0), (20, 20, 1), (60, 70, 1)
    ]
    states.undoSection(section, redo=True)
    assert series.ztraces["extended"].points == [
        (15, 17, 0), (20, 20, 1), (60, 70, 1)
    ]


@pytest.mark.parametrize("edit", ["title", "comment", "position", "status", "color"])
def test_flag_edit_after_redo_can_be_undone(history, edit):
    series, section, states = history
    flag = Flag("original", 1, 2, 0, [255, 0, 0])
    flag.addComment("tester", "original comment")
    section.addFlag(flag, log_event=False)
    states.commitSection(section)
    states.undoSection(section)
    states.undoSection(section, redo=True)
    before = deepcopy(section.flags[0].getList())
    flag = section.flags[0]
    if edit == "title":
        flag.name = "edited"
    elif edit == "comment":
        flag.comments[0].text = "edited comment"
        flag.addComment("tester", "new comment")
    elif edit == "position":
        flag.x, flag.y = 30, 40
    elif edit == "color":
        flag.color[0] = 128
    else:
        flag.resolve("tester", True)
    section.flags_modified = True
    after = flag.getList()
    states.commitSection(section)
    states.undoSection(section)
    assert section.flags[0].getList() == before
    states.undoSection(section, redo=True)
    assert section.flags[0].getList() == after


@pytest.mark.parametrize("redo", [False, True])
def test_series_undo_and_redo_load_only_affected_sections(history, monkeypatch, redo):
    series, _, states = history
    assert len(series.sections) > 100
    for _, section in series.enumerateSections(
        series_states=states, section_numbers=[1], show_progress=False
    ):
        section.addTrace(trace(), log_event=False)
        section.save()
    if redo:
        states.undoState()
    loaded = []
    load = series.loadSection

    def record_load(snum):
        loaded.append(snum)
        return load(snum)

    monkeypatch.setattr(series, "loadSection", record_load)
    states.undoState(redo=redo)
    assert len(load(1).contours.get("undo_audit", [])) == (1 if redo else 0)
    assert loaded == [1]
