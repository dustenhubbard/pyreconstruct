"""Both tracing option dialogs preserve and enable the selection filter."""
import pytest
from PySide6.QtWidgets import QCheckBox

from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickDialog

pytestmark = pytest.mark.gui


def _checkboxes(dialog):
    checks = {w.text(): w for w in dialog.findChildren(QCheckBox)}
    return checks['Automatically merge overlapping traces'], checks['Only merge selected traces']


def _edit_filter(dialog):
    auto_merge, selected_only = _checkboxes(dialog)
    assert not auto_merge.isChecked()
    assert selected_only.isChecked()
    assert not selected_only.isEnabled()
    auto_merge.setChecked(True)
    assert selected_only.isEnabled()
    selected_only.setChecked(False)
    auto_merge.setChecked(False)
    assert not selected_only.isEnabled()
    assert not selected_only.isChecked()
    auto_merge.setChecked(True)
    assert selected_only.isEnabled()
    assert not selected_only.isChecked()


def test_trace_mode_dialog_saves_filter_and_preserves_smoothing(main_window, monkeypatch):
    series = main_window.series
    series.setOption('auto_merge', False)
    series.setOption('auto_merge_selected_only', True)
    series.setOption('roll_average', True)
    series.setOption('roll_window', 7)

    def edit(dialog):
        _edit_filter(dialog)
        assert dialog.accept(close=False)
        return dialog.responses, True

    monkeypatch.setattr(QuickDialog, 'exec', edit)
    main_window.changeTraceMode()
    assert series.getOption('auto_merge') is True
    assert series.getOption('auto_merge_selected_only') is False
    assert series.getOption('roll_average') is True
    assert series.getOption('roll_window') == 7

    def reopen(dialog):
        auto_merge, selected_only = _checkboxes(dialog)
        assert auto_merge.isChecked()
        assert selected_only.isEnabled()
        assert not selected_only.isChecked()
        selected_only.setChecked(True)
        return None, False

    monkeypatch.setattr(QuickDialog, 'exec', reopen)
    main_window.changeTraceMode()
    assert series.getOption('auto_merge_selected_only') is False, 'Cancel must not save edits'


def test_all_options_saves_filter_and_resets_defaults(main_window, qtbot):
    series = main_window.series
    series.setOption('auto_merge', False)
    series.setOption('auto_merge_selected_only', True)
    dialog = AllOptionsDialog(main_window, series)
    qtbot.addWidget(dialog)
    widget = dialog.all_widgets['trace']
    _edit_filter(widget)
    dialog.accept()
    assert series.getOption('auto_merge') is True
    assert series.getOption('auto_merge_selected_only') is False

    dialog = AllOptionsDialog(main_window, series)
    qtbot.addWidget(dialog)
    dialog.resetDefaults()
    auto_merge, selected_only = _checkboxes(dialog.all_widgets['trace'])
    assert not auto_merge.isChecked()
    assert selected_only.isChecked()
    assert not selected_only.isEnabled()
    assert series.getOption('auto_merge_selected_only') is False, 'Reset must wait for OK'
