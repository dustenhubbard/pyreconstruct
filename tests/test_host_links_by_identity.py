"""Host links belong to objects, not names.

H hosts T; H is only on the first section and T only on the second. A
"replacement" is a new object drawn (or renamed) to the name H after the old H
was deleted. A link joins object ids, so deleting H leaves the link dormant,
an undo that brings H back shows it again, and the replacement never takes
it. When an undo brings the old H back while the replacement still exists,
the name H shows the links of both.

These drive a real main window, since undo runs through its saveState and
undoState.
"""
import pytest

from tests.test_undo_object_followups import _delete, _draw, _object_list, _traces

pytestmark = pytest.mark.gui

H = "hl_host"
T = "hl_traveler"
SPARE = "hl_spare"
X = "hl_renamed"
D = "hl_dangling"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _sections(window):
    return sorted(window.series.sections)[:4]


def _setup(window):
    """H on s1 hosts T on s2."""
    s1, s2, s3, s4 = _sections(window)
    window.changeSection(s1)
    _draw(window, H)
    window.changeSection(s2)
    _draw(window, T)
    window.series.host_tree.add(T, [H])
    assert _hosts(window) == [H]
    return s1, s2, s3, s4


def _hosts(window, name=T):
    return sorted(window.series.host_tree.getHosts(name))


def _delete_on(window, snum, name):
    window.changeSection(snum)
    _delete(window, _traces(window, name))
    assert snum not in getattr(window.series.data["objects"].get(name), "traces", {})


def _draw_on(window, snum, name):
    window.changeSection(snum)
    _draw(window, name, offset=0.5)


def _undo_on(window, snum, redo=False):
    window.changeSection(snum)
    window.undo(redo=redo)


def _delete_both_and_replace(window, host_first=False):
    s1, s2, s3, s4 = _setup(window)
    order = [(s2, T), (s1, H)]
    if host_first:
        order.reverse()
    for snum, name in order:
        _delete_on(window, snum, name)
    _draw_on(window, s3, H)
    assert _hosts(window) == []
    return s1, s2, s3, s4


def _rename_everywhere(window, old, new):
    window.saveAllData()
    window.series.editObjectAttributes(
        [old], name=new, series_states=window.field.series_states
    )
    window.field.reload()


# --------------------------------------------------------------------------- #
# orders that lost or misplaced the link
# --------------------------------------------------------------------------- #

def test_undone_replacement_draw_keeps_the_old_link(window):
    """F1"""
    s1, s2, s3, _ = _delete_both_and_replace(window)
    _undo_on(window, s3)
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]


def test_undone_rename_to_old_name_keeps_the_old_link(window, main_window_dialogs):
    """F2: the replacement is another object renamed to H from the list."""
    s1, s2, s3, s4 = _setup(window)
    _draw_on(window, s4, SPARE)
    _delete_on(window, s2, T)
    _delete_on(window, s1, H)
    _rename_everywhere(window, SPARE, H)
    assert H in window.series.data["objects"]
    assert _hosts(window) == []

    main_window_dialogs.linked_undo_responses = ["all"]
    _undo_on(window, s4)
    assert H not in window.series.data["objects"]
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]


@pytest.mark.parametrize("list_first", [True, False])
def test_object_list_delete_keeps_the_link(
        window, monkeypatch, main_window_dialogs, list_first):
    """F3: H deleted from the object list, T's trace deleted on the field,
    in either order; undo with `Only this section`, then undo T."""
    s1, s2, _, _ = _setup(window)

    def list_delete():
        window.changeSection(s1)
        _object_list(window, monkeypatch, [H])
        window.field.deleteObjects()

    if list_first:
        list_delete()
        _delete_on(window, s2, T)
    else:
        _delete_on(window, s2, T)
        list_delete()
    assert H not in window.series.data["objects"]

    main_window_dialogs.linked_undo_responses = ["section"]
    _undo_on(window, s1)
    assert H in window.series.data["objects"]
    _undo_on(window, s2)
    assert _hosts(window) == [H]


def test_traveler_undo_does_not_link_the_replacement(window):
    """F4"""
    s1, s2, s3, _ = _delete_both_and_replace(window)
    _undo_on(window, s2)
    assert T in window.series.data["objects"]
    assert _hosts(window) == []
    _undo_on(window, s3)
    _undo_on(window, s1)
    assert _hosts(window) == [H]


def test_series_undo_of_rename_keeps_the_link(window, main_window_dialogs):
    """F5: both old objects back beside the replacement, then H renamed on
    every section and the rename undone."""
    s1, s2, s3, _ = _delete_both_and_replace(window, host_first=True)
    _undo_on(window, s2)
    _undo_on(window, s1)
    # the old H is back while the replacement is still on s3: the name shows
    # the old H's link
    assert _hosts(window) == [H]

    _rename_everywhere(window, H, X)
    assert H not in window.series.data["objects"]
    assert _hosts(window) == [X]

    main_window_dialogs.linked_undo_responses = ["all"]
    _undo_on(window, s1)
    assert _hosts(window) == [H]
    _undo_on(window, s3)
    assert _hosts(window) == [H]


@pytest.mark.parametrize("remove", ["undo", "delete"])
def test_removing_the_replacement_shows_the_old_link(window, remove):
    """F6"""
    s1, s2, s3, _ = _delete_both_and_replace(window, host_first=True)
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]
    if remove == "undo":
        _undo_on(window, s3)
    else:
        _delete_on(window, s3, H)
    assert _hosts(window) == [H]


