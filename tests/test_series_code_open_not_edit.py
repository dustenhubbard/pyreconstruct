"""Setting the series code at open is not an edit.

A series with no code gets one at open, from the series name, shown in the
Series Code dialog when someone is there to confirm it. The code goes into
the series file, nothing is marked modified, and a section change with no
edits saves no section. The .jser takes the code when the series closes,
without asking, so the next open does not ask for it again; a Save or a
Save As carries it too, and a write that fails keeps the series open with
the code still to be written. A code typed over it is an edit and marks the
series modified. With no code and nobody to ask, nothing changes.
"""
import json
import os

import pytest

from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes import hybrid_store, local_stores, store_save
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.gui.main import main_window as mw

pytestmark = pytest.mark.gui

# series_code_pattern [0-9A-Za-z]+ on the series' name, "series"
DERIVED = "series"


@pytest.fixture
def launch(qapp, series_jser, qsettings_snapshot, main_window_dialogs):
    """Open a MainWindow on a .jser; ``launch.close(window)`` closes it the
    way the window's own close does and reports whether it closed."""
    import sys as _sys

    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP, ORG, current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    windows = []
    previous_excepthook = _sys.excepthook

    def start(jser=series_jser):
        QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
        window = MainWindow(str(jser))
        window._captureListLayout = lambda: None
        windows.append(window)
        return window

    def close(window):
        closed = window.close()
        if closed:
            windows.remove(window)
            window.deleteLater()
        return closed

    start.close = close
    yield start

    _sys.excepthook = previous_excepthook
    for window in windows:
        window.series.modified = False
        window.series.unsaved_series_data = False
        window.close()
        window.deleteLater()


def _series_file(series):
    with open(series.filepath, "rb") as f:
        return json.loads(f.read())


def _jser_code(path):
    """The series code the .jser at path holds."""
    with open(path, "rb") as f:
        data = json.loads(f.read())
    series = data.get("series")
    if series is None:
        series = next(v for k, v in data.items() if k.endswith(".ser"))
    return series["code"]


def _confirm_prefill(monkeypatch):
    """Answer the Series Code dialog with the code it offers; returns the
    codes offered."""
    offered = []

    def confirm(parent, structure, title, *args, **kwargs):
        offered.append(structure[2][1][2])
        return [structure[2][1][2]], True

    monkeypatch.setattr(mw, "user_is_present", lambda: True)
    monkeypatch.setattr(mw.QuickDialog, "get", staticmethod(confirm))
    return offered


def _count_section_saves(monkeypatch):
    saved = []
    real = Section.save

    def record(section, *args, **kwargs):
        saved.append(section.n)
        return real(section, *args, **kwargs)

    monkeypatch.setattr(Section, "save", record)
    return saved


def _other_section(window):
    current = window.series.current_section
    return next(n for n in sorted(window.series.sections) if n != current)


def test_a_code_from_the_name_is_not_an_edit(main_window):
    series = main_window.series
    assert series.code == DERIVED
    assert series.modified is False
    assert not main_window.windowTitle().endswith("*")
    assert _series_file(series)["code"] == DERIVED
    assert series.unsaved_series_data is True


def test_a_section_change_with_no_edits_saves_no_section(main_window, monkeypatch):
    saved = _count_section_saves(monkeypatch)
    other = _other_section(main_window)
    main_window.changeSection(other)
    assert main_window.series.current_section == other
    assert saved == []
    assert main_window.series.modified is False


def test_no_code_and_nobody_asked_changes_nothing(launch, series_jser, main_window_dialogs):
    nameless = series_jser.with_name("___.jser")
    series_jser.rename(nameless)
    window = launch(nameless)
    assert window.series.code in ("", None)
    assert window.series.modified is False
    assert window.series.unsaved_series_data is False
    assert "Series Code" not in main_window_dialogs.dialogs


def test_confirming_the_code_from_the_name_is_not_an_edit(launch, monkeypatch):
    offered = _confirm_prefill(monkeypatch)
    window = launch()
    assert offered == [DERIVED]
    assert window.series.code == DERIVED
    assert window.series.modified is False
    assert _series_file(window.series)["code"] == DERIVED


