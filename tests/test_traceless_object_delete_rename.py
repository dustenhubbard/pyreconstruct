"""Delete and full rename of an object that has no traces left.

An object emptied without a delete (its sections deleted, an import) keeps
its attributes, groups and host links. Deleting it outright, or renaming it
on every section, has no section to save, so the cleanup a section save does
for an object with traces never ran: the delete changed nothing, and the
rename left the old name's attributes and groups in the saved file.

H hosts T and K; each is on its own section. H has a comment, an alignment
pin and the only membership of a hidden group. Its section is deleted before
each case.
"""
import json

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Trace

H, T, K = "tl_host", "tl_traveler", "tl_other"
X = "tl_renamed"
GROUP = "tl_group"
PIN = "tl_pin"


@pytest.fixture
def series(real_series):
    real_series.setProgressReporter(NullProgressReporter)
    yield real_series
    real_series.setProgressReporter(None)


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.05
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _draw(series, snum, name, offset=0.2):
    section = series.loadSection(snum)
    trace = Trace(name, (0, 255, 0), True)
    trace.points = _square(series, offset)
    section.addTrace(trace)
    section.save()


def _free_sections(series):
    return [
        n for n in sorted(series.sections)
        if not {H, T, K, X} & set(series.loadSection(n).contours)
    ]


def setup(series):
    """H, T and K on sections of their own, T and K hosted by H, and H's
    metadata; then H's section is deleted. Returns a free section."""
    free = _free_sections(series)
    where = dict(zip((H, T, K), free))
    for name, snum in where.items():
        _draw(series, snum, name)
    series.host_tree.add(T, [H])
    series.host_tree.add(K, [H])
    series.setAttr(H, "comment", "the host")
    series.setAttr(H, "alignment", PIN)
    series.object_groups.add(group=GROUP, obj=H)
    series.groups_visibility[GROUP] = False

    series.deleteSections([where[H]])
    series.data.refresh()
    assert H not in series.data["objects"]
    assert series.getAttr(H, "comment") == "the host"
    assert series.host_tree.keptId(H) is not None
    return free[3]


def saved(series, path):
    """What the saved file says about the names here."""
    series.saveJser(str(path))
    data = json.loads(path.read_bytes())["series"]
    names = (H, T, K, X)
    return {
        "attrs": {
            name: {a: v for a, v in attrs.items() if a in ("comment", "alignment")}
            for name, attrs in data["obj_attrs"].items() if name in (H, X)
        },
        "groups": {
            group: members for group, members in data["object_groups"].items()
            if group == GROUP
        },
        "links": {
            name: hosts for name, hosts in data["host_tree"].items() if name in names
        },
    }


BEFORE = {
    "attrs": {H: {"comment": "the host", "alignment": PIN}},
    "groups": {GROUP: [H]},
    "links": {T: [H], K: [H]},
}


def test_deleting_a_traceless_object_removes_its_metadata_and_links(
        series, tmp_path):
    spare = setup(series)
    old_id = series.host_tree.keptId(H)
    assert saved(series, tmp_path / "before.jser") == BEFORE

    states = SeriesStates(series)
    series.deleteObjects([H], series_states=states)
    deleted = {"attrs": {}, "groups": {}, "links": {}}
    assert saved(series, tmp_path / "deleted.jser") == deleted
    assert series.object_groups.getObjectGroups(H) == set()
    assert GROUP not in series.groups_visibility
    assert series.host_tree.getHosts(T) == []

    for step in range(2):
        states.undoState()
        assert saved(series, tmp_path / f"undo-{step}.jser") == BEFORE
        assert series.groups_visibility[GROUP] is False
        assert series.host_tree.keptId(H) == old_id
        states.undoState(redo=True)
        assert saved(series, tmp_path / f"redo-{step}.jser") == deleted
        assert GROUP not in series.groups_visibility

    # a new H is a new object: it has a new id and none of the old links
    _draw(series, spare, H, offset=0.5)
    assert series.data.object_ids.live(H) and old_id not in series.data.object_ids.live(H)
    assert saved(series, tmp_path / "new.jser")["links"] == {}


def test_a_full_rename_of_a_traceless_object_leaves_nothing_on_the_old_name(
        series, tmp_path):
    setup(series)
    states = SeriesStates(series)
    series.editObjectAttributes([H], name=X, series_states=states)
    renamed = {
        "attrs": {X: {"comment": "the host", "alignment": PIN}},
        "groups": {GROUP: [X]},
        "links": {T: [X], K: [X]},
    }
    assert saved(series, tmp_path / "renamed.jser") == renamed
    assert H not in series.obj_attrs
    assert series.object_groups.getObjectGroups(H) == set()
    assert series.groups_visibility[GROUP] is False

    for step in range(2):
        states.undoState()
        assert saved(series, tmp_path / f"undo-{step}.jser") == BEFORE
        assert series.groups_visibility[GROUP] is False
        states.undoState(redo=True)
        assert saved(series, tmp_path / f"redo-{step}.jser") == renamed
        assert series.groups_visibility[GROUP] is False


def test_a_full_rename_onto_an_existing_object_keeps_the_destination_values(
        series, tmp_path):
    spare = setup(series)
    _draw(series, spare, X, offset=0.5)
    series.setAttr(X, "comment", "the destination")
    # a drawn object is pinned to the alignment it was drawn in
    own_pin = series.getAttr(X, "alignment")
    assert own_pin is not None and own_pin != PIN
    series.editObjectAttributes([H], name=X)
    got = saved(series, tmp_path / "merged.jser")
    assert got["attrs"] == {X: {"comment": "the destination", "alignment": own_pin}}
    assert got["groups"] == {GROUP: [X]}
    assert got["links"] == {T: [X], K: [X]}