def test_editing_an_old_trace_keeps_its_identity(window):
    """F7: an old H trace is moved after its delete is undone."""
    s1, s2, s3, _ = _delete_both_and_replace(window, host_first=True)
    _undo_on(window, s1)
    window.field.section.selected_traces = _traces(window, H)
    window.field.translate(1.0, 1.0)
    _undo_on(window, s3)
    _undo_on(window, s2)
    assert _hosts(window) == [H]


# --------------------------------------------------------------------------- #
# orders that already worked
# --------------------------------------------------------------------------- #

def test_split_replacement_undo_does_not_link_it(window):
    """G1: the replacement is on s3 and s4; it is deleted on both, then
    s3's delete and draw are undone, and s4's delete."""
    s1, s2, s3, s4 = _delete_both_and_replace(window)
    _draw_on(window, s4, H)
    _delete_on(window, s3, H)
    _delete_on(window, s4, H)
    _undo_on(window, s3)
    _undo_on(window, s3)
    _undo_on(window, s4)
    assert H in window.series.data["objects"]
    _undo_on(window, s2)
    assert _hosts(window) == []


@pytest.mark.parametrize("remove", ["redo", "delete"])
def test_redone_old_delete_unlinks_the_replacement(window, remove):
    """G2"""
    s1, s2, s3, _ = _delete_both_and_replace(window, host_first=True)
    _undo_on(window, s3)
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]
    _undo_on(window, s3, redo=True)
    assert _hosts(window) == [H]
    if remove == "redo":
        _undo_on(window, s1, redo=True)
    else:
        _delete_on(window, s1, H)
    assert H in window.series.data["objects"]
    assert _hosts(window) == []


def test_user_link_survives_undo_and_redo(window):
    """G3: with the old H back beside the replacement, the user sets H as
    T's host again, then H's old traces are deleted, undone and redone."""
    s1, s2, s3, _ = _setup(window)
    _delete_on(window, s1, H)
    _draw_on(window, s3, H)
    _undo_on(window, s1)
    window.series.setObjHosts([T], [H])
    _delete_on(window, s1, H)
    assert _hosts(window) == [H]
    _undo_on(window, s1)
    assert _hosts(window) == [H]
    _undo_on(window, s1, redo=True)
    assert _hosts(window) == [H]


def test_replacement_on_two_sections_then_undo_all(window):
    """G4"""
    s1, s2, s3, s4 = _delete_both_and_replace(window)
    _draw_on(window, s4, H)
    _undo_on(window, s4)
    _undo_on(window, s3)
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]


# --------------------------------------------------------------------------- #
# an object whose section was deleted keeps its links through undo
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "step", ["delete", "rename, undo all sections", "rename, undo this section"]
)
def test_undo_brings_back_the_links_of_a_kept_object(
        window, main_window_dialogs, gui_dialogs, tmp_path, step):
    """Old H back beside a replacement H; old H's only section is deleted,
    so it keeps its link to T without traces. Deleting the replacement, or
    renaming H from the object list, and undoing that, on every section or
    on the replacement's section alone, brings the link back and saves it."""
    from tests.test_object_ids_field import _section_list, _select, _unlock_sections

    s1, s2, s3, _ = _delete_both_and_replace(window, host_first=False)
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]

    _unlock_sections(window)
    window.changeSection(s3)
    widget = _section_list(window)
    _select(widget, s1)
    widget.deleteSections()
    assert s1 not in window.series.sections
    assert _hosts(window) == [H]
    # the delete cleared the undo history; leave s3 so it starts again there
    window.changeSection(s2)

    if step == "delete":
        _delete_on(window, s3, H)
        assert _hosts(window) == []
        _undo_on(window, s3)
    else:
        _rename_everywhere(window, H, X)
        assert _hosts(window) == [X]
        main_window_dialogs.linked_undo_responses = [
            "all" if step.endswith("all sections") else "section"
        ]
        _undo_on(window, s3)
    assert H in window.series.data["objects"]
    assert _hosts(window) == [H]
    assert _saved_host_tree(window, tmp_path / "kept.jser").get(T) == [H]


@pytest.mark.parametrize("scope", ["all", "section"])
def test_undoing_a_rename_to_a_linked_name_with_no_traces_keeps_its_link(
        window, main_window_dialogs, tmp_path, scope):
    """T is hosted by D, a name no section has traces of (a file can link
    one). Renaming an unrelated H to D from the object list gives D traces.
    Undoing the rename, on every section or on H's section alone, leaves T
    hosted by D as before, and saves it."""
    s1, s2, _, _ = _sections(window)
    window.changeSection(s1)
    _draw(window, H)
    window.changeSection(s2)
    _draw(window, T)
    window.series.host_tree.add(T, [D])
    assert D not in window.series.data["objects"]
    assert _hosts(window) == [D]

    _rename_everywhere(window, H, D)
    assert D in window.series.data["objects"]
    assert H not in window.series.data["objects"]
    assert _hosts(window) == [D]

    main_window_dialogs.linked_undo_responses = [scope]
    _undo_on(window, s1)
    assert H in window.series.data["objects"]
    assert D not in window.series.data["objects"]
    assert _hosts(window) == [D]
    assert _saved_host_tree(window, tmp_path / "dangling.jser").get(T) == [D]


