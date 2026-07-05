"""Regression test for get_zarr_array returning (not raising) on failure.

When no array is found, get_zarr_array did ``return ValueError(...)`` instead
of ``raise``. Callers then used the returned object as an array
(labels_array.attrs[...]), producing a confusing AttributeError far from the
real cause. It should raise so the failure surfaces where it happens.
"""
import zarr
import pytest

from PyReconstruct.modules.backend.autoseg import conversions as conv


def test_raises_when_no_array_found():
    # neither "raw" nor "raw/s0" is a zarr Array -> the not-found branch
    g = {"raw": object(), "raw/s0": object()}

    with pytest.raises(ValueError):
        conv.get_zarr_array(g, "raw")


def test_returns_array_when_present():
    arr = zarr.array([[1, 2], [3, 4]])
    g = {"raw": arr}

    assert conv.get_zarr_array(g, "raw") is arr
