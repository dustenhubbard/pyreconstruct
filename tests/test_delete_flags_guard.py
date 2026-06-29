"""Regression test for deleteFlags with no selection.

deleteFlags lacked the empty-selection guard its siblings markResolved and
deleteFlagName both have. With nothing selected, getSelected() returns [], so
no flag is removed -- yet the method still enumerated every section (a progress
dialog over the whole series) and unconditionally called field.reload() and
seriesModified(True), falsely marking the series as having unsaved changes.
Exercised against a duck-typed stub.
"""
import types

from PyReconstruct.modules.gui.table import flag as flagmod


def _stub(selected):
    rec = {"enum": 0, "reload": 0, "modified": []}

    def enumerate_sections(*a, **k):
        rec["enum"] += 1
        return iter([])  # no sections needed for this test

    series = types.SimpleNamespace(user="u", enumerateSections=enumerate_sections)
    mainwindow = types.SimpleNamespace(
        saveAllData=lambda: None,
        field=types.SimpleNamespace(
            reload=lambda: rec.__setitem__("reload", rec["reload"] + 1)
        ),
        seriesModified=lambda m=True: rec["modified"].append(m),
    )
    stub = types.SimpleNamespace(
        getSelected=lambda: list(selected),
        series=series,
        series_states=None,
        mainwindow=mainwindow,
        manager=types.SimpleNamespace(updateFlags=lambda s: None),
    )
    return stub, rec


def test_delete_flags_no_selection_is_noop():
    stub, rec = _stub([])

    flagmod.FlagTableWidget.deleteFlags(stub)

    assert rec["enum"] == 0, "must not walk sections when nothing is selected"
    assert rec["reload"] == 0, "must not reload the field"
    assert rec["modified"] == [], "must not mark the series modified"


def test_delete_flags_with_selection_proceeds():
    # a non-empty selection still runs the delete path (behavior preserved)
    stub, rec = _stub([types.SimpleNamespace(snum=0)])

    flagmod.FlagTableWidget.deleteFlags(stub)

    assert rec["enum"] == 1
    assert rec["reload"] == 1
    assert rec["modified"] == [True]