def test_undo_on_one_section_keeps_a_link_an_import_kept_on_another(window):
    """Old H back beside a replacement H on s3; the replacement is moved;
    an import empties old H on s1 and keeps its link; V is drawn on s1, so
    the import cannot be undone whole. Undoing the move on s3 leaves old
    H's link alone."""
    from PyReconstruct.modules.datatypes.section import Section

    series = window.series
    s1, s2, s3, _ = _delete_both_and_replace(window, host_first=False)
    _undo_on(window, s2)
    _undo_on(window, s1)
    assert _hosts(window) == [H]

    window.changeSection(s3)
    window.field.section.selected_traces = _traces(window, H)
    window.field.translate(1.0, 1.0)

    def empty_on_s1(section, other, *args, **kwargs):
        if section.n == s1 and H in section.contours:
            for trace in list(section.contours[H]):
                section.removeTrace(trace)
            del section.contours[H]
        section.save()

    window.saveAllData()
    original = Section.importTraces
    Section.importTraces = empty_on_s1
    try:
        series.importTraces(
            series, import_obj_attrs=False, series_states=window.field.series_states
        )
    finally:
        Section.importTraces = original
    window.field.reload()
    assert s1 not in series.data["objects"][H].traces
    assert _hosts(window) == [H]

    _draw_on(window, s1, SPARE)
    _undo_on(window, s3)
    assert _hosts(window) == [H]


def _import_from_a_copy_without(window, monkeypatch, tmp_path, name, snum=None):
    """Series > Import series data > From another series, from a copy of
    this series that deleted the object (or only its traces on snum):
    traces on all sections, history checked, object attributes not
    imported."""
    from PyReconstruct.modules.datatypes import Series
    import PyReconstruct.modules.gui.main.main_window as mw

    window.saveAllData()
    path = tmp_path / "copy.jser"
    window.series.saveJser(str(path))
    copy = Series.openJser(str(path))
    try:
        if snum is None:
            copy.deleteObjects([name])
        else:
            section = copy.loadSection(snum)
            for trace in list(section.contours[name]):
                section.removeTrace(trace)
            section.save()
        copy.saveJser(str(path))
    finally:
        copy.close()
    monkeypatch.setattr(mw.FileDialog, "get", lambda *a, **k: str(path))
    monkeypatch.setattr(mw.ImportSeriesDialog, "exec", lambda self: (
        {"traces": [None, [], [], 0.95, True, True, False, "self", ""]}, True,
    ))
    window.importfromseries_act.trigger()


@pytest.mark.parametrize("undone", [["s1"], ["s1", "s3"]])
def test_redoing_sections_of_an_import_alone_keeps_the_link_it_kept(
        window, main_window_dialogs, monkeypatch, tmp_path, undone):
    """H is on s1 and s3. An import from a copy that deleted H empties both
    and keeps the link, though H still had traces on s3 when the import
    passed s1. Undoing the import on s1 alone (then on s3), and redoing it
    there in the other order, keeps the link and saves it."""
    s1, s2, s3, _ = _setup(window)
    _draw_on(window, s3, H)
    _import_from_a_copy_without(window, monkeypatch, tmp_path, H)
    assert H not in window.series.data["objects"]
    assert _hosts(window) == [H]

    snums = {"s1": s1, "s3": s3}
    main_window_dialogs.linked_undo_responses = ["section"]
    for name in undone:
        window.changeSection(snums[name])
        window.undo_act.trigger()
        assert _hosts(window) == [H]
    for name in reversed(undone):
        window.changeSection(snums[name])
        window.redo_act.trigger()
    assert H not in window.series.data["objects"]
    assert _hosts(window) == [H]
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [H]}


@pytest.mark.parametrize("again", [False, True])
def test_redoing_a_later_step_keeps_a_link_a_rename_undo_brought_back(
        window, main_window_dialogs, monkeypatch, tmp_path, again):
    """Old H is back beside a replacement H on s3, and an import from a
    copy without old H's traces on s1 keeps old H with none. H is renamed
    to X, T is added to a group, and the group is undone. Undoing the
    rename on s3 alone brings H back, old H kept with it (again: after
    redoing it there and redoing and undoing the group). Redoing the group
    leaves T hosted by H, and saves it."""
    import PyReconstruct.modules.gui.main.field_widget_3_object as obj

    s1, s2, s3, _ = _delete_both_and_replace(window)
    _undo_on(window, s2)
    _undo_on(window, s1)
    _import_from_a_copy_without(window, monkeypatch, tmp_path, H, snum=s1)
    assert set(window.series.data["objects"][H].traces) == {s3}
    assert window.series.host_tree.keptIds(H)
    _rename_everywhere(window, H, X)
    assert _hosts(window) == [X]
    _object_list(window, monkeypatch, [T])
    monkeypatch.setattr(obj.ObjectGroupDialog, "exec", lambda self: ("g", True))
    window.field.addToGroup()

    _undo_on(window, s1)
    assert window.series.object_groups.getObjectGroups(T) == set()
    main_window_dialogs.linked_undo_responses = ["section"]
    _undo_on(window, s3)
    assert _hosts(window) == [H]
    if again:
        _undo_on(window, s3, redo=True)
        _undo_on(window, s1, redo=True)
        assert window.series.object_groups.getObjectGroups(T) == {"g"}
        _undo_on(window, s1)
        _undo_on(window, s3)
        assert _hosts(window) == [H]

    _undo_on(window, s1, redo=True)
    assert window.series.object_groups.getObjectGroups(T) == {"g"}
    assert _hosts(window) == [H]
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [H]}


