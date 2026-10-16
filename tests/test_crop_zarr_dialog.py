"""`Series > Images > Crop scaled images around an object...` runs the crop from PyReconstruct.

The crop is ``backend.crop_zarr``, the module ``dev/assets/misc/crop_zarr.py``
runs from the command line. The dialog takes the same inputs, checks them with
the same functions before anything is written, and ``cropWithProgress`` runs the
crop on a worker thread behind the progress dialog, whose Cancel stops it after
the section being written. The row is built only in the Dev build
(``constants.build_flavor.is_dev_build``): a nightly, a source checkout, or the
Dev app; the stable app has no row.

What is pinned here:

  * the dialog opens on the series' values: its objects, the selected object,
    its zarr as the source, ``<stem>_<object>_crop.zarr`` beside it as the
    output, every gap option on, and the tool line it will write
  * the output follows the object and the source until it is edited
  * a bad object, radius, source or output is refused with the crop's own
    message, and nothing is written
  * a crop through the dialog and the progress dialog writes what the command
    line writes, and a log naming this PyReconstruct as the tool
  * a stop before the first section, or after two, leaves the sections written
    so far and no log, and says so; the Cancel button sets the stop flag and
    relabels the progress dialog; a series closed under the crop stops it
  * the window writes the field's unsaved edits before the crop, offers the
    selected object, and shows the summary
  * the row is in the Dev build's menus and not in the stable app's, in the
    menu dicts and in a live window; ``is_dev_build`` reads the flavor stamp
    and the version

The crop case (a five-section series and a two-scale zarr) and the expected
pixels come from ``tests/test_crop_zarr_cli.py``, so the dialog is held to the
command line's answer.
"""
import os
import threading
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.backend.crop_zarr import (
    LOG_NAME,
    CropStopped,
    appTool,
    cropSections,
    resolvePaths,
)
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.series import Series, SeriesClosedError
from PyReconstruct.modules.gui.dialog import crop_zarr as dialog_module
from PyReconstruct.modules.gui.dialog.crop_zarr import (
    GAP_OPTIONS,
    CropProgress,
    CropZarrDialog,
    cropWithProgress,
)

from tests.test_crop_zarr_cli import (  # noqa: F401  (fixture)
    OBJECT,
    RADIUS,
    _arrays,
    _expected,
    case,
)

pytestmark = pytest.mark.gui

CROP_ROW = "Crop scaled images around an object..."
STABLE_ROWS = ["Find/change image directory", "Convert to scaled images", "Update image scales"]


@pytest.fixture
def series(case):  # noqa: F811  (fixture)
    """The crop case's series, open, with the paths of its jser and zarr."""
    jser, src = case
    opened = Series.openJser(str(jser), progress=NullProgressReporter)
    opened.setProgressReporter(NullProgressReporter)
    yield opened, jser, src
    if not opened.closed:
        opened.close()


@pytest.fixture
def notices(monkeypatch):
    """What the dialog would have said in a notice."""
    seen = []
    monkeypatch.setattr(dialog_module, "notify", seen.append)
    return seen


@pytest.fixture
def progbars(monkeypatch):
    """Every progress dialog cropWithProgress makes, as it makes them."""
    made = []
    real = dialog_module.getProgbar

    def wrapped(*args, **kwargs):
        bar = real(*args, **kwargs)
        made.append(bar)
        return bar

    monkeypatch.setattr(dialog_module, "getProgbar", wrapped)
    return made


def _dialog(opened, obj_name=OBJECT, radius=RADIUS):
    dialog = CropZarrDialog(None, opened, obj_name)
    dialog.radius_input.setText(str(radius))
    return dialog


def _files(folder):
    return sorted(p.name for p in Path(folder).iterdir())


