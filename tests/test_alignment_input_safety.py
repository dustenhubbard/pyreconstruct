"""Reject unsafe alignment inputs before changing saved transforms."""

import shutil

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Trace, Transform
from tests.test_transform_import_errors import _write_swift, _write_tforms


def _saved_transforms(series):
    return {
        snum: {
            name: transform.getList()
            for name, transform in series.loadSection(snum).tforms.items()
        }
        for snum in series.sections
    }


@pytest.mark.gui
@pytest.mark.parametrize(
    "matrix",
    ["nan 0 0 0 1 0", "1 0 inf 0 1 0", "1 0 0 0 1 -inf",
     "0 0 0 0 0 0", "1 2 3 2 4 5", "1e-13 0 0 0 1 0"],
)
def test_text_import_rejects_invalid_matrix_before_saving(
    main_window, main_window_dialogs, tmp_path, matrix
):
    window = main_window
    before = _saved_transforms(window.series)
    current = window.series.alignment
    first, last = min(window.series.sections), max(window.series.sections)
    path = tmp_path / "invalid.txt"
    path.write_text(f"{first} 1 0 5 0 1 7\n{last} {matrix}\n")

    window.importTransforms(str(path))

    assert _saved_transforms(window.series) == before
    assert window.series.alignment == current
    assert main_window_dialogs.notices == [
        "No transforms were imported. Line 2 does not contain a finite, "
        "invertible transform."
    ]


@pytest.mark.gui
@pytest.mark.parametrize("kind", ["text", "swift"])
@pytest.mark.parametrize("different_folder", [False, True])
@pytest.mark.parametrize("replace", [False, True])
def test_reimport_requires_confirmation_to_replace_alignment(
    main_window, main_window_dialogs, tmp_path, kind, different_folder, replace
):
    window = main_window
    dialogs = main_window_dialogs

    def run_import(path):
        if kind == "text":
            window.importTransforms(str(path))
        else:
            dialogs.responses.append((["1", [("Includes cal grid", False)]], True))
            window.importSwiftTransforms(str(path))

    if kind == "text":
        path = _write_tforms(window.series, tmp_path / "transforms.txt")
    else:
        path = _write_swift(tmp_path / "transforms.json", len(window.series.sections))
    run_import(path)
    alignment = window.series.alignment
    names = set(window.series.alignments)
    imported = _saved_transforms(window.series)
    section = window.field.section
    section.tforms[alignment] = Transform([1, 0, 123, 0, 1, 456])
    section.save()
    edited = _saved_transforms(window.series)
    window.changeAlignment("default")
    dialogs.notices.clear()
    dialogs.confirm_accepted = replace
    if different_folder:
        other = tmp_path / "other"
        other.mkdir()
        path = shutil.copy(path, other)

    run_import(path)

    assert _saved_transforms(window.series) == (imported if replace else edited)
    assert set(window.series.alignments) == names
    assert window.series.alignment == (alignment if replace else "default")
    assert alignment in dialogs.notices[0]
    assert "replace" in dialogs.notices[0].lower()
    assert dialogs.notices[-1] == (
        "Transforms imported successfully." if replace else dialogs.notices[0]
    )


@pytest.mark.parametrize("kind", ["text", "swift"])
def test_backend_reimport_preserves_alignment_without_explicit_permission(
    series_jser, tmp_path, kind
):
    from PyReconstruct.modules.backend.func import importSwiftTransforms, importTransforms
    from PyReconstruct.modules.backend.func.import_transforms import AlignmentExistsError
    from PyReconstruct.modules.datatypes import Series

    series = Series.openJser(str(series_jser))
    try:
        if kind == "text":
            path = _write_tforms(series, tmp_path / "transforms.txt")
            importer = importTransforms
        else:
            path = _write_swift(tmp_path / "transforms.json", len(series.sections))
            importer = importSwiftTransforms
        importer(series, path)
        section = series.loadSection(min(series.sections))
        section.tforms[series.alignment] = Transform([1, 0, 123, 0, 1, 456])
        section.save()
        edited = _saved_transforms(series)

        with pytest.raises(AlignmentExistsError, match="already exists"):
            importer(series, path)

        assert _saved_transforms(series) == edited
    finally:
        series.close()


def _landmarks(centers):
    traces = []
    for x, y in centers:
        trace = Trace("landmark", (255, 0, 0))
        trace.points = [(x - .1, y - .1), (x + .1, y - .1),
                        (x + .1, y + .1), (x - .1, y + .1)]
        traces.append(trace)
    return traces


@pytest.mark.gui
@pytest.mark.parametrize(
    "source,target",
    [
        ([(0, 0), (1, 0), (2, 0)], [(0, 1), (1, 1), (2, 1)]),
        ([(0, 0), (1, 0), (2, 0)], [(0, 1), (1, 1), (0, 2)]),
        ([(0, 0), (1, 0), (0, 1)], [(0, 1), (1, 1), (2, 1)]),
        ([(0, 0)] * 3, [(1, 1)] * 3),
        ([(-1, -1), (-1, 1), (1, -1), (1, 1)],
         [(-1, 1), (-1, -1), (1, -1), (1, 1)]),
    ],
)
def test_affine_alignment_rejects_degenerate_landmarks(
    main_window, main_window_dialogs, monkeypatch, source, target
):
    from PyReconstruct.modules.gui.main import field_widget_4_data as fw

    field = main_window.field
    field.section.align_locked = False
    field.section.selected_traces = _landmarks(source)
    other = next(n for n in field.series.sections if n != field.section.n)
    field.b_section = field.series.loadSection(other)
    field.b_section.tforms[field.series.alignment] = Transform.identity()
    field.b_section.selected_traces = _landmarks(target)
    before = field.section.tform.getList()
    monkeypatch.setattr(fw, "notify", main_window_dialogs.notify)

    field.affineAlign()

    assert field.section.tform.getList() == before
    assert main_window_dialogs.notices == [
        "Cannot align these landmarks. Select at least three non-collinear "
        "trace centers on each section."
    ]


def test_affine_estimator_keeps_valid_landmarks():
    source = [(0, 0), (1, 0), (0, 1)]
    target = [(2, 3), (4, 3), (2, 6)]

    transform = Transform.estimateTform(source, target)

    np.testing.assert_allclose(transform.map(source), target, atol=1e-12)
    np.testing.assert_allclose(transform.map(target, inverted=True), source, atol=1e-12)