def test_undoing_a_later_step_keeps_out_a_link_a_section_redo_let_go(
        window, main_window_dialogs, monkeypatch, tmp_path):
    """Old H is kept with no traces beside a replacement H on s3. H is
    renamed to X from the object list and T is added to a group. Undo on
    s3 takes back the group, and again, on that section only, the rename.
    Redo on s2 puts the group back and redo on s3 the rename, which lets
    old H go. Undoing the group then changes only the group: T stays
    hosted by X alone."""
    import PyReconstruct.modules.gui.main.field_widget_3_object as obj
    from PyReconstruct.modules.datatypes import Trace

    s1, s2, s3, _ = _delete_both_and_replace(window)
    _undo_on(window, s2)
    _undo_on(window, s1)
    _import_from_a_copy_without(window, monkeypatch, tmp_path, H, snum=s1)
    assert window.series.host_tree.keptIds(H)
    _object_list(window, monkeypatch, [H])
    monkeypatch.setattr(obj.TraceDialog, "exec", lambda self: (
        (Trace(X, (0, 255, 0), True), None), True,
    ))
    window.field.editAttributes()
    _object_list(window, monkeypatch, [T])
    monkeypatch.setattr(obj.ObjectGroupDialog, "exec", lambda self: ("g", True))
    window.field.addToGroup()

    for snum, redo, scope in [
        (s3, False, "all"),
        (s3, False, "section"),
        (s2, True, "all"),
        (s3, True, "all"),
    ]:
        window.changeSection(snum)
        main_window_dialogs.linked_undo_responses = [scope]
        action = window.redo_act if redo else window.undo_act
        assert action.isEnabled()
        action.trigger()
    assert window.series.object_groups.getObjectGroups(T) == {"g"}
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [X]}

    window.changeSection(s2)
    assert window.undo_act.isEnabled()
    window.undo_act.trigger()
    assert window.series.object_groups.getObjectGroups(T) == set()
    assert _hosts(window) == [X]
    assert _saved_host_tree(window, tmp_path / "undone.jser") == {T: [X]}



@pytest.mark.parametrize("old_host_back", [False, True])
def test_redoing_a_rename_on_one_section_makes_its_links_again(
        window, main_window_dialogs, monkeypatch, tmp_path, old_host_back):
    """H hosts T. H is renamed to X from the object list and T is added to
    a group (old_host_back: after a replacement H, the old H kept with no
    traces, as in the import tests above). Undo takes back the group and
    the rename. Redo on X's section only brings X back hosting T, and redo
    of the group then changes only the group."""
    import PyReconstruct.modules.gui.main.field_widget_3_object as obj
    from PyReconstruct.modules.datatypes import Trace

    if old_host_back:
        s1, s2, s3, _ = _delete_both_and_replace(window)
        _undo_on(window, s2)
        _undo_on(window, s1)
        _import_from_a_copy_without(window, monkeypatch, tmp_path, H, snum=s1)
        x_section = s3
    else:
        s1, s2, _, _ = _setup(window)
        x_section = s1
    _object_list(window, monkeypatch, [H])
    monkeypatch.setattr(obj.TraceDialog, "exec", lambda self: (
        (Trace(X, (0, 255, 0), True), None), True,
    ))
    window.field.editAttributes()
    _object_list(window, monkeypatch, [T])
    monkeypatch.setattr(obj.ObjectGroupDialog, "exec", lambda self: ("g", True))
    window.field.addToGroup()
    assert _saved_host_tree(window, tmp_path / "renamed.jser") == {T: [X]}

    for snum, redo, scope in [
        (s2, False, "all"),
        (s2, False, "all"),
        (x_section, True, "section"),
    ]:
        window.changeSection(snum)
        main_window_dialogs.linked_undo_responses = [scope]
        action = window.redo_act if redo else window.undo_act
        assert action.isEnabled()
        action.trigger()
    assert window.series.object_groups.getObjectGroups(T) == set()
    assert _hosts(window) == [X]
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [X]}

    assert window.redo_act.isEnabled()
    window.redo_act.trigger()
    assert window.series.object_groups.getObjectGroups(T) == {"g"}
    assert _saved_host_tree(window, tmp_path / "grouped.jser") == {T: [X]}


@pytest.mark.parametrize("undo_scope", ["all", "section"])
def test_redoing_an_import_on_one_section_makes_its_links_again(
        window, main_window_dialogs, monkeypatch, tmp_path, undo_scope):
    """H on s1 and T on s2, not linked. A copy moves T and makes H its
    host. Series > Import series data > From another series brings both
    in, preferring the copy, with object attributes. Undo takes back the
    import (on every section, or on s2 alone) and redo on s2 alone brings
    T back hosted by H."""
    from PyReconstruct.modules.datatypes import Series
    import PyReconstruct.modules.gui.main.main_window as mw

    _, s2, _, _ = _setup(window)
    window.series.host_tree.clearHosts(T)
    window.saveAllData()
    path = tmp_path / "copy.jser"
    window.series.saveJser(str(path))
    copy = Series.openJser(str(path))
    try:
        section = copy.loadSection(s2)
        section.selected_traces = list(section.contours[T])
        section.translateTraces(1.0, 1.0)
        section.save()
        copy.setObjHosts([T], [H])
        copy.saveJser(str(path))
    finally:
        copy.close()
    monkeypatch.setattr(mw.FileDialog, "get", lambda *a, **k: str(path))
    monkeypatch.setattr(mw.ImportSeriesDialog, "exec", lambda self: (
        {"traces": [None, [], [], 0.95, True, True, True, "other", "other"]}, True,
    ))
    window.importfromseries_act.trigger()
    assert _saved_host_tree(window, tmp_path / "imported.jser") == {T: [H]}

    window.changeSection(s2)
    imported = sorted(t.points for t in window.field.section.contours[T])
    for action, scope in [(window.undo_act, undo_scope), (window.redo_act, "section")]:
        main_window_dialogs.linked_undo_responses = [scope]
        assert action.isEnabled()
        action.trigger()
    assert sorted(t.points for t in window.field.section.contours[T]) == imported
    assert _hosts(window) == [H]
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [H]}


