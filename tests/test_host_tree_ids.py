"""HostTree on object ids, without a window.

A link joins two object ids. It shows while both ends are visible (they have
traces, or are held for a name with none) and goes dormant otherwise; it comes
back with its ids. The tree keeps its name interface and its saved shape.
"""
import random
import types

import pytest

from PyReconstruct.modules.datatypes.host_tree import HostTree
from PyReconstruct.modules.datatypes.object_ids import ObjectIds


def _series(ids):
    return types.SimpleNamespace(data=types.SimpleNamespace(object_ids=ids, objects={}))


@pytest.fixture
def ids():
    return ObjectIds()


@pytest.fixture
def tree(ids):
    return HostTree({}, _series(ids))


def test_a_deleted_object_s_link_goes_dormant_and_comes_back(ids, tree):
    h = ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H")
    assert tree.getHosts("T") == []
    assert tree.getDict() == {}
    ids.place(1, "H", h)
    assert tree.getHosts("T") == ["H"]


def test_a_new_object_with_the_old_name_does_not_take_the_link(ids, tree):
    ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H")
    ids.ensure(3, "H")
    assert tree.getHosts("T") == []


def test_old_and_new_object_under_one_name_show_the_old_link(ids, tree):
    """The union rule: an undo brings the old H back beside the new one."""
    old = ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H")
    ids.ensure(3, "H")
    ids.place(1, "H", old)
    assert tree.getHosts("T") == ["H"]
    ids.drop(3, "H")
    assert tree.getHosts("T") == ["H"]
    ids.drop(1, "H")
    assert tree.getHosts("T") == []


def test_clearing_hosts_leaves_a_dormant_link(ids, tree):
    h = ids.ensure(1, "H")
    ids.ensure(2, "T")
    ids.ensure(3, "K")
    tree.add("T", ["H", "K"])
    ids.drop(1, "H")
    tree.clearHosts("T")
    assert tree.getHosts("T") == []
    ids.place(1, "H", h)
    assert tree.getHosts("T") == ["H"]


def test_a_rename_copies_the_links_and_the_old_ones_go_with_the_old_object(ids, tree):
    x = ids.ensure(1, "X")
    ids.ensure(2, "H")
    ids.ensure(3, "T")
    tree.add("X", ["H"])
    tree.add("T", ["X"])
    tree.renameObject("X", "Y")
    # the sections are saved: X's traces are now Y's
    ids.drop(1, "X")
    ids.ensure(1, "Y")
    assert tree.getDict() == {"T": ["Y"], "Y": ["H"]}
    # an undo of the rename puts X back and takes Y away
    ids.drop(1, "Y")
    ids.place(1, "X", x)
    assert tree.getDict() == {"T": ["X"], "X": ["H"]}


def test_a_rename_does_not_trim_a_link_only_the_old_object_made_redundant(ids, tree):
    """A hosted by X, X hosted by Y: renaming X to Y must leave A hosted by
    Y, as it did when the old name was removed first."""
    for snum, name in enumerate(["A", "X", "Y"]):
        ids.ensure(snum, name)
    tree.add("X", ["Y"])
    tree.add("A", ["X"])
    tree.renameObject("X", "Y")
    ids.drop(1, "X")
    ids.ensure(1, "Y")
    assert tree.getDict() == {"A": ["Y"]}


def test_a_name_with_no_traces_keeps_its_links_as_before(ids, tree):
    """A link to a name no section has (a dangling host in a file) shows
    and saves, and the name's first traces take it."""
    ids.ensure(1, "T")
    tree.add("T", ["D"])
    assert tree.getDict() == {"T": ["D"]}
    ids.ensure(2, "D")
    assert tree.getHosts("T") == ["D"]


def test_copy_shares_the_ids_and_keeps_dormant_links(ids, tree):
    h = ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H")
    copied = tree.copy()
    tree.add("T", ["T2"])
    ids.place(1, "H", h)
    assert copied.getDict() == {"T": ["H"]}


def test_dropping_dormant_links_changes_nothing_visible(ids, tree):
    ids.ensure(1, "H")
    ids.ensure(2, "T")
    ids.ensure(3, "K")
    tree.add("T", ["H"])
    tree.add("K", ["H"])
    ids.drop(3, "K")
    before = tree.getDict()
    tree.dropDormant()
    assert tree.getDict() == before == {"T": ["H"]}
    ids.ensure(3, "K")
    assert tree.getHosts("K") == []


@pytest.mark.parametrize("seed", range(12))
def test_the_projection_kept_in_place_matches_a_rebuild(seed):
    """Random links, deletes, undos and reused names: the name projection a
    write updated in place must equal one built from scratch."""
    rng = random.Random(seed)
    ids = ObjectIds()
    tree = HostTree({}, _series(ids))
    names = [f"n{i}" for i in range(7)]
    dead = []
    for snum, name in enumerate(names):
        ids.ensure(snum, name)
    for step in range(150):
        op = rng.random()
        live = [n for n in names if ids.live(n)]
        if op < 0.35 and len(live) >= 2:
            t, h = rng.sample(live, 2)
            tree.add(t, [h])
        elif op < 0.45 and live:
            tree.clearHosts(rng.choice(live))
        elif op < 0.6 and live:
            name = rng.choice(live)
            for key in [k for k in ids.placed if k[1] == name]:
                dead.append((key, ids.placed[key]))
                ids.drop(*key)
        elif op < 0.75 and dead:
            (snum, name), oid = dead.pop(rng.randrange(len(dead)))
            if ids.peek(snum, name) is None:
                ids.place(snum, name, oid)
        elif op < 0.85:
            ids.ensure(rng.randrange(20), rng.choice(names))
        elif op < 0.92 and len(live) >= 2:
            old, new = rng.sample(live, 2)
            tree.renameObject(old, new, keep_old=rng.random() < 0.5)
        else:
            tree.getHosts(rng.choice(names))
        kept = [
            (n, {k: set(v) for k, v in d.items()}) for n, d in tree.objects.items()
        ]
        tree._stale = True
        rebuilt = [
            (n, {k: set(v) for k, v in d.items()}) for n, d in tree.objects.items()
        ]
        assert rebuilt == kept, f"seed {seed} step {step}"
