"""In-memory object ids (datatypes/object_ids.py).

Each (section, name) with traces has an id. A name keeps its id across
sections, a deleted name that is reused gets a fresh one, and undo and redo put
back the id each restored set of traces had. Nothing about ids is written to
the .jser.
"""
import json

import pytest

from PyReconstruct.modules.backend.func.state_manager import (
    SectionStates,
    SeriesStates,
)
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants.jser_format import SERIES_KEYS
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.datatypes.object_ids import ObjectIds

H = "ids_host"
T = "ids_traveler"


# --------------------------------------------------------------------------- #
# the registry on its own
# --------------------------------------------------------------------------- #

def test_a_name_has_one_id_across_sections():
    ids = ObjectIds()
    a = ids.ensure(1, H)
    assert ids.ensure(2, H) == a
    assert ids.ensure(1, H) == a
    assert ids.live(H) == {a}
    assert ids.ensure(1, T) != a


def test_an_id_lives_while_any_section_has_it():
    ids = ObjectIds()
    a = ids.ensure(1, H)
    ids.ensure(2, H)
    ids.drop(1, H)
    assert ids.live(H) == {a}
    assert ids.ensure(3, H) == a
    ids.drop(2, H)
    ids.drop(3, H)
    assert ids.live(H) == set()


def test_a_deleted_name_drawn_again_gets_a_fresh_id():
    ids = ObjectIds()
    old = ids.ensure(1, H)
    ids.drop(1, H)
    new = ids.ensure(1, H)
    assert new != old
    assert ids.name_of[old] == ids.name_of[new] == H


def test_an_id_keeps_its_name():
    ids = ObjectIds()
    a = ids.ensure(1, H)
    with pytest.raises(ValueError):
        ids.place(2, T, a)
    with pytest.raises(ValueError):
        ids.place(2, T, 999)


def test_an_undone_delete_and_a_new_object_share_a_name():
    """Undo brings old H back on one section while a new H lives on
    another; both are live, and a new section joins the newer."""
    ids = ObjectIds()
    old = ids.ensure(1, H)
    ids.drop(1, H)
    new = ids.ensure(3, H)
    ids.place(1, H, old)
    assert ids.live(H) == {old, new}
    assert ids.ensure(5, H) == new
    ids.drop(3, H)
    ids.drop(5, H)
    assert ids.live(H) == {old}


def test_a_reserved_id_is_taken_by_the_first_traces():
    ids = ObjectIds()
    r = ids.reserve(H)
    assert ids.reserve(H) == r
    assert ids.live(H) == set()
    assert ids.ensure(4, H) == r
    assert H not in ids.unplaced
    assert ids.reserve(H) == r


def test_reconcile_gives_a_new_pair_the_name_s_one_live_id():
    ids = ObjectIds()
    a = ids.ensure(1, H)
    b = ids.ensure(2, T)
    ids.reconcile([(5, H), (2, T)])
    assert ids.placed == {(5, H): a, (2, T): b}


def test_renumbering_keeps_two_ids_under_one_name_apart():
    """Delete H on section 1, draw a new H on section 3, undo the delete,
    then insert a section at the top."""
    ids = ObjectIds()
    old = ids.ensure(1, H)
    ids.drop(1, H)
    new = ids.ensure(3, H)
    ids.place(1, H, old)
    ids.renumber({0: 1, 1: 2, 2: 3, 3: 4})
    ids.reconcile([(2, H), (4, H)])
    assert ids.placed == {(2, H): old, (4, H): new}
    assert ids.live(H) == {old, new}


# --------------------------------------------------------------------------- #
# a real series
# --------------------------------------------------------------------------- #

@pytest.fixture
def series(real_series):
    real_series.setProgressReporter(NullProgressReporter)
    yield real_series
    real_series.setProgressReporter(None)


def _ids(series):
    return series.data.object_ids


def _square(series, offset=0.2):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.05
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _draw(series, section, name):
    trace = Trace(name, (0, 255, 0), True)
    trace.points = _square(series)
    section.addTrace(trace)


def _erase(section, name):
    for trace in list(section.contours.get(name, [])):
        section.removeTrace(trace)


def _act(series, states, section, edit):
    """An action recorded the way the field records one: the state first,
    then the series data and the lists."""
    edit(section)
    states.addState(section, series)
    series.data.updateSection(section, update_traces=True, all_traces=False)
    section.clearTracking()


def _step(series, states, section, redo=False):
    if redo:
        states.redoState(section, series)
    else:
        states.undoState(section, series)
    series.data.updateSection(section, update_traces=True, all_traces=False)
    section.clearTracking()


def _empty_sections(series, count):
    found = []
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        if H not in section.contours and T not in section.contours:
            found.append(snum)
        if len(found) == count:
            return found
    pytest.fail("fixture has too few sections")


