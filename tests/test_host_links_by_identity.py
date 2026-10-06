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

@pytest.mark.parametrize("step", ["delete", "rename"])
def test_undo_brings_back_the_links_of_a_parked_object(
        window, main_window_dialogs, gui_dialogs, step):
    """Old H back beside a replacement H; old H's only section is deleted,
    so it keeps its link to T without traces. Deleting the replacement, or
    renaming H, and undoing that brings the link back."""
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
        main_window_dialogs.linked_undo_responses = ["all"]
        _undo_on(window, s3)
    assert H in window.series.data["objects"]
    assert _hosts(window) == [H]


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
