"""The calibration a series starts with, and the notice that shows it.

A new series made from images is offered 0.002 um/px (2 nm, the tSEM pixel
size) in place of the old 0.00254. A series made from a .ser keeps the
calibration in its files, and a saved .jser keeps its own: nothing rescales
either. Each new series shows its calibration once it opens, before the
Save As.
"""

import json
import os
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import xmlToJSON
from PyReconstruct.modules.constants import blank_section, blank_series
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.main.main_window import (
    NEW_SERIES_MAG,
    newSeriesCalibrationText,
)


def _image(folder, name="img0.png"):
    fp = os.path.join(folder, name)
    open(fp, "wb").close()
    return fp


def _write_legacy_series(folder, name, mags):
    """A legacy XML series with one section per mag, numbered from 1."""
    snums = list(range(1, len(mags) + 1))
    with open(os.path.join(folder, f"{name}.ser"), "w") as f:
        f.write(
            blank_series.replace("[SECTION_NUM]", str(snums[0]))
            .replace("[SECTION_THICKNESS]", "0.05")
            .replace("[LAST3DSECTION]", str(snums[0]))
            .replace("[LASTTHUMBSECTION]", str(snums[0]))
        )
    for n, mag in zip(snums, mags):
        with open(os.path.join(folder, f"{name}.{n}"), "w") as f:
            f.write(
                blank_section.replace("[SECTION_INDEX]", str(n))
                .replace("[SECTION_THICKNESS]", "0.05")
                .replace("[TRANSFORM_DIM]", "3")
                .replace("[XCOEF]", "0 1 0 0 0 0")
                .replace("[YCOEF]", "0 0 1 0 0 0")
                .replace("[IMAGE_MAG]", str(mag))
                .replace("[IMAGE_SOURCE]", "a.tif")
                .replace("[IMAGE_LENGTH]", "100")
                .replace("[IMAGE_HEIGHT]", "100")
            )
    return os.path.join(folder, f"{name}.ser")


def _mags(series):
    return {snum: series.data["sections"][snum]["mag"] for snum in series.sections}


def _calibration_notices(recorder):
    return [n for n in recorder.notices if n.startswith("Image calibration:")]


def _series_of(mags, thicknesses):
    sections = {
        n: {"mag": m, "thickness": t}
        for n, (m, t) in enumerate(zip(mags, thicknesses))
    }
    return SimpleNamespace(data={"sections": sections})


# -- a new series from images ------------------------------------------------


def test_new_series_default_is_2_nm():
    assert NEW_SERIES_MAG == 0.002


@pytest.mark.gui
def test_new_series_offers_and_uses_2_nm(
    tmp_path, main_window, main_window_dialogs, monkeypatch
):
    from PySide6.QtWidgets import QInputDialog

    window = main_window
    offered = []

    def accept_default(parent, title, label, value, *args, **kwargs):
        offered.append((label, value))
        return value, True

    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(accept_default))
    monkeypatch.setattr(window, "saveAsToJser", lambda *a, **k: "cancel")

    images = tmp_path / "images"
    images.mkdir()
    window.newSeries(
        image_locations=[_image(str(images), "a.png"), _image(str(images), "b.png")],
        series_name="tsem",
        thickness=0.05,
    )

    assert offered == [("Enter image calibration (μm/px):", 0.002)]
    assert window.series.name == "tsem"
    assert set(_mags(window.series).values()) == {0.002}
    assert _calibration_notices(main_window_dialogs) == [
        "Image calibration: 0.002 μm/px (2 nm per pixel)\n"
        "Section thickness: 0.05 μm\n"
        "\n"
        "To change the calibration, use "
        "Series ▸ Calibration ▸ Manually set pixel mag..."
    ]
    window.series.modified = False


@pytest.mark.gui
def test_new_series_keeps_a_typed_calibration(
    tmp_path, main_window, main_window_dialogs, monkeypatch
):
    window = main_window
    monkeypatch.setattr(window, "saveAsToJser", lambda *a, **k: "cancel")

    window.newSeries(
        image_locations=[_image(str(tmp_path))],
        series_name="tem",
        mag=0.00254,
        thickness=0.05,
    )

    assert set(_mags(window.series).values()) == {0.00254}
    (notice,) = _calibration_notices(main_window_dialogs)
    assert notice.startswith("Image calibration: 0.00254 μm/px (2.54 nm per pixel)")
    window.series.modified = False


# -- a new series from a .ser ------------------------------------------------


