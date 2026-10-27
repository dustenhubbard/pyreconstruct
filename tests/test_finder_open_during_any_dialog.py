"""A .jser opened from the Finder while any dialog or progress window is up.

A command that shows a dialog and then writes into window.series finished on
the series the Finder opened under that dialog. While a modal dialog, a
progress window or a status bar worker wait is up, the Finder open is
skipped with a notice, and the command writes into the series it started on.
"""
import threading

import pytest

from test_finder_open_during_transition import (
    _holds,
    _two_more_series,
    finder,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui


def _when_modal(cls, step):
    """Run step(dialog) from inside the event loop of the next modal cls.

    Returns a list that holds the dialog once step has run.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    ran = []

    def poll(tries=500):
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, cls) and dialog.isVisible():
            ran.append(dialog)
            step(dialog)
        elif tries:
            QTimer.singleShot(10, lambda: poll(tries - 1))

    QTimer.singleShot(0, poll)
    return ran


@pytest.fixture
def real_input_dialogs(monkeypatch):
    """QInputDialog.getText and getDouble as real modal dialogs.

    main_window_dialogs replaces them with recorders that never show a
    window. These build the dialog the static functions build and exec it.
    """
    from PySide6.QtWidgets import QDialog, QInputDialog

    def get_text(parent, title, label, *args, text="", **kwargs):
        dialog = QInputDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setTextValue(text)
        ok = dialog.exec() == QDialog.Accepted
        return dialog.textValue(), ok

    def get_double(parent, title, label, value=0.0, *args, decimals=1, **kwargs):
        dialog = QInputDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.DoubleInput)
        dialog.setDoubleDecimals(decimals)
        dialog.setDoubleRange(-1e9, 1e9)
        dialog.setDoubleValue(value)
        ok = dialog.exec() == QDialog.Accepted
        return dialog.doubleValue(), ok

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(get_text))
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(get_double))


def _refused(window, first, dialogs, c_fp, unsaved_fp, unsaved, count=1):
    assert window.series is first and not first.closed
    assert _holds(unsaved_fp, unsaved)
    assert sum(c_fp in n for n in dialogs.notices) == count


def test_a_finder_open_under_the_section_transform_prompt_edits_the_first(
    main_window, main_window_dialogs, finder, real_input_dialogs, tmp_path  # noqa: F811
):
    from PySide6.QtWidgets import QInputDialog
    window = main_window
    first = window.series
    snum = first.current_section
    window.field.section.align_locked = False
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def step(dialog):
        finder(c_fp)
        dialog.setTextValue("1 0 17 0 1 23")
        dialog.accept()

    ran = _when_modal(QInputDialog, step)
    window.changeTform()
    window.saveAllData()

    assert ran
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    assert first.loadSection(snum).tform.getList() == [1, 0, 17, 0, 1, 23]


def test_a_finder_open_under_the_alignment_dialog_changes_the_first(
    main_window, main_window_dialogs, finder, tmp_path  # noqa: F811
):
    from PyReconstruct.modules.gui.dialog import AlignmentDialog
    window = main_window
    first = window.series
    snum = first.current_section
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def step(dialog):
        finder(c_fp)
        dialog.table.addAlignment("from_dialog")
        dialog.accept()

    ran = _when_modal(AlignmentDialog, step)
    window.modifyAlignments()

    assert ran
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    assert "from_dialog" in first.loadSection(snum).tforms


def test_a_finder_open_under_the_bc_profiles_dialog_changes_the_first(
    main_window, main_window_dialogs, finder, tmp_path  # noqa: F811
):
    from PyReconstruct.modules.gui.dialog import BCProfilesDialog
    window = main_window
    first = window.series
    snum = first.current_section
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def step(dialog):
        finder(c_fp)
        dialog.table.addProfile("from_dialog")
        dialog.accept()

    ran = _when_modal(BCProfilesDialog, step)
    window.changeBCProfiles()

    assert ran
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    assert "from_dialog" in first.loadSection(snum).bc_profiles


def test_a_finder_open_under_the_magnification_prompt_sets_the_first(
    main_window, main_window_dialogs, finder, real_input_dialogs, tmp_path  # noqa: F811
):
    from PySide6.QtWidgets import QInputDialog
    window = main_window
    first = window.series
    snum = first.current_section
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def step(dialog):
        finder(c_fp)
        dialog.setDoubleValue(0.123)
        dialog.accept()

    ran = _when_modal(QInputDialog, step)
    window.setSeriesMag()
    window.saveAllData()

    assert ran
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    assert first.loadSection(snum).mag == pytest.approx(0.123)


def test_a_finder_open_under_the_overlay_folder_dialog_sets_the_first(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path  # noqa: F811
):
    from PySide6.QtWidgets import QDialog, QFileDialog

    from PyReconstruct.modules.gui.main import main_window as mw
    window = main_window
    first = window.series
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    overlay = tmp_path / "overlay.zarr"
    overlay.mkdir()

    def choose_folder(file_mode, parent=None, caption="", *args, **kwargs):
        dialog = QFileDialog(parent, caption)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.DontUseNativeDialog)
        accepted = dialog.exec() == QDialog.Accepted
        return str(overlay) if accepted else ""

    def step(dialog):
        finder(c_fp)
        dialog.done(QDialog.Accepted)

    monkeypatch.setattr(mw.FileDialog, "get", staticmethod(choose_folder))
    ran = _when_modal(QFileDialog, step)
    window.setZarrLayer()

    assert ran
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    assert first.zarr_overlay_fp == str(overlay)


def test_a_finder_open_with_no_dialog_up_opens(
    main_window, main_window_dialogs, finder, tmp_path  # noqa: F811
):
    from PySide6.QtWidgets import QApplication
    window = main_window
    _, c_fp, _, _ = _two_more_series(window, tmp_path)
    assert QApplication.activeModalWidget() is None

    finder(c_fp)

    assert window.series.jser_fp == c_fp and not window.series.closed
    assert not any(c_fp in n for n in main_window_dialogs.notices)


def test_a_finder_open_under_nested_dialogs_waits_for_the_last_to_close(
    main_window, main_window_dialogs, finder, real_input_dialogs, tmp_path  # noqa: F811
):
    """The alignment dialog's own name prompt is a dialog inside a dialog."""
    from PySide6.QtWidgets import QInputDialog

    from PyReconstruct.modules.gui.dialog import AlignmentDialog
    window = main_window
    first = window.series
    snum = first.current_section
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    inner = []

    def name_it(prompt):
        finder(c_fp)
        prompt.setTextValue("from_nested")
        prompt.accept()

    def step(dialog):
        inner.append(_when_modal(QInputDialog, name_it))
        dialog.newAlignment()
        # the name prompt is closed, the alignment dialog is still up
        finder(c_fp)
        dialog.accept()

    ran = _when_modal(AlignmentDialog, step)
    window.modifyAlignments()

    assert ran and inner and inner[0]
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved, 2)
    assert "from_nested" in first.loadSection(snum).tforms

    # every dialog is closed: the next Finder open opens
    finder(c_fp)
    assert window.series.jser_fp == c_fp and not window.series.closed
    assert sum(c_fp in n for n in main_window_dialogs.notices) == 2


