"""Regression test for updateDictLists, the merge helper behind importUserCols.

User-defined columns are stored as {column name: [allowed options]}. When a
series is imported into another, Series.importUserCols merges the two mappings
with updateDictLists. The helper concatenated the two option lists and then
overwrote the result with ``list(set(l))`` -- the *incoming* list only -- so for
any column name present in both series the current series' own options were
discarded rather than merged. Columns present in only one series were fine,
which is why the bug survived: it only fires on the overlap, i.e. exactly the
case a merge exists for.

The rewritten helper also deduplicates in first-seen order instead of via
set() iteration order, which is not stable across processes.
"""
from PyReconstruct.modules.datatypes.series import updateDictLists


def test_shared_key_keeps_options_from_both_sides():
    mine = {"stage": ["draft", "checked"]}
    theirs = {"stage": ["reviewed"]}

    merged = updateDictLists(mine, theirs)

    assert set(merged["stage"]) == {"draft", "checked", "reviewed"}, (
        "the current series' own column options were dropped instead of merged"
    )


def test_duplicates_are_collapsed_once():
    merged = updateDictLists(
        {"stage": ["draft", "checked"]},
        {"stage": ["checked", "reviewed", "reviewed"]},
    )
    assert merged["stage"] == ["draft", "checked", "reviewed"], (
        "expected first-seen order with duplicates removed"
    )


def test_keys_unique_to_either_side_survive():
    merged = updateDictLists({"only_mine": ["a"]}, {"only_theirs": ["b"]})
    assert merged == {"only_mine": ["a"], "only_theirs": ["b"]}


def test_inputs_are_not_mutated():
    mine = {"stage": ["draft"]}
    theirs = {"stage": ["reviewed"]}
    updateDictLists(mine, theirs)
    assert mine == {"stage": ["draft"]}, "the left-hand dict must not be modified in place"
    assert theirs == {"stage": ["reviewed"]}, "the right-hand dict must not be modified in place"


def test_order_is_deterministic_for_many_options():
    """set() iteration order over strings varies with PYTHONHASHSEED; the merge
    layer must not inherit that."""
    mine = {"c": [f"mine{i}" for i in range(20)]}
    theirs = {"c": [f"theirs{i}" for i in range(20)]}
    expected = [f"mine{i}" for i in range(20)] + [f"theirs{i}" for i in range(20)]
    assert updateDictLists(mine, theirs)["c"] == expected