def test_loading_gives_each_object_one_id(series):
    ids = _ids(series)
    seen = {}
    for name, obj_data in series.data["objects"].items():
        oids = {ids.peek(snum, name) for snum in obj_data.traces}
        assert len(oids) == 1 and None not in oids, name
        seen[name] = oids.pop()
    assert len(set(seen.values())) == len(seen)
    assert len(ids.placed) == sum(
        len(o.traces) for o in series.data["objects"].values()
    )


def test_a_refresh_keeps_the_ids(series):
    before = dict(_ids(series).placed)
    series.data.refresh()
    assert _ids(series).placed == before


def test_saving_a_section_keeps_the_ids_in_step(series):
    s1, s2 = _empty_sections(series, 2)
    a, b = series.loadSection(s1), series.loadSection(s2)
    _draw(series, a, H)
    a.save()
    _draw(series, b, H)
    b.save()
    oid = _ids(series).peek(s1, H)
    assert oid is not None and _ids(series).peek(s2, H) == oid

    _erase(a, H)
    a.save()
    _erase(b, H)
    b.save()
    assert _ids(series).live(H) == set()

    _draw(series, a, H)
    a.save()
    assert _ids(series).peek(s1, H) not in (None, oid)


def test_rename_gives_the_new_name_its_own_id_and_undo_puts_back_the_old(series):
    s1, s2 = _empty_sections(series, 2)
    for snum in (s1, s2):
        section = series.loadSection(snum)
        _draw(series, section, H)
        section.save()
    old = _ids(series).peek(s1, H)

    states = SeriesStates(series)
    series.editObjectAttributes([H], name=T, series_states=states)
    new = _ids(series).peek(s1, T)
    assert new not in (None, old)
    assert _ids(series).placed.get((s2, T)) == new
    assert _ids(series).live(H) == set()

    states.undoState()
    assert _ids(series).peek(s1, H) == old
    assert _ids(series).peek(s2, H) == old
    assert _ids(series).live(T) == set()

    states.undoState(redo=True)
    assert _ids(series).peek(s1, T) == new
    assert _ids(series).peek(s2, T) == new
    assert _ids(series).live(H) == set()


def test_rename_on_some_sections_leaves_the_old_id_on_the_rest(series):
    s1, s2 = _empty_sections(series, 2)
    for snum in (s1, s2):
        section = series.loadSection(snum)
        _draw(series, section, H)
        section.save()
    old = _ids(series).peek(s1, H)

    series.editObjectAttributes([H], name=T, sections=[s1])
    assert _ids(series).live(H) == {old}
    assert _ids(series).peek(s2, H) == old
    assert _ids(series).peek(s1, T) not in (None, old)


def test_an_object_list_delete_undone_puts_back_the_id(series):
    s1, s2 = _empty_sections(series, 2)
    for snum in (s1, s2):
        section = series.loadSection(snum)
        _draw(series, section, H)
        section.save()
    old = _ids(series).peek(s1, H)

    states = SeriesStates(series)
    series.deleteObjects([H], series_states=states)
    assert _ids(series).live(H) == set()

    states.undoState()
    assert _ids(series).live(H) == {old}
    assert _ids(series).peek(s2, H) == old


def test_undo_and_redo_put_back_the_ids_on_one_section(series):
    """Draw H, delete it, draw a new H; undo and redo each step."""
    (s1,) = _empty_sections(series, 1)
    section = series.loadSection(s1)
    states = SectionStates(section, series)
    ids = _ids(series)

    _act(series, states, section, lambda s: _draw(series, s, H))
    old = ids.peek(s1, H)
    _act(series, states, section, lambda s: _erase(s, H))
    assert ids.live(H) == set()
    _act(series, states, section, lambda s: _draw(series, s, H))
    new = ids.peek(s1, H)
    assert new not in (None, old)

    _step(series, states, section)
    assert ids.live(H) == set()
    _step(series, states, section)
    assert ids.peek(s1, H) == old
    _step(series, states, section)
    assert ids.live(H) == set()

    _step(series, states, section, redo=True)
    assert ids.peek(s1, H) == old
    _step(series, states, section, redo=True)
    assert ids.live(H) == set()
    _step(series, states, section, redo=True)
    assert ids.peek(s1, H) == new


def test_undo_to_the_first_state_puts_back_the_loaded_id(series):
    """The section's first state reads the ids it holds, and an undo back
    to it (one state left) puts them back."""
    s1, s2 = _empty_sections(series, 2)
    a = series.loadSection(s1)
    _draw(series, a, H)
    a.save()
    a.clearTracking()
    old = _ids(series).peek(s1, H)

    states_a = SectionStates(a, series)
    _act(series, states_a, a, lambda s: _erase(s, H))
    b = series.loadSection(s2)
    states_b = SectionStates(b, series)
    _act(series, states_b, b, lambda s: _draw(series, s, H))
    new = _ids(series).peek(s2, H)
    assert new != old

    _step(series, states_a, a)
    assert _ids(series).peek(s1, H) == old
    assert _ids(series).live(H) == {old, new}


