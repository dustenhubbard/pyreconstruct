"""`Alignments > Import alignments > From SWiFT project...`, cal grid and bad files.

With `Includes cal grid` checked, the identity transform went to the lowest
section number, whichever section was marked as the cal grid. It goes to the
marked section now. With no section marked (or several), the lowest section
still gets it, and the notice says so.

A file that was not JSON, or a project missing the chosen scale, raised out of
the menu action. Both are a `TransformImportError` notice now.
"""

import json
import shutil

import pytest

from conftest import SERIES_FIXTURE


def _write_swift(path, n, scales=("s1",), stack_scales=("s1",)):
    """A new-format SWiFT project whose i-th transform has a1 = 2 + i / 100."""
    stack = []
    for i in range(n):
        cafm = [[2 + i / 100, 0, 0], [0, 1, 0], [0, 0, 1]]
        levels = {
            s: {"swim_settings": {"img_size": [100, 100]}, "alt_cafm": cafm}
            for s in stack_scales
        }
        stack.append({"levels": levels})
    with open(path, "w") as f:
        json.dump({"level_data": {s: {} for s in scales}, "stack": stack}, f)
    return str(path)


def _a1_by_section(series, alignment):
    return {
        snum: round(section.tforms[alignment].getList()[0], 6)
        for snum, section in series.enumerateSections(show_progress=False)
    }


def _expected(nums, grid_num):
    """Identity (a1 = 1) on the grid section, the stack in order on the rest."""
    rest = [n for n in nums if n != grid_num]
    expected = {grid_num: 1.0}
    expected.update({snum: round(2 + i / 100, 6) for i, snum in enumerate(rest)})
    return expected


def _open_copy(tmp_path, marked):
    from PyReconstruct.modules.datatypes import Series

    dst = tmp_path / "series.jser"
    shutil.copy(SERIES_FIXTURE, dst)
    series = Series.openJser(str(dst))
    for snum in marked(sorted(series.sections)):
        section = series.loadSection(snum)
        section.calgrid = True
        section.save()
    series.saveJser()
    series.close()
    return Series.openJser(str(dst))


@pytest.mark.parametrize(
    "marked, grid_index, note",
    [
        (lambda nums: [nums[2]], 2, None),
        (lambda nums: [nums[0]], 0, None),
        (lambda nums: [], 0, "No section is marked"),
        (lambda nums: [nums[1], nums[3]], 0, "2 sections are marked"),
    ],
    ids=["middle-marked", "first-marked", "none-marked", "two-marked"],
)
def test_cal_grid_identity_goes_to_the_marked_section(
    tmp_path, marked, grid_index, note
):
    from PyReconstruct.modules.backend.func import importSwiftTransforms

    series = _open_copy(tmp_path, marked)
    try:
        nums = sorted(series.sections)
        result = importSwiftTransforms(
            series, _write_swift(tmp_path / "p.json", len(nums) - 1), cal_grid=True
        )

        grid_num = nums[grid_index]
        assert _a1_by_section(series, series.alignment) == _expected(nums, grid_num)
        if note is None:
            assert result is None
        else:
            assert result.startswith(note)
            assert result.endswith(
                f"so the identity transform went to section {grid_num}, "
                "the first section."
            )
    finally:
        series.close()


def test_without_cal_grid_a_marked_section_changes_nothing(tmp_path):
    from PyReconstruct.modules.backend.func import importSwiftTransforms

    series = _open_copy(tmp_path, lambda nums: [nums[2]])
    try:
        nums = sorted(series.sections)
        result = importSwiftTransforms(
            series, _write_swift(tmp_path / "p.json", len(nums))
        )

        assert result is None
        assert _a1_by_section(series, series.alignment) == {
            snum: round(2 + i / 100, 6) for i, snum in enumerate(nums)
        }
    finally:
        series.close()


def _import(window, dialogs, path, cal_grid=False, scale="1"):
    dialogs.responses.append(([scale, [("Includes cal grid", cal_grid)]], True))
    window.importSwiftTransforms(str(path))


@pytest.mark.gui
def test_notice_says_when_no_section_is_marked(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    nums = sorted(window.series.sections)

    _import(
        window, main_window_dialogs,
        _write_swift(tmp_path / "p.json", len(nums) - 1), cal_grid=True,
    )

    assert main_window_dialogs.notices == [
        "Transforms imported successfully. No section is marked as the cal "
        f"grid, so the identity transform went to section {nums[0]}, the "
        "first section."
    ]


@pytest.mark.gui
def test_marked_section_gets_the_identity_in_the_window(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    nums = sorted(window.series.sections)
    window.series.data["sections"][nums[2]]["calgrid"] = True

    _import(
        window, main_window_dialogs,
        _write_swift(tmp_path / "p.json", len(nums) - 1), cal_grid=True,
    )

    assert main_window_dialogs.notices == ["Transforms imported successfully."]
    assert _a1_by_section(window.series, window.series.alignment) == _expected(
        nums, nums[2]
    )


@pytest.mark.gui
@pytest.mark.parametrize(
    "content, message",
    [
        ("{not json", "The file is not a SWiFT project."),
        ("[1, 2, 3]", "The file is not a SWiFT project."),
        ("{}", "The file is not a SWiFT project PyReconstruct can read."),
        ('{"level_data": {"sx": {}}}',
         "The file is not a SWiFT project PyReconstruct can read."),
    ],
    ids=["malformed", "list", "empty-object", "bad-scale-name"],
)
def test_unreadable_project_is_a_notice(
    main_window, main_window_dialogs, tmp_path, content, message
):
    window = main_window
    before = set(window.series.alignments)
    path = tmp_path / "p.json"
    path.write_text(content)

    window.importSwiftTransforms(str(path))  # must not raise

    assert set(window.series.alignments) == before
    assert main_window_dialogs.notices == [f"No transforms were imported. {message}"]


@pytest.mark.gui
def test_missing_scale_is_a_notice(main_window, main_window_dialogs, tmp_path):
    window = main_window
    before = set(window.series.alignments)
    n = len(window.series.sections)
    path = _write_swift(
        tmp_path / "p.json", n, scales=("s1", "s4"), stack_scales=("s1",)
    )

    _import(window, main_window_dialogs, path, scale="4")  # must not raise

    assert set(window.series.alignments) == before
    assert main_window_dialogs.notices == [
        "No transforms were imported. The SWiFT project has no transforms at scale 4."
    ]


@pytest.mark.gui
def test_project_with_no_sections_is_a_notice(
    main_window, main_window_dialogs, tmp_path
):
    window = main_window
    before = set(window.series.alignments)
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"level_data": {"s1": {}}, "stack": [], "data": {"scales": {"scale_1": {"stack": [], "image_src_size": [100, 100]}}}}))

    _import(window, main_window_dialogs, path)

    assert set(window.series.alignments) == before
    assert main_window_dialogs.notices == [
        "No transforms were imported. The SWiFT project has no sections."
    ]
