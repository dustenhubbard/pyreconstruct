"""Drive figure capture through real field widgets and inspect its outputs.

Set PYRECON_CAPTURE_ARTIFACT_DIR to save before/after pictures and the PNG
from test_save_and_copy_match_fresh_renderer for a review.
"""
import os
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QKeySequence, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import clear_latched_modifiers, menu_leaf_paths
from PyReconstruct.modules.backend.view.frame_render import FrameLayers, renderFrame
from PyReconstruct.modules.datatypes import Flag, Transform, Ztrace
from PyReconstruct.modules.gui.dialog.shortcuts import ShortcutsDialog
from PyReconstruct.modules.gui.main.figure_capture import SHAPES

pytestmark = pytest.mark.gui


@pytest.fixture
def series_jser(shapes1_jser):
    return shapes1_jser


@pytest.fixture
def capture(main_window, local_series_settings, qtbot):
    local_series_settings(main_window)
    main_window.resize(1200, 800)
    main_window.show()
    qtbot.wait(10)
    main_window.figurecapture_act.trigger()
    yield main_window.field.figure_capture
    if main_window.field.figure_capture is not None:
        main_window.field.figure_capture.close()


def pixels(image):
    image = image.convertToFormat(QImage.Format_ARGB32)
    return np.frombuffer(image.constBits(), np.uint32).reshape(image.height(), image.width()).copy()


def drag(widget, start, end):
    start, end = QPointF(start).toPoint(), QPointF(end).toPoint()
    QTest.mousePress(widget, Qt.LeftButton, pos=start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, pos=end)


def test_menu_shortcut_and_rebinding_open_one_capture(main_window, local_series_settings, qtbot):
    series = local_series_settings(main_window)
    main_window.show()
    main_window.activateWindow()
    main_window.field.setFocus()
    qtbot.wait(10)
    assert main_window.figurecapture_act.shortcut().toString() == "Ctrl+Shift+L"
    QTest.keySequence(main_window.field, QKeySequence("Ctrl+Shift+L"))
    clear_latched_modifiers()
    first = main_window.field.figure_capture
    assert first is not None and first.isVisible()
    main_window.figurecapture_act.trigger()
    assert main_window.field.figure_capture is first
    QTest.keyClick(first.width_input, Qt.Key_Escape)
    assert main_window.field.figure_capture is None

    dialog = ShortcutsDialog(main_window, series)
    qtbot.addWidget(dialog)
    assert "figurecapture_act" in dialog.act_widgets
    series.setOption("figurecapture_act", "Ctrl+Shift+J")
    main_window.createMenuBar()
    assert main_window.figurecapture_act.shortcut().toString() == "Ctrl+Shift+J"
    paths = menu_leaf_paths(main_window.menubar)
    assert "Section > Export > Figure..." in paths
    for suffix in ("svg", "png"):
        assert any("unlabeled 1 µm bar" in name and f".{suffix}" in name for name in paths)


def test_open_close_does_not_change_field_bar_or_selection(capture):
    field = capture.field
    window = list(field.series.window)
    view = pixels(field.field_pixmap.toImage())
    bar = field.mainwindow.mouse_palette.sb
    before = (bar.width(), bar.height(), bar.currentLength(), bar.override_length)
    selection = list(field.section.selected_traces)
    QTest.mouseClick(capture.label_size, Qt.LeftButton)
    capture.label_size.setValue(24)
    capture.tick_size.setValue(18)
    capture.outputImage()
    QTest.keyClick(capture, Qt.Key_Escape)
    assert field.figure_capture is None
    assert field.series.window == window
    assert np.array_equal(view, pixels(field.field_pixmap.toImage()))
    assert (bar.width(), bar.height(), bar.currentLength(), bar.override_length) == before
    assert field.section.selected_traces == selection


