"""The 3D autorefresh toggle is exposed in two places -- the 3D scene's
Scene-menu checkbox and the Series > Options dialog (View tab, 3D section) --
and both must read/write the SAME underlying ``3D_auto_refresh`` option so they
stay consistent.

The Scene-menu checkbox reads/writes ``series.getOption/setOption`` on
``3D_auto_refresh`` (see custom_plotter.py: initial ``setChecked`` and
``toggleAutoRefresh``). The Options dialog binds the same key in the
``smoothing_3D`` widget. These tests pin the shared-key contract:

1. The option defaults ON.
2. The Options-dialog checkbox is initialised from the stored value on open
   (built against a real series through the actual widgets).
3. The Options-dialog setter round-trips the value back to the same key.
4. Sync both directions: a value written the Scene-menu way is what the Options
   dialog reads, and a value written the Options-dialog way is what the
   Scene-menu path reads -- same key, no divergent cache.

The live 3D vedo/Qt window is exercised manually; the option plumbing is here.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)

OPTION = "3D_auto_refresh"


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


def _autorefresh_response(dlg):
    """Read the smoothing_3D widget's ACTUAL checkbox state via accept()."""
    w = dlg.all_widgets["smoothing_3D"]
    assert w.accept(close=False)          # populates w.responses from real widgets
    # the auto-refresh checkbox is the last interactive row (index 4);
    # a check response is a list of (label, checked) -> take the first's bool
    label, checked = w.responses[4][0]
    assert label == "Auto-refresh edited objects"
    return checked


def test_option_defaults_on(qapp, tmp_path):
    series = _series(tmp_path)
    assert series.getOption(OPTION) is True


def test_options_dialog_reads_stored_value_on_open(qapp, tmp_path):
    """Opening Series > Options must reflect whatever is currently stored --
    including a value the Scene-menu checkbox wrote."""
    series = _series(tmp_path)

    # default (nothing written yet) -> checkbox opens checked
    dlg = AllOptionsDialog(None, series)
    try:
        assert _autorefresh_response(dlg) is True
    finally:
        dlg.deleteLater()

    # Scene-menu turns it OFF (its toggleAutoRefresh does exactly this call)
    series.setOption(OPTION, False)

    dlg = AllOptionsDialog(None, series)
    try:
        assert _autorefresh_response(dlg) is False   # dialog reflects the change
    finally:
        dlg.deleteLater()


def test_options_dialog_setter_roundtrips_to_same_key(qapp, tmp_path):
    """Applying the Options dialog writes 3D_auto_refresh, which the Scene-menu
    path (getOption) then reads back -- proving one shared key, no divergence."""
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        w = dlg.all_widgets["smoothing_3D"]
        assert w.accept(close=False)             # capture real responses first
        responses = list(w.responses)
        # flip only the auto-refresh checkbox to OFF, leave siblings intact
        responses[4] = [("Auto-refresh edited objects", False)]
        w.responses = tuple(responses)
        w.set()                                   # runs the dialog's setOption closure
        assert series.getOption(OPTION) is False  # Scene-menu read sees the dialog write

        # and back ON
        responses[4] = [("Auto-refresh edited objects", True)]
        w.responses = tuple(responses)
        w.set()
        assert series.getOption(OPTION) is True
    finally:
        dlg.deleteLater()


def test_both_surfaces_resolve_to_same_stored_value(qapp, tmp_path):
    """End-to-end sync: Scene-menu write -> Options read, and Options write ->
    Scene-menu read, on the identical key."""
    series = _series(tmp_path)

    # Scene-menu writes OFF -> Options dialog opens showing OFF
    series.setOption(OPTION, False)
    dlg = AllOptionsDialog(None, series)
    try:
        assert _autorefresh_response(dlg) is False
        # Options dialog writes ON -> Scene-menu getOption reads ON
        w = dlg.all_widgets["smoothing_3D"]
        assert w.accept(close=False)
        responses = list(w.responses)
        responses[4] = [("Auto-refresh edited objects", True)]
        w.responses = tuple(responses)
        w.set()
    finally:
        dlg.deleteLater()

    assert series.getOption(OPTION) is True
