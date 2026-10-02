"""Export to XML keeps negative traces negative and positive traces positive.

Reconstruct has no negative flag: a closed contour is negative when its points
run clockwise, and `XMLContour.isNegative` reads it that way on import.
`Trace.getXMLObj` used to reverse the points of every negative trace, so a
negative trace whose points already ran clockwise went out positive, and a
positive trace drawn clockwise went out negative. A hole imported from XML
keeps its clockwise points in memory, so it was one of the ones flipped.

Reconstruct reads the direction after applying the contour's transform, so on
a section whose transform is mirrored, points that run counterclockwise in
PyReconstruct run clockwise in Reconstruct. Export and import both read the
sign from the raw points and the sign of the transform's determinant, not
from transformed points, so rounding cannot give a flat trace a sign.
"""
import math

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import (
    jsonToXML,
    xmlToJSON,
)
from PyReconstruct.modules.constants import blank_series
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes_legacy import (
    Contour as XMLContour,
    Transform as XMLTransform,
    process_section_file,
)

CCW = [(0, 0), (2, 0), (2, 2), (0, 2)]
CW = CCW[::-1]

# x' = 10 - x: a mirrored (negative determinant) section transform
MIRROR = XMLTransform(xcoef=[10, -1, 0, 0, 0, 0], ycoef=[0, 0, 1, 0, 0, 0])


def reads_negative(contour):
    """How Reconstruct reads the contour: direction after its transform."""
    points = contour.points
    if contour.transform is not None:
        points = contour.transform.transformPoints(points)
    return XMLContour(closed=True, points=points).isNegative()


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
@pytest.mark.parametrize("points", [CW, CCW], ids=["cw", "ccw"])
def test_mirrored_export_direction_matches_the_flag(points, negative):
    trace = Trace("t", [255, 0, 0], True)
    trace.points = list(points)
    trace.negative = negative

    contour = trace.getXMLObj(MIRROR)

    assert reads_negative(contour) is negative
    assert sorted(contour.points) == sorted(points)
    assert trace.points == points


@pytest.mark.parametrize(
    "points, negative",
    # mirrored, so counterclockwise points read clockwise (negative)
    [(CCW, True), (CW, False)],
    ids=["ccw-negative", "cw-positive"],
)
def test_mirrored_import_reads_the_transformed_direction(points, negative):
    contour = XMLContour(
        name="t", closed=True, mode=9, border=[1, 0, 0], fill=[1, 0, 0],
        hidden=False, points=list(points), transform=MIRROR,
    )

    assert Trace.fromXMLObj(contour, MIRROR).negative is negative


_C, _S = math.cos(math.radians(30)), math.sin(math.radians(30))
ROTATE_30 = XMLTransform(xcoef=[0, _C, -_S, 0, 0, 0], ycoef=[0, _S, _C, 0, 0, 0])
# a closed trace with no area: its points lie on one line
FLAT = [(1, 2), (2, 4), (3, 6), (4, 8)]


@pytest.mark.parametrize("points", [FLAT, FLAT[::-1]], ids=["up", "down"])
def test_flat_trace_on_a_rotated_section_imports_positive(points):
    contour = XMLContour(
        name="t", closed=True, mode=9, border=[1, 0, 0], fill=[1, 0, 0],
        hidden=False, points=list(points), transform=ROTATE_30,
    )

    assert Trace.fromXMLObj(contour, ROTATE_30).negative is False


@pytest.mark.parametrize("points", [FLAT, FLAT[::-1]], ids=["up", "down"])
def test_flat_trace_on_a_rotated_section_exports_in_order(points):
    trace = Trace("t", [255, 0, 0], True)
    trace.points = list(points)

    assert trace.getXMLObj(ROTATE_30).points == points


def test_counterclockwise_trace_on_a_nonlinear_section_imports_positive():
    tform = XMLTransform(xcoef=[0, 1, 0, 0, 1, 0], ycoef=[0, 0, 1, 0, 0, 0])
    contour = XMLContour(
        name="t", closed=True, mode=9, border=[1, 0, 0], fill=[1, 0, 0],
        hidden=False, points=[(2, 0), (3, 0), (3, 1), (2, 1)], transform=tform,
    )

    assert Trace.fromXMLObj(contour).negative is False


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


# The same section with every transform mirrored (x' = 10 - x). Points that
# run clockwise here run counterclockwise in Reconstruct, so the cell is drawn
# clockwise and the hole counterclockwise.
MIRRORED_SECTION = (
    SECTION.replace('xcoef=" 0 1 0 0 0 0"', 'xcoef=" 10 -1 0 0 0 0"')
    .replace('points="0 0, 2 0, 2 2, 0 2, "', 'points="0 2, 2 2, 2 0, 0 0, "')
    .replace(
        'points="0.5 0.5, 0.5 1.5, 1.5 1.5, 1.5 0.5, "',
        'points="1.5 0.5, 1.5 1.5, 0.5 1.5, 0.5 0.5, "',
    )
)


@pytest.mark.parametrize("section_xml", [SECTION, MIRRORED_SECTION], ids=["plain", "mirrored"])
def test_xml_round_trip_keeps_negative_flags(qapp, tmp_path, section_xml):
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
    (xml_in / "neg.0").write_text(section_xml)

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
    assert {c.name: reads_negative(c) for c in exported.contours} == expected

    again = xmlToJSON(str(xml_out / "neg.ser"))
    try:
        assert {t.name: t.negative for t in again.loadSection(0).tracesAsList()} == expected
    finally:
        again.close()
