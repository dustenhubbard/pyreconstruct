"""`File ▸ Import ▸ From ImageJ .roi` keeps each roi's own shape and place.

A polygon or rect comes in as its own vertices, a TRACED outline is closed and
an ANGLE is open, a composite roi keeps every sub-path, a multi-point roi gives
one stamp per marker, and the traces land where the file puts them on a
transformed section. One file that cannot be read is reported and the rest of
the batch still imports.
"""

import os

import numpy as np
import pytest

pytestmark = pytest.mark.gui


def _write_roi(fp, points, roitype, options=0):
    roifile = pytest.importorskip("roifile")
    roi = roifile.ImagejRoi.frompoints(np.array(points, dtype=float))
    roi.roitype = roitype
    roi.options |= roifile.ROI_OPTIONS(options)
    roi.tofile(str(fp))
    return str(fp)


def _import(tmp_path, points, roitype, options=0):
    from PyReconstruct.modules.backend.imports.imagej_roi import Roi

    return Roi(_write_roi(tmp_path / "probe.roi", points, roitype, options))


SQUARE = [(10.0, 10.0), (110.0, 10.0), (110.0, 110.0), (10.0, 110.0)]


def _field(points, img_height=200):
    return [(x, img_height - y) for x, y in points]


def _area(points):
    x, y = np.array(points).T
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


# --- geometry --------------------------------------------------------------------

def test_a_polygon_imports_as_its_own_vertices(tmp_path):
    roifile = pytest.importorskip("roifile")
    roi = _import(tmp_path, SQUARE, roifile.ROI_TYPE.POLYGON)

    assert roi.closed is True
    assert roi.get_field_shapes(200, 1.0) == [_field(SQUARE)]


def test_a_rect_imports_as_its_four_corners(tmp_path):
    roifile = pytest.importorskip("roifile")
    fp = tmp_path / "rect.roi"
    roifile.ImagejRoi(
        roitype=roifile.ROI_TYPE.RECT, left=10, top=10, right=110, bottom=110
    ).tofile(str(fp))
    from PyReconstruct.modules.backend.imports.imagej_roi import Roi

    shapes = Roi(str(fp)).get_field_shapes(200, 1.0)

    assert len(shapes) == 1
    assert sorted(shapes[0]) == sorted(_field(SQUARE))
    assert _area(shapes[0]) == pytest.approx(10000.0)


def test_only_a_spline_fit_roi_is_fitted(tmp_path):
    roifile = pytest.importorskip("roifile")
    roi = _import(
        tmp_path, SQUARE, roifile.ROI_TYPE.POLYGON, roifile.ROI_OPTIONS.SPLINE_FIT
    )

    (shape,) = roi.get_field_shapes(200, 1.0)
    # ImageJ evaluates a fitted spline at one point per 2 pixels of length
    # (this outline is about 400 pixels) and never fewer than 100 points
    assert len(shape) == 200
    # the curve still runs through the control points it was fitted to
    for p in _field(SQUARE):
        assert min(np.hypot(*(np.array(shape) - p).T)) < 3.0


def test_a_spline_fit_line_stays_open_and_keeps_its_endpoints(tmp_path):
    roifile = pytest.importorskip("roifile")
    line = [(0.0, 50.0), (25.0, 60.0), (50.0, 50.0), (75.0, 40.0), (100.0, 50.0)]
    roi = _import(
        tmp_path, line, roifile.ROI_TYPE.POLYLINE, roifile.ROI_OPTIONS.SPLINE_FIT
    )

    (shape,) = roi.get_field_shapes(100, 1.0)
    assert roi.closed is False
    assert len(shape) == 100
    assert shape[0] == pytest.approx((0.0, 50.0))
    assert shape[-1] == pytest.approx((100.0, 50.0))


def test_a_repeated_vertex_imports(tmp_path):
    roifile = pytest.importorskip("roifile")
    pts = [SQUARE[0]] + SQUARE
    for roitype in (roifile.ROI_TYPE.POLYGON, roifile.ROI_TYPE.POLYLINE):
        roi = _import(tmp_path, pts, roitype)
        assert roi.get_field_shapes(200, 1.0) == [_field(SQUARE)]


def test_a_repeated_vertex_in_a_spline_fit_roi_imports(tmp_path):
    roifile = pytest.importorskip("roifile")
    roi = _import(
        tmp_path,
        [SQUARE[0]] + SQUARE,
        roifile.ROI_TYPE.FREEHAND,
        roifile.ROI_OPTIONS.SPLINE_FIT,
    )
    (shape,) = roi.get_field_shapes(200, 1.0)
    assert len(shape) == 200


