"""Reset Defaults in ``Series > Options`` must move the sliders too.

``AllOptionsDialog.resetDefaults`` clears the tabs and calls
``createWidgets(use_defaults=True)``. An option that threads the flag through to
``series.getOption(name, use_defaults)`` comes back at the shipped default
instead of the stored value. Nine display-path reads did not thread it. Three
are fixed here: the 3D XY resolution slider (``3D_xy_res``), the scale bar size
slider (``scale_bar_width``) and the CPU usage slider (``cpu_max``). They read
the stored value unconditionally, so pressing Reset Defaults rebuilt the dialog
with those three sliders sitting exactly where the user had left them.

The other six are ``trace_mode``, ``sampling_frame_grid``,
``smoothing_iterations``, ``screenshot_res``, ``theme`` and
``series_code_pattern``. They still do not reset after this change and are the
subject of a separate branch (``fix/options-reset-non-sliders``). The tenth
bare read, ``theme`` inside the ``setOption`` closure, is correctly a
current-value read and is not a defect.

These tests drive the real dialog against a real series and read the slider
values back through the widgets themselves, so the assertion is on what the
user sees rather than on the argument list.

Also here because it is the same surface: ``determine_cpus`` multiplies by
``os.cpu_count()``, which Python documents as possibly returning ``None``.
Building the dialog does not call it. ``all_options.py`` does not import the
name, and the only caller is the image-to-zarr conversion in ``MainWindow``,
which is where a ``None`` raises today. The guard is kept anyway because the
slider readout branch (``feat/slider-readout``) imports ``determine_cpus`` into
``all_options.py`` and calls it from ``cpuSliderReadout``, which does run while
the dialog is built. So it is a prerequisite for that branch rather than a fix
for a crash reachable on open here.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev",
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


def _slider_value(dlg, widget_name, index):
    """Read a slider's actual position out of the built widget."""
    w = dlg.all_widgets[widget_name]
    assert w.accept(close=False)      # populates responses from the real widgets
    return w.responses[index]


def _identity(value):
    return value


# (option key, widget name, response index, a value that is not the default,
#  stored value -> slider position)
#
# `scale_bar_width` used to need a mapping of its own here, because the dialog
# squeezed the stored 20-100 range onto an 0-100 groove and squeezed it back on
# the way out. This branch deletes that squeeze -- it did not round trip, and 60
# of the 81 values came back one lower -- so the slider carries the 20-100 range
# itself and the number on screen is the number stored. Identity, like the other
# two. Left unchanged, this table fails with `assert 60 == 50` and `assert 25 == 6`.
SLIDERS = [
    ("3D_xy_res", "smoothing_3D", 0, 73, _identity),
    ("cpu_max", "computation", 0, 90, _identity),
    ("scale_bar_width", "scale_bar", 1, 60, _identity),
]


@pytest.mark.parametrize("option,widget,index,changed,position", SLIDERS)
def test_slider_opens_on_the_stored_value(qapp, tmp_path, option, widget, index, changed, position):
    """Precondition for the reset test: the slider tracks the stored value."""
    series = _series(tmp_path)
    series.setOption(option, changed)

    dlg = AllOptionsDialog(None, series)
    try:
        shown = _slider_value(dlg, widget, index)
    finally:
        dlg.deleteLater()

    assert shown == position(changed)


@pytest.mark.parametrize("option,widget,index,changed,position", SLIDERS)
def test_reset_defaults_moves_the_slider(qapp, tmp_path, option, widget, index, changed, position):
    """Move a slider, press Reset Defaults, and the slider must show the default."""
    series = _series(tmp_path)
    default = default_settings[option]
    assert position(changed) != position(default), "the test value must differ from the default"
    series.setOption(option, changed)

    dlg = AllOptionsDialog(None, series)
    try:
        dlg.resetDefaults()
        shown = _slider_value(dlg, widget, index)
    finally:
        dlg.deleteLater()

    assert shown == position(default)

    # Reset Defaults only repopulates the dialog; nothing is stored until OK
    assert series.getOption(option) == changed


def test_determine_cpus_survives_cpu_count_none(monkeypatch):
    """os.cpu_count() may return None; determine_cpus must still return >= 1."""
    from PyReconstruct.modules.backend.func import utils

    monkeypatch.setattr(utils.os, "cpu_count", lambda: None)
    assert utils.determine_cpus(50) == 1
    assert utils.determine_cpus(100) == 1


def test_options_dialog_opens_when_cpu_count_is_none(qapp, tmp_path, monkeypatch):
    """A None cpu count must not stop Series > Options from opening.

    This passes without the guard too, because the dialog never calls
    ``determine_cpus`` (see the module docstring). It is a regression guard for
    the slider readout branch, which does call it during the build.
    """
    from PyReconstruct.modules.backend.func import utils

    monkeypatch.setattr(utils.os, "cpu_count", lambda: None)
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        assert "computation" in dlg.all_widgets
    finally:
        dlg.deleteLater()
