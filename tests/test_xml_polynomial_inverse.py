"""The inverse of a polynomial XML transform lands on the right point.

`Transform.xy_inverse` finds the inverse of a nonlinear transform by
iteration, the way Reconstruct does. It started its guess at (0, 0) but took
the first error at the input point instead of at the guess, so the first step
went the wrong way and could settle on another solution of the same
transform. With x + x^2, the point at x = 2 came back as -2 instead of 1.
The identity and affine branches are untouched.
"""
import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import xmlToJSON
from PyReconstruct.modules.constants import blank_series
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes_legacy import (
    Contour as XMLContour,
    Transform as XMLTransform,
)

# x' = x + x^2, the transform from the report
SQUARE_X = XMLTransform(xcoef=[0, 1, 0, 0, 1, 0], ycoef=[0, 0, 1, 0, 0, 0])

POLYNOMIALS = {
    "square_x": SQUARE_X,
    # x' = x + x*y: folds along y = -1
    "shear_xy": XMLTransform(xcoef=[0, 1, 0, 1, 0, 0], ycoef=[0, 0, 1, 0, 0, 0]),
    # a small nonlinear correction on a near identity, like an aligned section
    "realistic": XMLTransform(
        xcoef=[0.3, 1.002, 0.004, 1e-5, -2e-5, 3e-5],
        ycoef=[-0.2, -0.003, 0.998, 2e-5, 1e-5, -1e-5],
    ),
    # mirrored linear part with quadratic terms
    "mirror": XMLTransform(xcoef=[0, -1, 0, 0, 0.05, 0], ycoef=[0, 0, 1, 0, 0, 0.02]),
    # the Jacobian determinant at the origin is 0.15. Smaller than that and
    # the ten iterations Reconstruct allows run out before it converges.
    "near_singular": XMLTransform(xcoef=[0, 0.15, 0, 0, 0.2, 0], ycoef=[0, 0, 1, 0, 0, 0]),
}


def test_the_reported_point_comes_back_where_it_was_drawn():
    x, y = SQUARE_X.xy_inverse(2, 0)

    assert x == pytest.approx(1)
    assert y == 0


@pytest.mark.parametrize("name", list(POLYNOMIALS))
@pytest.mark.parametrize("point", [(2, 0), (0.5, -0.25), (1.5, -2), (10, 10), (0.01, 0.02)])
def test_forward_of_the_inverse_is_the_point(name, point):
    tform = POLYNOMIALS[name]

    x, y = tform.xy_inverse(*point)

    assert tform.xy_forward(x, y) == pytest.approx(point, abs=1e-6)


@pytest.mark.parametrize("name", list(POLYNOMIALS))
@pytest.mark.parametrize("point", [(0.5, 0.25), (-0.3, 0.7), (1.2, -0.4), (0, 0)])
def test_inverse_of_the_forward_is_the_point(name, point):
    tform = POLYNOMIALS[name]

    forward = tform.xy_forward(*point)

    assert tform.xy_inverse(*forward) == pytest.approx(point, abs=1e-6)


def test_transform_points_matches_xy_inverse():
    points = [(2, 0), (3, 0), (3, 1), (2, 1)]

    assert SQUARE_X.transformPoints(points) == [SQUARE_X.xy_inverse(*p) for p in points]


AFFINE_PINS = {
    # values from the identity and affine branches, which do not change
    "identity": (
        [0, 1, 0, 0, 0, 0], [0, 0, 1, 0, 0, 0],
        [[3.7, 1.2], [-0.3, 0.45], [0, 0], [100.5, -20.25]],
    ),
    "translate": (
        [1.25, 1, 0, 0, 0, 0], [-0.75, 0, 1, 0, 0, 0],
        [[2.45, 1.95], [-1.55, 1.2], [-1.25, 0.75], [99.25, -19.5]],
    ),
    "affine": (
        [1.5, 2, 0.5, 0, 0, 0], [-0.25, -1, 3, 0, 0, 0],
        [
            [0.903846153846154, 0.7846153846153846],
            [-0.8846153846153846, -0.061538461538461556],
            [-0.7115384615384616, -0.15384615384615385],
            [47.23076923076923, 9.076923076923077],
        ],
    ),
    "rotate": (
        [0.1, 0.8660254037844387, -0.5, 0, 0, 0], [0.2, 0.5, 0.8660254037844387, 0, 0, 0],
        [
            [3.6176914536239795, -0.9339745962155613],
            [-0.22141016151377552, 0.41650635094610966],
            [-0.18660254037844387, -0.12320508075688776],
            [76.72395053995766, -67.91021950739177],
        ],
    ),
}
AFFINE_POINTS = [(3.7, 1.2), (-0.3, 0.45), (0, 0), (100.5, -20.25)]


@pytest.mark.parametrize("name", list(AFFINE_PINS))
def test_identity_and_affine_inverses_are_unchanged(name):
    xcoef, ycoef, expected = AFFINE_PINS[name]
    tform = XMLTransform(xcoef=xcoef, ycoef=ycoef)

    results = [tform.xy_inverse(*p) for p in AFFINE_POINTS]

    # exact: these values are pinned, not approximated
    assert results == expected


def test_from_xml_obj_places_the_trace_through_the_inverse():
    contour = XMLContour(
        name="t", closed=True, mode=9, border=[1, 0, 0], fill=[1, 0, 0],
        hidden=False, points=[(2, 0), (3, 0), (3, 1), (2, 1)], transform=SQUARE_X,
    )

    trace = Trace.fromXMLObj(contour)

    # x = (-1 + sqrt(1 + 4u)) / 2 for u = 2 and u = 3
    assert [c for p in trace.points for c in p] == pytest.approx(
        [1, 0, 1.3027756377319946, 0, 1.3027756377319946, 1, 1, 1]
    )
    assert trace.negative is False


SECTION = """<?xml version="1.0"?>
<!DOCTYPE Section SYSTEM "section.dtd">
<Section index="0" thickness="0.05" alignLocked="false">
<Transform dim="0" xcoef=" 0 1 0 0 0 0" ycoef=" 0 0 1 0 0 0">
<Image mag="0.00254" contrast="1" brightness="0" red="true" green="true" blue="true" src="a.tif" />
<Contour name="domain1" hidden="false" closed="true" simplified="false" border="1 0 1" fill="1 0 1" mode="11"
 points="0 0, 1000 0, 1000 1000, 0 1000, "/>
</Transform>
<Transform dim="6" xcoef=" 0 1 0 0 1 0" ycoef=" 0 0 1 0 0 0">
<Contour name="cell" hidden="false" closed="true" simplified="false" border="1 0 0" fill="1 0 0" mode="9"
 points="2 0, 3 0, 3 1, 2 1, "/>
</Transform>
</Section>"""


def test_new_series_from_xml_places_a_polynomial_trace(qapp, tmp_path):
    xml_in = tmp_path / "xml_in"
    xml_in.mkdir()
    (xml_in / "poly.ser").write_text(
        blank_series.replace("[SECTION_NUM]", "0")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "0")
        .replace("[LASTTHUMBSECTION]", "0")
    )
    (xml_in / "poly.0").write_text(SECTION)

    series = xmlToJSON(str(xml_in / "poly.ser"))
    try:
        traces = {t.name: t for t in series.loadSection(0).tracesAsList()}
    finally:
        series.close()

    # the import snaps points to the half pixel grid, 0.00127 at this mag
    assert [c for p in traces["cell"].points for c in p] == pytest.approx(
        [1, 0, 1.3027756377319946, 0, 1.3027756377319946, 1, 1, 1], abs=0.0013
    )
    assert traces["cell"].negative is False
