"""Redoing one section of an action does to an emptied object what the
action did.

An import that empties an object keeps it, with its attributes and groups,
so later traces under the name pick them up. An object list delete drops
them. Undoing either on one section and redoing it there must do the same
again. These drive the real Undo and Redo menu actions.
"""
import pytest

from tests.test_host_links_by_identity import (
    H, _draw_on, _import_from_a_copy_without, _setup,
)
from tests.test_undo_object_followups import _object_list

pytestmark = pytest.mark.gui

COMMENT = "keep this comment"
GROUP = "hl_group"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _label(window):
    window.series.setAttr(H, "comment", COMMENT)
    window.series.object_groups.add(group=GROUP, obj=H)


def _labels(window):
    return (
        window.series.getAttr(H, "comment"),
        sorted(window.series.object_groups.getObjectGroups(H)),
    )


@pytest.mark.parametrize("undone", [["s1"], ["s1", "s3"]])
def test_redoing_sections_of_an_import_keeps_the_emptied_object_attributes(
        window, main_window_dialogs, monkeypatch, tmp_path, undone):
    """H is on s1 and s3. An import from a copy that deleted H empties both
    and keeps H's comment and group. Undoing the import on s1 alone (then on
    s3) and redoing it there keeps them too."""
    s1, s2, s3, _ = _setup(window)
    _draw_on(window, s3, H)
    _label(window)
    _import_from_a_copy_without(window, monkeypatch, tmp_path, H)
    assert H not in window.series.data["objects"]
    assert _labels(window) == (COMMENT, [GROUP])

    snums = {"s1": s1, "s3": s3}
    main_window_dialogs.linked_undo_responses = ["section"]
    for name in undone:
        window.changeSection(snums[name])
        window.undo_act.trigger()
        assert _labels(window) == (COMMENT, [GROUP])
    assert main_window_dialogs.linked_undo_responses == []
    for name in reversed(undone):
        window.changeSection(snums[name])
        window.redo_act.trigger()
    assert H not in window.series.data["objects"]
    assert _labels(window) == (COMMENT, [GROUP])

    window.saveAllData()
    assert window.series.obj_attrs[H]["comment"] == COMMENT


def test_redoing_one_section_of_an_object_list_delete_drops_the_attributes(
        window, main_window_dialogs, monkeypatch):
    """H deleted from the object list loses its comment and group. Undoing
    the delete on s1 alone brings them back, and redoing it drops them again."""
    s1, _, _, _ = _setup(window)
    _label(window)
    window.saveAllData()
    window.changeSection(s1)
    _object_list(window, monkeypatch, [H])
    window.field.deleteObjects()
    assert H not in window.series.data["objects"]
    assert _labels(window) == ("", [])

    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo_act.trigger()
    assert main_window_dialogs.linked_undo_responses == []
    assert H in window.series.data["objects"]
    assert _labels(window) == (COMMENT, [GROUP])
    window.redo_act.trigger()
    assert H not in window.series.data["objects"]
    assert _labels(window) == ("", [])
