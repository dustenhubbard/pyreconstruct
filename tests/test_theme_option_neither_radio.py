"""Options preserves an unknown theme when neither radio matches.

Use a real Series and its isolated settings store so the dialog reads and
writes the same model throughout the accept/set path.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.utils import appearance

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _theme_widget(qapp, tmp_path, theme):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    store = DictSettingsStore()
    series.setSettingsStore(store)
    series.setOption("theme", theme)
    dialog = AllOptionsDialog(None, series)
    return dialog, dialog.all_widgets["theme"], store


def test_neither_radio_selected_preserves_current_theme(qapp, tmp_path):
    dialog, page, store = _theme_widget(qapp, tmp_path, "studio")
    try:
        layout = page.inputs[0].widget.layout()
        for index in range(layout.count()):
            button = layout.itemAt(index).widget()
            button.setAutoExclusive(False)
            button.setChecked(False)
        assert page.accept(close=False)
        assert all(not checked for _, checked in page.responses[0])
        page.set()
        assert store.value(None, "theme", str) == "studio"
    finally:
        dialog.series.close()
        dialog.deleteLater()


def test_selecting_a_radio_still_sets_that_theme(qapp, tmp_path):
    dialog, page, store = _theme_widget(qapp, tmp_path, "default")
    try:
        layout = page.inputs[0].widget.layout()
        for index, (_, value) in enumerate(appearance.choices()):
            if value == "qdark":
                layout.itemAt(index).widget().setChecked(True)
        assert page.accept(close=False)
        page.set()
        assert store.value(None, "theme", str) == "qdark"
    finally:
        dialog.series.close()
        dialog.deleteLater()