@pytest.mark.parametrize("shape", list(SHAPES))
def test_handle_drag_and_aspect_lock(capture, shape):
    # Start with room on all sides, independent of screen and font geometry.
    capture.frame = QRectF(100, 100, 280, 180)
    capture.refresh()
    QTest.mouseClick(capture.shape_buttons[shape], Qt.LeftButton)
    start = QRectF(capture.frame)
    drag(capture, start.bottomRight(), start.bottomRight() + QPointF(60, 50))
    assert capture.frame.width() > start.width()
    assert capture.frame.topLeft() == start.topLeft()
    assert capture.bounds().contains(capture.frame)
    if SHAPES[shape]:
        assert capture.frame.width() / capture.frame.height() == pytest.approx(SHAPES[shape])
    else:
        assert capture.frame == QRectF(100, 100, 340, 230)


def test_frame_and_bar_drag_are_separate_from_field_navigation(capture):
    capture.frame = QRectF(100, 100, 400, 300)
    capture.refresh()
    field = capture.field
    before = list(field.series.window)
    drag(capture, QPointF(180, 101), QPointF(220, 131))
    assert capture.frame == QRectF(140, 130, 400, 300)
    assert field.series.window == before
    bar = capture.scaleBarRect()
    center = bar.translated(capture.frame.topLeft()).center()
    drag(capture, center, center + QPointF(30, -60))
    after = capture.scaleBarRect()
    assert after.x() == pytest.approx(bar.x() + 30)
    assert after.y() == pytest.approx(bar.y() - 60)
    assert field.series.window == before
    assert field.mainwindow.mouse_palette.sb.override_length is capture.bar_length


@pytest.mark.parametrize("handle", ["nw", "n", "ne", "e", "se", "s", "sw", "w"])
def test_locked_handles_stay_inside_field_at_boundary(capture, handle):
    capture.frame = QRectF(100, 100, 320, 240)
    capture.ratio = 4 / 3
    capture.refresh()
    start = capture.handles()[handle]
    end = QPointF(-1000 if "w" in handle else 2000,
                  -1000 if "n" in handle else 2000)
    drag(capture, start, end)
    assert capture.bounds().contains(capture.frame)
    assert capture.frame.width() / capture.frame.height() == pytest.approx(4 / 3)
    assert capture.frame.width() > 320


def test_draw_new_frame_and_pan_under_it(capture):
    capture.frame = QRectF(300, 200, 300, 250)
    capture.refresh()
    drag(capture, QPointF(50, 50), QPointF(250, 170))
    assert capture.frame == QRectF(50, 50, 200, 120)
    # A larger frame leaves space clear of the bar and border for a pan.
    capture.frame = QRectF(100, 100, 400, 300)
    capture.refresh()
    old = list(capture.field.series.window)
    drag(capture, QPointF(350, 180), QPointF(375, 200))
    pw, ph = capture.field.pixmap_dim
    assert capture.field.series.window == pytest.approx(
        [old[0] - 25 * old[2] / pw, old[1] + 20 * old[3] / ph, old[2], old[3]])
    assert capture.frame == QRectF(100, 100, 400, 300)


