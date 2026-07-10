"""Default naming/location for the "convert images to scaled zarr" action.

Two invariants:
  * the default store sits NEXT TO the source image directory (one level up),
    not inside it, and is named ``<series>.zarr`` (not the old ``_images.zarr``);
  * the final store name always ends in ``zarr`` -- ``ImageLayer.is_zarr_file`` is
    ``series.src_dir.endswith("zarr")``, so anything else would break detection.
"""
import os

from PyReconstruct.modules.backend.func.zarr_naming import (
    default_scaled_zarr_fp,
    ensure_zarr_suffix,
)


def test_default_is_sibling_of_src_dir_named_after_series():
    assert default_scaled_zarr_fp("/data/exp/images", "myseries") == \
        os.path.join("/data/exp", "myseries.zarr")


def test_default_is_next_to_not_within_src_dir():
    src = "/data/exp/images"
    out = default_scaled_zarr_fp(src, "s")
    assert os.path.dirname(out) == os.path.dirname(os.path.normpath(src))
    assert not out.startswith(os.path.normpath(src) + os.sep)  # NOT inside src


def test_default_normalizes_trailing_separator():
    assert default_scaled_zarr_fp("/data/exp/images/", "s") == \
        os.path.join("/data/exp", "s.zarr")


def test_default_falls_back_to_bare_name_without_src_dir():
    assert default_scaled_zarr_fp("", "s") == "s.zarr"
    assert default_scaled_zarr_fp(None, "s") == "s.zarr"


def test_default_uses_dot_zarr_not_underscore_images():
    out = default_scaled_zarr_fp("/a/b", "proj")
    assert out.endswith("proj.zarr")
    assert "_images" not in out


def test_ensure_suffix_leaves_zarr_names_untouched():
    assert ensure_zarr_suffix("/x/proj.zarr") == "/x/proj.zarr"
    assert ensure_zarr_suffix("/x/proj-zarr") == "/x/proj-zarr"   # already ends in "zarr"


def test_ensure_suffix_appends_when_missing():
    assert ensure_zarr_suffix("/x/proj") == "/x/proj.zarr"
    assert ensure_zarr_suffix("/x/output") == "/x/output.zarr"


def test_ensure_suffix_always_satisfies_is_zarr_detection():
    # ImageLayer.is_zarr_file == src_dir.endswith("zarr")
    for name in ("proj", "proj.zarr", "proj-zarr", "weird_name"):
        assert ensure_zarr_suffix(f"/x/{name}").endswith("zarr")


def test_ensure_suffix_empty_is_noop():
    assert ensure_zarr_suffix("") == ""
