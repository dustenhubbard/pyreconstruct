"""Tests for ``Section.setGroupVisibility`` and its optional argument.

The method hides every trace belonging to a group the user has switched off,
by extending ``Section.traces_group_hide``. Its signature makes ``group_viz``
optional, so a caller is entitled to omit it:

    def setGroupVisibility(self, group_viz: Union[Dict[str, bool], None]=None)

That default used to raise. An early version guarded the argument first
("if not groups: return"), but a later rewrite moved the mapping walk ahead of
the guard, so the first statement executed on the default was
``None.items()``:

    AttributeError: 'NoneType' object has no attribute 'items'

No live path reached it: the only in-tree caller is ``Section.__init__``, which
passes ``series.groups_visibility``, and ``Series.initGroupViz`` returns a dict
(``{}`` at worst) rather than None. The default was reachable only from outside
the package, which is exactly where it is documented to be usable.

The contract pinned here: omitting the argument, or passing None or an empty
mapping, means there is nothing to apply, so ``traces_group_hide`` is left as
it is. Passing a mapping applies it.

``Section`` cannot be constructed without real series files, so these drive a
``Section.__new__`` instance carrying only the attributes the method touches.
"""
import pytest

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.datatypes.section import Section


def mk(name):
    t = Trace(name, (255, 0, 0), True)
    t.points = [(0, 0), (1, 0), (1, 1)]
    return t


class _ObjGroupsStub:
    """Stands in for Series.object_groups."""

    def __init__(self, groups):
        self.groups = groups

    def getGroupObjects(self, group):
        return set(self.groups.get(group, set()))


class _SeriesStub:
    def __init__(self, groups=None):
        self.object_groups = _ObjGroupsStub(groups or {})


def bare_section(traces, groups=None):
    s = Section.__new__(Section)
    s.n = 0
    s.series = _SeriesStub(groups)
    s.contours = {}
    for t in traces:
        s.contours.setdefault(t.name, Contour(t.name)).append(t)
    s.traces_group_hide = []
    return s


# --------------------------------------------------------------------------- #
# the documented default
# --------------------------------------------------------------------------- #
def test_omitting_group_viz_does_not_raise():
    """The signature's own default must be callable."""
    s = bare_section([mk("a")], {"g": {"a"}})

    s.setGroupVisibility()  # exactly the documented default

    assert s.traces_group_hide == []


def test_default_leaves_an_existing_hide_list_alone():
    """"Nothing to apply" means untouched, not cleared."""
    a = mk("a")
    s = bare_section([a], {"g": {"a"}})
    s.traces_group_hide = [a]

    s.setGroupVisibility()

    assert s.traces_group_hide == [a]


@pytest.mark.parametrize("group_viz", [None, {}])
def test_none_and_empty_are_also_nothing_to_apply(group_viz):
    s = bare_section([mk("a")], {"g": {"a"}})

    s.setGroupVisibility(group_viz)

    assert s.traces_group_hide == []


# --------------------------------------------------------------------------- #
# the argument still does its job
# --------------------------------------------------------------------------- #
def test_a_hidden_group_hides_its_traces():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b], {"g1": {"a"}, "g2": {"b"}})

    s.setGroupVisibility({"g1": False, "g2": True})

    assert s.traces_group_hide == [a]


def test_all_groups_visible_hides_nothing():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b], {"g1": {"a"}, "g2": {"b"}})

    s.setGroupVisibility({"g1": True, "g2": True})

    assert s.traces_group_hide == []


def test_a_hidden_group_with_no_traces_on_this_section_hides_nothing():
    a = mk("a")
    s = bare_section([a], {"g1": {"a"}, "g2": {"elsewhere"}})

    s.setGroupVisibility({"g1": True, "g2": False})

    assert s.traces_group_hide == []
