"""File > Export series > To legacy Reconstruct (XML)... names its files after
the file the user chose, and asks before it replaces anything.

The export used to pass only the folder to `jsonToXML`, which named the .ser
and every section file after `series.name`. Choosing `<name>_export.ser` in a
folder that already held `<name>.ser` wrote nothing under the chosen name and
replaced the existing files with no prompt.
"""
import os

import pytest

from PyReconstruct.modules.backend.func import xmlExportFiles

pytestmark = pytest.mark.gui


def _section_numbers(series):
    return sorted(series.sections)


def test_export_writes_under_the_chosen_name(main_window, main_window_dialogs, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    name = main_window.series.name
    first = _section_numbers(main_window.series)[0]
    (out / f"{name}.ser").write_text("ORIGINAL SERIES")
    (out / f"{name}.{first}").write_text("ORIGINAL SECTION")

    chosen = out / f"{name}_export.ser"
    main_window.exportToXML(str(chosen))

    assert chosen.exists()
    for n in _section_numbers(main_window.series):
        assert (out / f"{name}_export.{n}").exists()
    # the files under the series name were not part of this export
    assert (out / f"{name}.ser").read_text() == "ORIGINAL SERIES"
    assert (out / f"{name}.{first}").read_text() == "ORIGINAL SECTION"
    # nothing collided, so the only message is the notice naming the file
    assert len(main_window_dialogs.notices) == 1
    assert str(chosen) in main_window_dialogs.notices[0]


def test_declining_the_prompt_leaves_existing_files(main_window, main_window_dialogs, tmp_path):
    name = main_window.series.name
    first = _section_numbers(main_window.series)[0]
    ser = tmp_path / f"{name}.ser"
    sec = tmp_path / f"{name}.{first}"
    ser.write_text("ORIGINAL SERIES")
    sec.write_text("ORIGINAL SECTION")
    before = sorted(os.listdir(tmp_path))

    main_window_dialogs.confirm_accepted = False
    assert main_window.exportToXML(str(ser)) is False

    prompt = main_window_dialogs.notices[0]
    assert f"{name}.ser" in prompt and f"{name}.{first}" in prompt
    assert ser.read_text() == "ORIGINAL SERIES"
    assert sec.read_text() == "ORIGINAL SECTION"
    assert sorted(os.listdir(tmp_path)) == before


def test_accepting_the_prompt_replaces_the_files(main_window, main_window_dialogs, tmp_path):
    name = main_window.series.name
    first = _section_numbers(main_window.series)[0]
    ser = tmp_path / f"{name}.ser"
    sec = tmp_path / f"{name}.{first}"
    ser.write_text("ORIGINAL SERIES")
    sec.write_text("ORIGINAL SECTION")

    main_window_dialogs.confirm_accepted = True
    main_window.exportToXML(str(ser))

    assert len(main_window_dialogs.notices) == 2  # the prompt, then the notice
    assert ser.read_text() != "ORIGINAL SERIES"
    assert sec.read_text() != "ORIGINAL SECTION"


def test_old_section_files_under_the_name_are_named_in_the_prompt(
    main_window, main_window_dialogs, tmp_path
):
    name = main_window.series.name
    stale = tmp_path / f"{name}_export.9999"
    stale.write_text("STALE")

    main_window_dialogs.confirm_accepted = False
    assert main_window.exportToXML(str(tmp_path / f"{name}_export.ser")) is False

    assert stale.name in main_window_dialogs.notices[0]
    assert not (tmp_path / f"{name}_export.ser").exists()


def test_xml_export_files_splits_replaced_and_extra(main_window, tmp_path):
    series = main_window.series
    first = _section_numbers(series)[0]
    (tmp_path / "chosen.ser").write_text("")
    (tmp_path / f"chosen.{first}").write_text("")
    (tmp_path / "chosen.9999").write_text("")
    (tmp_path / "other.9999").write_text("")
    (tmp_path / "chosen.9999.bak").write_text("")

    replaced, extra = xmlExportFiles(series, str(tmp_path), "chosen")

    assert replaced == ["chosen.ser", f"chosen.{first}"]
    assert extra == ["chosen.9999"]