def test_a_finder_open_under_a_progress_window_is_refused(
    main_window, main_window_dialogs, finder, tmp_path  # noqa: F811
):
    from PyReconstruct.modules.gui.utils import getProgbar
    window = main_window
    first = window.series
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    progbar = getProgbar("Working", maximum=10)
    try:
        finder(c_fp)
    finally:
        progbar.close()

    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    finder(c_fp)
    assert window.series.jser_fp == c_fp


@pytest.mark.parametrize("where", ["window", "status bar"])
def test_a_finder_open_while_workers_run_is_refused(
    main_window, main_window_dialogs, finder, tmp_path, where  # noqa: F811
):
    from PySide6.QtCore import QTimer

    from PyReconstruct.modules.backend.threading import ThreadPoolProgBar
    window = main_window
    first = window.series
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    release = threading.Event()

    def arrive():
        # inside startAll's own event loop, while the worker still runs
        try:
            finder(c_fp)
        finally:
            release.set()

    pool = ThreadPoolProgBar()
    pool.createWorker(lambda: release.wait(10))
    QTimer.singleShot(0, arrive)
    status_bar = window.statusbar if where == "status bar" else None
    assert pool.startAll("Working", status_bar=status_bar)

    assert release.is_set()
    _refused(window, first, main_window_dialogs, c_fp, unsaved_fp, unsaved)
    assert not ThreadPoolProgBar.waiting()


def test_a_finder_open_after_a_legacy_series_import_opens(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path  # noqa: F811
):
    """The import's progress window is closed once it is done."""
    from PySide6.QtWidgets import QApplication
    from test_new_series_hidden_dir import _write_legacy_series
    window = main_window
    _, c_fp, _, _ = _two_more_series(window, tmp_path)
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    _write_legacy_series(str(xml_dir), "S", [1, 2])
    monkeypatch.setattr(window, "saveAsToJser", lambda *a, **k: "cancel")

    window.newFromXML(str(xml_dir / "S.ser"))
    assert QApplication.activeModalWidget() is None

    finder(c_fp)
    assert window.series.jser_fp == c_fp


def test_a_finder_open_after_a_failed_legacy_series_import_opens(
    main_window, main_window_dialogs, finder, tmp_path  # noqa: F811
):
    """A legacy import with a damaged .json reports it and closes its progress window."""
    from PySide6.QtWidgets import QApplication
    from test_new_series_hidden_dir import _write_legacy_series
    window = main_window
    first = window.series
    _, c_fp, _, _ = _two_more_series(window, tmp_path)
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    _write_legacy_series(str(xml_dir), "S", [1, 2])
    (xml_dir / "S.json").write_text("{bad json")

    window.newFromXML(str(xml_dir / "S.ser"))
    assert window.series is first
    assert len(main_window_dialogs.notices) == 1
    assert QApplication.activeModalWidget() is None

    finder(c_fp)
    assert window.series.jser_fp == c_fp


def test_a_legacy_section_that_fails_to_convert_closes_the_progress_window(
    main_window, main_window_dialogs, monkeypatch, tmp_path
):
    """An error while a section converts leaves no progress window behind."""
    from PySide6.QtWidgets import QApplication
    from PyReconstruct.modules.backend.func import xml_json_conversions
    from test_new_series_hidden_dir import _write_legacy_series
    window = main_window
    first = window.series
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    _write_legacy_series(str(xml_dir), "S", [1, 2])

    def fail(*args, **kwargs):
        raise OSError("section file unreadable")

    monkeypatch.setattr(xml_json_conversions, "sectionXMLtoJSON", fail)
    with pytest.raises(OSError):
        window.newFromXML(str(xml_dir / "S.ser"))
    assert window.series is first
    assert QApplication.activeModalWidget() is None