@pytest.mark.parametrize(
    "name, closed",
    [
        ("POLYGON", True), ("FREEHAND", True), ("TRACED", True),
        ("POLYLINE", False), ("FREELINE", False), ("ANGLE", False),
    ],
)
def test_roi_types_open_and_close_as_in_imagej(tmp_path, name, closed):
    roifile = pytest.importorskip("roifile")
    roi = _import(tmp_path, SQUARE[:3], getattr(roifile.ROI_TYPE, name))
    assert roi.closed is closed


def _square_path(x0, y0, s):
    # ImageJ shape path: 0 moveTo, 1 lineTo, 4 closePath
    return [0, x0, y0, 1, x0 + s, y0, 1, x0 + s, y0 + s, 1, x0, y0 + s, 4]


def _write_composite(fp, *squares):
    roifile = pytest.importorskip("roifile")
    path = sum((_square_path(*sq) for sq in squares), [])
    roifile.ImagejRoi(
        roitype=roifile.ROI_TYPE.RECT,
        multi_coordinates=np.array(path, dtype=np.float32),
        left=0, top=0, right=400, bottom=400,
        shape_roi_size=len(path),
    ).tofile(str(fp))
    return str(fp)


DONUT = [(50, 50, 200), (120, 120, 60)]


def test_every_sub_path_of_a_composite_roi_imports(tmp_path):
    from PyReconstruct.modules.backend.imports.imagej_roi import Roi

    roi = Roi(_write_composite(tmp_path / "donut.roi", *DONUT))
    shapes = roi.get_field_shapes(400, 1.0)

    assert roi.closed is True
    assert len(shapes) == 2
    assert sorted(_area(s) for s in shapes) == pytest.approx([3600.0, 40000.0])


@pytest.mark.parametrize(
    "squares, expected",
    [
        (DONUT, [False, True]),
        ([(10, 10, 100), (300, 300, 40)], [False, False]),
        # an island inside the hole is filled again
        ([(0, 0, 300), (50, 50, 200), (120, 120, 60)], [False, True, False]),
    ],
)
def test_a_nested_outline_of_a_composite_roi_is_a_hole(tmp_path, squares, expected):
    from PyReconstruct.modules.backend.imports.imagej_roi import Roi, holes

    shapes = Roi(_write_composite(tmp_path / "c.roi", *squares)).get_field_shapes(400, 1.0)
    assert holes(shapes) == expected


OUTER = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]


@pytest.mark.parametrize(
    "outline, is_hole",
    [
        # a hole whose first vertex sits on the outer outline
        ([(200, 50), (150, 50), (150, 100), (200, 100)], True),   # right edge
        ([(50, 200), (50, 150), (100, 150), (100, 200)], True),   # top edge
        ([(200, 200), (150, 200), (150, 150), (200, 150)], True), # corner
        ([(0, 50), (50, 50), (50, 100), (0, 100)], True),         # left edge
        ([(0, 0), (50, 0), (50, 50), (0, 50)], True),             # (0, 0)
        # a separate outline whose first vertex touches the other one
        ([(0, 50), (-50, 50), (-50, 100), (0, 100)], False),      # left edge
        ([(50, 0), (50, -50), (100, -50), (100, 0)], False),      # bottom edge
        ([(0, 0), (-50, 0), (-50, -50), (0, -50)], False),        # (0, 0)
        ([(200, 50), (250, 50), (250, 100), (200, 100)], False),  # right edge
    ],
)
def test_an_outline_touching_another_is_judged_off_the_edge(outline, is_hole):
    from PyReconstruct.modules.backend.imports.imagej_roi import holes

    outline = [(float(x), float(y)) for x, y in outline]
    assert holes([OUTER, outline]) == [False, is_hole]


def test_a_spline_fit_triangle_is_fitted(tmp_path):
    roifile = pytest.importorskip("roifile")
    triangle = [(10.0, 10.0), (110.0, 10.0), (60.0, 110.0)]
    roi = _import(
        tmp_path, triangle, roifile.ROI_TYPE.POLYGON, roifile.ROI_OPTIONS.SPLINE_FIT
    )

    (shape,) = roi.get_field_shapes(200, 1.0)
    assert len(shape) >= 100
    for p in _field(triangle):
        assert min(np.hypot(*(np.array(shape) - p).T)) < 3.0


def test_a_point_roi_gives_one_shape_per_marker(tmp_path):
    roifile = pytest.importorskip("roifile")
    puncta = [(10.0, 10.0), (50.0, 20.0), (90.0, 80.0), (30.0, 70.0), (60.0, 50.0)]
    roi = _import(tmp_path, puncta, roifile.ROI_TYPE.POINT)

    assert roi.get_field_shapes(100, 1.0) == [[p] for p in _field(puncta, 100)]


# --- the menu action --------------------------------------------------------------

