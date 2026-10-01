"""A legacy .ser with z-traces keeps its own 20-trace palette.

`fill_missing_ser_attributes` added the 20 default palette traces whenever the
series node did not have exactly 20 children. Every `ZContour` is a child too,
so a .ser with its full palette and any z-trace came in with a palette of 40:
its own 20 followed by the defaults. Only `Contour` children count now.
"""
from copy import deepcopy

import pytest
from lxml import etree

from PyReconstruct.modules.constants import blank_section, blank_series


@pytest.fixture
def settings_isolated():
    # getOption writes a default back when a key is missing, so the Series
    # built by xmlToJSON must never reach the real settings store.
    from PyReconstruct.modules.backend.settings_store import (
        DictSettingsStore, default_settings_store, set_default_settings_store,
    )
    original = default_settings_store()
    set_default_settings_store(DictSettingsStore())
    try:
        yield
    finally:
        set_default_settings_store(original)


def _write_ser(path, n_contours, n_zcontours):
    """A .ser with `n_contours` palette traces named mine0, mine1, ... and
    `n_zcontours` z-traces after them, as Reconstruct writes them."""
    txt = (
        blank_series.replace("[SECTION_NUM]", "1")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "1")
        .replace("[LASTTHUMBSECTION]", "1")
    )
    root = etree.fromstring(txt)
    defaults = [child for child in root if child.tag == "Contour"]
    assert len(defaults) == 20
    for child in list(root):
        root.remove(child)
    for i in range(n_contours):
        contour = deepcopy(defaults[i % 20])
        contour.set("name", f"mine{i}")
        root.append(contour)
    for i in range(n_zcontours):
        z = etree.SubElement(root, "ZContour")
        z.set("name", f"z{i}")
        z.set("closed", "false")
        z.set("border", "1 0 0")
        z.set("fill", "1 0 0")
        z.set("mode", "11")
        z.set("points", "0 0 1,\n1 1 2,\n")
    with open(path, "wb") as f:
        f.write(etree.tostring(root))


def _palette_names(path):
    from PyReconstruct.modules.datatypes_legacy import process_series_file

    return [contour.name for contour in process_series_file(str(path)).contours]


@pytest.mark.parametrize("n_zcontours", [1, 3, 20])
def test_full_palette_with_zcontours_is_not_doubled(tmp_path, n_zcontours):
    path = tmp_path / "S.ser"
    _write_ser(path, 20, n_zcontours)

    assert _palette_names(path) == [f"mine{i}" for i in range(20)]


def test_full_palette_without_zcontours_is_unchanged(tmp_path):
    path = tmp_path / "S.ser"
    _write_ser(path, 20, 0)

    assert _palette_names(path) == [f"mine{i}" for i in range(20)]


@pytest.mark.parametrize("n_zcontours", [0, 1])
def test_missing_palette_still_gets_the_defaults(tmp_path, n_zcontours):
    path = tmp_path / "S.ser"
    _write_ser(path, 0, n_zcontours)

    names = _palette_names(path)
    assert len(names) == 20
    assert not any(name.startswith("mine") for name in names)


def test_new_series_from_ser_has_a_palette_of_20(qapp, settings_isolated, tmp_path):
    from PyReconstruct.modules.backend.func import xml_json_conversions as conv

    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "S.ser", 20, 1)
    (d / "S.1").write_text(
        blank_section.replace("[SECTION_INDEX]", "1")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[TRANSFORM_DIM]", "3")
        .replace("[XCOEF]", "0 1 0 0 0 0")
        .replace("[YCOEF]", "0 0 1 0 0 0")
        .replace("[IMAGE_MAG]", "0.00254")
        .replace("[IMAGE_SOURCE]", "a.tif")
        .replace("[IMAGE_LENGTH]", "100")
        .replace("[IMAGE_HEIGHT]", "100")
    )

    series = conv.xmlToJSON(str(d / "S.ser"))
    try:
        palettes = series.palette_traces
        assert list(palettes) == ["palette1"]
        assert [trace.name for trace in palettes["palette1"]] == [
            f"mine{i}" for i in range(20)
        ]
    finally:
        series.close()
