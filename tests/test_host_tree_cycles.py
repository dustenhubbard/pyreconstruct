"""Regression tests for host cycles in HostTree.

Renaming an object could make it its own host: rename a traveler to its host's
name, rename a host and its traveler to one name in a single edit, or rename an
object to the name of its grand-host. HostTree.getHosts and getTravelers then
recursed forever, so the rename died with RecursionError partway through
Series.editObjectAttributes. That left the series half-renamed (attributes and
group memberships copied to the new name, traces still under the old one) and
left a self-host edge in the tree, which serialized into the .jser and made the
series raise RecursionError on every subsequent open.

The tests assert the fixed behavior (the rename completes, no cycle exists, a
cyclic tree is traversable and loadable) rather than any recursion depth, since
the limit differs per platform.
"""
import os
import random
import shutil

import pytest

from PyReconstruct.modules.datatypes.host_tree import HostTree

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)


def _tree(host_dict):
    return HostTree(host_dict, None)


def _raw(host_dict):
    """Build a tree by writing self.objects directly, bypassing add().

    Needed to test that traversal survives a cycle, because add() now refuses to
    create one.
    """
    tree = HostTree.__new__(HostTree)
    tree.series = None
    tree.objects = {}
    for name, hosts in host_dict.items():
        tree.objects.setdefault(name, {"hosts": set(), "travelers": set()})
        for h in hosts:
            tree.objects.setdefault(h, {"hosts": set(), "travelers": set()})
            tree.objects[name]["hosts"].add(h)
            tree.objects[h]["travelers"].add(name)
    return tree


def _self_hosts(tree):
    return [n for n, d in tree.objects.items() if n in d["hosts"]]


# --------------------------------------------------------------------------
# the three rename paths that produced a cycle
# --------------------------------------------------------------------------

def test_rename_traveler_to_its_host_name_completes():
    """Path (a): the object list rename of one object to its host's name."""
    tree = _tree({"traveler": ["host"]})

    tree.renameObject("traveler", "host")

    assert "traveler" not in tree.objects
    assert _self_hosts(tree) == []
    # the relationship had one end left after the merge, so it is gone
    assert tree.getDict() == {}


def test_rename_host_and_traveler_to_one_name_completes():
    """Path (b): multi-select a host plus its traveler, rename both at once.

    Series.editObjectAttributes renames each selected object in turn, so this is
    two renameObject calls onto the same new name.
    """
    tree = _tree({"traveler": ["host"]})

    for old in ("traveler", "host"):
        tree.renameObject(old, "merged")

    assert _self_hosts(tree) == []
    assert tree.getDict() == {}


def test_rename_to_grand_host_name_keeps_the_existing_edge():
    """Path (c): the new name is two levels up, so the collision is a 2-cycle.

    Filtering out only the new name would miss this one; the guard has to be a
    reachability check.
    """
    tree = _tree({"traveler": ["middle"], "middle": ["top"]})

    tree.renameObject("traveler", "top")

    assert _self_hosts(tree) == []
    # middle was already hosted by top before the rename; that survives, and the
    # edge that would have closed the loop (top hosted by middle) is not created
    assert tree.getDict() == {"middle": ["top"]}
    assert sorted(tree.getHosts("top", True)) == []


# --------------------------------------------------------------------------
# add() enforces the invariant the callers already advertise
# --------------------------------------------------------------------------

def test_add_refuses_self_host_and_reports_it():
    tree = _tree({})

    refused = tree.add("a", ["a"])

    assert refused == ["a"]
    assert tree.getHosts("a") == []
    # the object is still registered, as it was before
    assert "a" in tree.objects


def test_add_refuses_an_edge_that_would_close_a_loop():
    tree = _tree({"a": ["b"], "b": ["c"]})

    refused = tree.add("c", ["a"])

    assert refused == ["a"]
    assert _self_hosts(tree) == []
    assert tree.getDict() == {"a": ["b"], "b": ["c"]}


def test_add_still_accepts_a_legitimate_host():
    tree = _tree({})

    assert tree.add("a", ["b"]) == []
    assert tree.getHosts("a") == ["b"]
    assert tree.getTravelers("b") == ["a"]


