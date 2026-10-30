"""A second open frees the open series before the new one loads.

The window held the closed series (field, palette, menus) until the new one
took its place, so a second open of a large series needed memory for both:
893 MB in use on DW14, twice one series. The window now opens the welcome
series in its place before the load starts, and an open that fails or is
canceled from there leaves the welcome series, the app's no-series state.
"""

import gc
import shutil
import sys
import weakref

import pytest

from PyReconstruct.modules.datatypes.series import Series, SeriesOpenError

pytestmark = pytest.mark.gui


def _action_states(window):
    """Every menubar action's enabled state, keyed by its menu path."""
    states = {}

    def walk(actions, path):
        for act in actions:
            if act.isSeparator():
                continue
            key = path + (act.text(),)
            states[key] = act.isEnabled()
            if act.menu():
                walk(act.menu().actions(), key)

    walk(window.menuBar().actions(), ())
    return states


def _fresh_welcome_states():
    from PySide6.QtWidgets import QApplication

    from PyReconstruct.modules.gui.main import MainWindow

    previous_excepthook = sys.excepthook
    fresh = MainWindow(None)
    try:
        assert fresh.series.isWelcomeSeries()
        return _action_states(fresh)
    finally:
        sys.excepthook = previous_excepthook
        fresh.close()
        fresh.deleteLater()
        QApplication.processEvents()


def _other_copy(window, tmp_path):
    other = tmp_path / "other" / "series.jser"
    other.parent.mkdir()
    shutil.copy(window.series.jser_fp, other)
    return str(other)


def test_open_series_is_freed_before_the_new_one_loads(
    main_window, tmp_path, monkeypatch
):
    window = main_window
    other = _other_copy(window, tmp_path)
    first = weakref.ref(window.series)
    real_open = Series.openJser
    held_at_load = []

    def openJser(fp, *args, **kwargs):
        gc.collect()
        held_at_load.append(first() is not None)
        return real_open(fp, *args, **kwargs)

    monkeypatch.setattr(Series, "openJser", staticmethod(openJser))

    window.seriesModified(False)
    window.openSeries(jser_fp=other)

    assert held_at_load == [False], "the open series was still held at the load"
    assert window.series.jser_fp == other


@pytest.mark.parametrize("outcome", ["fails", "canceled"])
def test_a_second_open_that_does_not_load_leaves_no_series(
    main_window, main_window_dialogs, tmp_path, monkeypatch, outcome
):
    window = main_window
    other = _other_copy(window, tmp_path)
    first = weakref.ref(window.series)
    real_open = Series.openJser

    def openJser(fp, *args, **kwargs):
        if fp != other:  # the series that was open stays readable
            return real_open(fp, *args, **kwargs)
        if outcome == "fails":
            raise SeriesOpenError("unreadable")
        return None  # the progress window's Cancel

    monkeypatch.setattr(Series, "openJser", staticmethod(openJser))

    window.seriesModified(False)
    window.openSeries(jser_fp=other)
    gc.collect()

    assert window.series.isWelcomeSeries()
    assert window.field.series is window.series
    assert first() is None
    expected = ["unreadable"] if outcome == "fails" else []
    assert main_window_dialogs.notices == expected
    # the menus read as on a fresh welcome window: Backup and Save are off
    assert not window.backupmenu.menuAction().isEnabled()
    assert _action_states(window) == _fresh_welcome_states()
