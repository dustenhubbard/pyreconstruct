"""Save, close and Export through the local store, in the real MainWindow.

When the .jser is written and when a backup is made, in each Save mode, and
the menu row that writes the .jser now. With the switch off, the window saves
and closes as today, and the row is not there.
"""
import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import store_open, store_save
from PyReconstruct.modules.datatypes.series import Series

from test_hybrid_store import store_root  # noqa: F401  (fixture)

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


def _backups(window):
    calls = []
    window.backup = lambda *a, **k: calls.append(k)
    return calls


@pytest.fixture
def kept(qapp, series_jser, store_root, qsettings_snapshot, main_window_dialogs, monkeypatch):  # noqa: F811
    """series_jser with the switch on and its store made (the first open imports it)."""
    monkeypatch.setenv(store_open.ENV_SWITCH, "1")
    _window(series_jser).close()
    # that first close asks to save the fixture, with the switch off as well
    main_window_dialogs.save_prompts = 0
    return series_jser


def _store_mode(monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)


def _opened_as_today(fp, snum, edited, monkeypatch):
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH)
        plain = Series.openJser(str(fp), progress=NullProgressReporter)
        try:
            assert plain.loadSection(snum).getDict() == edited
        finally:
            plain.close()


def test_jser_mode_saves_and_backs_up_as_today(kept, main_window_dialogs, monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_JSER)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        assert store_save.heldStore(window.series) is not None
        snum, edited = _move_a_trace(window)
        window.saveToJser()
        assert kept.read_bytes() != before
        assert backups == [{"check_auto": True, "from_saved": True}]
        assert not store_save.ahead(window.series)
        saved = kept.read_bytes()
    finally:
        window.close()
    assert backups == [{"check_auto": True, "from_saved": True}]
    assert kept.read_bytes() == saved
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_a_store_only_save_makes_no_backup_and_close_writes_the_jser_and_one(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        window.saveToJser()
        assert kept.read_bytes() == before
        assert backups == []
        assert not window.series.modified
        assert store_save.ahead(window.series)
    finally:
        window.close()
    assert main_window_dialogs.save_prompts == 0
    assert backups == [{"check_auto": True, "from_saved": True}]
    assert kept.read_bytes() != before
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_export_now_writes_the_jser_and_a_backup_and_close_then_writes_nothing(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        window.exportjsernow_act.trigger()
        assert len(backups) == 1
        assert not window.series.modified
        assert not store_save.ahead(window.series)
        exported = (kept.read_bytes(), kept.stat().st_mtime_ns)
    finally:
        window.close()
    assert len(backups) == 1
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == exported
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_close_with_nothing_saved_writes_no_jser_and_no_backup(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    first = (kept.read_bytes(), kept.stat().st_mtime_ns)
    window = _window(kept)
    backups = _backups(window)
    window.changeSection(sorted(window.series.sections)[1])
    window.close()
    assert backups == []
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == first


def test_no_at_the_close_prompt_writes_the_last_save_and_a_backup(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        window.saveToJser()
        _move_a_trace(window)  # not saved
        main_window_dialogs.save_response = "no"
    finally:
        window.close()
    assert main_window_dialogs.save_prompts == 1
    assert backups == [{"check_auto": True, "from_saved": True}]
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_the_export_row_is_there_only_when_save_writes_the_store_alone(kept, main_window_dialogs, monkeypatch):
    for mode, expected in ((store_save.MODE_JSER, False), (store_save.MODE_STORE, True)):
        monkeypatch.setenv(store_save.ENV_MODE, mode)
        window = _window(kept)
        try:
            assert hasattr(window, "exportjsernow_act") is expected, mode
        finally:
            window.close()


def test_with_the_switch_off_the_window_saves_and_closes_as_today(
    qapp, series_jser, store_root, qsettings_snapshot, main_window_dialogs, monkeypatch,  # noqa: F811
):
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)
    before = series_jser.read_bytes()
    window = _window(series_jser)
    backups = _backups(window)
    try:
        assert store_save.heldStore(window.series) is None
        assert not hasattr(window, "exportjsernow_act")
        _move_a_trace(window)
        window.saveToJser()
        assert series_jser.read_bytes() != before
        assert backups == [{"check_auto": True, "from_saved": True}]
    finally:
        window.close()
    assert len(backups) == 1
    assert not store_root.exists()
