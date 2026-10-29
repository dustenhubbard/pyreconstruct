"""After a series opens in the window, the cyclic garbage collector is settled
for it (collector.py: one collection, gc.freeze(), a young threshold of 10000),
and the settings it found come back when that series closes, whether the
window closes or another series opens. Another Series object closing (an
import from a second .jser) leaves the window's series settled. Settled or
not, the field draws the same pixels and the section holds the same data.
"""
import gc
import shutil
import sys

import pytest

from PyReconstruct.modules.datatypes import Series, collector
from PyReconstruct.modules.constants.fast_json import fast_dumps
from PyReconstruct.modules.gui.main import main_window as MW


@pytest.fixture
def unsettled():
    """No series settled when the test starts; the thresholds it starts with."""
    collector.restore(collector.settledSeries())
    return gc.get_threshold()


def _copy(src, tmp_path, name):
    (tmp_path / name).mkdir()
    return str(shutil.copy(src, tmp_path / name / "series.jser"))


def _window(jser):
    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    previous_excepthook = sys.excepthook
    window = MW.MainWindow(jser)
    window._captureListLayout = lambda: None
    sys.excepthook = previous_excepthook
    return window


def _close(window):
    window.series.modified = False
    window.series.unsaved_series_data = False
    window.close()
    window.deleteLater()


def _assert_settled(series, before):
    assert collector.settledSeries() is series
    assert gc.get_threshold() == (collector.YOUNG_THRESHOLD, before[1], before[2])
    assert gc.get_freeze_count() > 0


def _assert_restored(before):
    assert collector.settledSeries() is None
    assert gc.get_threshold() == before
    assert gc.get_freeze_count() == 0


@pytest.mark.gui
def test_an_open_settles_and_closing_the_window_restores(
    qapp, unsettled, main_window_dialogs, series_jser
):
    window = _window(str(series_jser))
    try:
        _assert_settled(window.series, unsettled)
    finally:
        _close(window)
    _assert_restored(unsettled)


@pytest.mark.gui
def test_a_second_open_settles_for_it_and_keeps_the_first_settings(
    qapp, unsettled, main_window_dialogs, series_jser, tmp_path
):
    window = _window(str(series_jser))
    try:
        first = window.series
        window.openSeries(jser_fp=_copy(series_jser, tmp_path, "second"), query_prev=False)
        assert window.series is not first and first.closed
        _assert_settled(window.series, unsettled)
    finally:
        _close(window)
    _assert_restored(unsettled)


@pytest.mark.gui
def test_another_series_closing_leaves_the_window_series_settled(
    qapp, unsettled, main_window_dialogs, series_jser, tmp_path
):
    window = _window(str(series_jser))
    try:
        other = Series.openJser(_copy(series_jser, tmp_path, "other"))
        other.close()
        _assert_settled(window.series, unsettled)
    finally:
        _close(window)
    _assert_restored(unsettled)


@pytest.mark.gui
def test_the_same_pixels_and_data_settled_or_not(qapp, unsettled, main_window_dialogs, series_jser):
    window = _window(str(series_jser))
    try:
        series = window.series
        _assert_settled(series, unsettled)
        snums = sorted(series.sections)

        def page():
            frames, data = [], []
            for n in snums:
                window.changeSection(n)
                window.field.generateView()
                frames.append(window.field.grab().toImage())
                data.append(fast_dumps(window.field.section.getDict()))
            return frames, data

        settled = page()
        collector.restore(series)
        _assert_restored(unsettled)
        assert page() == settled
    finally:
        _close(window)