# --------------------------------------------------------------------------- #
# the dialog
# --------------------------------------------------------------------------- #
def test_the_dialog_opens_on_the_series_values(qapp, series):
    opened, jser, src = series
    dialog = CropZarrDialog(None, opened, OBJECT)
    box = dialog.object_box
    assert box.currentText() == OBJECT
    assert [box.itemText(i) for i in range(box.count())] == sorted(opened.data["objects"])
    assert dialog.radius_input.text() == "2"
    assert dialog.source_input.text() == str(src)
    assert dialog.output_input.text() == str(src.parent / f"imgs_{OBJECT}_crop.zarr")
    assert list(dialog.gap_boxes) == [keyword for keyword, _label in GAP_OPTIONS]
    assert all(box.isChecked() for box in dialog.gap_boxes.values())
    from PySide6.QtWidgets import QLabel
    note = [label.text() for label in dialog.findChildren(QLabel) if LOG_NAME in label.text()]
    assert len(note) == 1 and appTool() in note[0]
    assert appTool().startswith("PyReconstruct ")


def test_a_series_without_a_selected_object_offers_the_first_by_name(qapp, series):
    opened, jser, src = series
    dialog = CropZarrDialog(None, opened)
    assert dialog.object_box.currentText() == sorted(opened.data["objects"])[0]
    dialog = CropZarrDialog(None, opened, "not_an_object")
    assert dialog.object_box.currentText() == sorted(opened.data["objects"])[0]


def test_the_output_follows_the_object_and_the_source_until_edited(qapp, series):
    opened, jser, src = series
    dialog = CropZarrDialog(None, opened, OBJECT)
    other = next(name for name in sorted(opened.data["objects"]) if name != OBJECT)

    dialog.object_box.setCurrentText(other)
    assert dialog.output_input.text() == str(src.parent / f"imgs_{other}_crop.zarr")
    dialog.source_input.le.setText("/elsewhere/volume-zarr")
    assert dialog.output_input.text() == f"/elsewhere/volume_{other}_crop-zarr"
    dialog.source_input.le.setText("/elsewhere/not a zarr")
    assert dialog.output_input.text() == ""

    # typed: kept through a change of object; cleared: follows again
    dialog.source_input.le.setText(str(src))
    dialog.output_input.setText("/elsewhere/mine.zarr")
    dialog.output_input.textEdited.emit("/elsewhere/mine.zarr")
    dialog.object_box.setCurrentText(OBJECT)
    assert dialog.output_input.text() == "/elsewhere/mine.zarr"
    dialog.output_input.setText("")
    dialog.output_input.textEdited.emit("")
    assert dialog.output_input.text() == str(src.parent / f"imgs_{OBJECT}_crop.zarr")


@pytest.mark.parametrize("problem, said", [
    ("unknown object", "Object 'squid' is not in this series."),
    ("negative radius", "Enter a radius of zero or more microns."),
    ("radius not a number", "Enter a radius of zero or more microns."),
    ("no source", "Choose the source zarr."),
    ("source not a zarr", "Not a zarr: "),
    ("output is the source", "The output path is the source zarr or inside it"),
    ("output inside the source", "The output path is the source zarr or inside it"),
    ("output holds the source", "The output path holds the source zarr"),
    ("output exists", "The output already exists"),
])
def test_bad_inputs_are_refused_before_anything_is_written(qapp, series, notices, problem, said):
    opened, jser, src = series
    dialog = _dialog(opened)
    before = _files(src.parent), _files(src)
    if problem == "unknown object":
        dialog.object_box.check_text = False
        dialog.object_box.setCurrentText("squid")
    elif problem == "negative radius":
        dialog.radius_input.setText("-1")
    elif problem == "radius not a number":
        dialog.radius_input.setText("two")
    elif problem == "no source":
        dialog.source_input.le.setText("")
    elif problem == "source not a zarr":
        dialog.source_input.le.setText(str(src.parent))
        dialog.output_input.setText(str(src.parent / "crop.zarr"))
    elif problem == "output is the source":
        dialog.output_input.setText(str(src))
    elif problem == "output inside the source":
        dialog.output_input.setText(str(src / "scale_1" / "crop"))
    elif problem == "output holds the source":
        dialog.output_input.setText(str(src.parent))
    elif problem == "output exists":
        (src.parent / "taken.zarr").mkdir()
        before = _files(src.parent), _files(src)
        dialog.output_input.setText(str(src.parent / "taken.zarr"))

    dialog.accept()

    assert dialog.settings is None
    assert dialog.result() == 0
    assert len(notices) == 1 and said in notices[0], notices
    assert (_files(src.parent), _files(src)) == before


