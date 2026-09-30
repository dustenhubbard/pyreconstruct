"""New from XML imports only the chosen series' files.

`xmlToJSON` used to get the folder and pick files by suffix: the last `.ser`
it listed and every file ending in a number. So a folder holding two series
swept the other series' sections in, and a series named `ser` could pick the
hidden `.ser` folder of an earlier conversion as its series file, which made
the hidden folder path the XML folder itself and deleted the originals.
"""
import os
import types

import pytest

from PyReconstruct.modules.backend.func import xml_json_conversions as conv
from PyReconstruct.modules.constants import blank_section, blank_series


@pytest.fixture
def settings_isolated():
    # getOption writes a default back when a key is missing, so the Series
    # built by xmlToJSON must never reach the real settings store.
    from PyReconstruct.modules.backend.settings_store import (
        DictSettingsStore, default_settings_store, set_default_settings_store,
    )
    original = default_settings_store()
    set_default_settings_store(DictSettingsStore())
    try:
        yield
    finally:
        set_default_settings_store(original)


def _write_ser(path):
    txt = (
        blank_series.replace("[SECTION_NUM]", "1")
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", "1")
        .replace("[LASTTHUMBSECTION]", "1")
    )
    with open(path, "w") as f:
        f.write(txt)


def _write_section(path, n):
    txt = (
        blank_section.replace("[SECTION_INDEX]", str(n))
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[TRANSFORM_DIM]", "3")
        .replace("[XCOEF]", "0 1 0 0 0 0")
        .replace("[YCOEF]", "0 0 1 0 0 0")
        .replace("[IMAGE_MAG]", "0.00254")
        .replace("[IMAGE_SOURCE]", "a.tif")
        .replace("[IMAGE_LENGTH]", "100")
        .replace("[IMAGE_HEIGHT]", "100")
    )
    with open(path, "w") as f:
        f.write(txt)


def test_two_series_in_one_folder(qapp, settings_isolated, tmp_path):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    for n in (1, 2):
        _write_section(d / f"Alpha.{n}", n)
    _write_ser(d / "Beta.ser")
    for n in (3, 4):
        _write_section(d / f"Beta.{n}", n)

    for chosen, snums in (("Alpha", [1, 2]), ("Beta", [3, 4])):
        series = conv.xmlToJSON(str(d / f"{chosen}.ser"))
        assert series.name == chosen
        assert sorted(series.sections) == snums
        assert sorted(os.listdir(series.getwdir())) == sorted(
            [f"{chosen}.ser", "existing_log.csv"] + [f"{chosen}.{n}" for n in snums]
        )


def test_series_named_ser_keeps_its_originals(qapp, settings_isolated, tmp_path):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "ser.ser")
    _write_section(d / "ser.1", 1)

    # The first conversion leaves the hidden folder `.ser` behind, as an open
    # or crashed session would. The second must not take it for the series.
    first = conv.xmlToJSON(str(d / "ser.ser"))
    assert os.path.isdir(d / ".ser")
    second = conv.xmlToJSON(str(d / "ser.ser"))

    assert first.name == second.name == "ser"
    assert sorted(second.sections) == [1]
    assert {"ser.ser", "ser.1"} <= set(os.listdir(d))


def test_files_that_only_look_like_sections_are_skipped(
    qapp, settings_isolated, tmp_path
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)
    _write_section(d / "Alphabet.2", 2)  # shares the prefix, not the name
    _write_section(d / "notes.3", 3)
    (d / "Alpha.4").mkdir()  # a folder, not a section file

    series = conv.xmlToJSON(str(d / "Alpha.ser"))
    assert sorted(series.sections) == [1]


def test_new_from_xml_passes_the_chosen_file(monkeypatch):
    from PyReconstruct.modules.gui.main import main_window

    seen = []
    monkeypatch.setattr(
        main_window, "xmlToJSON", lambda fp: seen.append(fp) or None
    )
    fake = types.SimpleNamespace()
    main_window.MainWindow.newFromXML(fake, "/data/xml/Alpha.ser")
    assert seen == ["/data/xml/Alpha.ser"]
