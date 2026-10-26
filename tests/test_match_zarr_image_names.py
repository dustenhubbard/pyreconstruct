"""Pointing a series at a zarr that names its images another way offers the zarr's names.

`changeSrcDir` reloads the image after the folder changes. When the folder is
a zarr and no section image is in it, every section is paired with the zarr
image carrying the number in its image name (`backend.image_name_match`), a
dialog lists the pairs and draws a few sections' traces over the proposed
images, and on confirmation the names are applied through `setImageNames`,
the path `Edit all image sources...` uses, so unsaved traces survive. The
zarr is read and never written, and the series file is left to the save.
A .jser opened from the Finder while the dialog is up is skipped with a
notice, and the names go to the series the change started on.

The tests run on shapes1 (five sections, traces, images) in place of the
default fixture series.
"""
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel

from PyReconstruct.modules.datatypes import Trace

pytestmark = pytest.mark.gui

FILES = Path(__file__).resolve().parents[1] / "dev" / "assets" / "checker" / "files"
GRID = {n: f"00{n}_shapes_grid0{n}_sec0{n}.tif" for n in range(5)}
SHAPES = {n: f"shapes_{n}.tif" for n in range(5)}
NAME = "match_probe"
SQUARE = [(100, 300), (200, 300), (200, 200), (100, 200)]


@pytest.fixture
def series_jser(tmp_path):
    """shapes1 in place of the class series, with its images beside it."""
    source = FILES / "shapes1.jser"
    if not source.exists():  # pragma: no cover - repo layout guard
        pytest.skip("fixture shapes1.jser not found")
    destination = tmp_path / "shapes1.jser"
    shutil.copy(source, destination)
    for image in FILES.glob("shapes_*.tif"):
        shutil.copy(image, tmp_path / image.name)
    return destination


def _image(snum):
    """A shapes image as a 2D uint8 array."""
    gray = QImage(str(FILES / SHAPES[snum])).convertToFormat(QImage.Format_Grayscale8)
    rows = np.frombuffer(gray.constBits(), dtype=np.uint8)
    return rows.reshape(gray.height(), gray.bytesPerLine())[:, :gray.width()].copy()


def _zarr(tmp_path, names=GRID, layout="scaled"):
    """A zarr of the shapes images under the given names."""
    import zarr

    fp = str(tmp_path / "grid.zarr")
    root = zarr.open_group(fp, mode="w")
    if layout == "scaled":
        groups = [root.create_group("scale_1"), root.create_group("scale_2")]
    else:
        groups = [root]
    for snum, name in names.items():
        data = _image(snum % 5)
        for step, group in zip((1, 2), groups):
            group.create_dataset(name, data=data[::step, ::step], chunks=(256, 256))
    return fp


def _snapshot(folder):
    found = {}
    for root, _, files in os.walk(folder):
        for f in files:
            path = os.path.join(root, f)
            with open(path, "rb") as fh:
                found[os.path.relpath(path, folder)] = fh.read()
    return found


def _names_on_disk(series):
    return {snum: series.loadSection(snum).src for snum in series.sections}


@pytest.fixture
def on_screen(monkeypatch):
    """A user at the screen, so the prompts are allowed to show."""
    from PyReconstruct.modules.gui.utils import utils as gui_utils

    monkeypatch.delenv(gui_utils.UNATTENDED_ENV_VAR, raising=False)
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)


@pytest.fixture
def answer(monkeypatch):
    """The dialog, built for real but never shown; records each one built.

    Set `answer.confirmed` to False to cancel.
    """
    from PyReconstruct.modules.gui.main import main_window as mw

    class Answer:
        confirmed = True
        built = []

    def exec_(dialog):
        Answer.built.append(dialog)
        return 1 if Answer.confirmed else 0

    monkeypatch.setattr(mw.MatchImageNamesDialog, "exec", exec_)
    return Answer


def _draw(field):
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(SQUARE, field.tracing_trace, closed=True)


def _count(section):
    return len(section.contours.get(NAME, []))


def test_confirming_uses_the_zarr_names_in_the_series(
    main_window, main_window_dialogs, on_screen, answer, tmp_path
):
    series = main_window.series
    fp = _zarr(tmp_path)
    zarr_before = _snapshot(fp)
    with open(series.jser_fp, "rb") as fh:
        jser_before = fh.read()
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(fp)

    assert len(answer.built) == 1
    assert _names_on_disk(series) == GRID
    assert main_window.field.section.src == GRID[series.current_section]
    assert main_window.field.section_layer.image_found
    assert series.modified
    assert main_window_dialogs.notices == []
    assert _snapshot(fp) == zarr_before, "the zarr was written"
    with open(series.jser_fp, "rb") as fh:
        assert fh.read() == jser_before, "the series file changed before a save"