def test_add_checks_each_host_against_the_ones_already_added():
    """add("x", [...]) is checked one host at a time, because an earlier host in
    the list can be what makes a later one cyclic."""
    tree = _tree({"b": ["c"]})

    refused = tree.add("c", ["a", "b"])

    assert refused == ["b"]
    assert tree.getHosts("c") == ["a"]
    assert _self_hosts(tree) == []


# --------------------------------------------------------------------------
# a series saved with a cycle in it must become loadable again
# --------------------------------------------------------------------------

def test_a_host_dict_containing_a_self_cycle_loads_and_is_repaired():
    """Files written before the guard existed can contain "x": ["x"]. Loading
    one raised RecursionError in HostTree.__init__, so the series could not be
    opened at all."""
    tree = _tree({"x": ["x"]})

    assert _self_hosts(tree) == []
    assert tree.getDict() == {}


def test_a_host_dict_containing_a_two_cycle_loads():
    tree = _tree({"a": ["b"], "b": ["a"]})

    assert _self_hosts(tree) == []
    # exactly one of the two edges survives; either way the result is acyclic
    # and every traversal terminates
    assert len(tree.getDict()) <= 1
    for name in ("a", "b"):
        tree.getHosts(name, True)
        tree.getTravelers(name, True)


# --------------------------------------------------------------------------
# traversal terminates on a cycle that is already in memory
# --------------------------------------------------------------------------

@pytest.mark.parametrize("host_dict", [
    {"a": ["a"]},
    {"a": ["b"], "b": ["a"]},
    {"a": ["b"], "b": ["c"], "c": ["a"]},
])
def test_traversal_terminates_on_a_cyclic_tree(host_dict):
    tree = _raw(host_dict)
    names = sorted(tree.objects)

    for name in names:
        # every name in the cycle is reachable from every other name
        assert sorted(tree.getHosts(name, True)) == names
        assert sorted(tree.getTravelers(name, True)) == names
        assert sorted(tree.getHosts(name, True, True)) == names
        assert sorted(tree.getTravelers(name, True, True)) == names


@pytest.mark.parametrize("host_dict", [
    {"a": ["a"]},
    {"a": ["b"], "b": ["a"]},
    {"a": ["b"], "b": ["c"], "c": ["a"]},
])
def test_getascii_terminates_on_a_cyclic_tree(host_dict):
    tree = _raw(host_dict)
    for name in sorted(tree.objects):
        for hosts in (True, False):
            assert tree.getASCII(name, hosts)


def test_getobjtoupdate_terminates_on_a_cyclic_tree():
    """The GUI calls this after every object edit; it traverses travelers."""
    tree = _raw({"a": ["b"], "b": ["a"]})

    assert tree.getObjToUpdate(["a"]) == {"a", "b"}


# --------------------------------------------------------------------------
# acyclic semantics are unchanged
# --------------------------------------------------------------------------

def _reference_get(tree, obj_name, edge, traverse=False, only_secondary=False):
    """The pre-fix recursive implementation, verbatim except for the edge name.

    Correct on acyclic input, which is the only input given to it here.
    """
    if obj_name not in tree.objects:
        return []
    direct = list(tree.objects[obj_name][edge]).copy()
    if not traverse:
        return direct
    s = set() if only_secondary else set(direct.copy())
    for n in direct:
        s = s.union(set(_reference_get(tree, n, edge, traverse)))
    return list(s)


def _random_dag(rng, n_objects=9):
    """A random acyclic host graph. Object i may only be hosted by a j > i, so
    no cycle is possible and add() never refuses anything."""
    names = [f"o{i}" for i in range(n_objects)]
    host_dict = {}
    for i, name in enumerate(names):
        candidates = names[i + 1:]
        if not candidates:
            continue
        k = rng.randint(0, min(2, len(candidates)))
        if k:
            host_dict[name] = rng.sample(candidates, k)
    return host_dict


