"""UI v1 Slice 3 — lists-left tabbed/collapsible panel (headless backbone).

These tests cover BEHAVIOR only (offscreen); the look is signed off interactively.
QSettings is isolated to a temp dir by the session-autouse fixture in conftest.py, so
the getOption/setOption round-trips never touch real user preferences.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from PyReconstruct.modules.datatypes.series import Series  # noqa: E402


def _global_series():
    """A minimal Series instance for exercising GLOBAL (computer-wide) options.

    The global getOption/setOption path only reads ``self.options`` and the class-level
    ``qsettings_defaults``; it never needs the heavy jser construction, so __new__ + an
    empty options dict is sufficient and isolated.
    """
    s = Series.__new__(Series)
    s.options = {}
    return s


def _clear(*keys):
    settings = QSettings("KHLab", "PyReconstruct")
    for k in keys:
        settings.remove(k)
    settings.sync()


# --- B1: register the two global QSettings defaults -------------------------------

def test_b1_keys_registered_global_with_defaults():
    assert Series.qsettings_defaults.get("lists_panel_collapsed") is False
    assert Series.qsettings_defaults.get("open_tables") == ["object"]


def test_b1_keys_are_global_not_per_series_or_internal():
    # not per-series
    assert "lists_panel_collapsed" not in Series.qsettings_series_defaults
    assert "open_tables" not in Series.qsettings_series_defaults
    # not an internal per-series option (so the series.py:440-444 prune never touches them)
    empty_opts = Series.getEmptyDict()["options"]
    assert "lists_panel_collapsed" not in empty_opts
    assert "open_tables" not in empty_opts


def test_b1_getOption_returns_defaults_when_unset():
    _clear("lists_panel_collapsed", "open_tables")
    s = _global_series()
    assert s.getOption("lists_panel_collapsed") is False
    assert s.getOption("open_tables") == ["object"]


def test_b1_setOption_getOption_roundtrip():
    s = _global_series()
    s.setOption("lists_panel_collapsed", True)
    assert s.getOption("lists_panel_collapsed") is True
    s.setOption("open_tables", ["object", "trace"])
    assert s.getOption("open_tables") == ["object", "trace"]


def test_b1_resolves_via_global_qsettings_not_internal_options():
    # The keys must route through the global QSettings("KHLab","PyReconstruct"),
    # not self.options. A fresh instance with empty options still resolves them.
    s = _global_series()
    assert "open_tables" not in s.options
    s.setOption("open_tables", ["object", "ztrace"])
    # value lives in global QSettings, readable by an independent instance
    other = _global_series()
    assert other.getOption("open_tables") == ["object", "ztrace"]