@pytest.mark.parametrize("action", ["copy", "split"])
def test_redoing_a_copy_or_split_on_one_section_makes_its_links_again(
        window, main_window_dialogs, monkeypatch, tmp_path, action):
    """H hosts T. T is copied (Create copy of object(s)) or split (Split
    traces into individual objects) from the object list, and the new
    object takes T's host after the sections are recorded. Undo takes it
    back on every section, and redo on s2 alone brings the new object
    back hosted by H."""
    _, s2, _, _ = _setup(window)
    _object_list(window, monkeypatch, [T])
    if action == "copy":
        window.field.copyObjects()
        made = T + "_copy"
    else:
        window.field.splitObject()
        made = T + "_1"
    assert _saved_host_tree(window, tmp_path / "made.jser")[made] == [H]

    window.changeSection(s2)
    for act, scope in [(window.undo_act, "all"), (window.redo_act, "section")]:
        main_window_dialogs.linked_undo_responses = [scope]
        assert act.isEnabled()
        act.trigger()
    assert made in window.field.section.contours
    assert _hosts(window, made) == [H]
    assert _saved_host_tree(window, tmp_path / "redone.jser").get(made) == [H]


A, Z = "hl_a", "hl_z"
A_COPY, Z_COPY = A + "_copy", Z + "_copy"


def _trigger_on(window, dialogs, snum, act, scope):
    window.changeSection(snum)
    dialogs.linked_undo_responses = [scope]
    assert act.isEnabled()
    act.trigger()


def _copy_into_names_that_exist(window, dialogs, monkeypatch, tmp_path, middle=None):
    """A_COPY on s1 is hosted by Z_COPY on s4 (through middle on s1 if
    given), and Z on s2 is hosted by A_COPY; A on s3 has no host. Copying A
    then Z from the object list clears A_COPY's hosts, then gives Z_COPY the
    host A_COPY. Undo takes it back on every section."""
    s1, s2, s3, s4 = _sections(window)
    for snum, name in [(s1, A_COPY), (s2, Z), (s3, A), (s4, Z_COPY)]:
        _draw_on(window, snum, name)
    if middle is None:
        window.series.setObjHosts([A_COPY], [Z_COPY])
    else:
        _draw_on(window, s1, middle)
        window.series.setObjHosts([middle], [Z_COPY])
        window.series.setObjHosts([A_COPY], [middle])
    window.series.setObjHosts([Z], [A_COPY])
    before = _saved_host_tree(window, tmp_path / "before.jser")
    _object_list(window, monkeypatch, [A, Z])
    window.field.copyObjects()
    copied = _saved_host_tree(window, tmp_path / "copied.jser")
    assert copied[Z_COPY] == [A_COPY] and A_COPY not in copied
    _trigger_on(window, dialogs, s2, window.undo_act, "all")
    assert _saved_host_tree(window, tmp_path / "undone.jser") == before
    return s2, s3, before, copied


@pytest.mark.parametrize("then", ["save", "draw", "reopen"])
def test_redoing_a_copy_into_names_that_exist_on_one_section_replaces_their_hosts(
        window, main_window_dialogs, monkeypatch, tmp_path, then):
    """Redo on s2 alone gives Z_COPY the host A_COPY and takes away A_COPY's
    host Z_COPY, as the copy did, so the two do not host each other. The
    saved tree stays the same after an unrelated draw or a reopen."""
    s2, _, _, copied = _copy_into_names_that_exist(
        window, main_window_dialogs, monkeypatch, tmp_path
    )
    _trigger_on(window, main_window_dialogs, s2, window.redo_act, "section")
    if then == "draw":
        _draw_on(window, s2, SPARE)
    path = tmp_path / "redone.jser"
    assert _saved_host_tree(window, path) == copied
    if then == "reopen":
        from PyReconstruct.modules.datatypes import Series

        other = Series.openJser(str(path))
        try:
            assert other.host_tree.getDict() == copied
        finally:
            other.close()


def test_redoing_a_copy_on_one_section_refuses_a_host_that_would_host_itself(
        window, main_window_dialogs, monkeypatch, tmp_path):
    """A_COPY is hosted by Z_COPY through M. Redo on s2 alone cannot give
    Z_COPY the host A_COPY: the copy took away A_COPY's host M on s3, which
    is not redone yet. Redo on s3 then makes the copy's tree."""
    M = "hl_middle"
    s2, s3, before, copied = _copy_into_names_that_exist(
        window, main_window_dialogs, monkeypatch, tmp_path, middle=M
    )
    _trigger_on(window, main_window_dialogs, s2, window.redo_act, "section")
    assert _saved_host_tree(window, tmp_path / "s2.jser") == before
    _draw_on(window, s2, SPARE)
    assert _saved_host_tree(window, tmp_path / "drawn.jser") == before
    _trigger_on(window, main_window_dialogs, s3, window.redo_act, "section")
    assert _saved_host_tree(window, tmp_path / "s3.jser") == copied


