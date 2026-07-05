"""Regression test for editObjectAttributes(sections=None).

The `sections` parameter is documented as "default: all", and is reached with
its default (None) through the object name-setter (Object.name). Before the
fix, the per-section guard `if snum not in sections` raised
`TypeError: argument of type 'NoneType' is not iterable` whenever sections was
left at its default, so editing an object without an explicit section list
crashed. With the fix, sections=None means "every section the object appears
on".
"""
import os
import shutil
import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def _pick_object(series):
    names = list(series.data["objects"].keys())
    assert names, "fixture had no objects"
    return names[0]


def test_sections_none_does_not_raise_and_edits_all(tmp_path):
    series = _load_series(tmp_path)
    obj = _pick_object(series)
    target_sections = series.getObjectSections([obj])
    assert target_sections, "chosen object appears on no sections"
    new_color = (1, 2, 3)

    # Before the fix this raised TypeError on the first iterated section.
    series.editObjectAttributes(
        [obj], color=new_color, sections=None, log_event=False
    )

    # sections=None means "all sections the object is on": every trace of the
    # object should now carry the new color.
    checked = 0
    for snum, section in series.enumerateSections(show_progress=False):
        if snum not in target_sections:
            continue
        if obj in section.contours:
            for trace in section.contours[obj].getTraces():
                assert tuple(trace.color) == new_color
                checked += 1
    assert checked, "no traces were verified"


def test_explicit_sections_only_edits_those(tmp_path):
    """An explicit subset still restricts the edit (guards against the fix
    accidentally turning every call into an all-sections edit)."""
    series = _load_series(tmp_path)
    obj = _pick_object(series)
    target_sections = sorted(series.getObjectSections([obj]))
    if len(target_sections) < 2:
        pytest.skip("object spans fewer than two sections")

    kept = target_sections[0]          # only edit the first section
    excluded = target_sections[1:]
    new_color = (4, 5, 6)

    series.editObjectAttributes(
        [obj], color=new_color, sections=[kept], log_event=False
    )

    for snum, section in series.enumerateSections(show_progress=False):
        if obj not in section.contours:
            continue
        for trace in section.contours[obj].getTraces():
            if snum == kept:
                assert tuple(trace.color) == new_color
            elif snum in excluded:
                assert tuple(trace.color) != new_color
