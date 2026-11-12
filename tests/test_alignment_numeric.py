"""Alignment geometry checked against known image shifts and landmark coordinates."""

import numpy as np
import pytest

from PyReconstruct.modules.calc import correlate
from PyReconstruct.modules.datatypes import Trace, Transform


def _image(shape):
    image = np.full(shape, 128, dtype=np.uint8)
    image[11:19, 18:27] = np.random.default_rng(31).integers(
        20, 240, size=(8, 9), dtype=np.uint8
    )
    return image


@pytest.mark.parametrize("shape", [(31, 47), (32, 64)])
@pytest.mark.parametrize(
    "shift, expected", [((5, -7), (7, -5)), ((-4, 9), (-9, 4)), ((0, 0), (0, 0))]
)
@pytest.mark.parametrize("rgb", [False, True])
def test_correlation_recovers_signed_xy_shift(shape, shift, expected, rgb):
    reference = _image(shape)
    moving = np.roll(reference, shift, axis=(0, 1))
    if rgb:
        reference = np.repeat(reference[:, :, None], 3, axis=2)
        moving = np.repeat(moving[:, :, None], 3, axis=2)
    reference_before = reference.copy()
    moving_before = moving.copy()

    assert correlate(moving, reference) == expected
    np.testing.assert_array_equal(reference, reference_before)
    np.testing.assert_array_equal(moving, moving_before)


@pytest.mark.gui
def test_correlation_applies_pixel_shift_in_field_coordinates_and_undoes(
    main_window, monkeypatch
):
    field = main_window.field
    field.changeSection(1)
    field.section.align_locked = False
    field.section.mag = 0.25
    field.section.tform = Transform([2, 0.5, 7, -0.25, 1, -3])
    field.saveState()
    reference = np.repeat(_image((32, 64))[:, :, None], 3, axis=2)
    moving = np.roll(reference, (-4, 6), axis=(0, 1))

    def _fake_array(array):
        def generate(pixmap_dim, window, get_crop_only=False, bc=True):
            return array

        return generate

    monkeypatch.setattr(
        field.b_section_layer, "generateImageArray", _fake_array(reference)
    )
    monkeypatch.setattr(field.section_layer, "generateImageArray", _fake_array(moving))
    field.scaling = 2

    field.corrAlign()

    assert field.section.tform.getList() == pytest.approx(
        [2, 0.5, 6.25, -0.25, 1, -3.5]
    )
    assert field.section.tform.map(2, 3) == pytest.approx((11.75, -1))
    field.undoState()
    assert field.section.tform.getList() == pytest.approx([2, 0.5, 7, -0.25, 1, -3])
    field.undoState(redo=True)
    assert field.section.tform.map(2, 3) == pytest.approx((11.75, -1))


def _select_landmarks(section, centers):
    section.selected_traces.clear()
    for x, y in centers:
        trace = Trace("landmark", (255, 0, 0), closed=True)
        trace.points = [
            (x - 0.1, y - 0.1),
            (x + 0.1, y - 0.1),
            (x + 0.1, y + 0.1),
            (x - 0.1, y + 0.1),
        ]
        section.addTrace(trace, log_event=False)
        section.selected_traces.append(trace)


@pytest.mark.gui
def test_affine_alignment_fits_raw_landmarks_to_transformed_reference(main_window):
    field = main_window.field
    field.changeSection(1)
    field.section.align_locked = False
    field.section.tform = Transform([0.8, 0.2, 90, -0.1, 1.3, -70])
    field.b_section.tform = Transform([2, 0.5, 7, -0.25, 1, -3])
    _select_landmarks(field.section, [(0, 0), (4, 0), (0, 3), (2, 1)])
    _select_landmarks(field.b_section, [(1, -2), (5, -2), (1, 4), (3, 0)])
    field.saveState()

    field.affineAlign()

    assert field.section.tform.getList() == pytest.approx([2, 1, 8, -0.25, 2, -5.25])
    assert field.section.tform.map(3, 2) == pytest.approx((16, -2))
    field.undoState()
    assert field.section.tform.getList() == pytest.approx(
        [0.8, 0.2, 90, -0.1, 1.3, -70]
    )