def test_redoing_an_import_on_one_section_keeps_a_host_it_made_redundant(
        window, main_window_dialogs, monkeypatch, tmp_path):
    """H hosts T, and X is on s3. A copy moves T and puts X between them.
    Importing s2 from it gives T the host X, and H drops from T's hosts as
    X's host. Redo on s2 alone after an undo there makes T -> X but not
    X -> H, which belongs to X, so T keeps H."""
    from PyReconstruct.modules.datatypes import Series
    import PyReconstruct.modules.gui.main.main_window as mw

    _, s2, s3, _ = _setup(window)
    _draw_on(window, s3, X)
    window.saveAllData()
    path = tmp_path / "copy.jser"
    window.series.saveJser(str(path))
    copy = Series.openJser(str(path))
    try:
        section = copy.loadSection(s2)
        section.selected_traces = list(section.contours[T])
        section.translateTraces(1.0, 1.0)
        section.save()
        copy.setObjHosts([X], [H])
        copy.setObjHosts([T], [X])
        copy.saveJser(str(path))
    finally:
        copy.close()
    monkeypatch.setattr(mw.FileDialog, "get", lambda *a, **k: str(path))
    monkeypatch.setattr(mw.ImportSeriesDialog, "exec", lambda self: (
        {"traces": [(s2, s2 + 1), [], [], 0.95, True, True, True, "other", "other"]},
        True,
    ))
    window.importfromseries_act.trigger()
    assert _saved_host_tree(window, tmp_path / "imported.jser") == {T: [X], X: [H]}
    _trigger_on(window, main_window_dialogs, s2, window.undo_act, "all")
    _trigger_on(window, main_window_dialogs, s2, window.redo_act, "section")
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [H, X]}


def _copy_or_split_t(window, monkeypatch, action):
    """Copy or split T from the object list; the name T's copy takes."""
    _object_list(window, monkeypatch, [T])
    if action == "copy":
        window.field.copyObjects()
        return T + "_copy"
    window.field.splitObject()
    return T + "_1"


@pytest.mark.parametrize("then", ["clear", "draw", "reopen"])
@pytest.mark.parametrize("action", ["copy", "split"])
def test_redoing_a_copy_or_split_on_one_section_clears_a_host_still_reachable(
        window, main_window_dialogs, monkeypatch, tmp_path, action, then):
    """X on s3 is hosted by H and hosts T; C on s4, the name T's copy takes,
    is hosted by H. The copy or split clears C's host H and gives it X, so
    H is still C's host through X. Redo on s2 alone after an undo there
    takes H away again: clearing C's hosts leaves none, and the saved tree
    stays the same after an unrelated draw or a reopen."""
    _, s2, s3, s4 = _setup(window)
    made = T + ("_copy" if action == "copy" else "_1")
    _draw_on(window, s3, X)
    _draw_on(window, s4, made)
    window.series.setObjHosts([X], [H])
    window.series.setObjHosts([T], [X])
    window.series.setObjHosts([made], [H])
    _copy_or_split_t(window, monkeypatch, action)
    forward = _saved_host_tree(window, tmp_path / "forward.jser")
    assert forward[made] == [X]
    _trigger_on(window, main_window_dialogs, s2, window.undo_act, "all")
    _trigger_on(window, main_window_dialogs, s2, window.redo_act, "section")
    path = tmp_path / "redone.jser"
    assert _saved_host_tree(window, path) == forward
    if then == "clear":
        _object_list(window, monkeypatch, [made])
        window.field.clearHosts()
        assert made not in _saved_host_tree(window, tmp_path / "cleared.jser")
    elif then == "draw":
        _draw_on(window, s3, SPARE)
        assert _saved_host_tree(window, tmp_path / "drawn.jser") == forward
    else:
        from PyReconstruct.modules.datatypes import Series

        other = Series.openJser(str(path))
        try:
            assert other.host_tree.getDict() == forward
        finally:
            other.close()


@pytest.mark.parametrize("between", [False, True])
@pytest.mark.parametrize("action", ["copy", "split"])
def test_undoing_a_copy_or_split_redone_on_one_section_gives_back_the_old_host(
        window, main_window_dialogs, monkeypatch, tmp_path, action, between):
    """C on s3, the name T's copy takes, is hosted by O on s4. The copy or
    split gives C the host H instead. After an undo on every section, redo
    on s2 alone gives C the host H again, and an undo on s2 after it gives
    C back O, also with a draw on s2 done and undone in between."""
    O = "hl_old_host"
    _, s2, s3, s4 = _setup(window)
    made = T + ("_copy" if action == "copy" else "_1")
    _draw_on(window, s3, made)
    _draw_on(window, s4, O)
    window.series.setObjHosts([made], [O])
    before = _saved_host_tree(window, tmp_path / "before.jser")
    _copy_or_split_t(window, monkeypatch, action)
    assert _saved_host_tree(window, tmp_path / "forward.jser")[made] == [H]
    _trigger_on(window, main_window_dialogs, s2, window.undo_act, "all")
    _trigger_on(window, main_window_dialogs, s2, window.redo_act, "section")
    assert _saved_host_tree(window, tmp_path / "redone.jser")[made] == [H]
    if between:
        _draw_on(window, s2, SPARE)
        _trigger_on(window, main_window_dialogs, s2, window.undo_act, "section")
    _trigger_on(window, main_window_dialogs, s2, window.undo_act, "section")
    assert _saved_host_tree(window, tmp_path / "undone.jser") == before