def test_cancel_changes_nothing(main_window, main_window_dialogs, on_screen, answer, tmp_path):
    series = main_window.series
    fp = _zarr(tmp_path)
    answer.confirmed = False
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(fp)

    assert len(answer.built) == 1
    assert _names_on_disk(series) == SHAPES
    assert not main_window.field.section_layer.image_found
    assert main_window_dialogs.notices == []


def test_unsaved_traces_survive_the_rename(main_window, on_screen, answer, tmp_path):
    field, series = main_window.field, main_window.series
    _draw(field)
    current = series.current_section
    assert _count(field.section) == 1
    fp = _zarr(tmp_path)

    main_window.changeSrcDir(fp)

    assert field.section.src == GRID[current]
    assert _count(field.section) == 1, "the unsaved trace vanished from the field"
    assert _count(series.loadSection(current)) == 1, "the trace never reached disk"


def test_a_match_that_is_not_one_to_one_says_why(
    main_window, main_window_dialogs, on_screen, answer, tmp_path
):
    series = main_window.series
    names = dict(GRID)
    names[5] = "005_shapes_grid05_sec05.tif"
    fp = _zarr(tmp_path, names)
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(fp)

    assert answer.built == []
    [notice] = main_window_dialogs.notices
    assert notice.startswith("No section image in this series is in grid.zarr")
    assert "the zarr's 6 images are numbered 0-5, and the series' 5 image names 0-4" in notice
    assert notice.endswith("The image names were not changed.")
    assert _names_on_disk(series) == SHAPES


def test_a_zarr_holding_the_series_names_is_used_as_it_is(
    main_window, main_window_dialogs, on_screen, answer, tmp_path
):
    fp = _zarr(tmp_path, SHAPES)
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(fp)

    assert answer.built == []
    assert main_window_dialogs.notices == []
    assert main_window.field.section_layer.image_found
    assert _names_on_disk(main_window.series) == SHAPES


def test_nothing_is_offered_without_a_user(main_window, main_window_dialogs, answer, tmp_path):
    fp = _zarr(tmp_path)
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(fp)

    assert answer.built == []
    assert main_window_dialogs.notices == []
    assert _names_on_disk(main_window.series) == SHAPES


def test_a_plain_image_folder_is_not_matched(
    main_window, main_window_dialogs, on_screen, answer, tmp_path
):
    folder = tmp_path / "grid"
    folder.mkdir()
    for snum, name in GRID.items():
        shutil.copy(FILES / SHAPES[snum], folder / name)
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(str(folder))

    assert answer.built == []
    assert main_window_dialogs.notices == []
    assert _names_on_disk(main_window.series) == SHAPES


def test_the_flat_layout_is_matched_too(main_window, on_screen, answer, tmp_path):
    fp = _zarr(tmp_path, layout="flat")

    main_window.changeSrcDir(fp)

    assert len(answer.built) == 1
    assert _names_on_disk(main_window.series) == GRID
    assert main_window.field.section_layer.image_found


def _dialog(main_window, fp):
    """The dialog built the way changeSrcDir builds it, without the window's prompt."""
    from PyReconstruct.modules.backend.image_name_match import matchByNumber, zarrImageNames
    from PyReconstruct.modules.gui.dialog import MatchImageNamesDialog

    series = main_window.series
    series.src_dir = fp
    series_names = _names_on_disk(series)
    match, reason = matchByNumber(series_names, zarrImageNames(fp))
    assert reason == ""
    return MatchImageNamesDialog(main_window, series, series_names, match, fp)


def _distinct(pixmap):
    image = pixmap.toImage().convertToFormat(QImage.Format_Grayscale8)
    rows = np.frombuffer(image.constBits(), dtype=np.uint8)
    return len(np.unique(rows.reshape(image.height(), image.bytesPerLine())[:, :image.width()]))


def test_the_preview_draws_three_sections_over_their_images(main_window, on_screen, tmp_path):
    series = main_window.series
    fp = _zarr(tmp_path)
    window_before = list(series.window)

    dialog = _dialog(main_window, fp)

    assert dialog.preview_sections == [0, 2, 4]
    assert dialog.table.rowCount() == 5
    assert [dialog.table.item(r, 2).text() for r in range(5)] == [GRID[n] for n in range(5)]
    for snum in dialog.preview_sections:
        pixmap = dialog.previews[snum]
        assert pixmap.width() == dialog.PREVIEW_WIDTH
        assert _distinct(pixmap) > 2, f"section {snum} preview is blank"
    assert not dialog.grab().isNull()
    assert list(series.window) == window_before
    assert _names_on_disk(series) == SHAPES, "building the preview changed a section"


