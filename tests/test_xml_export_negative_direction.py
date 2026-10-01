"""Export to XML keeps negative traces negative and positive traces positive.

Reconstruct has no negative flag: a closed contour is negative when its points
run clockwise, and `XMLContour.isNegative` reads it that way on import.
`Trace.getXMLObj` used to reverse the points of every negative trace, so a
negative trace whose points already ran clockwise went out positive, and a
positive trace drawn clockwise went out negative. A hole imported from XML
keeps its clockwise points in memory, so it was one of the ones flipped.
"""
import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.constants import blank_series
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes_legacy import process_section_file

CCW = [(0, 0), (2, 0), (2, 2), (0, 2)]
CW = CCW[::-1]


@pytest.mark.parametrize("negative", [True, False])
@pytest.mark.parametrize("points", [CW, CCW], ids=["cw", "ccw"])
def test_exported_direction_matches_the_flag(points, negative):
    trace = Trace("t", [255, 0, 0], True)
    trace.points = list(points)
    trace.negative = negative

    contour = trace.getXMLObj()

    assert contour.isNegative() is negative
    assert sorted(contour.points) == sorted(points)
    assert trace.points == points  # the trace itself is not reordered


@pytest.mark.parametrize("negative", [True, False])
def test_open_trace_keeps_its_point_order(negative):
    trace = Trace("t", [255, 0, 0], False)
    trace.points = [(0, 0), (1, 0), (1, 1)]
    trace.negative = negative

    assert trace.getXMLObj().points == [(0, 0), (1, 0), (1, 1)]


SECTION = """<?xml version="1.0"?>
<!DOCTYPE Section SYSTEM "section.dtd">
<Section index="0" thickness="0.05" alignLocked="false">
<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">
<Image mag="0.00254" contrast="1" brightness="0" red="true" green="true" blue="true" src="a.tif" />
<Contour name="domain1" hidden="false" closed="true" simplified="false" border="1 0 1" fill="1 0 1" mode="11"
 points="0 0, 1000 0, 1000 1000, 0 1000, "/>
</Transform>
<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">
<Contour name="cell" hidden="false" closed="true" simplified="false" border="1 0 0" fill="1 0 0" mode="9"
 points="0 0, 2 0, 2 2, 0 2, "/>
</Transform>
<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">
<Contour name="hole" hidden="false" closed="true" simplified="false" border="0 1 0" fill="0 1 0" mode="9"
 points="0.5 0.5, 0.5 1.5, 1.5 1.5, 1.5 0.5, "/>
</Transform>
</Section>"""


def test_xml_round_trip_keeps_negative_flags(qapp, tmp_path):
    xml_in = tmp_path / "xml_in"
    xml_out = tmp_path / "xml_out"
    xml_in.mkdir()
    xml_out.mkdir()
    (xml_in / "neg.ser").write_text(
        blank_series.replace("[SECTION_NUM]", "0")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "0")
        .replace("[LASTTHUMBSECTION]", "0")
    )
    (xml_in / "neg.0").write_text(SECTION)

    series = xmlToJSON(str(xml_in / "neg.ser"))
    try:
        section = series.loadSection(0)
        # importing is unchanged: the clockwise hole is negative
        assert {t.name: t.negative for t in section.tracesAsList()} == {
            "cell": False, "hole": True,
        }
        for name, points, negative in [
            ("drawn_neg_cw", [(3, 3), (3, 4), (4, 4), (4, 3)], True),
            ("drawn_neg_ccw", [(5, 5), (6, 5), (6, 6), (5, 6)], True),
            ("drawn_pos_cw", [(7, 7), (7, 8), (8, 8), (8, 7)], False),
        ]:
            trace = Trace(name, [255, 255, 0], True)
            trace.points = points
            trace.negative = negative
            section.addTrace(trace)
        section.save()
        expected = {t.name: t.negative for t in series.loadSection(0).tracesAsList()}
        jsonToXML(series, str(xml_out))
    finally:
        series.close()

    exported = process_section_file(str(xml_out / "neg.0"))
    assert {c.name: c.isNegative() for c in exported.contours} == expected

    again = xmlToJSON(str(xml_out / "neg.ser"))
    try:
        assert {t.name: t.negative for t in again.loadSection(0).tracesAsList()} == expected
    finally:
        again.close()
