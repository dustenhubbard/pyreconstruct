"""Reset Defaults in ``Series > Options`` must reset the non-slider options too.

``AllOptionsDialog.resetDefaults`` clears the tabs and calls
``createWidgets(use_defaults=True)``. Every ``series.getOption`` call in that
method must thread the flag through so it returns the shipped default instead
of the stored value. Six non-slider options did not:

- ``trace_mode`` (Mouse Tools tab, trace mode radio)
- ``sampling_frame_grid`` (Mouse Tools tab, grid checkbox)
- ``smoothing_iterations`` (View tab, 3D section)
- ``screenshot_res`` (View tab, 3D section)
- ``theme`` (View tab, theme radio)
- ``series_code_pattern`` (User/Series tab, series code text)

Each test sets the option to a value that differs from the default, calls
``resetDefaults()``, and checks that the widget shows the default -- not the
stored value. Nothing is written to disk: the series uses ``DictSettingsStore``
and the assertion is on the widget state, not on ``getOption``.

A revert-and-fail note: removing one ``use_defaults`` from the fixed call and
re-running confirms the test fails, because the widget reads the stored
non-default value instead.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _series(tmp_path):
    """A real series backed by an in-memory settings store (no QSettings I/O)."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


# ---------------------------------------------------------------------------
# helpers to read widget state after resetDefaults()
# ---------------------------------------------------------------------------

def _trace_mode_response(dlg):
    """Return the selected trace mode string from the trace widget."""
    w = dlg.all_widgets["trace"]
    assert w.accept(close=False)
    # response[0] is the radio row: [("Scribble", bool), ("Poly", bool), ("Combo", bool)]
    radios = w.responses[0]
    for label, checked in radios:
        if checked:
            return label.lower()
    return None


def _sampling_frame_grid_response(dlg):
    """Return the sampling-frame-grid checkbox state from the grid widget."""
    w = dlg.all_widgets["grid"]
    assert w.accept(close=False)
    # grid widget: 6 float/int cells (indices 0-5) then the checkbox row (index 6)
    label, checked = w.responses[6][0]
    assert label == "Sampling frame"
    return checked


def _smoothing_iterations_response(dlg):
    """Return the smoothing_iterations int from the smoothing_3D widget."""
    w = dlg.all_widgets["smoothing_3D"]
    assert w.accept(close=False)
    # structure: [0]=slider, [1]=radio, [2]=smoothing_iterations, [3]=screenshot_res, [4]=checkbox
    return w.responses[2]


def _screenshot_res_response(dlg):
    """Return the screenshot_res int from the smoothing_3D widget."""
    w = dlg.all_widgets["smoothing_3D"]
    assert w.accept(close=False)
    return w.responses[3]


def _theme_response(dlg):
    """Return the selected theme label from the theme widget."""
    w = dlg.all_widgets["theme"]
    assert w.accept(close=False)
    # response[0] is the radio row: [("default", bool), ("dark", bool)]
    radios = w.responses[0]
    for label, checked in radios:
        if checked:
            return label
    return None


def _series_code_pattern_response(dlg):
    """Return the series_code_pattern text from the series_code widget."""
    w = dlg.all_widgets["series_code"]
    assert w.accept(close=False)
    # structure: [0]=series code text, [1]=series_code_pattern text
    return w.responses[1]


# ---------------------------------------------------------------------------
# parametrized data: (option key, non-default value, helper fn, expected label)
# The expected label is the value the helper returns when the default is shown.
# ---------------------------------------------------------------------------

NON_SLIDERS = [
    (
        "trace_mode",
        "scribble",               # non-default (default is "combo")
        _trace_mode_response,
        "combo",                  # default label returned by _trace_mode_response
    ),
    (
        "sampling_frame_grid",
        False,                    # non-default (default is True)
        _sampling_frame_grid_response,
        True,
    ),
    (
        "smoothing_iterations",
        99,                       # non-default (default is 10)
        _smoothing_iterations_response,
        default_settings["smoothing_iterations"],
    ),
    (
        "screenshot_res",
        72,                       # non-default (default is 300)
        _screenshot_res_response,
        default_settings["screenshot_res"],
    ),
    (
        "theme",
        "qdark",                  # non-default (default is "default")
        _theme_response,
        "default",
    ),
    (
        "series_code_pattern",
        "CUSTOM_[0-9]+",          # non-default
        _series_code_pattern_response,
        default_settings["series_code_pattern"],
    ),
]


@pytest.mark.parametrize("option,changed,read_fn,expected", NON_SLIDERS)
def test_widget_opens_on_stored_value(qapp, tmp_path, option, changed, read_fn, expected):
    """Precondition: the widget reflects the stored value when the dialog opens normally."""
    series = _series(tmp_path)
    series.setOption(option, changed)
    dlg = AllOptionsDialog(None, series)
    try:
        shown = read_fn(dlg)
    finally:
        dlg.deleteLater()
    assert shown != expected, (
        f"{option!r}: stored value {changed!r} should produce a different "
        f"widget state than the default ({expected!r})"
    )


@pytest.mark.parametrize("option,changed,read_fn,expected", NON_SLIDERS)
def test_reset_defaults_shows_default(qapp, tmp_path, option, changed, read_fn, expected):
    """After resetDefaults(), each widget must show the shipped default, not the stored value."""
    series = _series(tmp_path)
    series.setOption(option, changed)

    dlg = AllOptionsDialog(None, series)
    try:
        dlg.resetDefaults()
        shown = read_fn(dlg)
    finally:
        dlg.deleteLater()

    assert shown == expected, (
        f"{option!r}: after Reset Defaults the widget showed {shown!r}; "
        f"expected the default {expected!r} (stored value was {changed!r})"
    )

    # resetDefaults() only refreshes the dialog; the stored value must not change
    assert series.getOption(option) == changed, (
        f"{option!r}: Reset Defaults must not write to storage "
        f"(stored value changed from {changed!r} to {series.getOption(option)!r})"
    )