def test_renumbered_sections_are_flagged_and_drawn_first(main_window, on_screen, tmp_path):
    series = main_window.series
    for snum, other in ((0, 1), (1, 0)):
        section = series.loadSection(snum)
        section.src = SHAPES[other]
        section.save()
    fp = _zarr(tmp_path)

    dialog = _dialog(main_window, fp)

    assert dialog.preview_sections[:2] == [0, 1]
    assert dialog.match["names"][0] == GRID[1]
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert any(t.startswith("On 2 sections (0-1) the number in the image name") for t in texts)


def test_edit_all_image_sources_still_renames_every_section(main_window, monkeypatch):
    """The section list's action now runs through setImageNames."""
    from PyReconstruct.modules.gui.table import section as section_mod
    from PyReconstruct.modules.gui.table.section import SectionTableWidget

    series = main_window.series
    # the action refuses locked sections, so unlock them on disk first
    for snum in list(series.sections):
        section = series.loadSection(snum)
        section.align_locked = False
        section.save()
    main_window.field.reload()
    monkeypatch.setattr(
        section_mod.QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("img_#.tif", True)),
    )
    table = SectionTableWidget(series, main_window, main_window.field.table_manager)

    table.modifyAllSrc()

    assert _names_on_disk(series) == {n: f"img_{n}.tif" for n in range(5)}
    assert main_window.field.section.src == f"img_{series.current_section}.tif"


@pytest.fixture
def finder(qapp, main_window):
    """Route a .jser opened from the Finder to the window, as the app does."""
    from PyReconstruct.run import FileOpenWatcher

    watcher = FileOpenWatcher()
    watcher.main_window = main_window
    qapp.installEventFilter(watcher)
    yield watcher
    qapp.removeEventFilter(watcher)


def _send_finder_open(tmp_path):
    """Send the event a Finder double-click on a copy of shapes1 sends.

    Returns the file of that copy, series B.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent
    from PySide6.QtWidgets import QApplication

    folder = tmp_path / "series_b"
    folder.mkdir()
    fp = folder / "series_b.jser"
    shutil.copy(FILES / "shapes1.jser", fp)
    for image in FILES.glob("shapes_*.tif"):
        shutil.copy(image, folder / image.name)
    app = QApplication.instance()
    app.sendEvent(app, QFileOpenEvent(QUrl.fromLocalFile(str(fp))))
    return str(fp)


def _open_from_finder(window, tmp_path):
    """Open a copy of shapes1 as series B, the way a Finder double-click does.

    Asked to save the series it closes, the window gets "no" from the
    dialog recorder.
    """
    fp = _send_finder_open(tmp_path)
    assert window.series.jser_fp == fp
    return window.series


def _logged(series):
    return [log.event for log in series.log_set.all_logs]


def test_a_finder_open_while_the_dialog_is_up_is_skipped(
    main_window, main_window_dialogs, finder, on_screen, monkeypatch, tmp_path
):
    """The dialog's event loop delivers a .jser from the Finder; it is not opened."""
    from PyReconstruct.modules.gui.main import main_window as mw

    first = main_window.series
    sent = []

    def exec_(dialog):
        sent.append(_send_finder_open(tmp_path))
        return 1

    monkeypatch.setattr(mw.MatchImageNamesDialog, "exec", exec_)
    fp = _zarr(tmp_path)
    main_window_dialogs.notices.clear()

    main_window.changeSrcDir(fp)

    [b_fp] = sent
    assert main_window.series is first and not first.closed
    assert _names_on_disk(first) == GRID
    assert main_window.field.section_layer.image_found
    assert len(main_window_dialogs.notices) == 1
    assert b_fp in main_window_dialogs.notices[0]


def test_edit_all_image_sources_leaves_a_series_opened_meanwhile_alone(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    """The name prompt has its own event loop, so the Finder reaches it too."""
    from PyReconstruct.modules.gui.table import section as section_mod
    from PyReconstruct.modules.gui.table.section import SectionTableWidget

    first = main_window.series
    for snum in list(first.sections):
        section = first.loadSection(snum)
        section.align_locked = False
        section.save()
    main_window.field.reload()
    opened = []

    def get_text(*args, **kwargs):
        second = _open_from_finder(main_window, tmp_path)
        opened.append((second, second.modified))
        return "img_#.tif", True

    monkeypatch.setattr(section_mod.QInputDialog, "getText", staticmethod(get_text))
    table = SectionTableWidget(first, main_window, main_window.field.table_manager)
    main_window_dialogs.notices.clear()

    table.modifyAllSrc()

    [(second, modified)] = opened
    assert main_window.series is second
    assert _names_on_disk(second) == SHAPES
    assert not any("img_#.tif" in event for event in _logged(second))
    assert second.modified == modified
    assert main_window_dialogs.notices == [
        f"{first.name} was closed, so its image names were not changed."
    ]