def test_a_typed_code_is_an_edit(launch, monkeypatch, main_window_dialogs):
    monkeypatch.setattr(mw, "user_is_present", lambda: True)
    main_window_dialogs.responses = [(["XY7"], True)]
    window = launch()
    assert window.series.code == "XY7"
    assert window.series.modified is True
    assert window.windowTitle().endswith("*")


def test_the_confirmed_code_reaches_the_jser_on_close(
        launch, monkeypatch, series_jser, main_window_dialogs):
    offered = _confirm_prefill(monkeypatch)
    window = launch()
    saved = _count_section_saves(monkeypatch)
    window.changeSection(_other_section(window))
    assert saved == []

    assert launch.close(window) is True
    assert main_window_dialogs.save_prompts == 0
    assert _jser_code(series_jser) == DERIVED

    second = launch()
    assert offered == [DERIVED]
    assert second.series.code == DERIVED
    assert second.series.modified is False
    assert second.series.unsaved_series_data is False


def test_the_code_reaches_the_jser_on_close_with_nobody_asked(
        launch, series_jser, main_window_dialogs):
    window = launch()
    assert launch.close(window) is True
    assert main_window_dialogs.save_prompts == 0
    assert _jser_code(series_jser) == DERIVED


def test_save_as_carries_the_code(launch, tmp_path, main_window_dialogs):
    window = launch()
    target = tmp_path / "elsewhere" / "copy.jser"
    target.parent.mkdir()
    main_window_dialogs.file_responses.append(str(target))
    window.saveAsToJser()
    assert _jser_code(target) == DERIVED
    assert window.series.unsaved_series_data is False


def test_a_failed_write_at_close_keeps_the_series_open(
        launch, monkeypatch, series_jser):
    window = launch()
    shown = []
    window.series._surfaceSaveError = lambda fp, err, message=None: shown.append(err)
    write = series_module._atomicWrite

    def full(fp, data):
        if str(fp) == window.series.jser_fp:
            raise OSError(28, "No space left on device")
        return write(fp, data)

    monkeypatch.setattr(series_module, "_atomicWrite", full)
    assert launch.close(window) is False
    assert shown
    assert window.series.unsaved_series_data is True
    assert os.path.isdir(window.series.hidden_dir)

    monkeypatch.setattr(series_module, "_atomicWrite", write)
    assert launch.close(window) is True
    assert _jser_code(series_jser) == DERIVED


def _store_mode(monkeypatch, tmp_path):
    monkeypatch.setenv(local_stores.ENV_SWITCH, "1")
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(tmp_path / "stores"))
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)


def test_the_code_reaches_the_jser_on_close_through_the_store(
        launch, monkeypatch, tmp_path, series_jser, main_window_dialogs):
    _store_mode(monkeypatch, tmp_path)
    window = launch()
    assert window.series.code == DERIVED
    assert window.series.modified is False
    assert launch.close(window) is True
    assert main_window_dialogs.save_prompts == 0
    assert _jser_code(series_jser) == DERIVED


def test_a_store_save_refused_at_close_keeps_the_series_open(
        launch, monkeypatch, tmp_path, series_jser):
    """A section's working file is missing, so the store refuses the save."""
    _store_mode(monkeypatch, tmp_path)
    window = launch()
    series = window.series
    told = []
    series._surfaceSaveError = lambda fp, err, message=None: told.append(err)
    missing = _other_section(window)
    path = os.path.join(series.hidden_dir, series.sections[missing])
    with open(path, "rb") as f:
        content = f.read()
    os.remove(path)

    assert launch.close(window) is False
    assert window.isVisible()
    assert told
    assert series.unsaved_series_data is True
    assert os.path.isdir(series.hidden_dir)
    assert getattr(series, "closed", False) is False

    with open(path, "wb") as f:
        f.write(content)
    assert launch.close(window) is True
    assert _jser_code(series_jser) == DERIVED
