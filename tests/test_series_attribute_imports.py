"""Attribute imports preserve local choices and keep curation provenance together."""

from copy import deepcopy
import shutil

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series


@pytest.fixture
def series_pair(shapes1_jser, tmp_path):
    incoming = tmp_path / "incoming.jser"
    shutil.copyfile(shapes1_jser, incoming)
    opened = []
    try:
        for path in (shapes1_jser, incoming):
            series = Series.openJser(str(path), progress=NullProgressReporter)
            opened.append(series)
            series.setSettingsStore(DictSettingsStore())
            series.setProgressReporter(NullProgressReporter)
        yield tuple(opened)
    finally:
        for series in reversed(opened):
            series.close()


def test_import_columns_unions_options_and_preserves_existing_object_choices(series_pair):
    current, incoming = series_pair
    current.addUserCol("stage", ["draft", "checked"], log_event=False)
    current.addUserCol("local", ["yes"], log_event=False)
    current.setUserColAttr("square", "stage", "checked")
    incoming.addUserCol("stage", ["draft", "reviewed"], log_event=False)
    incoming.addUserCol("batch", ["A", "B"], log_event=False)
    incoming.setUserColAttr("square", "stage", "reviewed")
    incoming.setUserColAttr("square", "batch", "A")
    incoming.setUserColAttr("star", "stage", "reviewed")
    incoming.setUserColAttr("missing", "batch", "B")
    source_attrs = deepcopy(incoming.obj_attrs)

    current.importUserCols(incoming)
    current.importUserCols(incoming)

    assert current.user_columns == {
        "stage": ["draft", "checked", "reviewed"],
        "local": ["yes"],
        "batch": ["A", "B"],
    }
    assert current.getAttr("square", "user_columns") == {
        "stage": "checked", "batch": "A",
    }
    assert current.getUserColAttr("star", "stage") == "reviewed"
    assert "missing" not in current.obj_attrs
    assert incoming.obj_attrs == source_attrs
    current.user_columns["batch"].append("C")
    current.setUserColAttr("star", "stage", "draft")
    assert incoming.user_columns["batch"] == ["A", "B"]
    assert incoming.getUserColAttr("star", "stage") == "reviewed"


@pytest.mark.parametrize("method", ["importObjAttrs", "importUserCols"])
@pytest.mark.parametrize(
    ("filters", "restricted", "expected"),
    [
        (["square"], [], {"square"}),
        (["s.*"], ["star", "triangle"], {"star"}),
        (["s"], [], set()),
    ],
)
def test_import_filters_select_whole_existing_names(
        series_pair, method, filters, restricted, expected):
    current, incoming = series_pair
    incoming.addUserCol("stage", ["reviewed"], log_event=False)
    for name in ("square", "star", "triangle", "square_extra"):
        incoming.setAttr(name, "comment", "incoming note")
        incoming.setUserColAttr(name, "stage", "reviewed")
    current.setAttr("triangle", "comment", "local note")

    getattr(current, method)(incoming, regex_filters=filters, restrict_to=restricted)

    if method == "importObjAttrs":
        assert {
            name for name, attrs in current.obj_attrs.items()
            if attrs.get("comment") == "incoming note"
        } == expected
        assert all("user_columns" not in attrs for attrs in current.obj_attrs.values())
    else:
        assert {
            name for name, attrs in current.obj_attrs.items()
            if attrs.get("user_columns") == {"stage": "reviewed"}
        } == expected
        assert current.user_columns == {"stage": ["reviewed"]}
    assert current.getAttr("triangle", "comment") == "local note"
    assert "square_extra" not in current.obj_attrs


def test_import_attributes_fills_missing_values_without_overwriting_local_values(series_pair):
    current, incoming = series_pair
    current.setAttr("square", "comment", "local note")
    current.setAttr("square", "locked", False)
    incoming.obj_attrs = {
        "square": {"comment": "incoming note", "locked": True, "last_user": "alice"},
        "star": {"comment": "new note", "user_columns": {"stage": "reviewed"}},
        "missing": {"comment": "no traces here"},
    }

    current.importObjAttrs(incoming)

    assert current.obj_attrs == {
        "square": {"comment": "local note", "locked": False, "last_user": "alice"},
        "star": {"comment": "new note"},
    }


@pytest.mark.parametrize("date", ["26-01-01", "26-02-01", "26-03-01"])
@pytest.mark.parametrize("local_by", [None, "local-reviewer"])
@pytest.mark.parametrize("incoming_by", [None, "incoming-reviewer"])
@pytest.mark.parametrize("assigner_first", [False, True])
def test_import_curation_keeps_the_assigner_of_the_winning_status(
        series_pair, date, local_by, incoming_by, assigner_first):
    current, incoming = series_pair
    current.setAttr("square", "curation", (True, "local-user", "26-02-01"))
    if local_by is not None:
        current.setAttr("square", "curation_by", local_by)
    attrs = {"curation": (False, "assignee", date)}
    if incoming_by is not None:
        attrs["curation_by"] = incoming_by
    if assigner_first:
        attrs = dict(reversed(list(attrs.items())))
    incoming.obj_attrs = {"square": attrs}
    source_attrs = deepcopy(incoming.obj_attrs)

    current.importObjAttrs(incoming)

    if date == "26-01-01":
        assert current.getAttr("square", "curation") == (True, "local-user", "26-02-01")
        assert current.getAttr("square", "curation_by") == local_by
    else:
        assert current.getAttr("square", "curation") == (False, "assignee", date)
        assert current.getAttr("square", "curation_by") == incoming_by
    assert incoming.obj_attrs == source_attrs


@pytest.mark.parametrize("incoming_by", [None, "incoming-reviewer"])
def test_first_imported_curation_replaces_a_stale_assigner(series_pair, incoming_by):
    current, incoming = series_pair
    current.setAttr("square", "curation_by", "previous-reviewer")
    incoming.setAttr("square", "curation", (False, "assignee", "26-03-01"))
    if incoming_by is not None:
        incoming.setAttr("square", "curation_by", incoming_by)

    current.importObjAttrs(incoming)

    assert current.getAttr("square", "curation") == (False, "assignee", "26-03-01")
    assert current.getAttr("square", "curation_by") == incoming_by
