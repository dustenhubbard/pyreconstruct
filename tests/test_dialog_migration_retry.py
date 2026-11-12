"""Settings dialogs keep untouched old preferences while their copy waits.

Each dialog here shows several options. The user changes one and presses OK
while the copy of the old KHLab store fails. Once the copy succeeds, the
option the user left alone must hold its old value, not the default the
dialog showed in its place. The completed-copy case is the control.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QWidget

from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickDialog
from test_settings_migration_retry import domain, fail_legacy  # noqa: F401  (fixture)

pytestmark = pytest.mark.gui


@pytest.fixture
def legacy(domain, monkeypatch):  # noqa: F811  (fixture)
    """Seed old values with `seed(pending, **values)`; `finish()` copies them."""
    app, make = domain
    old = make("KHLab")
    state = {}

    def seed(pending, **values):
        for key, value in values.items():
            # stored as Series.setOption stores it
            old.setValue(key, json.dumps(value) if isinstance(value, list) else value)
        old.sync()
        state["bytes"] = Path(old.fileName()).read_bytes()
        state["fail"] = fail_legacy(monkeypatch, app)
        state["fail"]["fail"] = pending

    def finish(series, *keys):
        state["fail"]["fail"] = False
        values = {key: series.getOption(key) for key in keys}
        assert Path(old.fileName()).read_bytes() == state["bytes"]
        return values

    return SimpleNamespace(seed=seed, finish=finish)


@pytest.fixture
def series(qapp, series_jser):
    opened = Series.openJser(str(series_jser))
    opened.setSettingsStore(QSettingsStore())
    yield opened
    opened.close()


def accept_quick_dialog(monkeypatch, edit):
    """Make the next QuickDialog apply `edit` and press OK."""
    def run(dialog):
        edit(dialog)
        assert dialog.accept(close=False)
        return dialog.responses, True

    def get(parent, structure, title="Dialog", grid=False, cancelable=True, spacing=1):
        # built here, since the main_window fixture replaces QuickDialog.get
        return run(QuickDialog(parent, structure, title, grid,
                               cancelable=cancelable, spacing=spacing))

    monkeypatch.setattr(QuickDialog, "exec", run)
    monkeypatch.setattr(QuickDialog, "get", staticmethod(get))


def accept_dialog(monkeypatch, edit):
    """Make the next plain QDialog apply `edit` and press OK."""
    def run(dialog):
        edit(dialog)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", run)


def buttons(field):
    layout = field.widget.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


class StubWindow(QWidget):
    """The parts of MainWindow its option dialogs use."""

    def __init__(self, series):
        super().__init__()
        self.series = series
        self.field = SimpleNamespace(closed_trace_shape="trace")

    def seriesModified(self, modified=True):
        pass


@pytest.mark.parametrize("pending", [False, True])
def test_scale_bar_dialog_keeps_untouched_text_option(series, legacy, pending):
    from PyReconstruct.modules.gui.dialog.scale_bar_settings import (
        ScaleBarSettingsDialog,
    )

    legacy.seed(pending, show_scale_bar_text=False)
    dialog = ScaleBarSettingsDialog(None, series)
    try:
        dialog.inputs[2].widget.setValue(61)
        assert dialog.accept()
    finally:
        dialog.close()
    values = legacy.finish(series, "show_scale_bar_text", "scale_bar_width")
    print(f"scale bar pending={pending} {values}")
    assert values == {"show_scale_bar_text": False, "scale_bar_width": 61}


@pytest.mark.parametrize("pending", [False, True])
def test_pointer_dialog_keeps_untouched_closest_option(series, legacy, monkeypatch, pending):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    legacy.seed(pending, display_closest=False)
    accept_quick_dialog(monkeypatch, lambda d: buttons(d.inputs[0])[0].setChecked(True))
    MainWindow.modifyPointer(StubWindow(series))
    values = legacy.finish(series, "pointer", "display_closest")
    print(f"pointer pending={pending} {values}")
    assert values == {"pointer": ["rect", "exc"], "display_closest": False}


@pytest.mark.parametrize("pending", [False, True])
def test_grid_dialog_keeps_untouched_grid(series, legacy, monkeypatch, pending):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    legacy.seed(pending, grid=[2, 2, 2, 2, 3, 3])
    accept_dialog(monkeypatch, lambda d: d.sf_cb.setChecked(False))
    MainWindow.modifyGrid(StubWindow(series))
    values = legacy.finish(series, "grid", "sampling_frame_grid")
    print(f"grid pending={pending} {values}")
    assert values == {"grid": [2, 2, 2, 2, 3, 3], "sampling_frame_grid": False}


@pytest.mark.parametrize("pending", [False, True])
def test_knife_dialog_keeps_untouched_window(series, legacy, monkeypatch, pending):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    legacy.seed(pending, roll_knife_window=25)
    accept_quick_dialog(monkeypatch, lambda d: d.inputs[0].widget.setText("5"))
    MainWindow.modifyKnife(StubWindow(series))
    values = legacy.finish(series, "knife_del_threshold", "roll_knife_window")
    print(f"knife pending={pending} {values}")
    assert values == {"knife_del_threshold": 5.0, "roll_knife_window": 25}


@pytest.mark.parametrize("pending", [False, True])
def test_trace_mode_dialog_keeps_untouched_merge(series, legacy, monkeypatch, pending):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    legacy.seed(pending, auto_merge=True)
    accept_quick_dialog(monkeypatch, lambda d: d.inputs[5].widget.setText("7"))
    MainWindow.changeTraceMode(StubWindow(series))
    values = legacy.finish(series, "auto_merge", "roll_window")
    print(f"trace mode pending={pending} {values}")
    assert values == {"auto_merge": True, "roll_window": 7}


@pytest.mark.parametrize("pending", [False, True])
def test_3d_step_dialog_keeps_untouched_rotate_step(series, legacy, monkeypatch, pending):
    from PyReconstruct.modules.gui.popup.custom_plotter import CustomPlotter

    legacy.seed(pending, rotate_step_3D=45.0)
    accept_quick_dialog(monkeypatch, lambda d: d.inputs[0].widget.setText("0.5"))
    CustomPlotter.setStep(StubWindow(series))
    values = legacy.finish(series, "translate_step_3D", "rotate_step_3D")
    print(f"3D step pending={pending} {values}")
    assert values == {"translate_step_3D": 0.5, "rotate_step_3D": 45.0}


@pytest.mark.parametrize("pending", [False, True])
def test_flag_dialog_keeps_untouched_name(legacy, monkeypatch, request, pending):
    legacy.seed(pending, flag_name="legacy-flag")
    window = request.getfixturevalue("main_window")
    accept_quick_dialog(monkeypatch, lambda d: d.inputs[2].widget.setText("20"))
    window.mouse_palette.modifyFlag()
    values = legacy.finish(window.series, "flag_name", "flag_size")
    print(f"flag pending={pending} {values}")
    assert values == {"flag_name": "legacy-flag", "flag_size": 20}


def _set_binding(name, sequence):
    def edit(dialog):
        from PySide6.QtGui import QKeySequence
        dialog.act_widgets[name].setKeySequence(QKeySequence(sequence))
    return edit


@pytest.mark.parametrize("pending", [False, True])
def test_shortcuts_dialog_keeps_untouched_binding(legacy, monkeypatch, request, pending):
    legacy.seed(pending, redo_act="Ctrl+Alt+Y")
    window = request.getfixturevalue("main_window")
    accept_dialog(monkeypatch, _set_binding("undo_act", "Ctrl+Alt+U"))
    window.displayShortcuts()
    values = legacy.finish(window.series, "undo_act", "redo_act")
    print(f"shortcuts pending={pending} {values}")
    assert values == {"undo_act": "Ctrl+Alt+U", "redo_act": "Ctrl+Alt+Y"}


@pytest.mark.parametrize("pending", [False, True])
def test_shortcuts_reset_defaults_is_stored(legacy, monkeypatch, request, pending):
    legacy.seed(pending, undo_act="Ctrl+Alt+U")
    window = request.getfixturevalue("main_window")
    accept_dialog(monkeypatch, lambda d: d.resetDefaults())
    window.displayShortcuts()
    values = legacy.finish(window.series, "undo_act")
    print(f"shortcuts reset pending={pending} {values}")
    assert values == {"undo_act": Series.qsettings_defaults["undo_act"]}


@pytest.mark.parametrize("transient", [False, True])
def test_scale_bar_recovery_during_open_keeps_the_untouched_mode(
    series, legacy, monkeypatch, transient
):
    from PySide6.QtCore import QSettings
    from PyReconstruct.modules.gui.dialog.scale_bar_settings import (
        ScaleBarSettingsDialog,
    )

    legacy.seed(False, scale_bar_mode="micron_pinned")
    app = series._settingsStore().APP
    status = QSettings.status
    remaining = [int(transient)]

    def fail_once(self):
        # only the first read of the old store fails
        if (remaining[0] and self.organizationName() == "KHLab"
                and self.applicationName() == app):
            remaining[0] -= 1
            return QSettings.AccessError
        return status(self)

    monkeypatch.setattr(QSettings, "status", fail_once)
    dialog = ScaleBarSettingsDialog(None, series)
    try:
        dialog.inputs[2].widget.setValue(61)
        assert dialog.accept()
    finally:
        dialog.close()
    values = legacy.finish(series, "scale_bar_mode", "scale_bar_width")
    print(f"scale bar transient={transient} {values}")
    assert values == {"scale_bar_mode": "micron_pinned", "scale_bar_width": 61}


def _open_main_window_dialog(request, monkeypatch, method):
    window = request.getfixturevalue("main_window")
    accept_quick_dialog(monkeypatch, lambda d: None)
    accept_dialog(monkeypatch, lambda d: None)
    return lambda: method(window)


def _open_with_stub(series, monkeypatch, method):
    accept_quick_dialog(monkeypatch, lambda d: None)
    accept_dialog(monkeypatch, lambda d: None)
    return lambda: method(StubWindow(series))


def _dialogs():
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
    from PyReconstruct.modules.gui.dialog.backup import BackupDialog
    from PyReconstruct.modules.gui.dialog.scale_bar_settings import (
        ScaleBarSettingsDialog,
    )
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    from PyReconstruct.modules.gui.popup.custom_plotter import CustomPlotter

    return {
        "scale bar": lambda s, r, m: lambda: ScaleBarSettingsDialog(None, s).close(),
        "options": lambda s, r, m: lambda: AllOptionsDialog(None, s).close(),
        "backup": lambda s, r, m: lambda: BackupDialog(None, s).close(),
        "pointer": lambda s, r, m: _open_with_stub(s, m, MainWindow.modifyPointer),
        "grid": lambda s, r, m: _open_with_stub(s, m, MainWindow.modifyGrid),
        "knife": lambda s, r, m: _open_with_stub(s, m, MainWindow.modifyKnife),
        "trace mode": lambda s, r, m: _open_with_stub(s, m, MainWindow.changeTraceMode),
        "3D step": lambda s, r, m: _open_with_stub(s, m, CustomPlotter.setStep),
        "flag": lambda s, r, m: _open_main_window_dialog(
            r, m, lambda w: w.mouse_palette.modifyFlag()),
        "shortcuts": lambda s, r, m: _open_main_window_dialog(
            r, m, lambda w: w.displayShortcuts()),
    }


@pytest.mark.parametrize("name", [
    "scale bar", "options", "backup", "pointer", "grid", "knife", "trace mode",
    "3D step", "flag", "shortcuts",
])
def test_dialogs_check_for_a_pending_copy_before_reading_options(
    domain, series, monkeypatch, request, name  # noqa: F811  (fixture)
):
    """A copy that finishes during the opening reads leaves the earlier ones at
    their defaults, so each dialog checks for a pending copy first."""
    from PyReconstruct.modules.gui.dialog import all_options, backup, chosen_options

    open_dialog = _dialogs()[name](series, request, monkeypatch)
    events = []
    get_option = Series.getOption

    def read(self, *args, **kwargs):
        events.append("read")
        return get_option(self, *args, **kwargs)

    for module in (all_options, backup, chosen_options):
        def check(series, _check=module.settings_copy_pending):
            events.append("check")
            return _check(series)
        monkeypatch.setattr(module, "settings_copy_pending", check)
    monkeypatch.setattr(Series, "getOption", read)
    open_dialog()
    print(f"{name}: {events[:4]}")
    assert events[:1] == ["check"]
