"""XML overwrite warnings distinguish aliases, stale sections and other series."""

from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.func.xml_json_conversions import xmlExportFiles


def test_xml_export_counts_aliases_once_and_reports_unwritten_sections(tmp_path):
    series = SimpleNamespace(name="Sample", sections={1: "Sample.1", 3: "Sample.3"})
    originals = {
        "Sample.ser": "existing series",
        "Sample.1": "existing section",
        "SAMPLE.3": "another section with a different case",
        "Sample.9": "a section outside this export",
        "Other.9": "another series",
        "Sample.9.bak": "a backup",
    }
    for name, text in originals.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    if (tmp_path / "SAMPLE.1").exists():
        pytest.skip("requires a case-sensitive filesystem")
    (tmp_path / "SAMPLE.1").hardlink_to(tmp_path / "Sample.1")

    assert xmlExportFiles(series, str(tmp_path)) == (
        ["Sample.ser", "Sample.1"], ["SAMPLE.3", "Sample.9"],
    )
    assert {
        name: (tmp_path / name).read_text(encoding="utf-8") for name in originals
    } == originals


def test_xml_export_to_a_new_directory_has_no_overwrite_warning(tmp_path):
    series = SimpleNamespace(name="Sample", sections={1: "Sample.1"})
    output = tmp_path / "new"

    assert xmlExportFiles(series, str(output)) == ([], [])
    assert not output.exists()

    output.mkdir()
    (output / "Sample.1").write_text("existing section", encoding="utf-8")
    assert xmlExportFiles(series, str(output)) == (["Sample.1"], [])
    assert (output / "Sample.1").read_text(encoding="utf-8") == "existing section"
