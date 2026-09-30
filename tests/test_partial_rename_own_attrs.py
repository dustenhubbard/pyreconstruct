"""A rename on only some sections gives the new object its own attributes.

Renaming B to A on a subset of B's sections leaves B in place. `renameObjAttrs`
copied B's attribute values into A by reference, so A and B shared one
`user_columns` dict: setting a column on A changed it on B too, and the next
save wrote the wrong value for B.
"""

import os
import shutil

import pytest

pytestmark = pytest.mark.gui

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)


def _load(fp):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    data = SeriesData(series)
    data.refresh()
    series.data = data
    return series


def test_rename_copies_mutable_attrs(real_series):
    real_series.obj_attrs["old"] = {
        "comment": "note",
        "user_columns": {"status": "good"},
        "curation": [True, "someone", "2026-09-30"],
    }
    real_series.renameObjAttrs("old", "new")

    old = real_series.obj_attrs["old"]
    new = real_series.obj_attrs["new"]
    assert new == old
    assert new["user_columns"] is not old["user_columns"]
    assert new["curation"] is not old["curation"]

    real_series.setUserColAttr("new", "status", "bad")
    assert real_series.getUserColAttr("old", "status") == "good"
    assert real_series.getUserColAttr("new", "status") == "bad"


def test_partial_rename_keeps_columns_apart_after_save(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    series = _load(fp)

    old = next(
        n for n in series.data["objects"]
        if len(series.getObjectSections([n])) >= 2
    )
    first = sorted(series.getObjectSections([old]))[0]
    new = "renamed_part"
    assert new not in series.data["objects"]

    series.setUserColAttr(old, "status", "good")
    series.setAttr(old, "comment", "kept")
    series.editObjectAttributes(
        [old], name=new, sections=[first], log_event=False
    )
    series.data.refresh()
    assert old in series.data["objects"] and new in series.data["objects"]

    series.setUserColAttr(new, "status", "bad")
    series.setAttr(new, "comment", "changed")
    assert series.getUserColAttr(old, "status") == "good"

    series.save()
    series.saveJser()
    series.close()

    reopened = _load(fp)
    try:
        assert reopened.getUserColAttr(old, "status") == "good"
        assert reopened.getUserColAttr(new, "status") == "bad"
        assert reopened.getAttr(old, "comment") == "kept"
        assert reopened.getAttr(new, "comment") == "changed"
    finally:
        reopened.close()
