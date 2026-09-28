"""Redo brings back a recreated object's attributes and groups.

Undoing an object's last trace deletes the object, and deleting it clears its
attributes and group memberships. Section undo states hold only traces,
transforms and flags, so redo used to bring the trace back bare. A palette
button's groups and custom columns (fork #419), applied when the first trace
is drawn, were the visible case. Each undo step now keeps a copy of the
attributes and groups of the objects it touched, and redo puts them back on an
object it recreates.
"""
import pytest

from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "redo_attr_obj"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _square(series, offset=0.3):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _draw_from_palette(window, name, defaults, offset=0.3):
    field = window.field
    item = Trace(name, (0, 255, 0), True)
    item.obj_defaults = defaults
    field.setTracingTrace(item)
    # newTrace is a field_interaction: it saves its own undo step
    field.newTrace(_square(window.series, offset), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)


def test_redo_brings_back_palette_groups_and_columns(window):
    series = window.series
    series.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
    _draw_from_palette(window, NAME, {"groups": ["axons"], "user_columns": {"Reviewer": "KH"}})
    assert "axons" in series.object_groups.getObjectGroups(NAME)
    assert series.getAttr(NAME, "user_columns") == {"Reviewer": "KH"}

    window.undo()
    assert NAME not in series.data["objects"], "undo removes the new object"
    assert "axons" not in series.object_groups.getObjectGroups(NAME)

    window.undo(redo=True)
    assert NAME in series.data["objects"]
    assert "axons" in series.object_groups.getObjectGroups(NAME), (
        "redo must bring the object's groups back"
    )
    assert series.getAttr(NAME, "user_columns") == {"Reviewer": "KH"}, (
        "redo must bring the object's custom column values back"
    )


def test_redo_leaves_an_existing_objects_attributes_alone(window):
    """A redo that adds a trace to an object that still exists must not
    overwrite what that object carries now."""
    series = window.series
    series.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
    _draw_from_palette(window, NAME, {"user_columns": {"Reviewer": "KH"}}, offset=0.2)
    # a second trace of the same object, drawn as its own step
    _draw_from_palette(window, NAME, None, offset=0.6)

    window.undo()                     # removes only the second trace
    assert NAME in series.data["objects"]
    series.setAttr(NAME, "user_columns", {"Reviewer": "DH"})

    window.undo(redo=True)
    assert series.getAttr(NAME, "user_columns") == {"Reviewer": "DH"}


def test_plain_draw_undo_redo_is_unchanged(window):
    series = window.series
    _draw_from_palette(window, NAME, None)
    window.undo()
    window.undo(redo=True)
    assert NAME in series.data["objects"]
    assert not series.object_groups.getObjectGroups(NAME)


def test_redo_keeps_a_hidden_group_hidden(window):
    """The recreated object was the only member of a hidden group: undo
    removes the group but keeps its visibility, and redo must not show it."""
    series = window.series
    _draw_from_palette(window, NAME, {"groups": ["solo_group"]})
    series.groups_visibility["solo_group"] = False

    window.undo()
    assert "solo_group" not in series.object_groups.getGroupList()
    window.undo(redo=True)

    assert "solo_group" in series.object_groups.getObjectGroups(NAME)
    assert series.groups_visibility["solo_group"] is False, (
        "redo showed a group the user had hidden"
    )


def test_redo_lists_a_returned_group_in_the_groups_menu(window):
    """Redo can bring back a group no object holds any more. The Groups menu
    must list it again, which means rebuilding the menubar."""
    series = window.series
    other = NAME + "_b"
    _draw_from_palette(window, NAME, {"groups": ["shared"]}, offset=0.2)
    _draw_from_palette(window, other, {"groups": ["shared"]}, offset=0.6)

    window.undo()                       # takes back the second draw only
    assert other not in series.data["objects"]
    assert "shared" in series.object_groups.getGroupList()

    # Remove the last member the way the object list's "Remove from all
    # groups" does. It records a series step only, so the redo stays.
    series_states = window.field.series_states
    series_states.addState()
    series.object_groups.removeObject(NAME)
    del series.groups_visibility["shared"]
    window.createMenuBar()
    assert "shared" not in series.object_groups.getGroupList()
    assert not hasattr(window, "shared_viz_act")

    window.field.undoState(redo=True)
    assert "shared" in series.object_groups.getObjectGroups(other)
    assert hasattr(window, "shared_viz_act"), (
        "the returned group is missing from the Groups menu"
    )