def test_scroll_zooms_under_frame_without_changing_section(capture):
    field = capture.field
    old = list(field.series.window)
    section = field.section.n
    frame = QRectF(capture.frame)
    pos = QPointF(350, 250)
    event = QWheelEvent(pos, pos, QPoint(), QPoint(0, 120), Qt.NoButton,
                        Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(capture, event)
    new = field.series.window
    assert new[2] < old[2]
    pw, ph = field.pixmap_dim
    assert new[0] + pos.x() / pw * new[2] == pytest.approx(old[0] + pos.x() / pw * old[2])
    assert new[1] + (1 - pos.y() / ph) * new[3] == pytest.approx(old[1] + (1 - pos.y() / ph) * old[3])
    assert field.section.n == section
    assert capture.frame == frame


def test_output_pixels_inches_dpi_and_native(capture):
    field = capture.field
    capture.frame = QRectF(100, 100, 400, 200)
    capture.refresh()
    capture.width_input.setValue(1600)
    assert capture.outputDim() == (1600, 800)
    capture.height_input.setValue(600)
    assert capture.outputDim() == (1200, 600)
    capture.units.setCurrentText("Inches")
    assert capture.width_input.value() == 4
    assert capture.height_input.value() == 2
    capture.dpi.setValue(150)
    assert capture.outputDim() == (600, 300)
    capture.width_input.setValue(3)
    assert capture.outputDim() == (450, 225)
    capture.units.setCurrentText("Pixels")
    capture.dpi.setValue(300)
    assert capture.outputDim() == (450, 225)
    field.section.tform = Transform.identity()
    QTest.mouseClick(capture.native_button, Qt.LeftButton)
    assert capture.outputDim()[0] == round(capture.frameWindow()[2] / field.section.mag)
    field.section.tform = Transform([2, 0, 0, 0, 2, 0])
    QTest.mouseClick(capture.native_button, Qt.LeftButton)
    assert capture.outputDim()[0] == round(capture.frameWindow()[2] / (2 * field.section.mag))


def test_save_and_copy_match_fresh_renderer(capture, monkeypatch, tmp_path):
    field = capture.field
    # Put the star from the design example inside the 480 x 320 frame.
    pw, ph = field.pixmap_dim
    unit = 3.2 / 480
    field.series.window = [0.7 - 100 * unit,
                            0.8 - (ph - 400) * unit,
                            pw * unit, ph * unit]
    field.generateView()
    # Pictures are reproducible by running this test with the documented env var.
    artifacts = os.environ.get("PYRECON_CAPTURE_ARTIFACT_DIR")
    if artifacts:
        artifacts = Path(artifacts)
        artifacts.mkdir(parents=True, exist_ok=True)
        capture.hide()
        field.mainwindow.grab().save(str(artifacts / "before.png"))
        capture.show()
    capture.frame = QRectF(100, 80, 480, 320)
    capture.width_input.setValue(1440)
    capture.label_size.setValue(18)
    capture.tick_size.setValue(14)
    capture.refresh()
    x, y, width, height = field.series.window
    pw, ph = field.pixmap_dim
    expected_window = [x + 100 * width / pw, y + (ph - 80 - 320) * height / ph,
                       480 * width / pw, 320 * height / ph]
    bar = capture.scaleBarRect()
    expected = renderFrame(field.series, field.section, expected_window,
                           (480, 320), (1440, 960), FrameLayers(),
                           (bar.x(), bar.y()), capture.bar_length, 18, 14)
    before_window = list(field.series.window)
    before_view = pixels(field.field_pixmap.toImage())
    path = tmp_path / "figure.png"
    monkeypatch.setattr("PyReconstruct.modules.gui.main.figure_capture.FileDialog.get",
                        lambda *args, **kwargs: str(path))
    QTest.mouseClick(capture.save_button, Qt.LeftButton)
    assert path.exists(), capture.status.text()
    saved = QImage(str(path))
    assert saved.size().toTuple() == (1440, 960)
    assert np.array_equal(pixels(saved), pixels(expected))
    assert saved.dotsPerMeterX() == saved.dotsPerMeterY() == 11811
    QTest.mouseClick(capture.copy_button, Qt.LeftButton)
    copied = QApplication.clipboard().image()
    assert copied.size().toTuple() == (1440, 960)
    assert np.array_equal(pixels(copied), pixels(expected))
    assert field.series.window == before_window
    assert np.array_equal(pixels(field.field_pixmap.toImage()), before_view)
    if artifacts:
        capture.grab().save(str(artifacts / "after.png"))
        saved.save(str(artifacts / "figure.png"))


def test_layer_boxes_default_off_and_capture_checked_layers(capture):
    field = capture.field
    x, y, width, height = capture.frameWindow()
    field.section.flags = [Flag("capture flag", x + width / 2, y + height / 2,
                                field.section.n, (255, 0, 0))]
    field.series.ztraces = {"capture ztrace": Ztrace("capture ztrace", (0, 255, 0),
        [(x + width / 3, y + height / 3, field.section.n),
         (x + width / 2, y + height / 3, field.section.n)])}
    field.series.setOption("show_flags", "all")
    field.series.setOption("show_ztraces", True)
    field.section.selected_flags = field.section.flags[:]
    assert all(not check.isChecked() for check in capture.layer_checks.values())
    off = pixels(capture.outputImage())
    for check in capture.layer_checks.values():
        QTest.mouseClick(check, Qt.LeftButton, pos=QPoint(10, check.height() // 2))
        assert check.isChecked()
    on = pixels(capture.outputImage())
    assert not np.array_equal(off, on)
    bar = capture.scaleBarRect()
    expected = renderFrame(field.series, field.section, capture.frameWindow(),
        capture.frameDim(), capture.outputDim(), FrameLayers(flags=True, ztraces=True, selection=True),
        (bar.x(), bar.y()))
    assert np.array_equal(on, pixels(expected))


def test_hidden_field_image_and_traces_stay_hidden(capture):
    field = capture.field
    field.hide_image = True
    field.hide_trace_layer = True
    field.generateView()
    bar = capture.scaleBarRect()
    expected = renderFrame(field.series, field.section, capture.frameWindow(),
        capture.frameDim(), capture.outputDim(), FrameLayers(image=False, traces=False),
        (bar.x(), bar.y()))
    assert np.array_equal(pixels(capture.outputImage()), pixels(expected))


def test_save_cancel_and_failure_leave_existing_file(capture, monkeypatch, tmp_path):
    path = tmp_path / "figure.png"
    path.write_bytes(b"existing figure")
    files_before = set(tmp_path.iterdir())
    target = "PyReconstruct.modules.gui.main.figure_capture.FileDialog.get"
    monkeypatch.setattr(target, lambda *args, **kwargs: "")
    QTest.mouseClick(capture.save_button, Qt.LeftButton)
    assert path.read_bytes() == b"existing figure"
    monkeypatch.setattr(target, lambda *args, **kwargs: str(path))
    monkeypatch.setattr("PyReconstruct.modules.gui.main.figure_capture.QImageWriter.write",
                        lambda self, image: False)
    QTest.mouseClick(capture.save_button, Qt.LeftButton)
    assert "Could not save figure" in capture.status.text()
    assert path.read_bytes() == b"existing figure"
    assert set(tmp_path.iterdir()) == files_before


def test_output_limit_and_bar_fit_disable_export(capture):
    capture.width_input.setValue(30000)
    assert not capture.save_button.isEnabled()
    assert not capture.copy_button.isEnabled()
    assert "too large" in capture.status.text()
    capture.width_input.setValue(1200)
    capture.frame = QRectF(100, 100, 80, 50)
    capture.label_size.setValue(36)
    assert not capture.save_button.isEnabled()
    assert "does not fit" in capture.status.text()


def test_edit_shortcuts_do_not_modify_traces_behind_capture(capture):
    field = capture.field
    trace = field.section.tracesAsList()[0]
    field.section.selected_traces = [trace]
    before = trace.getList()
    count = len(field.section.tracesAsList())
    capture.setFocus()
    QTest.keyClick(capture, Qt.Key_Delete)
    QTest.keyClick(capture, Qt.Key_Right)
    assert trace.getList() == before
    assert len(field.section.tracesAsList()) == count


def test_resize_and_new_series_clean_up_capture(capture, qtbot):
    field = capture.field
    QTest.mouseClick(capture.shape_buttons["4:3"], Qt.LeftButton)
    field.mainwindow.resize(900, 650)
    qtbot.wait(10)
    assert capture.geometry() == field.geometry()
    assert capture.bounds().contains(capture.frame)
    assert capture.frame.width() / capture.frame.height() == pytest.approx(4 / 3)
    field.createField(field.series)
    assert field.figure_capture is None
    assert not capture.isVisible()
