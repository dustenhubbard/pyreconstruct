"""A new series never empties a hidden folder that is already there.

`Series.new` and `xmlToJSON` used to make the working folder with
`createHiddenDir`, which deletes every file in an existing `.<name>` before
making a new one. The folder it hit could be the working folder of the same
series open in another window (unsaved edits included), unsaved work left by
a session that did not close, or, when the images folder is not writable and
the series falls back to the home folder, any dot folder whose name matches
the series name.

In one window, `newSeries` and `newFromXML` close the outgoing series after
the new one is made, and that close deleted the folder the new series had
just been given, so the new series opened with no files at all.
"""

import os
import shutil
import stat
import time

import pytest

from PyReconstruct.modules.constants import createNewSeriesDir
from PyReconstruct.modules.datatypes import Series


MAG = 0.00254
THICKNESS = 0.05


def _snapshot(folder):
    """Every file under folder with its bytes, for an exact before/after."""
    out = {}
    for dirpath, _, files in os.walk(folder):
        for f in files:
            fp = os.path.join(dirpath, f)
            with open(fp, "rb") as fh:
                out[os.path.relpath(fp, folder)] = fh.read()
    return out


def _image(folder, name="img0.png"):
    fp = os.path.join(folder, name)
    open(fp, "wb").close()
    return fp


def test_createNewSeriesDir_skips_taken_names(tmp_path):
    (tmp_path / ".A").mkdir()
    (tmp_path / ".A" / "A.0").write_text("keep")
    (tmp_path / ".A-2").mkdir()

    made = createNewSeriesDir(str(tmp_path), "A")

    assert made == str(tmp_path / ".A-3")
    assert os.listdir(made) == []
    assert (tmp_path / ".A" / "A.0").read_text() == "keep"
    assert os.listdir(tmp_path / ".A-2") == []


def test_createNewSeriesDir_uses_plain_name_when_free(tmp_path):
    assert createNewSeriesDir(str(tmp_path), "A") == str(tmp_path / ".A")


def test_new_series_leaves_open_series_folder_alone(series_jser):
    """Same name, same folder as a series open in another window."""
    folder = os.path.dirname(series_jser)
    opened = Series.openJser(str(series_jser))
    try:
        hidden = opened.hidden_dir
        # what an open window keeps there: a heartbeat file and an edit
        open(os.path.join(hidden, str(round(time.time()))), "w").close()
        with open(opened.filepath, "a") as f:
            f.write(" ")
        before = _snapshot(hidden)

        new = Series.new([_image(folder)], opened.name, MAG, THICKNESS)

        assert _snapshot(hidden) == before
        assert not os.path.samefile(new.hidden_dir, hidden)
        assert new.name == opened.name
        assert os.path.isfile(new.filepath)
    finally:
        opened.close()


def test_closing_old_series_keeps_new_series_files(series_jser):
    """The order MainWindow.newSeries uses: Series.new, then the old close."""
    folder = os.path.dirname(series_jser)
    opened = Series.openJser(str(series_jser))

    new = Series.new([_image(folder)], opened.name, MAG, THICKNESS)
    opened.close()

    assert os.path.isfile(new.filepath)
    for fname in new.sections.values():
        assert os.path.isfile(os.path.join(new.hidden_dir, fname))
    new.close()
    assert not os.path.exists(new.hidden_dir)


@pytest.mark.skipif(os.name == "nt", reason="read-only folder via chmod")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root can write a read-only folder",
)
def test_home_fallback_leaves_dot_folder_alone(tmp_path, monkeypatch):
    """Images folder not writable, so the series goes to the home folder."""
    home = tmp_path / "home"
    dot = home / ".ssh"
    (dot / "sub").mkdir(parents=True)
    (dot / "id_key").write_text("secret")
    (dot / "sub" / "config").write_text("secret")
    before = _snapshot(dot)

    images = tmp_path / "images"
    images.mkdir()
    img = _image(str(images))
    images.chmod(stat.S_IRUSR | stat.S_IXUSR)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HOMEPATH", str(home))
    try:
        new = Series.new([img], "ssh", MAG, THICKNESS)
    finally:
        images.chmod(stat.S_IRWXU)

    assert _snapshot(dot) == before
    assert os.path.dirname(new.hidden_dir) == str(home)
    assert new.hidden_dir != str(dot)
    assert os.path.isfile(new.filepath)
    shutil.rmtree(new.hidden_dir)


@pytest.mark.gui
def test_new_series_named_like_open_series_opens(
    main_window, main_window_dialogs
):
    """New series in the open series' folder, under the same name."""
    window = main_window
    old_name = window.series.name
    folder = os.path.dirname(window.series.jser_fp)
    img = _image(folder)

    window.newSeries(
        image_locations=[img],
        series_name=old_name,
        mag=MAG,
        thickness=THICKNESS,
    )

    series = window.series
    assert series.name == old_name
    assert series.jser_fp in ("", None)  # the Save As was dismissed
    assert os.path.isfile(series.filepath)
    for fname in series.sections.values():
        assert os.path.isfile(os.path.join(series.hidden_dir, fname))


def _write_legacy_series(folder, name, section_numbers):
    """A minimal legacy XML series: the blank .ser and blank sections."""
    from PyReconstruct.modules.constants import blank_section, blank_series

    ser = (
        blank_series.replace("[SECTION_NUM]", str(section_numbers[0]))
        .replace("[SECTION_THICKNESS]", "0.05")
        .replace("[LAST3DSECTION]", str(section_numbers[0]))
        .replace("[LASTTHUMBSECTION]", str(section_numbers[0]))
    )
    with open(os.path.join(folder, f"{name}.ser"), "w") as f:
        f.write(ser)
    for n in section_numbers:
        sec = (
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
        with open(os.path.join(folder, f"{name}.{n}"), "w") as f:
            f.write(sec)


@pytest.mark.gui
def test_new_from_xml_twice_keeps_both_folders(
    tmp_path, main_window, main_window_dialogs, monkeypatch
):
    """`File ▸ New series ▸ From legacy .ser...` twice on the same folder."""
    window = main_window
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    _write_legacy_series(str(xml_dir), "S", [1, 2])
    # the user dismisses the Save As that follows each import
    monkeypatch.setattr(window, "saveAsToJser", lambda *a, **k: "cancel")

    window.newFromXML(str(xml_dir / "S.ser"))
    first = window.series
    first_dir = first.hidden_dir
    first.modified = True
    # stands in for the open series' unsaved state; saveAllData rewrites the
    # series files before the prompt, so their bytes are not a fixed baseline
    marker = os.path.join(first_dir, "unsaved_marker.txt")
    with open(marker, "w") as f:
        f.write("edit")

    # the second import asks about the first series; the user discards it
    main_window_dialogs.save_response = "no"
    marker_at_close = []
    real_close = first.close

    def close_and_record():
        marker_at_close.append(os.path.isfile(marker))
        real_close()

    monkeypatch.setattr(first, "close", close_and_record)
    window.newFromXML(str(xml_dir / "S.ser"))
    second = window.series

    assert second is not first
    # untouched until the user discarded it (openSeries closes it twice)
    assert marker_at_close[0] is True
    assert not os.path.samefile(xml_dir, second.hidden_dir)
    assert os.path.isfile(second.filepath)
    second.loadSection(1)
    second.modified = False
