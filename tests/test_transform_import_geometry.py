"""Transform imports preserve geometry through unit conversion and saved series."""

import json

import pytest

from PyReconstruct.modules.backend.func import importSwiftTransforms, importTransforms
from PyReconstruct.modules.backend.func.import_transforms import TransformImportError
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, Transform


@pytest.fixture
def sparse_series(tmp_path):
    images = [str(tmp_path / f"section-{n}.png") for n in range(6)]
    series = Series.new(images, "alignment", 0.25, 0.05)
    series.setProgressReporter(NullProgressReporter)
    try:
        series.deleteSections([0, 2, 3, 5], log_event=False)
        series.current_section = 1
        for snum, mag in [(1, 0.25), (4, 0.5)]:
            section = series.loadSection(snum)
            section.mag = mag
            section.tform = Transform([1, 0.2, 9, 0, 1, -7])
            section.save()
        series.save()
        yield series
    finally:
        series.close()


def _swift_project(legacy):
    # These legacy matrices are the explicit inverses of the modern matrices.
    matrices = (
        [[[0.4, -0.2, -2], [0.4, 0.8, 2]], [[1, -0.5, 5], [0, 0.5, -3]]]
        if legacy
        else [[[2, 0.5, 3], [-1, 1, -4]], [[1, 1, -2], [0, 2, 6]]]
    )
    if legacy:
        return {
            "data": {
                "scales": {
                    "scale_1": {"image_src_size": [200, 240]},
                    "scale_4": {
                        "image_src_size": [50, 60],
                        "stack": [
                            {
                                "alignment": {
                                    "method_results": {"cumulative_afm": matrix}
                                }
                            }
                            for matrix in matrices
                        ],
                    },
                }
            }
        }
    return {
        "level_data": {"s1": {}, "s4": {}},
        "stack": [
            {
                "levels": {
                    "s1": {"swim_settings": {"img_size": [200, 240]}},
                    "s4": {"swim_settings": {"img_size": [50, 60]}, "alt_cafm": matrix},
                }
            }
            for matrix in matrices
        ],
    }


def _snapshot(series):
    return {
        n: {
            name: tform.getList()
            for name, tform in series.loadSection(n).tforms.items()
        }
        for n in sorted(series.sections)
    }


@pytest.mark.parametrize("legacy", [False, True], ids=["modern", "legacy"])
def test_scaled_swift_import_converts_axes_units_and_stack_order(
    sparse_series, tmp_path, legacy
):
    series = sparse_series
    before = _snapshot(series)
    path = tmp_path / "scaled.json"
    path.write_text(json.dumps(_swift_project(legacy)))

    importSwiftTransforms(series, str(path), scale=4)

    alignment = series.alignment
    expected = {1: [2, -0.5, 28, 1, 1, 4], 4: [1, -1, 96, 0, 2, -112]}
    for snum, coefficients in expected.items():
        section = series.loadSection(snum)
        assert section.tform.getList() == pytest.approx(coefficients)
        for name, original in before[snum].items():
            assert section.tforms[name].getList() == original
    assert series.loadSection(1).tform.map(2, 3) == pytest.approx((30.5, 9))
    assert series.loadSection(4).tform.map(2, 3) == pytest.approx((95, -106))

    saved = tmp_path / "saved.jser"
    series.saveJser(str(saved))
    series.close()
    reopened = Series.openJser(str(saved))
    try:
        assert reopened.alignment == alignment
        for snum, coefficients in expected.items():
            assert reopened.loadSection(snum).tform.getList() == pytest.approx(
                coefficients
            )
    finally:
        reopened.close()


def test_partial_text_import_keeps_unlisted_section_geometry(sparse_series, tmp_path):
    series = sparse_series
    before = _snapshot(series)
    path = tmp_path / "partial.txt"
    path.write_text("1 2 0.5 12 -1 3 -8\n")

    importTransforms(series, str(path))

    assert series.loadSection(1).tform.getList() == [2, 0.5, 3, -1, 3, -2]
    assert series.loadSection(1).tform.map(2, 3) == (8.5, 5)
    assert series.loadSection(4).tform.getList() == [1, 0.2, 9, 0, 1, -7]
    for snum in before:
        for name, original in before[snum].items():
            assert series.loadSection(snum).tforms[name].getList() == original


@pytest.mark.parametrize(
    "bad_line, message",
    [
        ("4 1 0 invalid 0 1 0", "Line 2 is not a section number"),
        ("9 1 0 0 0 1 0", "Line 2 is for section 9"),
    ],
)
def test_bad_text_row_rejects_all_rows_without_mutating_series(
    sparse_series, tmp_path, bad_line, message
):
    series = sparse_series
    before = _snapshot(series)
    alignment = series.alignment
    path = tmp_path / "bad.txt"
    path.write_text(f"1 2 0.5 12 -1 3 -8\n{bad_line}\n")

    with pytest.raises(TransformImportError, match=message):
        importTransforms(series, str(path))

    assert series.alignment == alignment
    assert _snapshot(series) == before