@pytest.mark.parametrize("then", ["draw", "reopen", "undo"])
def test_redoing_a_copy_on_one_section_drops_a_host_it_made_redundant(
        window, main_window_dialogs, monkeypatch, tmp_path, then):
    """Y on s3 is hosted by C on s4, the name T's copy takes, and by H. The
    copy gives C the host H, so H drops from Y's hosts as C's host. Redo on
    s2 alone after an undo there drops it again, and the saved tree stays
    the same after an unrelated draw or a reopen. An undo on s2 after the
    redo gives Y its host H back."""
    Y = "hl_y"
    _, s2, s3, s4 = _setup(window)
    made = T + "_copy"
    _draw_on(window, s4, made)
    _draw_on(window, s3, Y)
    window.series.setObjHosts([Y], [made, H])
    before = _saved_host_tree(window, tmp_path / "before.jser")
    _copy_or_split_t(window, monkeypatch, "copy")
    forward = _saved_host_tree(window, tmp_path / "forward.jser")
    assert forward[Y] == [made] and forward[made] == [H]
    _trigger_on(window, main_window_dialogs, s2, window.undo_act, "all")
    _trigger_on(window, main_window_dialogs, s2, window.redo_act, "section")
    path = tmp_path / "redone.jser"
    assert _saved_host_tree(window, path) == forward
    if then == "draw":
        _draw_on(window, s3, SPARE)
        assert _saved_host_tree(window, tmp_path / "drawn.jser") == forward
    elif then == "reopen":
        from PyReconstruct.modules.datatypes import Series

        other = Series.openJser(str(path))
        try:
            assert other.host_tree.getDict() == forward
        finally:
            other.close()
    else:
        _trigger_on(window, main_window_dialogs, s2, window.undo_act, "section")
        assert _saved_host_tree(window, tmp_path / "undone.jser") == before


def _copy_where_h_hosts_moved_t(window, monkeypatch, tmp_path):
    """H on s1 and T on s2, not linked. A copy moves T and makes H its
    host; the import below reads that copy."""
    from PyReconstruct.modules.datatypes import Series
    import PyReconstruct.modules.gui.main.main_window as mw

    _, s2, _, _ = _setup(window)
    window.series.host_tree.clearHosts(T)
    window.saveAllData()
    path = tmp_path / "copy.jser"
    window.series.saveJser(str(path))
    copy = Series.openJser(str(path))
    try:
        section = copy.loadSection(s2)
        section.selected_traces = list(section.contours[T])
        section.translateTraces(1.0, 1.0)
        section.save()
        copy.setObjHosts([T], [H])
        copy.saveJser(str(path))
    finally:
        copy.close()
    monkeypatch.setattr(mw.FileDialog, "get", lambda *a, **k: str(path))
    return s2


def _import(window, monkeypatch, response):
    import PyReconstruct.modules.gui.main.main_window as mw

    monkeypatch.setattr(
        mw.ImportSeriesDialog, "exec", lambda self: (response, True)
    )
    window.importfromseries_act.trigger()


_HOSTS_ONLY = [[
    ("groups", False), ("hosts", True), ("columns", False),
    ("z-trace groups", False), ("misc", False),
]]


@pytest.mark.parametrize("with_flags", [False, True])
def test_redoing_an_import_on_one_section_makes_attributes_tab_hosts_again(
        window, main_window_dialogs, monkeypatch, tmp_path, with_flags):
    """The import brings T in with object attributes off on the Traces tab
    and Hosts checked on the Attributes tab, with or without flags too.
    Undo takes back the traces on every section and redo on s2 alone
    brings T back hosted by H."""
    s2 = _copy_where_h_hosts_moved_t(window, monkeypatch, tmp_path)
    response = {
        "traces": [None, [], [], 0.95, True, True, False, "other", "other"],
        "attributes": _HOSTS_ONLY,
    }
    if with_flags:
        response["flags"] = [min(window.series.sections), max(window.series.sections)]
    _import(window, monkeypatch, response)
    assert _saved_host_tree(window, tmp_path / "imported.jser") == {T: [H]}

    window.changeSection(s2)
    imported = sorted(t.points for t in window.field.section.contours[T])
    undos = 2 if with_flags else 1
    for action, scope in [(window.undo_act, "all")] * undos + [(window.redo_act, "section")]:
        main_window_dialogs.linked_undo_responses = [scope]
        assert action.isEnabled()
        action.trigger()
    assert sorted(t.points for t in window.field.section.contours[T]) == imported
    assert _hosts(window) == [H]
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [H]}


def test_importing_only_hosts_from_the_attributes_tab_links_them(
        window, monkeypatch, tmp_path):
    """Hosts alone, with no traces, links T to H and adds no undo step."""
    _copy_where_h_hosts_moved_t(window, monkeypatch, tmp_path)
    undos = len(window.field.series_states.undos)
    _import(window, monkeypatch, {"attributes": _HOSTS_ONLY})
    assert _hosts(window) == [H]
    assert len(window.field.series_states.undos) == undos