def test_good_inputs_are_accepted_as_the_crop_takes_them(qapp, series, notices):
    opened, jser, src = series
    dialog = _dialog(opened)
    dialog.gap_boxes["gray_missing"].setChecked(False)

    dialog.accept()

    assert notices == []
    assert dialog.result() == 1
    settings = dialog.settings
    assert settings.obj_name == OBJECT
    assert settings.radius == RADIUS
    assert settings.scales == [1, 2]
    assert settings.out_fp == os.path.realpath(src.parent / f"imgs_{OBJECT}_crop.zarr")
    assert settings.gaps == {
        "fill_untraced": True, "gray_missing": False, "check_blank": True,
        "match_by_number": True, "full_on_fail": True,
    }
    assert not os.path.exists(settings.out_fp), "accepting the dialog wrote the output"


# --------------------------------------------------------------------------- #
# the crop, behind the progress dialog
# --------------------------------------------------------------------------- #
def test_a_crop_runs_behind_the_progress_dialog_and_writes_the_log(qapp, series, notices, progbars):
    opened, jser, src = series
    settings = _dialog(opened).values()
    assert notices == []
    stop = threading.Event()

    summary = cropWithProgress(opened, settings, stop=stop)

    out = Path(settings.out_fp)
    assert out == Path(os.path.realpath(src.parent / f"imgs_{OBJECT}_crop.zarr"))
    got, want = _arrays(out), _expected(src)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
    log = (out / LOG_NAME).read_text().splitlines()
    assert log[0].startswith("crop_zarr.py log, written ")
    assert f"Tool: {appTool()}" in log
    assert f"Series: {opened.jser_fp}" in log
    assert f"Object: {OBJECT}" in log
    assert summary[0] == f"Cropped around {OBJECT}: 3 of 5 sections."
    assert summary[-1] == f"Log: {out / LOG_NAME}"
    assert summary == log[log.index("Summary") + 1:][:len(summary) - 1] + [summary[-1]]
    [progbar] = progbars
    assert progbar.labelText().startswith(f"Cropping images around {OBJECT}...")
    assert not progbar.isVisible()
    assert not stop.is_set(), "closing the progress dialog counted as Cancel"
    assert not opened.closed


def test_cancel_before_the_first_section_stops_the_crop(qapp, series, notices, progbars):
    opened, jser, src = series
    settings = _dialog(opened).values()
    stop = threading.Event()
    stop.set()

    with pytest.raises(CropStopped) as caught:
        cropWithProgress(opened, settings, stop=stop)

    assert (caught.value.done, caught.value.total) == (0, 5)
    assert str(caught.value) == (
        f"The crop was stopped after 0 of 5 sections. The partial output "
        f"{settings.out_fp!r} has no {LOG_NAME}; remove it to use its name again."
    )
    out = Path(settings.out_fp)
    assert out.is_dir(), "the partial output was removed"
    assert _arrays(out) == {}
    assert not (out / LOG_NAME).exists()
    assert not progbars[0].isVisible()


