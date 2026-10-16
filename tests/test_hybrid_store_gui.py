"""The hybrid store prototype through the real MainWindow: Save writes the
store and leaves the .jser alone; closing the window writes the .jser."""
import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import hybrid_store
from PyReconstruct.modules.datatypes.series import Series

from tests.test_hybrid_store import store_on  # noqa: F401  (fixture)

pytestmark = pytest.mark.gui


def _window(path):
    """A MainWindow on path, built as the main_window fixture builds it."""
    from PySide6.QtCore import QSettings
    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    window = MainWindow(str(path))
    window._captureListLayout = lambda: None
    return window


def _move_a_trace(window):
    for snum in sorted(window.series.sections):
        window.changeSection(snum)
        section = window.field.section
        traces = section.tracesAsList()
        if traces:
            section.selected_traces = [traces[0]]
            section.translateTraces(4.0, 2.0)
            window.series.modified = True
            return snum, section.getDict()
    raise AssertionError("no traces")


@pytest.mark.parametrize("save_mode", ["store", "jser"])
def test_save_and_close_write_what_the_save_mode_says(
    save_mode, qapp, store_on, series_jser, qsettings_snapshot, main_window_dialogs, monkeypatch,  # noqa: F811
):
    monkeypatch.setenv(hybrid_store.ENV_SAVE, save_mode)
    before = series_jser.read_bytes()
    window = _window(series_jser)
    try:
        series = window.series
        assert series.store is not None
        snum, edited = _move_a_trace(window)

        window.saveToJser()

        assert not series.store.hasPending()
        assert not series.modified
        if save_mode == "store":
            assert series_jser.read_bytes() == before
            assert series.store.meta("dirty") == "1"
        else:
            assert series_jser.read_bytes() != before
            assert not series.store.hasUnexportedWork()
    finally:
        window.close()

    assert main_window_dialogs.save_prompts == 0
    assert series_jser.read_bytes() != before
    monkeypatch.delenv(hybrid_store.ENV_SWITCH)
    plain = Series.openJser(str(series_jser), progress=NullProgressReporter)
    try:
        assert plain.store is None
        assert plain.loadSection(snum).getDict() == edited
    finally:
        plain.close()


def test_switch_off_save_still_writes_the_jser(
    qapp, series_jser, qsettings_snapshot, main_window_dialogs, monkeypatch, tmp_path,
):
    monkeypatch.delenv(hybrid_store.ENV_SWITCH, raising=False)
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(tmp_path / "stores"))
    before = series_jser.read_bytes()
    window = _window(series_jser)
    try:
        assert window.series.store is None
        _move_a_trace(window)
        window.saveToJser()
        assert series_jser.read_bytes() != before
        window.series.modified = False
    finally:
        window.close()
    assert not (tmp_path / "stores").exists()
