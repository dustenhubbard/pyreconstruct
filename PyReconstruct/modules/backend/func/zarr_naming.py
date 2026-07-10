"""Naming/location helpers for the "convert images to scaled zarr" action.

Kept Qt-free so the default-path and suffix logic is unit-testable without a GUI.
The store name must end in ``zarr`` -- ``image_layer.ImageLayer.is_zarr_file`` is
``series.src_dir.endswith("zarr")`` -- so ``ensure_zarr_suffix`` enforces that
invariant regardless of what the user types or how the save dialog behaves.
"""
import os


def default_scaled_zarr_fp(src_dir: str, series_name: str) -> str:
    """Default save path for a newly converted scaled zarr.

    Places ``<series>.zarr`` as a **sibling** of the source image directory (one
    level up), so the zarr sits next to the images rather than inside them. When
    the source directory is empty/unknown, returns just the filename and lets the
    save dialog fall back to its last-used folder.
    """
    name = f"{series_name}.zarr"
    if src_dir:
        return os.path.join(os.path.dirname(os.path.normpath(src_dir)), name)
    return name


def ensure_zarr_suffix(fp: str) -> str:
    """Guarantee the store path ends in ``zarr`` (what ``is_zarr_file`` checks).

    A name already ending in ``zarr`` is left untouched -- so an override like
    ``proj.zarr`` or ``proj-zarr`` is respected -- and ``.zarr`` is appended
    otherwise (e.g. the user typed a bare ``proj``).
    """
    if not fp:
        return fp
    return fp if os.path.normpath(fp).endswith("zarr") else fp + ".zarr"