@pytest.mark.parametrize("seed", range(40))
def test_traversal_matches_the_recursive_version_on_acyclic_input(seed):
    """The visited set must not change any result for input without a cycle,
    since checkRedundantHosts and the GUI both depend on the exact semantics of
    traverse and only_secondary."""
    rng = random.Random(seed)
    host_dict = _random_dag(rng)
    tree = _tree(host_dict)
    assert _self_hosts(tree) == []

    for name in sorted(tree.objects):
        for traverse in (False, True):
            for only_secondary in (False, True):
                assert sorted(tree.getHosts(name, traverse, only_secondary)) == \
                    sorted(_reference_get(
                        tree, name, "hosts", traverse, only_secondary
                    )), (name, traverse, only_secondary, host_dict)
                assert sorted(tree.getTravelers(name, traverse, only_secondary)) == \
                    sorted(_reference_get(
                        tree, name, "travelers", traverse, only_secondary
                    )), (name, traverse, only_secondary, host_dict)


def test_only_secondary_still_reports_a_shared_host():
    """checkRedundantHosts trims a host that is also reachable through another
    host, and it finds it via only_secondary=True. That case must keep working:
    a name at distance 1 that is also at distance 2 is still reported."""
    tree = _raw({"a": ["b", "c"], "b": ["c"]})

    assert tree.getHosts("a", True, True) == ["c"]


def test_checkredundanthosts_still_trims_the_shared_host():
    tree = _tree({"a": ["b", "c"], "b": ["c"]})

    # a is hosted by both b and c, and b is hosted by c, so c is redundant for a
    assert tree.getHosts("a") == ["b"]
    assert sorted(tree.getTravelers("c")) == ["b"]


def test_getascii_still_prints_a_shared_host_under_each_parent():
    """The cycle guard in getASCII is a path check, not a visited set: a name
    legitimately appears more than once when two objects share a host."""
    tree = _tree({"a": ["b", "c"], "b": ["d"], "c": ["d"]})

    out = tree.getASCII("a")

    assert out.count("d") == 2, out


# --------------------------------------------------------------------------
# end to end through Series
# --------------------------------------------------------------------------

def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series, fp


def _two_objects(series):
    names = list(series.data["objects"].keys())
    if len(names) < 2:
        pytest.skip("fixture has fewer than two objects")
    return names[0], names[1]


def test_renaming_a_traveler_to_its_host_moves_every_trace(tmp_path):
    """The half-rename: before the fix this raised RecursionError inside
    editObjectAttributes after the group memberships and object attributes had
    been migrated but before any trace was renamed."""
    series, _ = _load_series(tmp_path)
    traveler, host = _two_objects(series)
    series.host_tree.add(traveler, [host])
    series.object_groups.add("grp", traveler)
    sections = series.getObjectSections([traveler])
    assert sections, "traveler appears on no sections"

    series.editObjectAttributes([traveler], name=host, log_event=False)

    # the rename completed on all three: traces, groups, host tree
    assert series.getObjectSections([traveler]) == set()
    assert series.getObjectSections([host]) >= sections
    assert series.object_groups.getObjectGroups(traveler) == set()
    assert "grp" in series.object_groups.getObjectGroups(host)
    assert _self_hosts(series.host_tree) == []
    series.close()


def test_renaming_a_host_and_its_traveler_together_moves_every_trace(tmp_path):
    series, _ = _load_series(tmp_path)
    traveler, host = _two_objects(series)
    series.host_tree.add(traveler, [host])
    sections = series.getObjectSections([traveler]) | series.getObjectSections([host])

    series.editObjectAttributes([traveler, host], name="merged", log_event=False)

    assert series.getObjectSections([traveler]) == set()
    assert series.getObjectSections([host]) == set()
    assert series.getObjectSections(["merged"]) == sections
    assert _self_hosts(series.host_tree) == []
    series.close()


def test_a_series_saved_after_the_rename_reopens(tmp_path):
    """The saved host tree used to contain "x": ["x"], and HostTree.__init__
    raised RecursionError on it, so the .jser could not be opened again."""
    from PyReconstruct.modules.datatypes.series import Series

    series, fp = _load_series(tmp_path)
    traveler, host = _two_objects(series)
    series.host_tree.add(traveler, [host])
    series.editObjectAttributes([traveler], name=host, log_event=False)
    series.saveJser()
    series.close()

    reopened = Series.openJser(fp)
    assert _self_hosts(reopened.host_tree) == []
    reopened.close()
