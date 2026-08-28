"""The last of the review fleet's confirmed findings (2026-08-28).

Small, scattered, all real: an exported group name cut in two, stacked zarr
palettes wired to the wrong store, a menubar that never let a generation
die, dead file dialogs by the dozen, a Reset that reset nothing, a stamp
radius of zero, and navigation rows that pointed at the wrong trace after a
delete.
"""

import pytest

from PySide6.QtCore import Qt

pytestmark = pytest.mark.gui


# --- zarr export: group names with spaces -------------------------------------

def test_group_names_with_spaces_survive_into_the_command(main_window, monkeypatch, main_window_dialogs, tmp_path):
    import subprocess


    launched = []
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda cmd, **kw: launched.append(cmd) or None,
    )
    # the wizard's answers: sections, padding, the group, export-all
    main_window_dialogs.responses.append((
        [0, 5, 50, ["dendrite 1"], [("Export all tissue", False)]], True
    ))
    main_window_dialogs.file_responses.append(str(tmp_path / "out.zarr"))

    main_window.exportToZarr()

    assert launched, "the converter was never launched"
    cmd = launched[0]
    assert "dendrite 1" in cmd, (
        f"the group name was split or dropped: {cmd}"
    )
    assert "dendrite" not in [c for c in cmd if c != "dendrite 1"]


# --- the menubar generation dies with its rebuild -------------------------------

def test_menubar_rebuilds_do_not_stack_menu_generations(main_window, qapp):
    from PySide6.QtWidgets import QMenu

    menubar = main_window.menubar
    qapp.processEvents()
    baseline = len(menubar.findChildren(QMenu))

    for _ in range(3):
        main_window.createMenuBar()
    qapp.processEvents()

    assert len(menubar.findChildren(QMenu)) == baseline, (
        "old menu generations survive as menubar children"
    )


# --- zarr palettes never stack ----------------------------------------------------

def test_a_second_zarr_palette_retires_the_first(main_window, qapp, monkeypatch, tmp_path, main_window_dialogs):
    from shiboken6 import isValid

    zarr_a = tmp_path / "a.zarr"; (zarr_a / "g1").mkdir(parents=True)
    zarr_b = tmp_path / "b.zarr"; (zarr_b / "g2").mkdir(parents=True)

    main_window_dialogs.file_responses.append(str(zarr_a))
    main_window.setZarrLayer()
    first = main_window.zarr_palette
    assert first is not None

    main_window_dialogs.file_responses.append(str(zarr_b))
    main_window.setZarrLayer()
    qapp.processEvents()

    assert main_window.zarr_palette is not first
    # the old palette's widgets are gone from the window, so its combobox
    # can no longer write an old group name against the new store
    assert not isValid(first.bttn) or not first.bttn.isVisible()


# --- file dialogs leave nothing behind ---------------------------------------------

def test_file_dialog_get_leaves_no_child_behind(main_window, qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from PyReconstruct.modules.gui.dialog import file_dialog as fd_module

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    before = len(main_window.findChildren(QFileDialog))
    for _ in range(5):
        fd_module.FileDialog.get("file", main_window, "Open")
    qapp.processEvents()

    assert len(main_window.findChildren(QFileDialog)) == before


def test_update_settings_survives_a_vanished_directory(tmp_path):
    from PyReconstruct.modules.gui.dialog.file_dialog import FileDialog

    ghost = tmp_path / "gone" / "deeper" / "file.jser"
    FileDialog.updateSettings(str(ghost))    # raised UnboundLocalError before


# --- quick dialogs are destroyed on close -------------------------------------------

def test_a_confirmable_quick_dialog_dies_on_close(main_window, qapp):
    from shiboken6 import isValid

    from PyReconstruct.modules.gui.dialog import QuickDialog

    dialog = QuickDialog(
        main_window, [["Just a label"]], "Probe", include_confirm=True
    )
    dialog.show()
    dialog.close()
    for _ in range(5):
        qapp.processEvents()

    assert not isValid(dialog), "a one-shot quick dialog survived its close"


# --- the pill press swallow only eats the replayed press -----------------------------

def test_a_selection_close_does_not_eat_the_next_pill_click(main_window, qapp, monkeypatch):
    import time

    from PySide6.QtWidgets import QApplication

    segment = main_window.status_readout.lists_segment

    # a close by SELECTION: no mouse button is down when it lands
    monkeypatch.setattr(
        QApplication, "mouseButtons",
        staticmethod(lambda: Qt.MouseButton.NoButton),
    )
    segment.popupOpened()
    segment.popupClosed()

    assert segment._popup_hidden_at == 0.0, (
        "a keyboard/selection close armed the press swallow"
    )

    # a dismissal BY an outside press: the button is down at close time
    monkeypatch.setattr(
        QApplication, "mouseButtons",
        staticmethod(lambda: Qt.MouseButton.LeftButton),
    )
    segment.popupOpened()
    segment.popupClosed()
    assert time.monotonic() - segment._popup_hidden_at < 1.0


# --- surviving review rows keep pointing at their trace ------------------------------

def test_go_to_trace_stays_true_after_deleting_earlier_rows(main_window, qapp):
    from PyReconstruct.modules.gui.dialog.malformed_contours import (
        MalformedContoursDialog,
    )

    def record(index):
        return {
            "name": "axon", "section": 3, "index": index, "points": 4,
            "location": (0.0, 0.0), "reason": "test",
            "match": {"color": (1, 2, 3), "points": [index]},
        }

    records = [record(0), record(1), record(2)]
    visited = []
    dialog = MalformedContoursDialog(
        main_window, records,
        navigate=lambda snum, name, index: visited.append(index),
        delete=lambda recs: recs,      # "deleted" them all successfully
    )
    try:
        # delete the FIRST trace of the contour; the survivors shift down
        dialog._deleteRecordsUnprompted = None
        dialog._pruneRecords([records[0]])

        assert records[1]["index"] == 0
        assert records[2]["index"] == 1
    finally:
        dialog.deleteLater()
