"""Zarr import reads the voxel size in the units the Zarr declares (fork #499).

Neuroglancer Zarrs store ``resolution`` (or ``voxel_size``) in nanometers.
PyReconstruct works in micrometers, so both the pixel size and the section
thickness have to be divided by 1000 unless ``units`` says micrometers. A
``true_mag`` written by PyReconstruct's own export still wins for XY.
"""

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg.conversions import (
    get_thickness,
    get_true_mag,
    zarrToNewSeries,
)


def _raw(attrs):
    arr = zarr.zeros((2, 32, 32), dtype=np.uint8)
    arr.attrs.update(attrs)
    return arr


@pytest.mark.parametrize(
    "attrs, mag, thickness",
    [
        # neuroglancer resolution in nm, no units
        ({"resolution": [50, 4, 4]}, 0.004, 0.05),
        # nm said out loud
        ({"resolution": [50, 4, 4], "units": ["nm", "nm", "nm"]}, 0.004, 0.05),
        # voxel_size only
        ({"voxel_size": [50, 8, 8]}, 0.008, 0.05),
        # micrometers declared, no conversion
        ({"voxel_size": [0.05, 0.008, 0.008], "units": "µm"}, 0.008, 0.05),
        ({"resolution": [0.05, 0.004, 0.004], "units": ["um", "um", "um"]}, 0.004, 0.05),
        (
            {"resolution": [0.05, 0.004, 0.004], "units": ["micrometer"] * 3},
            0.004,
            0.05,
        ),
        # PyReconstruct's own export: true_mag wins for XY
        (
            {"voxel_size": [50, 4, 4], "units": ["nm", "nm", "nm"], "true_mag": 0.00425},
            0.00425,
            0.05,
        ),
    ],
)
def test_voxel_size_read_in_declared_units(attrs, mag, thickness):
    raw = _raw(attrs)

    assert get_true_mag(raw) == pytest.approx(mag)
    assert get_thickness(raw) == pytest.approx(thickness)


def test_no_voxel_size_keeps_the_default_mag():
    assert get_true_mag(_raw({})) == pytest.approx(0.004)


@pytest.mark.parametrize(
    "attrs, mag",
    [
        ({"resolution": [50, 4, 4], "units": ["nm", "nm", "nm"]}, 0.004),
        ({"voxel_size": [50, 8, 8], "units": ["nm", "nm", "nm"]}, 0.008),
    ],
)
def test_new_series_from_nm_zarr_gets_micrometer_mag(tmp_path, attrs, mag):
    zarr_fp = tmp_path / "ng.zarr"
    root = zarr.open(str(zarr_fp), "w")
    root.create_dataset("raw", data=np.zeros((2, 32, 32), dtype=np.uint8))
    root["raw"].attrs.update(attrs)

    series = zarrToNewSeries(str(zarr_fp), [], "new")
    try:
        section = series.loadSection(0)
        assert section.mag == pytest.approx(mag)
        assert section.thickness == pytest.approx(0.05)
    finally:
        series.close()
