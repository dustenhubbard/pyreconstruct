"""Export to XML writes a trace whose fill mode came from an unusual
Reconstruct mode.

On import, `convertMode` turns any Reconstruct mode other than 9, 11, 13 and
15 into a fill style of `None`. On export it only knew `none`, `transparent`
and `solid`, so such a trace raised `UnboundLocalError` and the export stopped
at the section that held it, with no `.ser`.

A filled trace with the condition `none` is filled when it is unselected, but
export wrote it with a positive mode, which reads back as filled when selected.
It now goes out negative, the same as `unselected`.
"""
import os

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.constants import blank_section, blank_series
from PyReconstruct.modules.datatypes import Trace
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
        # the field fills these when unselected, so they go out negative
        (("transparent", "none"), -9),
        (("solid", "none"), -13),
    ],
)
def test_export_mode(pair, mode):
    assert convertMode(pair) == mode


@pytest.mark.parametrize(
    "fill_mode",
    [
        ("none", "none"),
        ("transparent", "selected"),
        ("transparent", "unselected"),
        ("solid", "selected"),
        ("solid", "unselected"),
    ],
)
def test_representable_fill_modes_round_trip(fill_mode):
    # The XML mode stores the condition only as its sign, so "always" is left out.
    trace = Trace("t", [255, 0, 0], True)
    trace.points = [(0, 0), (2, 0), (2, 2), (0, 2)]
    trace.fill_mode = fill_mode

    imported = Trace.fromXMLObj(trace.getXMLObj())

    assert imported.fill_mode == fill_mode


W, H = 400, 400
PPU = 100.0  # pixels per field unit
# lower left corners, in field units, of four 1 x 1 squares
CORNERS = [(0.5, 0.5), (2.5, 0.5), (0.5, 2.5), (2.5, 2.5)]


@pytest.fixture
def shapes_series(qapp, shapes1_jser):
    from PyReconstruct.modules.datatypes.series import Series

    series = Series.openJser(str(shapes1_jser))
    yield series
    series.close()


def _filled(series, traces):
    """Draw four (trace, selected) pairs as squares and say which are filled."""
    from PyReconstruct.modules.backend.view.section_layer import SectionLayer

    section = series.loadSection(list(series.sections.keys())[0])
    for contour in section.contours.values():
        for t in contour.getTraces():
            t.hidden = True
    window = [0, 0, W / PPU, H / PPU]
    series.window = window

    for (trace, selected), (x, y) in zip(traces, CORNERS):
        square = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        trace.points = [
            tuple(p)
            for p in section.tform.mapPointsArray(square, inverted=True).tolist()
        ]
        section.addTrace(trace, log_event=False)
        if selected:
            section.addSelectedTrace(trace)

    image = SectionLayer(section, series, load_image_layer=False).generateTraceLayer(
        (W, H), window, window_moved=True
    ).toImage()
    # field y grows upward; the center of each square is half a unit in
    return [
        image.pixelColor(round((x + 0.5) * PPU), round(H - (y + 0.5) * PPU)).alpha() > 0
        for x, y in CORNERS
    ]


@pytest.mark.parametrize("condition", ["none", "selected", "unselected"])
@pytest.mark.parametrize("style", ["transparent", "solid"])
def test_a_fill_is_drawn_the_same_after_a_round_trip(shapes_series, style, condition):
    # "always" is left out: the XML mode stores the condition only as its sign
    trace = Trace("t", [255, 0, 0], True)
    trace.points = [(0, 0), (2, 0), (2, 2), (0, 2)]
    trace.fill_mode = (style, condition)
    imported = Trace.fromXMLObj(trace.getXMLObj())

    filled = _filled(
        shapes_series,
        [(trace, True), (trace.copy(), False), (imported, True), (imported.copy(), False)],
    )

    before, after = filled[:2], filled[2:]
    assert any(before), "the trace is filled in neither state"
    assert after == before


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
