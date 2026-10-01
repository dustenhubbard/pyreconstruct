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


def _snapshot(d):
    return sorted(
        os.path.relpath(os.path.join(root, f), d)
        for root, dirs, files in os.walk(d)
        for f in files + dirs
    )


@pytest.mark.parametrize("name", [".", ".ser", "Alpha.SER.d"])
def test_a_folder_is_refused_and_nothing_is_deleted(
    qapp, settings_isolated, tmp_path, name
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "ser.ser")
    _write_section(d / "ser.1", 1)
    (d / ".ser").mkdir()
    (d / ".ser" / "ser.ser").write_text("{}")
    (d / "Alpha.SER.d").mkdir()
    before = _snapshot(d)

    with pytest.raises(ValueError):
        conv.xmlToJSON(str(d / name))
    assert _snapshot(d) == before


def _contents(d):
    """Every path under d with a checksum of each file's bytes."""
    import hashlib
    out = {}
    for root, dirs, files in os.walk(d):
        for name in dirs:
            out[os.path.relpath(os.path.join(root, name), d)] = "dir"
        for name in files:
            fp = os.path.join(root, name)
            with open(fp, "rb") as f:
                out[os.path.relpath(fp, d)] = hashlib.sha256(f.read()).hexdigest()
    return out


@pytest.mark.parametrize("name", [".ser", "..ser", ".SER", "..SER"])
def test_a_ser_file_whose_hidden_folder_leaves_the_xml_folder_is_refused(
    qapp, settings_isolated, tmp_path, name
):
    # ".ser" would put the hidden folder at the xml folder itself and "..ser"
    # at its parent, and creating the hidden folder empties it
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / name)
    _write_section(d / "ser.1", 1)
    for i in range(6):
        (tmp_path / f"keep{i}.txt").write_text(f"parent file {i}")
    (tmp_path / "keep.ser").write_text("not touched")
    before = _contents(tmp_path)

    with pytest.raises(ValueError):
        conv.xmlToJSON(str(d / name))
    assert _contents(tmp_path) == before


def test_an_uppercase_suffix_and_a_bare_relative_path_work(
    qapp, settings_isolated, tmp_path, monkeypatch
):
    _write_ser(tmp_path / "Alpha.SER")
    _write_section(tmp_path / "Alpha.1", 1)
    monkeypatch.chdir(tmp_path)

    series = conv.xmlToJSON("Alpha.SER")
    assert series.name == "Alpha"
    assert sorted(series.sections) == [1]
    # crash recovery looks for a lowercase .ser in the hidden folder
    assert "Alpha.ser" in os.listdir(tmp_path / ".Alpha")


SCRIPT = os.path.join(
    os.path.dirname(__file__), os.pardir, "dev", "scripts", "series-from-xml"
)


def _run_script(monkeypatch, *args):
    import runpy
    monkeypatch.setattr("sys.argv", ["series-from-xml", *map(str, args)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(SCRIPT, run_name="__main__")
        raise SystemExit(0)
    return exit_info.value.code


@pytest.mark.parametrize("by_folder", [False, True])
def test_dev_script_converts_the_series(
    qapp, settings_isolated, tmp_path, monkeypatch, by_folder
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)
    (d / ".Alpha.ser").mkdir()  # hidden folder that is not a series file
    out = tmp_path / "out.jser"

    code = _run_script(monkeypatch, d if by_folder else d / "Alpha.ser", out)
    assert code in (0, None)
    assert out.is_file()
    assert {"Alpha.ser", "Alpha.1"} <= set(os.listdir(d))


def test_dev_script_refuses_a_folder_with_two_series(
    qapp, settings_isolated, tmp_path, monkeypatch, capsys
):
    d = tmp_path / "xml"
    d.mkdir()
    for name in ("Alpha", "Beta"):
        _write_ser(d / f"{name}.ser")
        _write_section(d / f"{name}.1", 1)
    before = _snapshot(d)

    assert _run_script(monkeypatch, d, tmp_path / "out.jser") == 1
    assert "Found 2 .ser files" in capsys.readouterr().out
    assert _snapshot(d) == before
    assert not (tmp_path / "out.jser").exists()


def _case_insensitive(d):
    probe = d / "CaseProbe"
    probe.write_text("")
    try:
        return (d / "caseprobe").exists()
    finally:
        probe.unlink()


def test_section_files_match_in_any_case(qapp, settings_isolated, tmp_path):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "ALPHA.1", 1)
    _write_section(d / "Alpha.2", 2)

    series = conv.xmlToJSON(str(d / "Alpha.ser"))
    assert sorted(series.sections) == [1, 2]
    # the working files carry the series name, so Save As renames them
    assert sorted(os.listdir(series.getwdir())) == [
        "Alpha.1", "Alpha.2", "Alpha.ser", "existing_log.csv"
    ]


def test_a_lowercased_path_finds_the_sections(
    qapp, settings_isolated, tmp_path
):
    d = tmp_path / "xml"
    d.mkdir()
    if not _case_insensitive(d):
        pytest.skip("needs a case-insensitive disk")
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)

    series = conv.xmlToJSON(str(d / "alpha.ser"))
    assert sorted(series.sections) == [1]


