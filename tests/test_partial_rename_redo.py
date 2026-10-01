"""Redo of a partial rename brings back the new object's attributes.

Renaming an object on only some of its sections copies its attributes and
groups to the new object. Undo deletes the new object when it restores the
sections, and that clears what the rename copied. `SeriesStates.undoState`
captured the series attributes for the redo only after that, so the redo
brought the new object back with no attributes, no groups and no hosts. The
capture now happens before any section is restored.
"""
import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from tests.test_data_integrity_invariants import rich_series  # noqa: F401  (fixture)

pytestmark = pytest.mark.gui


def _attrs(series, name):
    """The new object's attributes, without the provenance a log writes."""
    attrs = dict(series.obj_attrs.get(name, {}))
    attrs.pop("last_user", None)
    return attrs


def _state(series, name):
    return (
        _attrs(series, name),
        sorted(series.object_groups.getObjectGroups(name)),
        series.host_tree.getDict(),
    )


def test_redo_of_partial_rename_keeps_new_object_attrs(rich_series):  # noqa: F811
    series = rich_series
    first = sorted(series.getObjectSections(["star"]))[0]
    states = SeriesStates(series)

    series.editObjectAttributes(
        ["star"], name="new", sections=[first], series_states=states
    )
    series.data.refresh()
    assert "star" in series.data["objects"] and "new" in series.data["objects"]
    after = _state(series, "new")
    assert after[0].get("comment") == "keep me"
    assert after[1] == ["shapes"]

    states.undoState()
    series.data.refresh()
    assert "new" not in series.data["objects"]

    states.undoState(redo=True)
    series.data.refresh()
    assert "new" in series.data["objects"]
    assert _state(series, "new") == after
