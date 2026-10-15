"""Undoing an alignment rename puts back each object's and z-trace's alignment.

An object or z-trace can be set to its own alignment, and a rename of that
alignment carries the setting to the new name (`Series.remapStoredAlignments`).
The series undo state is saved when the section pass hands out its first
section, and the carry ran before that, so the undo state already held the new
name. Undo then left the object on the new name.

The rename here is the two calls `MainWindow.modifyAlignments` makes once the
dialog has been confirmed.
"""
import pytest

from PyReconstruct.modules.datatypes.ztrace import Ztrace

pytestmark = pytest.mark.gui


def _modify(window, alignment_dict):
    window.series.modifyAlignments(alignment_dict, window.field.series_states)
    window.createContextMenus()


def _add(window, name):
    alignment_dict = {a: a for a in window.series.alignments}
    alignment_dict[name] = window.series.alignment
    _modify(window, alignment_dict)


def _rename(window, old, new):
    alignment_dict = {a: a for a in window.series.alignments}
    alignment_dict[new] = old
    alignment_dict[old] = None
    _modify(window, alignment_dict)


def _stored(window, name, ztrace=False):
    return window.series.getAttr(name, "alignment", ztrace=ztrace)


@pytest.fixture
def renamed(main_window):
    """An object and a z-trace set to "extra", then "extra" renamed "extra2"."""
    window = main_window
    series = window.series
    _add(window, "extra")

    obj = sorted(series.data["objects"])[0]
    series.setAttr(obj, "alignment", "extra")
    snums = sorted(series.sections)[:2]
    series.ztraces["zt"] = Ztrace(
        "zt", [0, 255, 0], [(1.0, 1.0, snums[0]), (2.0, 2.0, snums[1])]
    )
    series.setAttr("zt", "alignment", "extra", ztrace=True)

    _rename(window, "extra", "extra2")
    return window, obj


def test_the_rename_carries_the_settings(renamed):
    window, obj = renamed

    assert _stored(window, obj) == "extra2"
    assert _stored(window, "zt", ztrace=True) == "extra2"


def test_the_undo_state_holds_the_old_settings(renamed):
    window, obj = renamed
    attrs = window.field.series_states.undos[-1].series_attrs

    assert attrs["obj_attrs"][obj]["alignment"] == "extra"
    assert attrs["ztrace_attrs"]["zt"]["alignment"] == "extra"


def test_undo_puts_the_old_settings_back(renamed):
    window, obj = renamed

    window.undo()

    assert _stored(window, obj) == "extra"
    assert _stored(window, "zt", ztrace=True) == "extra"


def test_redo_carries_them_again(renamed):
    window, obj = renamed
    window.undo()

    window.undo(True)

    assert _stored(window, obj) == "extra2"
    assert _stored(window, "zt", ztrace=True) == "extra2"
