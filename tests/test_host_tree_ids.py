"""HostTree on object ids, without a window.

A link joins two object ids. It shows while both ends are visible (they have
traces, or the tree keeps them for a name with none) and goes dormant
otherwise; it comes back with its ids. The tree keeps its name interface and
its saved shape.
"""
import random
import types

import pytest

from PyReconstruct.modules.datatypes.host_tree import HostTree
from PyReconstruct.modules.datatypes.object_ids import ObjectIds


def _series():
    """A stand-in series whose registry and tree find each other, as a
    series' own do: the registry takes an id the tree keeps for a name's
    first traces (ObjectIds.ensure), and tells the tree what lost or got
    traces."""
    series = types.SimpleNamespace(data=types.SimpleNamespace(objects={}))
    series.data.object_ids = ObjectIds(series)
    series.host_tree = HostTree({}, series)
    return series


@pytest.fixture
def series():
    return _series()


@pytest.fixture
def ids(series):
    return series.data.object_ids


@pytest.fixture
def tree(series):
    return series.host_tree


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


# --------------------------------------------------------------------------- #
# the ids the tree keeps for names without traces
# --------------------------------------------------------------------------- #

def test_an_object_emptied_without_a_delete_keeps_its_link(ids, tree):
    """A deleted section or an import empties H without deleting it: the
    tree keeps H's id, its link stays, and H's next traces take the id."""
    h = ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H", keep=True)
    assert tree.keptIds("H") == {h}
    assert tree.getHosts("T") == ["H"]
    assert tree.getDict() == {"T": ["H"]}
    assert ids.ensure(3, "H") == h
    assert tree.keptIds("H") == set()
    assert tree.getHosts("T") == ["H"]


def test_a_delete_takes_the_kept_ids_of_the_name_out_of_sight(ids, tree):
    """Old H is kept beside a live replacement H (an undo brought it back,
    then its section was deleted). Deleting the replacement's last trace
    deletes the object H: the kept id goes out of sight too, until an undo
    keeps it again."""
    old = ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H")
    new = ids.ensure(3, "H")
    ids.place(1, "H", old)
    ids.drop(1, "H", keep=True)
    assert tree.keptIds("H") == {old} and ids.live("H") == {new}
    assert tree.getHosts("T") == ["H"]
    ids.drop(3, "H")
    assert tree.keptIds("H") == set()
    assert tree.getHosts("T") == []
    ids.place(3, "H", new)
    tree.restoreKept({"H": [old]})
    assert tree.keptIds("H") == {old}
    assert tree.getHosts("T") == ["H"]


def test_restoring_kept_ids_leaves_an_id_with_traces_alone(ids, tree):
    h = ids.ensure(1, "H")
    tree.add("T", ["H"])
    tree.restoreKept({"H": [h], "T": [99]})
    assert tree.keptIds("H") == set()


def test_a_rename_takes_the_old_name_s_kept_ids_out_of_sight(ids, tree):
    """H, kept with no traces, is renamed to X: X takes a copy of its link
    and H's kept id goes out of sight with the old name."""
    ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    ids.drop(1, "H", keep=True)
    tree.renameObject("H", "X")
    assert tree.keptIds("H") == set()
    assert tree.getDict() == {"T": ["X"]}
    assert ids.ensure(1, "X") == tree.keptId("X") or tree.keptIds("X") == set()
    assert tree.getDict() == {"T": ["X"]}


def test_a_copy_installed_by_a_series_undo_inherits_what_was_kept_since(ids, tree):
    """A series undo swaps in a copy of the tree. H lost its traces with no
    undoable step after the copy was taken (an unlogged update), so the tree
    kept H's id; the copy keeps it too. An id the copy neither links nor
    lists is not worth keeping."""
    h = ids.ensure(1, "H")
    ids.ensure(2, "T")
    tree.add("T", ["H"])
    copied = tree.copy()
    ids.drop(1, "H", keep=True)
    ids.ensure(3, "K")
    tree.add("K", ["X"])
    x = tree.keptId("X")
    assert tree.keptIds("H") == {h} and x is not None
    copied.inheritKept(tree)
    assert copied.keptIds("H") == {h}
    assert copied.keptIds("X") == set()
    assert copied.getDict() == {"T": ["H"]}


def test_an_inherited_copy_drops_a_kept_id_that_has_traces_now(ids, tree):
    """The copy kept D for a dangling link; D was drawn since, so the id has
    traces and needs no keeping."""
    ids.ensure(1, "T")
    tree.add("T", ["D"])
    d = tree.keptId("D")
    copied = tree.copy()
    assert copied.keptIds("D") == {d}
    assert ids.ensure(2, "D") == d
    copied.inheritKept(tree)
    assert copied.keptIds("D") == set()
    assert copied.getHosts("T") == ["D"]


@pytest.mark.parametrize("seed", range(12))
def test_the_projection_kept_in_place_matches_a_rebuild(seed):
    """Random links, deletes, undos and reused names: the name projection a
    write updated in place must equal one built from scratch."""
    rng = random.Random(seed)
    series = _series()
    ids, tree = series.data.object_ids, series.host_tree
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
