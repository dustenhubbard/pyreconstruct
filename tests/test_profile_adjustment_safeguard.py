"""The first profile adjustment offers a copy and preserves the starting values."""

import pytest
from PySide6.QtWidgets import QMessageBox, QInputDialog

from PyReconstruct.modules.datatypes import Transform, Trace

pytestmark = pytest.mark.gui


def snapshot(series, name, alignment=False):
    values = {}
    for n in series.sections:
        section = series.loadSection(n)
        values[n] = (section.tforms[name].getList() if alignment
                     else tuple(section.bc_profiles[name]))
    return values


@pytest.mark.parametrize("adjustment", ["brightness", "contrast", "alignment"])
def test_skipping_new_profile_preserves_original(
    main_window, main_window_dialogs, adjustment,
):
    field, series = main_window.field, main_window.series
    alignment = adjustment == "alignment"
    current = series.alignment if alignment else series.bc_profile
    profiles = field.section.tforms if alignment else field.section.bc_profiles
    names_before = set(profiles)
    before = snapshot(series, current, alignment)
    main_window_dialogs.message_box_response = QMessageBox.No

    if alignment:
        field.unlockSection()
        field.changeTform(Transform([1, 0, 5, 0, 1, 7]))
    elif adjustment == "brightness":
        field.setBrightness(34)
    else:
        field.setContrast(-23)

    if alignment:
        assert series.alignment == current
        assert field.section.tform.getList() == [1, 0, 5, 0, 1, 7]
    else:
        assert series.bc_profile == current
        assert (field.section.brightness if adjustment == "brightness"
                else field.section.contrast) == (34 if adjustment == "brightness" else -23)
    main_window.saveAllData()

    profiles = field.section.tforms if alignment else field.section.bc_profiles
    backups = set(profiles) - names_before
    assert len(backups) == 1, "the first adjustment must save the original profile"
    backup = backups.pop()
    for n in series.sections:
        section = series.loadSection(n)
        saved = (section.tforms[backup].getList() if alignment
                 else tuple(section.bc_profiles[backup]))
        assert saved == before[n]
    assert main_window_dialogs.message_boxes, "offer a new profile before editing"


@pytest.mark.parametrize("alignment", [False, True], ids=["bc", "alignment"])
def test_new_profile_keeps_source_and_receives_first_adjustment(
    main_window, main_window_dialogs, monkeypatch, alignment,
):
    field, series = main_window.field, main_window.series
    current = series.alignment if alignment else series.bc_profile
    before = snapshot(series, current, alignment)
    current_before = before[series.current_section]
    main_window_dialogs.message_box_response = QMessageBox.Yes
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("adjusted", True))

    if alignment:
        field.unlockSection()
        field.changeTform(Transform([1, 0, 5, 0, 1, 7]))
        assert series.alignment == "adjusted"
        assert field.section.tforms[current].getList() == current_before
        assert field.section.tform.getList() == [1, 0, 5, 0, 1, 7]
        field.translateTform(1, 0)
    else:
        field.setBrightness(34)
        assert series.bc_profile == "adjusted"
        assert tuple(field.section.bc_profiles[current]) == current_before
        assert field.section.brightness == 34
        field.setContrast(-23)
    assert len(main_window_dialogs.message_boxes) == 1
    main_window.saveAllData()
    assert snapshot(series, current, alignment) == before


@pytest.mark.parametrize("alignment", [False, True], ids=["bc", "alignment"])
@pytest.mark.parametrize("answer,name", [
    (QMessageBox.Cancel, None),
    (QMessageBox.Yes, None),
    (QMessageBox.Yes, ""),
    (QMessageBox.Yes, "existing"),
])
def test_cancel_or_invalid_name_does_not_adjust_or_copy(
    main_window, main_window_dialogs, monkeypatch, alignment, answer, name,
):
    field, series = main_window.field, main_window.series
    profiles = field.section.tforms if alignment else field.section.bc_profiles
    before = {n: v.getList() if alignment else tuple(v) for n, v in profiles.items()}
    current = series.alignment if alignment else series.bc_profile
    main_window_dialogs.message_box_response = answer
    monkeypatch.setattr(
        QInputDialog, "getText",
        lambda *a, **k: (current if name == "existing" else name, name is not None),
    )

    if alignment:
        field.section.align_locked = False
        field.translateTform(1, 0)
    else:
        (_, slider), _ = main_window.mouse_palette.bc_widgets
        slider.setValue(70)
        assert slider.value() == 0

    profiles = field.section.tforms if alignment else field.section.bc_profiles
    assert {n: v.getList() if alignment else tuple(v) for n, v in profiles.items()} == before


def test_backup_is_not_replaced_by_more_edits_or_paging(main_window, main_window_dialogs):
    field, series = main_window.field, main_window.series
    main_window_dialogs.message_box_response = QMessageBox.No
    current = series.bc_profile
    before = snapshot(series, current)
    field.setBrightness(34)
    backup = (set(field.section.bc_profiles) - {current}).pop()
    field.setContrast(-23)
    dest = next(n for n in series.sections if n != series.current_section)
    main_window.changeSection(dest)
    field.setBrightness(57)
    main_window.saveAllData()

    assert len(main_window_dialogs.message_boxes) == 1
    assert snapshot(series, backup) == before