def test_a_stop_after_two_sections_leaves_them_whole_and_no_log(series):
    opened, jser, src = series
    out_fp, src_group, scales = resolvePaths(opened, OBJECT, "", str(src.parent / "stopped.zarr"))
    asked, reported, lines = [], [], []

    def stop_from_the_third_ask():
        asked.append(1)
        return len(asked) > 2

    with pytest.raises(CropStopped) as caught:
        cropSections(
            opened, OBJECT, RADIUS, src_group, scales, out_fp, show_progress=False,
            echo=lines.append, progress=reported.append, should_stop=stop_from_the_third_ask,
        )

    assert (caught.value.done, caught.value.total, caught.value.out_fp) == (2, 5, out_fp)
    got, want = _arrays(out_fp), _expected(src)
    assert sorted(got) == [(1, "shapes_0.tif"), (1, "shapes_1.tif"), (2, "shapes_0.tif"), (2, "shapes_1.tif")]
    for key in got:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
    assert not os.path.exists(os.path.join(out_fp, LOG_NAME))
    assert reported == [20.0, 40.0]
    assert lines == []


def test_the_cancel_button_sets_the_stop_flag_and_relabels(qapp):
    from PySide6.QtWidgets import QPushButton

    stop = threading.Event()
    progress = CropProgress("Cropping images around x...", stop)
    progbar = progress.dialog
    progress.report(40)
    assert progbar.value() == 40
    progress.report(100)
    assert progbar.value() == 99, "100 resets a QProgressDialog"
    assert not stop.is_set()

    progbar.findChild(QPushButton).click()

    assert stop.is_set()
    assert progbar.labelText() == "Stopping after the section being written..."
    assert progbar.maximum() == 0, "a busy bar while the section finishes"
    progress.report(60)
    assert progbar.labelText() == "Stopping after the section being written..."
    progress.close()
    assert not progbar.isVisible()


def test_closing_the_progress_dialog_is_not_a_cancel(qapp):
    stop = threading.Event()
    progress = CropProgress("Cropping images around x...", stop)
    progress.report(50)

    progress.close()

    assert not stop.is_set()
    assert not progress.dialog.isVisible()
    assert progress.dialog.labelText() == "Cropping images around x..."


def test_a_series_closed_under_the_crop_stops_it(series):
    opened, jser, src = series
    out_fp, src_group, scales = resolvePaths(opened, OBJECT, "", str(src.parent / "closed.zarr"))

    def close_the_series(percent):
        if not opened.closed:
            opened.close()

    with pytest.raises(SeriesClosedError) as caught:
        cropSections(
            opened, OBJECT, RADIUS, src_group, scales, out_fp, show_progress=False,
            echo=lambda line: None, progress=close_the_series,
        )

    assert "was closed while this ran" in str(caught.value)
    assert sorted(_arrays(out_fp)) == [(1, "shapes_0.tif"), (2, "shapes_0.tif")]
    assert not os.path.exists(os.path.join(out_fp, LOG_NAME))


# --------------------------------------------------------------------------- #
# the window
# --------------------------------------------------------------------------- #
@pytest.fixture
def series_jser(case):  # noqa: F811  (fixture)
    """The crop case's series in place of the fixture series, for main_window."""
    return case[0]


@pytest.fixture
def answer(monkeypatch):
    """The dialog, built for real and accepted with its offered values at RADIUS."""
    from PyReconstruct.modules.gui.main import main_window as mw

    class Answer:
        confirmed = True
        built = []

    def exec_(dialog):
        Answer.built.append(dialog)
        if not Answer.confirmed:
            return None, False
        dialog.radius_input.setText(str(RADIUS))
        settings = dialog.values()
        assert settings is not None
        return settings, True

    monkeypatch.setattr(mw.CropZarrDialog, "exec", exec_)
    return Answer