@pytest.fixture
def section_with_image(main_window, tmp_path, monkeypatch):
    """The current section, with a blank 400x400 image so it has a height."""
    import cv2

    monkeypatch.chdir(tmp_path)
    section = main_window.field.section
    fp = section.src_fp
    if not os.path.isabs(fp):
        fp = os.path.join(os.getcwd(), fp)
    if not os.path.exists(fp):
        cv2.imwrite(fp, np.zeros((400, 400), dtype=np.uint8))
    assert section.img_dims == (400, 400)
    return section


def _run_import(main_window, main_window_dialogs, fps):
    main_window_dialogs.file_responses.append([str(fp) for fp in fps])
    main_window.importROIFiles()


def test_imported_points_match_the_file_on_a_transformed_section(
    main_window, main_window_dialogs, section_with_image, tmp_path
):
    roifile = pytest.importorskip("roifile")
    from PyReconstruct.modules.datatypes import Transform

    section = section_with_image
    section.tform = Transform([1, 0, 1.0, 0, 1, 0.5])
    fp = _write_roi(tmp_path / "shifted.roi", SQUARE, roifile.ROI_TYPE.POLYGON)

    _run_import(main_window, main_window_dialogs, [fp])

    (trace,) = section.contours["shifted"].traces
    mag = section.mag
    expected = [(x * mag, (400 - y) * mag) for x, y in SQUARE]
    assert np.allclose(trace.points, expected, atol=1e-9)


def test_a_bad_file_is_reported_and_the_rest_import(
    main_window, main_window_dialogs, section_with_image, tmp_path, monkeypatch
):
    roifile = pytest.importorskip("roifile")
    from PyReconstruct.modules.backend.imports import imagej_roi

    first = _write_roi(tmp_path / "first.roi", SQUARE, roifile.ROI_TYPE.POLYGON)
    bad = _write_roi(tmp_path / "bad.roi", SQUARE, roifile.ROI_TYPE.POLYGON)
    last = _write_roi(tmp_path / "last.roi", SQUARE, roifile.ROI_TYPE.POLYGON)

    real = imagej_roi.Roi.get_field_shapes

    def get_field_shapes(self, *args):
        if self.roi_fp == bad:
            raise ValueError("Invalid inputs.")
        return real(self, *args)

    monkeypatch.setattr(imagej_roi.Roi, "get_field_shapes", get_field_shapes)

    _run_import(main_window, main_window_dialogs, [first, bad, last])

    contours = section_with_image.contours
    assert len(contours["first"].traces) == 1
    assert len(contours["last"].traces) == 1
    assert "bad" not in contours or contours["bad"].isEmpty()
    (notice,) = main_window_dialogs.notices
    assert "2 of 3" in notice
    assert "bad.roi" in notice


def test_each_marker_of_a_point_roi_becomes_a_stamp(
    main_window, main_window_dialogs, section_with_image, tmp_path
):
    roifile = pytest.importorskip("roifile")
    puncta = [(10.0, 10.0), (50.0, 20.0), (90.0, 80.0)]
    fp = _write_roi(tmp_path / "puncta.roi", puncta, roifile.ROI_TYPE.POINT)

    _run_import(main_window, main_window_dialogs, [fp])

    traces = section_with_image.contours["puncta"].traces
    assert len(traces) == 3
    mag = section_with_image.mag
    centers = sorted(tuple(np.mean(t.points, axis=0)) for t in traces)
    expected = sorted((x * mag, (400 - y) * mag) for x, y in puncta)
    stamp = np.mean(main_window.field.tracing_trace.points, axis=0)
    assert np.allclose(centers, np.array(expected) + stamp, atol=1e-9)
    assert all(t.closed for t in traces)


def test_a_composite_hole_imports_as_a_negative_trace(
    main_window, main_window_dialogs, section_with_image, tmp_path
):
    fp = _write_composite(tmp_path / "donut.roi", *DONUT)

    _run_import(main_window, main_window_dialogs, [fp])

    traces = section_with_image.contours["donut"].traces
    mag = section_with_image.mag
    areas = sorted(
        (t.negative, round(_area(t.points) / mag**2)) for t in traces
    )
    assert areas == [(False, 40000), (True, 3600)]


def test_a_file_that_makes_no_trace_is_reported(
    main_window, main_window_dialogs, section_with_image, tmp_path
):
    roifile = pytest.importorskip("roifile")
    good = _write_roi(tmp_path / "good.roi", SQUARE, roifile.ROI_TYPE.POLYGON)
    # every vertex the same: one point, too few for a trace
    dot = _write_roi(tmp_path / "dot.roi", [SQUARE[0]] * 3, roifile.ROI_TYPE.POLYGON)

    _run_import(main_window, main_window_dialogs, [good, dot])

    (notice,) = main_window_dialogs.notices
    assert "1 of 2" in notice
    assert "dot.roi" in notice
