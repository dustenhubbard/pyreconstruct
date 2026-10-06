"""Host links of an object that lost its traces without being deleted.

Deleting a section, or an import that empties an object, does not delete the
object: its attributes stay, and so do its host links, in memory and in the
saved file. A new object drawn under the name later picks them up. Only an
object delete (the field, the object list, an undo) puts its links out of
sight until an undo brings it back.

H hosts T and K; each is on its own section. The expected files are what the
tree saved before links were kept by object.
"""
import json

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.host_tree import HostTree

H, T, K = "kl_host", "kl_traveler", "kl_other"


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
        if not {H, T, K} & set(series.loadSection(n).contours)
    ]


def setup(series):
    """H, T and K on three sections of their own; T and K hosted by H."""
    where = dict(zip((H, T, K), _free_sections(series)))
    for name, snum in where.items():
        _draw(series, snum, name)
    series.host_tree.add(T, [H])
    series.host_tree.add(K, [H])
    return where


def saved_links(series, path):
    series.saveJser(str(path))
    tree = json.loads(path.read_bytes())["series"]["host_tree"]
    return {name: hosts for name, hosts in tree.items() if name in (H, T, K)}


def empty_by_import(series, other_path, name, attrs, states=None):
    """Run the series import with the section step replaced by one that
    removes the object, the way the import's history check removes an
    object the other series deleted. With attrs, the import also merges the
    other series' host links (the same links here)."""
    def remove(section, other, *args, **kwargs):
        if name in section.contours:
            for trace in list(section.contours[name]):
                section.removeTrace(trace)
            del section.contours[name]
        section.save()

    series.saveJser(str(other_path))
    other = Series.openJser(str(other_path))
    original = Section.importTraces
    Section.importTraces = remove
    try:
        series.importTraces(other, import_obj_attrs=attrs, series_states=states)
    finally:
        Section.importTraces = original
        other.close()


def run(series, tmp_path, case):
    """Empty H or T by the case's path; return the saved links."""
    where = setup(series)
    name = H if "host" in case else T
    if case.startswith("section"):
        series.deleteSections([where[name]])
        series.data.refresh()
    else:
        empty_by_import(
            series, tmp_path / "other.jser", name, attrs=not case.endswith("bare")
        )
    assert name not in series.data["objects"]
    return saved_links(series, tmp_path / f"{case}.jser")


# What the tree saved for each case before links were kept by object.
SAVED_BEFORE = {T: [H], K: [H]}


CASES = [
    "section-host", "section-traveler",
    "import-host", "import-traveler", "import-host-bare", "import-traveler-bare",
]


@pytest.mark.parametrize("case", CASES)
def test_an_object_emptied_without_a_delete_keeps_its_saved_links(
        series, tmp_path, case):
    assert run(series, tmp_path, case) == SAVED_BEFORE


@pytest.mark.parametrize("case", ["section-host", "import-host", "import-host-bare"])
def test_a_host_drawn_again_picks_up_its_travelers(series, tmp_path, case):
    run(series, tmp_path, case)
    _draw(series, _free_sections(series)[0], H, offset=0.5)
    assert series.host_tree.getHosts(T) == [H]
    assert saved_links(series, tmp_path / "again.jser") == SAVED_BEFORE


@pytest.mark.parametrize("emptied", ["host", "traveler"])
def test_undo_and_redo_of_an_import_keep_the_links(series, tmp_path, emptied):
    """The import empties H (or T) and keeps the link; undoing and redoing
    the whole import keeps it at every step."""
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates

    where = setup(series)
    states = SeriesStates(series)
    series.current_section = where[H]
    name = H if emptied == "host" else T
    empty_by_import(series, tmp_path / "other.jser", name, attrs=False, states=states)
    assert name not in series.data["objects"]
    assert saved_links(series, tmp_path / "import.jser") == SAVED_BEFORE

    states.undoState()
    assert name in series.data["objects"]
    assert saved_links(series, tmp_path / "undo.jser") == SAVED_BEFORE

    states.undoState(redo=True)
    assert name not in series.data["objects"]
    assert saved_links(series, tmp_path / "redo.jser") == SAVED_BEFORE

    states.undoState()
    assert saved_links(series, tmp_path / "undo-again.jser") == SAVED_BEFORE


