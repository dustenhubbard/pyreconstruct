"""Regression test for getImgDims on a missing/unreadable image.

cv2.imread returns None (no exception) for a missing or unreadable image, so
getImgDims did None.shape -> AttributeError: 'NoneType' has no attribute
'shape', a cryptic failure far from the cause (a stale/moved src_dir).
Raise a clear, catchable error instead.
"""
import types

import pytest

from PyReconstruct.modules.calc import image as image_mod


def test_missing_image_raises_clear_error(monkeypatch):
    monkeypatch.setattr(image_mod.cv2, "imread", lambda *a, **k: None)

    with pytest.raises(FileNotFoundError):
        image_mod.getImgDims("/no/such/image.png")


def test_valid_image_returns_shape(monkeypatch):
    monkeypatch.setattr(
        image_mod.cv2, "imread", lambda *a, **k: types.SimpleNamespace(shape=(10, 20))
    )

    assert image_mod.getImgDims("/some/image.png") == (10, 20)