def test_renumbering_drops_placements_on_deleted_sections():
    """Section 0 was deleted and the series data not refreshed yet; section
    1 becomes section 0. The id dies with its last trace."""
    ids = ObjectIds()
    a = ids.ensure(0, H)
    ids.ensure(1, H)
    ids.renumber({1: 0})
    assert ids.placed == {(0, H): a}
    ids.drop(0, H)
    assert ids.live(H) == set()
    assert ids.ensure(0, H) != a


def test_renumbering_refuses_two_sections_on_one_number():
    ids = ObjectIds()
    a = ids.ensure(0, H)
    with pytest.raises(ValueError):
        ids.renumber({0: 5, 1: 5})
    assert ids.placed == {(0, H): a}


def _two_live_ids(series):
    """H on two sections under two ids: draw H on the first, delete it, draw
    a new H on the second, then undo the delete. Both sections are saved."""
    s1, s2 = _empty_sections(series, 2)
    ids = _ids(series)
    a = series.loadSection(s1)
    states = SectionStates(a, series)
    _act(series, states, a, lambda s: _draw(series, s, H))
    old = ids.peek(s1, H)
    _act(series, states, a, lambda s: _erase(s, H))
    b = series.loadSection(s2)
    _draw(series, b, H)
    b.save()
    new = ids.peek(s2, H)
    _step(series, states, a)
    a.save()
    assert ids.live(H) == {old, new} and old != new
    return s1, s2, old, new


def test_inserting_a_section_keeps_both_ids(series):
    s1, s2, old, new = _two_live_ids(series)
    renumbered = series.insertSection(min(series.sections), "no-image", 0.00254, 0.05)
    series.data.refresh()
    ids = _ids(series)
    assert renumbered[s1] != s1
    assert ids.peek(renumbered[s1], H) == old
    assert ids.peek(renumbered[s2], H) == new
    assert ids.live(H) == {old, new}


def test_reordering_sections_keeps_both_ids(series):
    s1, s2, old, new = _two_live_ids(series)
    order = {snum: snum for snum in series.sections}
    order[s1], order[s2] = s2, s1
    series.reorderSections(order)
    series.data.refresh()
    ids = _ids(series)
    assert ids.peek(s2, H) == old
    assert ids.peek(s1, H) == new
    assert ids.live(H) == {old, new}


def test_deleting_sections_keeps_the_ids_that_are_left(series):
    s1, s2, old, new = _two_live_ids(series)
    other = next(n for n in sorted(series.sections) if n not in (s1, s2))
    series.deleteSections([other])
    series.data.refresh()
    ids = _ids(series)
    assert ids.peek(s1, H) == old and ids.peek(s2, H) == new

    series.deleteSections([s1])
    series.data.refresh()
    assert ids.live(H) == {new}
    assert ids.peek(s2, H) == new


def test_reordering_right_after_a_delete_lets_the_id_die(series):
    """Delete a section and reorder before the series data is refreshed: a
    section moves onto the deleted one's number. Once the object's last
    trace is gone, a new trace under its name gets a fresh id."""
    s1, s2 = _empty_sections(series, 2)
    assert s1 == min(series.sections)
    for snum in (s1, s2):
        section = series.loadSection(snum)
        _draw(series, section, H)
        section.save()
    old = _ids(series).peek(s2, H)

    series.deleteSections([s1])
    order = series.reorderSections()
    assert order[s2] == s1
    assert _ids(series).placed.get((s1, H)) == old

    section = series.loadSection(s1)
    _erase(section, H)
    section.save()
    assert _ids(series).live(H) == set()
    _draw(series, section, H)
    section.save()
    assert _ids(series).peek(s1, H) not in (None, old)


def test_ids_are_not_saved(series, tmp_path):
    """Save and reopen: no id in the file, the series keys are the same,
    and a second save writes the same bytes."""
    s1, s2 = _empty_sections(series, 2)
    for snum, name in ((s1, H), (s2, T)):
        section = series.loadSection(snum)
        _draw(series, section, name)
        section.save()
    series.host_tree.add(T, [H])
    oid = _ids(series).peek(s1, H)

    first = tmp_path / "first.jser"
    series.saveJser(str(first))
    data = json.loads(first.read_bytes())
    ser = data["series"]
    assert set(ser) <= set(SERIES_KEYS)
    assert ser["host_tree"][T] == [H]
    assert str(oid) not in json.dumps(ser["host_tree"])

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    assert not {"oid", "oids", "object_id", "object_ids"} & set(keys(data))

    reopened = Series.openJser(str(first))
    try:
        second = tmp_path / "second.jser"
        reopened.saveJser(str(second))
        assert second.read_bytes() == first.read_bytes()
    finally:
        reopened.close()