def test_an_existing_backup_is_never_overwritten(main_window, main_window_dialogs):
    field, series = main_window.field, main_window.series
    main_window_dialogs.message_box_response = QMessageBox.No
    before = snapshot(series, series.bc_profile)
    field.setBrightness(34)
    main_window.saveToJser(notify=False)
    main_window.openSeries(jser_fp=series.jser_fp, query_prev=False)
    field, series = main_window.field, main_window.series
    field.setBrightness(57)
    main_window.saveAllData()

    assert snapshot(series, "default (backup)") == before
    assert tuple(field.section.bc_profiles["default (backup 2)"]) == (34, 0)


def test_bulk_bc_adjustment_preserves_each_sections_values(main_window, main_window_dialogs):
    field, series = main_window.field, main_window.series
    main_window_dialogs.message_box_response = QMessageBox.No
    other = next(n for n in series.sections if n != series.current_section)
    section = series.loadSection(other)
    section.bc_profiles[series.bc_profile] = (17, -31)
    section.save()
    field.openList("section")
    table = field.table_manager.tables["section"][0]

    table.setBC([series.current_section, other], b=45, c=10)

    assert tuple(series.loadSection(other).bc_profiles["default (backup)"]) == (17, -31)
    assert tuple(series.loadSection(other).bc_profiles["default"]) == (45, 10)
    assert tuple(field.section.bc_profiles["default (backup)"]) == (0, 0)


def test_optimization_safeguards_profile_before_backend_runs(
    main_window, main_window_dialogs, monkeypatch,
):
    from PyReconstruct.modules.gui.main import main_window as mw

    main_window_dialogs.message_box_response = QMessageBox.No
    before = snapshot(main_window.series, main_window.series.bc_profile)
    monkeypatch.setattr(mw.QuickDialog, "get", lambda *a, **k: ([128, 60, [(None, True)]], True))
    monkeypatch.setattr(mw, "noUndoWarning", lambda: True)
    called = []

    def optimize(series, *args):
        assert snapshot(series, "default (backup)") == before
        called.append(True)

    monkeypatch.setattr(mw, "optimizeSeriesBC", optimize)
    main_window.optimizeBC()
    assert called == [True]


def test_alignment_undo_keeps_backup_until_copy_is_undone(main_window, main_window_dialogs):
    field, series = main_window.field, main_window.series
    main_window_dialogs.message_box_response = QMessageBox.No
    field.unlockSection()
    current = series.alignment
    before = field.section.tform.getList()
    field.translateTform(5, 7)
    backup = f"{current} (backup)"

    main_window.undo()
    assert field.section.tform.getList() == before
    assert field.section.tforms[backup].getList() == before
    main_window.undo()
    assert backup not in field.section.tforms
    field.translateTform(2, 3)
    assert backup in field.section.tforms
    assert len(main_window_dialogs.message_boxes) == 2


@pytest.mark.parametrize("route", ["navigation", "bulk"])
def test_propagation_preserves_every_sections_original_transform(
    main_window, main_window_dialogs, monkeypatch, route,
):
    from PyReconstruct.modules.gui.main import field_widget_4_data as data

    monkeypatch.setattr(data, "notifyConfirm", lambda *a, **k: True)
    field, series = main_window.field, main_window.series
    main_window_dialogs.message_box_response = QMessageBox.No
    start = series.current_section
    other = next(n for n in sorted(series.sections) if n > start)
    section = series.loadSection(other)
    section.align_locked = False
    section.save()
    current = series.alignment
    before = snapshot(series, current, alignment=True)
    field.setPropagationMode(True)
    delta = Transform([1, 0, 5, 0, 1, 7])
    field.stored_tform = delta.copy()

    if route == "navigation":
        main_window.changeSection(other)
    else:
        field.propagateTo(to_end=True)
    main_window.saveAllData()

    assert snapshot(series, f"{current} (backup)", alignment=True) == before
    assert series.loadSection(other).tform.equals(delta * Transform(before[other]))


@pytest.mark.parametrize("alignment", [False, True], ids=["bc", "alignment"])
def test_profile_copy_keeps_unsaved_traces_in_both_held_sections(
    main_window, main_window_dialogs, alignment,
):
    field, series = main_window.field, main_window.series
    main_window_dialogs.message_box_response = QMessageBox.No
    first = series.current_section
    other = next(n for n in series.sections if n != first)
    trace = Trace("unsaved_safeguard", (0, 255, 0), True)
    square = [(100, 300), (200, 300), (200, 200), (100, 200)]
    field.newTrace(square, trace, closed=True)
    field.changeSection(other)
    field.newTrace(square, trace, closed=True)

    if alignment:
        field.unlockSection()
        field.translateTform(5, 7)
    else:
        field.setBrightness(34)

    for n in (first, other):
        assert len(series.loadSection(n).contours[trace.name]) == 1
    assert len(field.section.contours[trace.name]) == 1
    assert len(field.b_section.contours[trace.name]) == 1


def test_no_change_or_locked_alignment_does_not_prompt(main_window, main_window_dialogs):
    field = main_window.field
    before_bc = set(field.section.bc_profiles)
    before_alignments = set(field.section.tforms)

    field.setBrightness(field.section.brightness)
    field.setContrast(field.section.contrast)
    field.changeTform(field.section.tform.copy())
    field.section.align_locked = True
    field.translateTform(5, 7)

    assert main_window_dialogs.message_boxes == []
    assert set(field.section.bc_profiles) == before_bc
    assert set(field.section.tforms) == before_alignments
