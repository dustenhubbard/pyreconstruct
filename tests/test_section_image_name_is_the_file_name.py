"""A section's image name is its file name, however it was saved or typed.

Series exist whose saved names carry a folder: the class series in
dev/assets/checker stores Cropped Images/d03/000ZGBJY.tif, while the zarr made
for it holds 000ZGBJY.tif. So a section loads the file name alone. The image
source edits reloaded the section, so the image was found by the file name at
once, but they saved the typed folder and the section list showed it until the
series was opened again. Now the saved name, the list entry and the image
lookup agree.
"""
import os
import sys

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Section

pytestmark = pytest.mark.gui

CLASS_NAME = "Cropped Images/d03/000ZGBJY.tif"


def _write_zarr(tmp_path, name, scales):
    """A zarr holding one image, written by zarr under its own key rule."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for k in scales:
        group.require_group(f"scale_{k}").create_dataset(
            name, data=np.zeros((64 // k, 64 // k), dtype="u1"), chunks=(16, 16)
        )
    return fp


def _save_and_reload(series, src):
    """Save the first section with this image name and load it again."""
    snum = sorted(series.sections)[0]
    section = series.loadSection(snum)
    section.src = src
    section.save()
    return series.loadSection(snum)


def test_a_saved_folder_is_dropped_so_the_zarr_array_is_found(
    qapp, real_series, tmp_path
):
    fp = _write_zarr(tmp_path, "000ZGBJY.tif", (1, 2, 4))
    section = _save_and_reload(real_series, CLASS_NAME)

    assert section.src == "000ZGBJY.tif"
    real_series.src_dir = fp
    assert sorted(section.zarr_scales) == [1, 2, 4]


def test_the_class_series_names_its_images_with_a_folder():
    """The series the docstring of Section.imageName points to."""
    import json

    fp = os.path.join(
        os.path.dirname(__file__), os.pardir,
        "dev", "assets", "checker", "files", "class_series.jser",
    )
    if not os.path.exists(fp):  # pragma: no cover - repo layout guard
        pytest.skip("class_series.jser not found")
    with open(fp) as f:
        data = json.load(f)
    # an older .jser: one key per section file, each holding its "src"
    names = [s["src"] for s in data.values() if "src" in s]
    assert CLASS_NAME in names
    assert all(name.startswith("Cropped Images/d03/") for name in names)


@pytest.mark.parametrize("saved, loaded", [
    ("/data/images/b.png", "b.png"),
    ("../images/b.png", "b.png"),
    ("a/b.png", "b.png"),
    ("b.png", "b.png"),
    ("", ""),
])
def test_a_saved_name_loads_as_its_file_name(qapp, real_series, saved, loaded):
    assert _save_and_reload(real_series, saved).src == loaded


@pytest.mark.skipif(sys.platform == "win32", reason="a backslash splits on Windows")
def test_a_backslash_name_is_one_file_name_on_macos_and_linux():
    assert Section.imageName("a\\b.png") == "a\\b.png"


@pytest.fixture
def table(main_window, monkeypatch):
    from PyReconstruct.modules.gui.table.section import SectionTableWidget

    series = main_window.series
    # the fixture ships every section locked, and the edits refuse locked ones
    for snum in list(series.sections):
        s = series.loadSection(snum)
        s.align_locked = False
        s.save()
    main_window.field.reload()
    return SectionTableWidget(series, main_window, main_window.field.table_manager)


def _answer(monkeypatch, text):
    from PyReconstruct.modules.gui.table import section as section_mod

    monkeypatch.setattr(
        section_mod.QInputDialog, "getText",
        staticmethod(lambda *a, **k: (text, True)),
    )


@pytest.mark.parametrize("typed", [CLASS_NAME, "/data/images/000ZGBJY.tif"])
def test_edit_image_source_keeps_the_name_the_section_loads(
    main_window, table, monkeypatch, typed
):
    series = main_window.series
    snum = series.current_section
    monkeypatch.setattr(table, "getSelected", lambda single=False: snum)
    _answer(monkeypatch, typed)

    table.editSrc()

    assert series.data["sections"][snum]["src"] == "000ZGBJY.tif"
    assert main_window.field.section.src == "000ZGBJY.tif"
    assert series.loadSection(snum).src == "000ZGBJY.tif"


def test_edit_all_image_sources_keeps_the_names_the_sections_load(
    main_window, table, monkeypatch
):
    series = main_window.series
    _answer(monkeypatch, "Cropped Images/d03/#ZGBJY.tif")

    table.modifyAllSrc()

    for snum in series.sections:
        shown = series.data["sections"][snum]["src"]
        assert shown.endswith("ZGBJY.tif") and "/" not in shown
        assert series.loadSection(snum).src == shown
