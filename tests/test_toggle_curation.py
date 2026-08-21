"""TableManager.toggleCuration works, now that it is reachable.

The Help-menu search made every menubar command runnable by name, and the
first real invocation of this one crashed: it iterated the manager's `tables`
dict (yielding type-name strings) and indexed each table's `columns` like a
dict (it is a list of (name, shown) pairs). Both are pinned here by driving
the real method against stand-ins shaped exactly like ObjectTableWidget.
"""
import types

from PyReconstruct.modules.backend.table.manager import TableManager


def _manager_with(columns_list):
    m = TableManager.__new__(TableManager)
    m.tables = {"object": [], "trace": [], "section": [], "ztrace": [], "flag": []}
    m.recreated = []
    m.recreateTable = lambda t, _m=m: _m.recreated.append(t)
    for cols in columns_list:
        m.tables["object"].append(types.SimpleNamespace(columns=list(cols)))
    return m


def test_toggles_curation_on_when_any_table_hides_it():
    m = _manager_with([
        [("Range", True), ("Curate", False)],
        [("Range", True), ("Curate", True)],
    ])
    m.toggleCuration()
    for t in m.tables["object"]:
        assert dict(t.columns)["Curate"] is True
        # and only Curate moved
        assert dict(t.columns)["Range"] is True
    assert len(m.recreated) == 2


def test_toggles_curation_off_when_every_table_shows_it():
    m = _manager_with([[("Curate", True)], [("Curate", True)]])
    m.toggleCuration()
    for t in m.tables["object"]:
        assert dict(t.columns)["Curate"] is False


def test_no_object_tables_is_a_quiet_no_op():
    m = _manager_with([])
    m.toggleCuration()   # must not raise
    assert m.recreated == []