def _import_a_host_with_no_traces(window, monkeypatch, tmp_path):
    """H on s1 and T on s2, not linked. A copy draws X on s3, moves T and
    makes X its host. Importing only s2 from the copy, preferring it, with
    object attributes, makes X T's host though X has no traces here."""
    from PyReconstruct.modules.datatypes import Series, Trace
    import PyReconstruct.modules.gui.main.main_window as mw

    _, s2, s3, _ = _setup(window)
    window.series.host_tree.clearHosts(T)
    window.saveAllData()
    path = tmp_path / "copy.jser"
    window.series.saveJser(str(path))
    copy = Series.openJser(str(path))
    try:
        section = copy.loadSection(s3)
        trace = Trace(X, (0, 255, 0), True)
        trace.points = [(1.0, 1.0), (2.0, 1.0), (1.0, 2.0)]
        section.addTrace(trace)
        section.save()
        section = copy.loadSection(s2)
        section.selected_traces = list(section.contours[T])
        section.translateTraces(1.0, 1.0)
        section.save()
        copy.setObjHosts([T], [X])
        copy.saveJser(str(path))
    finally:
        copy.close()
    monkeypatch.setattr(mw.FileDialog, "get", lambda *a, **k: str(path))
    monkeypatch.setattr(mw.ImportSeriesDialog, "exec", lambda self: (
        {"traces": [(s2, s2 + 1), [], [], 0.95, True, True, True, "other", "other"]},
        True,
    ))
    window.importfromseries_act.trigger()
    assert X not in window.series.data["objects"]
    assert _saved_host_tree(window, tmp_path / "imported.jser") == {T: [X]}
    return s2, s3


def test_redoing_an_import_on_one_section_keeps_a_host_with_no_traces(
        window, main_window_dialogs, monkeypatch, tmp_path):
    """After the import above, undo on every section and redo on s2 alone
    bring T back hosted by X. Deleting T from the object list then takes
    the link off, its undo puts it back and its redo takes it off again."""
    s2, _ = _import_a_host_with_no_traces(window, monkeypatch, tmp_path)
    window.changeSection(s2)
    imported = sorted(t.points for t in window.field.section.contours[T])
    for action, scope in [(window.undo_act, "all"), (window.redo_act, "section")]:
        main_window_dialogs.linked_undo_responses = [scope]
        assert action.isEnabled()
        action.trigger()
    assert sorted(t.points for t in window.field.section.contours[T]) == imported
    assert _hosts(window) == [X]
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {T: [X]}

    _object_list(window, monkeypatch, [T])
    window.field.deleteObjects()
    assert T not in window.series.data["objects"]
    assert _saved_host_tree(window, tmp_path / "deleted.jser") == {}
    for action, saved in [(window.undo_act, {T: [X]}), (window.redo_act, {})]:
        main_window_dialogs.linked_undo_responses = ["all"]
        assert action.isEnabled()
        action.trigger()
        assert _saved_host_tree(window, tmp_path / "again.jser") == saved


@pytest.mark.parametrize("renamed", [False, True])
def test_redo_on_one_section_keeps_out_a_host_deleted_since(
        window, main_window_dialogs, monkeypatch, tmp_path, renamed):
    """After the import above (then T renamed to SPARE from the object
    list), undo on s2 alone. X is drawn on s3, taking the host's id, and
    its trace deleted. Redo on s2 does not bring the deleted X back as the
    traveler's host."""
    import PyReconstruct.modules.gui.main.field_widget_3_object as obj
    from PyReconstruct.modules.datatypes import Trace

    s2, s3 = _import_a_host_with_no_traces(window, monkeypatch, tmp_path)
    traveler = T
    if renamed:
        _object_list(window, monkeypatch, [T])
        monkeypatch.setattr(obj.TraceDialog, "exec", lambda self: (
            (Trace(SPARE, (0, 255, 0), True), None), True,
        ))
        window.field.editAttributes()
        traveler = SPARE
    host_id = window.series.host_tree.keptId(X)
    window.changeSection(s2)
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo_act.trigger()
    assert window.series.host_tree.keptIds(X) == {host_id}

    _draw_on(window, s3, X)
    assert window.series.data.object_ids.peek(s3, X) == host_id
    window.field.section.selected_traces = _traces(window, X)
    monkeypatch.setattr(window, "getFocusWidget", lambda: window.field)
    window.delete_act.trigger()
    assert _saved_host_tree(window, tmp_path / "deleted.jser") == {}

    window.changeSection(s2)
    main_window_dialogs.linked_undo_responses = ["section"]
    assert window.redo_act.isEnabled()
    window.redo_act.trigger()
    assert _hosts(window, traveler) == []
    assert _saved_host_tree(window, tmp_path / "redone.jser") == {}

# --------------------------------------------------------------------------- #
# save
# --------------------------------------------------------------------------- #

def _saved_host_tree(window, path):
    import json

    window.saveAllData()
    window.series.saveJser(str(path))
    return json.loads(path.read_bytes())["series"]["host_tree"]


def test_save_writes_the_same_host_tree(window, tmp_path):
    """A save after load writes the same bytes twice; after F4's undo of
    T, the file does not link T to the replacement."""
    first = tmp_path / "first.jser"
    second = tmp_path / "second.jser"
    _saved_host_tree(window, first)
    _saved_host_tree(window, second)
    assert first.read_bytes() == second.read_bytes()

    s1, s2, s3, _ = _delete_both_and_replace(window)
    _undo_on(window, s2)
    tree = _saved_host_tree(window, tmp_path / "f4.jser")
    assert H not in tree.get(T, [])
