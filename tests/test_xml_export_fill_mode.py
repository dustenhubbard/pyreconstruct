"""Export to XML writes a trace whose fill mode came from an unusual
Reconstruct mode.

On import, `convertMode` turns any Reconstruct mode other than 9, 11, 13 and
15 into a fill style of `None`. On export it only knew `none`, `transparent`
and `solid`, so such a trace raised `UnboundLocalError` and the export stopped
after the first section file, with no `.ser`.
"""
import os

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.constants import blank_section, blank_series
from PyReconstruct.modules.datatypes.trace import convertMode
from PyReconstruct.modules.datatypes_legacy import process_section_file


def _write_xml_series(folder, mode):
    ser = (
        blank_series.replace("[SECTION_NUM]", "0")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "0")
        .replace("[LASTTHUMBSECTION]", "0")
    )
    (folder / "probe.ser").write_text(ser)
    sec = (
        blank_section.replace("[SECTION_INDEX]", "0")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[TRANSFORM_DIM]", "0")
        .replace("[XCOEF]", "0 1 0 0 0 0")
        .replace("[YCOEF]", "0 0 1 0 0 0")
        .replace("[IMAGE_MAG]", "0.00254")
        .replace("[IMAGE_SOURCE]", "a.tif")
        .replace("[IMAGE_LENGTH]", "1000")
        .replace("[IMAGE_HEIGHT]", "1000")
    )
    contour = (
        '<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">\n'
        '<Contour name="d001" hidden="false" closed="true" simplified="true" '
        f'border="1 0 0" fill="1 0 0" mode="{mode}" '
        'points="0.5 0.5, 1.5 0.5, 1.5 1.5, 0.5 1.5, "/>\n'
        "</Transform>\n"
    )
    (folder / "probe.0").write_text(sec.replace("</Section>", contour + "</Section>"))
    return str(folder / "probe.ser")


@pytest.mark.parametrize("mode, pair", [(7, (None, "selected")), (-5, (None, "unselected"))])
def test_import_of_an_unusual_mode_is_unchanged(mode, pair):
    assert convertMode(mode) == pair


@pytest.mark.parametrize(
    "pair, mode",
    [
        ((None, "selected"), 13),
        ((None, "unselected"), -13),
        ([None, "selected"], 13),
        # the pairs that already exported keep their modes
        (("none", "none"), 11),
        (("transparent", "selected"), 9),
        (("transparent", "unselected"), -9),
        (("solid", "selected"), 13),
        (("solid", "unselected"), -13),
        (("solid", "always"), 13),
    ],
)
def test_export_mode(pair, mode):
    assert convertMode(pair) == mode


@pytest.mark.parametrize("mode, expected", [(7, 13), (-7, -13)])
def test_series_with_an_unusual_mode_exports(qapp, tmp_path, mode, expected):
    xml_in = tmp_path / "xml_in"
    xml_out = tmp_path / "xml_out"
    xml_in.mkdir()
    xml_out.mkdir()

    series = xmlToJSON(_write_xml_series(xml_in, mode))
    try:
        jsonToXML(series, str(xml_out))
        name = series.name
    finally:
        series.close()

    assert sorted(os.listdir(xml_out)) == [f"{name}.0", f"{name}.ser"]
    section = process_section_file(str(xml_out / f"{name}.0"))
    modes = {c.name: c.mode for c in section.contours}
    assert modes == {"d001": expected}
