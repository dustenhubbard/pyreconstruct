"""The conftest guard on `Series.setOption` writes from tests.

A write that would land in the worker's shared settings store fails, from a test
body and from a module-scoped fixture alike. A write that lands in a store of
the test's own, or that writes nothing, passes.
"""

import pytest

from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    QSettingsStore,
)
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes import series as series_module

Failed = pytest.fail.Exception


def bare(store=None):
    """A series with no file behind it, on ``store`` (None: the shared one)."""
    series = Series.__new__(Series)
    series.options = {}
    series.code = "option-guard"
    series.filepath = "/nonexistent/option-guard.ser"
    series.setSettingsStore(store)
    return series


def test_a_shared_write_from_a_test_fails_before_it_is_written():
    with pytest.raises(Failed, match="trace_mode"):
        bare().setOption("trace_mode", "poly")
    assert bare().getOption("trace_mode", write_default=False) != "poly"


@pytest.fixture(scope="module")
def module_write():
    """A module-scoped fixture's shared write, and what it raised."""
    try:
        bare().setOption("trace_mode", "scribble")
    except Failed as raised:
        return raised
    return None


def test_a_shared_write_from_a_module_fixture_fails(module_write):
    assert isinstance(module_write, Failed)
    assert "trace_mode" in str(module_write)
    assert bare().getOption("trace_mode", write_default=False) != "scribble"


def test_a_write_through_local_series_settings_passes(local_series_settings):
    series = local_series_settings(bare())
    series.setOption("trace_mode", "poly")
    assert series.getOption("trace_mode") == "poly"


def test_a_write_to_an_injected_dict_store_passes():
    series = bare(DictSettingsStore())
    series.setOption("trace_mode", "poly")
    assert series.getOption("trace_mode") == "poly"


def test_a_qsettings_store_on_a_private_file_passes(tmp_path):
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "private.ini"), QSettings.IniFormat)
    store = QSettingsStore()
    store._settings = lambda code: settings
    series = bare(store)
    series.setOption("trace_mode", "poly")
    assert series.getOption("trace_mode") == "poly"


def test_a_welcome_series_per_series_option_writes_nothing_and_passes(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(series_module, "welcome_series_dir", str(tmp_path))
    (tmp_path / "welcome.ser").touch()
    series = bare()
    series.filepath = str(tmp_path / "welcome.ser")
    assert series.isWelcomeSeries()
    series.setOption("backup_dir", "/not-written")


def test_an_option_kept_in_the_series_file_passes():
    series = bare()
    series.options["small_dist"] = 0.1
    series.setOption("small_dist", 0.0123)
    assert series.options["small_dist"] == 0.0123


@pytest.mark.shared_settings_store
def test_the_marker_lets_a_test_about_the_shared_store_write_it():
    series = bare()
    before = series.getOption("trace_mode")
    series.setOption("trace_mode", before)
    assert series.getOption("trace_mode") == before