def test_the_window_saves_the_field_and_crops_around_the_selected_object(
    main_window, main_window_dialogs, answer, case  # noqa: F811  (fixture)
):
    jser, src = case
    series, field = main_window.series, main_window.field
    snum = series.current_section
    # an unsaved trace of the object on the current section, selected
    field.setTracingTrace(Trace(OBJECT, (0, 255, 0), True))
    field.newTrace([(100, 300), (200, 300), (200, 200), (100, 200)], field.tracing_trace, closed=True)
    field.section.selected_traces = list(field.section.contours[OBJECT])
    assert len(series.loadSection(snum).contours.get(OBJECT, [])) < len(field.section.contours[OBJECT])
    main_window_dialogs.notices.clear()

    main_window.cropScaledImages()

    [dialog] = answer.built
    assert dialog.object_box.currentText() == OBJECT
    out = src.parent / f"imgs_{OBJECT}_crop.zarr"
    [notice] = main_window_dialogs.notices
    assert notice.startswith(f"Cropped around {OBJECT}: ")
    assert notice.endswith(f"Log: {os.path.realpath(out / LOG_NAME)}")
    assert f"Tool: {appTool()}" in (out / LOG_NAME).read_text().splitlines()
    # the crop read the saved field: the new trace widened this section's window
    got, want = _arrays(out), _expected(src)
    key = (1, f"shapes_{snum}.tif")
    assert np.any(got[key][want[key] == 0]), "the crop did not see the unsaved trace"
    assert len(series.loadSection(snum).contours[OBJECT]) == len(field.section.contours[OBJECT])


def test_cancelling_the_dialog_crops_nothing(main_window, main_window_dialogs, answer, case):  # noqa: F811  (fixture)
    jser, src = case
    answer.confirmed = False
    before = _files(src.parent)
    main_window_dialogs.notices.clear()

    main_window.cropScaledImages()

    assert len(answer.built) == 1
    assert _files(src.parent) == before
    assert main_window_dialogs.notices == []


# --------------------------------------------------------------------------- #
# the Dev build
# --------------------------------------------------------------------------- #
@pytest.fixture
def stable_build(monkeypatch):
    """The stable app: no flavor stamp, a final version."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    monkeypatch.setattr(build_flavor, "running_version", lambda: "1.24.0")


@pytest.fixture
def dev_app(monkeypatch):
    """The Dev app: the flavor stamp, whatever the version."""
    monkeypatch.setenv("PYRECON_APP_NAME", "PyReconstruct Dev")
    monkeypatch.setattr(build_flavor, "running_version", lambda: "1.24.0")


@pytest.mark.parametrize("stamp, version, dev", [
    ("PyReconstruct Dev", "1.24.0", True),
    (None, "1.25.0.dev202610151111", True),
    (None, "1.25.0.dev5+g0123abc", True),
    (None, "unknown", True),
    (None, "1.24.0", False),
    (None, "1.24.0b1", False),
    ("PyReconstruct", "1.24.0", False),
])
def test_is_dev_build_reads_the_stamp_and_the_version(monkeypatch, stamp, version, dev):
    if stamp is None:
        monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    else:
        monkeypatch.setenv("PYRECON_APP_NAME", stamp)
    monkeypatch.setattr(build_flavor, "running_version", lambda: version)
    assert build_flavor.is_dev_build() is dev


def test_the_menu_dicts_carry_the_row_only_in_the_dev_build(monkeypatch):
    from PyReconstruct.modules.gui.main import menubar
    from tests.test_menubar_labels import _rows

    monkeypatch.setattr(menubar, "is_dev_build", lambda: True)
    dev = [(d, kind, attr, text) for d, kind, attr, text in _rows()]
    monkeypatch.setattr(menubar, "is_dev_build", lambda: False)
    stable = [(d, kind, attr, text) for d, kind, attr, text in _rows()]

    row = (2, "act", "cropzarr_act", CROP_ROW)
    assert row in dev
    assert dev[dev.index(row) - 1] == (2, "act", "scalezarr_act", "Update image scales")
    assert [r for r in dev if r != row] == stable


def test_the_dev_app_window_has_the_crop_row(dev_app, main_window):
    rows = [action.text() for action in main_window.imagesmenu.actions()]
    assert rows == STABLE_ROWS + [CROP_ROW]
    assert main_window.cropzarr_act is not None
    assert main_window.cropzarr_act.text() == CROP_ROW


def test_the_stable_app_window_has_no_crop_row(stable_build, main_window):
    rows = [action.text() for action in main_window.imagesmenu.actions()]
    assert rows == STABLE_ROWS
    assert not hasattr(main_window, "cropzarr_act")
