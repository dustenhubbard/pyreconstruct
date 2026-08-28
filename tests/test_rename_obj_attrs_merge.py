"""Renaming an object onto an existing one merges attributes, never clobbers.

Renaming B onto A is the routine way to merge two objects. `renameObjAttrs`
has careful merge loops for exactly that, but a leftover wholesale copy after
them (older than the loops, found 2026-08-28) replaced A's whole attribute
dict with B's: A's comment, curation, lock, alignment pin, and user-column
values were silently lost, and where B had no such attribute A's value
vanished entirely. The copy is gone; these tests pin the merge semantics the
loops always intended.
"""

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def series(real_series):
    real_series.obj_attrs["keeper"] = {
        "comment": "the curated one",
        "locked": True,
        "user_columns": {"Reviewer": "abc", "Stage": "done"},
    }
    real_series.obj_attrs["incoming"] = {
        "comment": "scratch note",
        "alignment": "rough",
        "user_columns": {"Stage": "draft", "Batch": "7"},
    }
    return real_series


def test_the_destination_keeps_what_it_already_says(series):
    series.renameObjAttrs("incoming", "keeper")

    kept = series.obj_attrs["keeper"]
    assert kept["comment"] == "the curated one"       # not B's scratch note
    assert kept["locked"] is True                     # did not vanish
    assert kept["user_columns"]["Reviewer"] == "abc"
    assert kept["user_columns"]["Stage"] == "done"    # A's value wins


def test_the_destination_gains_what_it_lacked(series):
    series.renameObjAttrs("incoming", "keeper")

    kept = series.obj_attrs["keeper"]
    assert kept["alignment"] == "rough"               # only B had one
    assert kept["user_columns"]["Batch"] == "7"       # only B had one


def test_a_plain_rename_still_carries_everything(series):
    series.renameObjAttrs("incoming", "fresh_name")

    fresh = series.obj_attrs["fresh_name"]
    assert fresh["comment"] == "scratch note"
    assert fresh["alignment"] == "rough"
    assert fresh["user_columns"] == {"Stage": "draft", "Batch": "7"}