@pytest.mark.parametrize("mags", [[0.00254, 0.00254], [0.00254, 0.0031], [0.0011, 0.0011]])
def test_ser_keeps_its_calibration(qapp, tmp_path, mags):
    series = xmlToJSON(_write_legacy_series(str(tmp_path), "S", mags))
    try:
        assert _mags(series) == {1: mags[0], 2: mags[1]}
        assert series.loadSection(1).mag == mags[0]
        assert series.loadSection(2).mag == mags[1]
    finally:
        series.close()


@pytest.mark.gui
def test_new_from_ser_shows_the_ser_calibration(
    tmp_path, main_window, main_window_dialogs, monkeypatch
):
    window = main_window
    monkeypatch.setattr(window, "saveAsToJser", lambda *a, **k: "cancel")
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()

    window.newFromXML(_write_legacy_series(str(xml_dir), "S", [0.00254, 0.0031]))

    assert _mags(window.series) == {1: 0.00254, 2: 0.0031}
    # no calibration prompt: the .ser has one
    assert "Enter image calibration (μm/px):" not in main_window_dialogs.dialogs
    (notice,) = _calibration_notices(main_window_dialogs)
    assert notice.splitlines()[:3] == [
        "Image calibration: 0.00254 to 0.0031 μm/px (2.54 to 3.1 nm per pixel)",
        "Section thickness: 0.05 μm",
        "The sections do not all have the same calibration.",
    ]
    window.series.modified = False


# -- an existing .jser ---------------------------------------------------------


def _saved_jser(tmp_path, mag):
    images = tmp_path / "images"
    images.mkdir()
    series = Series.new(
        [_image(str(images), "a.png"), _image(str(images), "b.png")],
        "old",
        mag,
        0.05,
    )
    fp = str(tmp_path / "old.jser")
    series.saveJser(save_fp=fp, close=True)
    return fp


def _mags_on_disk(fp):
    with open(fp) as f:
        data = json.load(f)
    return [s["mag"] for s in data["sections"] if s]


@pytest.mark.parametrize("mag", [0.00254, 0.0011])
def test_existing_jser_keeps_its_calibration(qapp, tmp_path, mag):
    fp = _saved_jser(tmp_path, mag)
    assert _mags_on_disk(fp) == [mag, mag]

    series = Series.openJser(fp)
    try:
        assert set(_mags(series).values()) == {mag}
        assert all(series.loadSection(n).mag == mag for n in series.sections)
        series.saveJser()
    finally:
        series.close()

    assert _mags_on_disk(fp) == [mag, mag]


def test_section_saved_without_a_mag_still_reads_as_before(qapp, tmp_path):
    fp = _saved_jser(tmp_path, 0.0011)
    with open(fp) as f:
        data = json.load(f)
    first = next(s for s in data["sections"] if s)
    del first["mag"]
    with open(fp, "w") as f:
        json.dump(data, f)

    series = Series.openJser(fp)
    try:
        mags = sorted(series.loadSection(n).mag for n in series.sections)
    finally:
        series.close()

    assert mags == [0.0011, 0.00254]


@pytest.mark.gui
def test_opening_a_jser_shows_no_calibration_notice(
    tmp_path, main_window, main_window_dialogs
):
    fp = _saved_jser(tmp_path, 0.00254)

    main_window.openSeries(jser_fp=fp)

    assert main_window.series.jser_fp == fp
    assert set(_mags(main_window.series).values()) == {0.00254}
    assert _calibration_notices(main_window_dialogs) == []


# -- the notice text ---------------------------------------------------------


def test_notice_one_calibration():
    text = newSeriesCalibrationText(_series_of([0.002, 0.002], [0.05, 0.05]))
    assert text.splitlines() == [
        "Image calibration: 0.002 μm/px (2 nm per pixel)",
        "Section thickness: 0.05 μm",
        "",
        "To change the calibration, use Series ▸ Calibration ▸ Manually set pixel mag...",
    ]


def test_notice_mixed_calibration_and_thickness():
    text = newSeriesCalibrationText(
        _series_of([0.0031, 0.00254, 0.00254], [0.05, 0.07, 0.05])
    )
    assert text.splitlines()[:3] == [
        "Image calibration: 0.00254 to 0.0031 μm/px (2.54 to 3.1 nm per pixel)",
        "Section thickness: 0.05 to 0.07 μm",
        "The sections do not all have the same calibration.",
    ]
