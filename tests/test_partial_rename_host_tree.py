"""A rename on only some sections leaves the old object's hosts in place.

Renaming an object on a subset of its sections leaves the old object in the
series, but `HostTree.renameObject` removed it from the host tree: its hosts
went to the new object and its travelers moved over to the new object, so the
old object was left with neither. Now the old object keeps both, and the new
object gets the same relationships, the way `renameObjAttrs` copies groups and
attributes. A rename on every section still moves them.
"""
import pytest

from PyReconstruct.modules.datatypes.host_tree import HostTree
from tests.test_data_integrity_invariants import rich_series  # noqa: F401  (fixture)

pytestmark = pytest.mark.gui


def _setup(series):
    # square is hosted by star (from rich_series); circle2 travels in square
    series.setObjHosts(["circle2"], ["square"])
    series.data.refresh()
    assert series.host_tree.getDict() == {
        "circle2": ["square"], "square": ["star"],
    }
    return sorted(series.getObjectSections(["square"]))


def test_tree_keep_old_copies_relationships():
    tree = HostTree({"circle2": ["square"], "square": ["star"]}, None)
    tree.renameObject("square", "new", keep_old=True)
    assert tree.getDict() == {
        "circle2": ["new", "square"],
        "new": ["star"],
        "square": ["star"],
    }


def test_partial_rename_keeps_old_hosts_and_travelers(rich_series):
    secs = _setup(rich_series)
    rich_series.editObjectAttributes(
        ["square"], name="new", sections=secs[:1], log_event=False
    )
    rich_series.data.refresh()
    assert "square" in rich_series.data["objects"]
    assert "new" in rich_series.data["objects"]

    tree = rich_series.host_tree
    assert tree.getHosts("square") == ["star"]
    assert tree.getTravelers("square") == ["circle2"]
    assert tree.getHosts("new") == ["star"]
    assert sorted(tree.getHosts("circle2")) == ["new", "square"]


@pytest.mark.parametrize("every_section", [False, True])
def test_full_rename_moves_hosts_and_travelers(rich_series, every_section):
    secs = _setup(rich_series)
    rich_series.editObjectAttributes(
        ["square"], name="new",
        sections=secs if every_section else None,
        log_event=False,
    )
    rich_series.data.refresh()
    assert "square" not in rich_series.data["objects"]
    assert rich_series.host_tree.getDict() == {
        "circle2": ["new"], "new": ["star"],
    }