def test_no_sections_is_refused_and_leaves_no_folder(
    qapp, settings_isolated, tmp_path
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Beta.1", 1)
    before = _contents(tmp_path)

    with pytest.raises(ValueError, match="No section files for Alpha.ser"):
        conv.xmlToJSON(str(d / "Alpha.ser"))
    assert _contents(tmp_path) == before


def test_new_from_xml_shows_a_refusal(monkeypatch):
    from PyReconstruct.modules.gui.main import main_window

    def refuse(fp):
        raise ValueError("No section files for Alpha.ser were found.")

    shown = []
    monkeypatch.setattr(main_window, "xmlToJSON", refuse)
    monkeypatch.setattr(main_window, "notify", shown.append)
    fake = types.SimpleNamespace(
        openSeries=lambda *a, **k: pytest.fail("opened a series")
    )
    main_window.MainWindow.newFromXML(fake, "/data/xml/Alpha.ser")
    assert shown == ["No section files for Alpha.ser were found."]


def test_dev_script_reports_a_refusal(
    qapp, settings_isolated, tmp_path, monkeypatch, capsys
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")

    assert _run_script(monkeypatch, d / "Alpha.ser", tmp_path / "out.jser") == 1
    assert "No section files for Alpha.ser" in capsys.readouterr().out
    assert sorted(os.listdir(d)) == ["Alpha.ser"]


def _write_reconcropper(path, *section_files, tag="ALIGNMENT_A"):
    import json
    coef = {"xcoef": [0, 1, 0, 0, 0, 0], "ycoef": [0, 0, 1, 0, 0, 0]}
    with open(path, "w") as f:
        json.dump({tag: {name: coef for name in section_files}}, f)


def _alignments(series, snum):
    import json
    with open(os.path.join(series.getwdir(), series.sections[snum])) as f:
        return set(json.load(f)["tforms"])


def test_each_series_uses_its_own_reconcropper_file(
    qapp, settings_isolated, tmp_path
):
    d = tmp_path / "xml"
    d.mkdir()
    for name, tag in (("Alpha", "ALIGNMENT_A"), ("Beta", "ALIGNMENT_B")):
        _write_ser(d / f"{name}.ser")
        _write_section(d / f"{name}.1", 1)
        _write_reconcropper(d / f"{name}.json", f"{name}.1", tag=tag)

    alpha = conv.xmlToJSON(str(d / "Alpha.ser"))
    beta = conv.xmlToJSON(str(d / "Beta.ser"))
    assert _alignments(alpha, 1) == {"default", "ALIGNMENT_A"}
    assert _alignments(beta, 1) == {"default", "ALIGNMENT_B"}


def test_another_series_reconcropper_file_is_not_used(
    qapp, settings_isolated, tmp_path
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)
    _write_ser(d / "Beta.ser")
    _write_reconcropper(d / "Beta.json", "Alpha.1", tag="ALIGNMENT_B")

    alpha = conv.xmlToJSON(str(d / "Alpha.ser"))
    assert _alignments(alpha, 1) == {"default"}


def test_the_only_json_is_used_and_an_unrelated_one_is_skipped(
    qapp, settings_isolated, tmp_path
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)
    _write_reconcropper(d / "cropped.json", "Alpha.1")

    assert _alignments(conv.xmlToJSON(str(d / "Alpha.ser")), 1) == {
        "default", "ALIGNMENT_A"
    }

    (d / "cropped.json").write_text("[1, 2, 3]")  # not reconcropper data
    assert _alignments(conv.xmlToJSON(str(d / "Alpha.ser")), 1) == {"default"}


def test_a_same_name_ser_in_another_case_keeps_its_sections(
    qapp, settings_isolated, tmp_path, monkeypatch
):
    # Alpha.ser and alpha.ser side by side need a case-sensitive disk, so on
    # a case-insensitive one alpha.ser is added to the listing and treated as
    # a different file.
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)
    _write_section(d / "alpha.2", 2)
    _write_reconcropper(d / "alpha.json", "Alpha.1", tag="ALIGNMENT_LOWER")
    if _case_insensitive(d):
        real_listdir, real_samefile = os.listdir, os.path.samefile
        monkeypatch.setattr(
            os, "listdir",
            lambda p: real_listdir(p) + (["alpha.ser"] if p == str(d) else []),
        )
        monkeypatch.setattr(
            os.path, "samefile",
            lambda a, b: os.path.basename(a) == os.path.basename(b)
            and real_samefile(a, b),
        )
    else:
        _write_ser(d / "alpha.ser")

    series = conv.xmlToJSON(str(d / "Alpha.ser"))
    assert sorted(series.sections) == [1]
    assert _alignments(series, 1) == {"default"}


def test_dev_script_does_not_replace_an_existing_jser(
    qapp, settings_isolated, tmp_path, monkeypatch, capsys
):
    d = tmp_path / "xml"
    d.mkdir()
    _write_ser(d / "Alpha.ser")
    _write_section(d / "Alpha.1", 1)
    (d / "Alpha.jser").write_text("my converted series")

    assert _run_script(monkeypatch, d) == 1
    assert "already exists" in capsys.readouterr().out
    assert (d / "Alpha.jser").read_text() == "my converted series"