@pytest.mark.parametrize("how", ["unlogged update", "refresh"])
def test_undo_of_an_earlier_action_keeps_links_kept_since(series, tmp_path, how):
    """A group change from the object list, then H loses its traces with no
    undoable step (an unlogged update or a refresh). Undoing the group
    change leaves H's link alone."""
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates

    where = setup(series)
    states = SeriesStates(series)
    states.addState()
    series.object_groups.add(group="kl_group", obj=T)

    section = series.loadSection(where[H])
    for trace in list(section.contours[H]):
        section.removeTrace(trace)
    del section.contours[H]
    section.save(update_series_data=False)
    if how == "refresh":
        series.data.refresh()
    else:
        series.data.updateSection(section, update_traces=True, log_events=False)
    assert H not in series.data["objects"]
    assert saved_links(series, tmp_path / "emptied.jser") == SAVED_BEFORE

    series.current_section = where[T]
    states.undoState()
    assert series.object_groups.getObjectGroups(T) == set()
    assert saved_links(series, tmp_path / "undone.jser") == SAVED_BEFORE


def test_an_object_delete_still_takes_its_links_out_of_the_file(series, tmp_path):
    setup(series)
    series.deleteObjects([H])
    assert saved_links(series, tmp_path / "deleted.jser") == {}


# --------------------------------------------------------------------------- #
# importing links keeps the order the tree has always walked them in
# --------------------------------------------------------------------------- #

class _Data(dict):
    def __init__(self, objects, ids=None):
        super().__init__(objects={n: True for n in objects})
        if ids is not None:
            self.object_ids = ids


class _Series:
    def __init__(self, objects, ids=None):
        self.data = _Data(objects, ids)


def _source(entries, id_order):
    """A tree loaded from a file whose objects got their ids in id_order
    (the series data is read before the tree is built)."""
    try:
        from PyReconstruct.modules.datatypes.object_ids import ObjectIds
    except ImportError:  # the tree before object ids
        return HostTree(entries, _Series(id_order))
    ids = ObjectIds()
    for snum, name in enumerate(id_order):
        ids.ensure(snum, name)
    return HostTree(entries, _Series(id_order, ids))


def import_links(entries, id_order, copy):
    """Import a loaded tree, or its copy, into one where A hosts B."""
    source = _source(entries, id_order)
    if copy:
        source = source.copy()
    dest = HostTree({"A": ["B"]}, _Series(["A", "B", "C", "X"]))
    dest.merge(source)
    return dest.getDict()


# Legacy entries the load trims (X's host A is also a host of its host C)
# or refuses (A -> B closes a cycle), plus links that conflict with A -> B.
LEGACY = {
    "trimmed": {"B": ["C"], "C": ["A"], "X": ["A", "C"]},
    "refused": {"B": ["C"], "C": ["A"], "A": ["B"]},
}
IMPORTED_BEFORE = {
    "trimmed": {"A": ["B"], "B": ["C"], "X": ["C"]},
    "refused": {"A": ["B"], "B": ["C"]},
}


@pytest.mark.parametrize("copy", [False, True])
def test_an_import_from_a_copy_walks_the_saved_order(copy):
    """A copy lists its names as its saved form does, so the import refuses
    the same link of the two that close a cycle."""
    source = HostTree({"C": ["A"], "B": ["C"]}, _Series(["A", "B", "C"]))
    if copy:
        source = source.copy()
    dest = HostTree({"A": ["B"]}, _Series(["A", "B", "C"]))
    dest.merge(source)
    expected = {"A": ["B"], "B": ["C"]} if copy else {"A": ["B"], "C": ["A"]}
    assert dest.getDict() == expected


@pytest.mark.parametrize("copy", [False, True])
@pytest.mark.parametrize("legacy", sorted(LEGACY))
def test_an_import_keeps_the_same_link_as_before(legacy, copy):
    entries = LEGACY[legacy]
    assert import_links(entries, ["C", "B", "A", "X"], copy) == IMPORTED_BEFORE[legacy]
