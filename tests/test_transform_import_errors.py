"""`Alignments > Import alignments`, `From .txt file...` and `From SWiFT project...`.

The .txt importer stopped at the first line that was not seven numbers and only
printed to the console, and `MainWindow.importTransforms` then showed
`Transforms imported successfully.` anyway. A blank line counted as a bad line,
so a file ending in an extra newline never imported. Blank lines are now
skipped, and a bad line stops the import with a notice that names it.

The SWiFT importer numbered its transforms 0, 1, 2 and so on and required each
number to be a section, so a series numbered from 1 always failed, with an
`IncorrectSecNumError` that escaped the menu action. Transforms now go to the
sections in order, and a count mismatch is a notice.
"""

import json
import shutil

import pytest

from conftest import SERIES_FIXTURE


def _write_tforms(series, path, header="", trailer=""):
    with open(path, "w") as f:
        f.write(header)
        for snum in sorted(series.sections):
            f.write(f"{snum} 1 0 5 0 1 7\n")
        f.write(trailer)
    return str(path)


def _write_swift(path, n):
    """A SWiFT project (new format) whose i-th transform has a1 = 1 + i / 100."""
    stack = []
    for i in range(n):
        cafm = [[1 + i / 100, 0, 0], [0, 1, 0], [0, 0, 1]]
        level = {"swim_settings": {"img_size": [100, 100]}, "alt_cafm": cafm}
        stack.append({"levels": {"s1": level}})
    with open(path, "w") as f:
        json.dump({"level_data": {"s1": {}}, "stack": stack}, f)
    return str(path)


def _a1_by_section(series, alignment):
    return {
        snum: round(section.tforms[alignment].getList()[0], 6)
        for snum, section in series.enumerateSections(show_progress=False)
    }


@pytest.mark.gui
@pytest.mark.parametrize("trailer", ["\n", "\n\n", "   \n"])
def test_txt_with_trailing_blank_lines_imports(
    main_window, main_window_dialogs, tmp_path, trailer
):
    window = main_window
    before = set(window.series.alignments)

    window.importTransforms(
        _write_tforms(window.series, tmp_path / "tforms.txt", trailer=trailer)
    )

    new = set(window.series.alignments) - before
    assert len(new) == 1
    assert window.series.alignment in new
    assert main_window_dialogs.notices == ["Transforms imported successfully."]


@pytest.mark.gui
def test_txt_with_a_header_line_says_which_line(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    before = set(window.series.alignments)
    current = window.series.alignment

    window.importTransforms(
        _write_tforms(
            window.series, tmp_path / "tforms.txt", header="section a b c d e f\n"
        )
    )

    assert set(window.series.alignments) == before
    assert window.series.alignment == current
    assert main_window_dialogs.notices == [
        "No transforms were imported. Line 1 is not a section number followed "
        "by six transform numbers."
    ]


@pytest.mark.gui
def test_txt_with_an_unknown_section_says_which_line(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    before = set(window.series.alignments)
    missing = max(window.series.sections) + 1

    window.importTransforms(
        _write_tforms(
            window.series,
            tmp_path / "tforms.txt",
            trailer=f"{missing} 1 0 0 0 1 0\n",
        )
    )

    line = len(window.series.sections) + 1
    assert set(window.series.alignments) == before
    assert main_window_dialogs.notices == [
        f"No transforms were imported. Line {line} is for section {missing}, "
        "which is not in this series."
    ]


@pytest.mark.gui
@pytest.mark.parametrize("content", ["", "\n\n   \n"], ids=["empty", "blank-lines"])
def test_txt_with_no_transforms_is_a_notice(
    main_window, main_window_dialogs, tmp_path, content
):
    window = main_window
    before = set(window.series.alignments)
    current = window.series.alignment
    path = tmp_path / "tforms.txt"
    path.write_text(content)

    window.importTransforms(str(path))

    assert set(window.series.alignments) == before
    assert window.series.alignment == current
    assert main_window_dialogs.notices == [
        "No transforms were imported. The file has no transforms."
    ]


@pytest.mark.gui
def test_swift_count_mismatch_is_a_notice(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    before = set(window.series.alignments)
    n = len(window.series.sections)
    main_window_dialogs.responses.append(
        (["1", [("Includes cal grid", False)]], True)
    )

    window.importSwiftTransforms(_write_swift(tmp_path / "p.json", n - 1))  # must not raise

    assert set(window.series.alignments) == before
    assert main_window_dialogs.notices == [
        f"No transforms were imported. The SWiFT project has {n - 1} sections, "
        f"and this series has {n}."
    ]


@pytest.mark.gui
def test_swift_count_mismatch_with_cal_grid_is_a_notice(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    before = set(window.series.alignments)
    n = len(window.series.sections)
    main_window_dialogs.responses.append(
        (["1", [("Includes cal grid", True)]], True)
    )

    window.importSwiftTransforms(_write_swift(tmp_path / "p.json", n))

    assert set(window.series.alignments) == before
    assert main_window_dialogs.notices == [
        f"No transforms were imported. The SWiFT project has {n} sections, "
        f"so with the cal grid this series needs {n + 1}, and it has {n}."
    ]


def _open_copy(tmp_path, drop_section_zero):
    from PyReconstruct.modules.datatypes import Series

    dst = tmp_path / "series.jser"
    shutil.copy(SERIES_FIXTURE, dst)
    if drop_section_zero:
        series = Series.openJser(str(dst))
        series.deleteSections([0])
        series.saveJser()
        series.close()
    return Series.openJser(str(dst))


@pytest.mark.parametrize("drop_section_zero", [False, True])
def test_swift_transforms_go_to_sections_in_order(tmp_path, drop_section_zero):
    """Numbered from 0 (as before) and from 1 (used to raise)."""
    from PyReconstruct.modules.backend.func import importSwiftTransforms

    series = _open_copy(tmp_path, drop_section_zero)
    try:
        nums = sorted(series.sections)
        assert (nums[0] == 1) is drop_section_zero

        importSwiftTransforms(series, _write_swift(tmp_path / "p.json", len(nums)))

        a1 = _a1_by_section(series, series.alignment)
        assert a1 == {snum: round(1 + i / 100, 6) for i, snum in enumerate(nums)}
    finally:
        series.close()
