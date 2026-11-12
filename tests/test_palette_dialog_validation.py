"""Palette edits preserve buttons and reject radii that cannot define a stamp."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QInputDialog

from PyReconstruct.modules.gui.dialog import trace as trace_dialog
from PyReconstruct.modules.gui.dialog import trace_palette

pytestmark = pytest.mark.gui


@pytest.fixture
def press_ok(monkeypatch):
    def exec_(dialog):
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", exec_)


def test_renaming_palette_to_current_tab_text_keeps_buttons(
    qtbot, real_series, monkeypatch, press_ok
):
    series = real_series
    old_name = series.palette_index[0]
    stamp = series.palette_traces[old_name][0].copy()
    stamp.points = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    stamp.tags = {"axon"}
    stamp.obj_defaults = {"groups": ["axons"]}
    series.palette_traces[old_name] = [stamp]
    before = [t.copy() for t in series.palette_traces[old_name]]
    token = series.paletteToken(old_name)
    dialog = trace_palette.TracePaletteDialog(None, series)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("current_tab_text", True)
    )
    qtbot.mouseClick(
        dialog.tab_widget,
        Qt.RightButton,
        pos=dialog.tab_widget.tabBar().tabRect(
            dialog.tab_widget.currentIndex()
        ).center(),
    )
    assert "current_tab_text" in dialog.inputs

    _, confirmed = dialog.exec()

    assert confirmed
    assert series.palette_index[0] == "current_tab_text"
    assert old_name not in series.palette_traces
    after = series.palette_traces["current_tab_text"]
    assert [t.name for t in after] == [t.name for t in before]
    assert [t.tags for t in after] == [t.tags for t in before]
    assert [t.obj_defaults for t in after] == [t.obj_defaults for t in before]
    assert [c for t in after for p in t.points for c in p] == pytest.approx(
        [c for t in before for p in t.points for c in p], abs=1e-7
    )
    assert [t.getRadius() for t in after] == pytest.approx(
        [t.getRadius() for t in before], abs=1e-7
    )
    assert series.paletteToken("current_tab_text") == token


@pytest.mark.parametrize("radius", ["nan", "inf", "-inf", "1e309", "0", "-1"])
def test_all_palettes_reject_bad_radius_before_any_palette_changes(
    qtbot, real_series, monkeypatch, press_ok, radius
):
    series = real_series
    palettes = series.palette_traces
    before = {name: [list(t.points) for t in traces] for name, traces in palettes.items()}
    index = list(series.palette_index)
    dialog = trace_palette.TracePaletteDialog(None, series)
    qtbot.addWidget(dialog)
    notices = []
    monkeypatch.setattr(trace_palette, "notify", notices.append)
    # Use the last radius so a valid earlier row cannot be committed first.
    dialog.inputs[index[0]][-1].widget.setText(radius)

    _, confirmed = dialog.exec()

    assert not confirmed
    assert notices
    assert series.palette_traces is palettes
    assert series.palette_index == index
    assert {name: [list(t.points) for t in traces] for name, traces in palettes.items()} == before


@pytest.mark.parametrize("radius", ["nan", "inf", "-inf", "1e309", "0", "-1"])
def test_single_button_rejects_bad_radius(
    qtbot, real_series, monkeypatch, press_ok, radius
):
    series = real_series
    name, index = series.palette_index
    trace = series.palette_traces[name][index]
    before = list(trace.points)
    dialog = trace_dialog.TraceDialog(None, [trace], is_palette=True, series=series)
    qtbot.addWidget(dialog)
    notices = []
    monkeypatch.setattr(trace_dialog, "notify", notices.append)
    dialog.stamp_size_input.setText(radius)

    answer, confirmed = dialog.exec()

    assert not confirmed
    assert answer is None
    assert notices
    assert list(trace.points) == before
