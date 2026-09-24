"""Tag sets: the data layer behind the tags dropdown.

Covers the TagSets container on its own, the series wiring (load, save,
back-fill, canonical key order, import), and the one behavior that touches
trace data: applying a pick-one choice to a trace's tag set.

The pins that matter most:

- An old file without the key opens and saves with an empty mapping.
- A malformed entry drops on load without taking the series down or the other
  sets with it.
- ``apply`` with None leaves a set alone. A dialog on a mixed selection passes
  None, and a blank there must never read as "clear".
- A save and reopen round trip keeps sets, modes, order, and descriptions.
"""
import json
import os
import shutil

import pytest

from PyReconstruct.modules.constants import SERIES_KEYS
from PyReconstruct.modules.datatypes.tag_sets import TagSets, MODE_ONE, MODE_MANY

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

PROTRUSION = {
    "mode": "one",
    "tags": ["spine", "shaft", "branched"],
    "descriptions": {"spine": "A protrusion with a head and a neck."},
}
QUALIFIERS = {"mode": "many", "tags": ["estimated", "partial"], "descriptions": {}}


def _sets():
    return TagSets({"Protrusion type": PROTRUSION, "Qualifiers": QUALIFIERS})


# ---------------------------------------------------------------------------
# the container
# ---------------------------------------------------------------------------
def test_round_trips_its_stored_form():
    data = {"Protrusion type": PROTRUSION, "Qualifiers": QUALIFIERS}
    assert TagSets(data).getDict() == data


def test_getDict_is_a_copy():
    ts = _sets()
    d = ts.getDict()
    d["Protrusion type"]["tags"].append("junk")
    assert "junk" not in ts.tags("Protrusion type")


def test_missing_or_none_data_is_empty():
    assert len(TagSets(None)) == 0
    assert len(TagSets({})) == 0
    assert TagSets("not a dict").getDict() == {}


def test_malformed_entries_drop_and_the_rest_load():
    data = {
        "Good": {"mode": "one", "tags": ["a", "b"]},
        "": {"mode": "one", "tags": ["x"]},
        "Not a dict": ["a", "b"],
        "Odd mode": {"mode": "several", "tags": ["c", 3, None, "  c ", "", "d"]},
        "Stale description": {"mode": "many", "tags": ["e"], "descriptions": {"gone": "x", "e": " kept "}},
    }
    ts = TagSets(data)
    assert ts.names() == ["Good", "Odd mode", "Stale description"]
    assert ts.mode("Odd mode") == MODE_MANY, "an unknown mode reads as pick many"
    assert ts.tags("Odd mode") == ["c", "d"], "non-strings, blanks and duplicates drop"
    assert ts.get("Stale description")["descriptions"] == {"e": "kept"}


def test_all_tags_is_set_order_then_tag_order_once_each():
    ts = _sets()
    ts.add("Overlap", MODE_MANY, ["shaft", "other"])
    assert ts.allTags() == ["spine", "shaft", "branched", "estimated", "partial", "other"]


def test_lookups():
    ts = _sets()
    assert ts.pickOneSets() == ["Protrusion type"]
    assert ts.pickManySets() == ["Qualifiers"]
    assert ts.setsFor("shaft") == ["Protrusion type"]
    assert ts.setsFor("nowhere") == []
    assert ts.description("Protrusion type", "spine").startswith("A protrusion")
    assert ts.description("Protrusion type", "shaft") == ""
    assert ts.describe("spine") == PROTRUSION["descriptions"]["spine"]
    assert ts.describe("estimated") == ""


def test_add_refuses_duplicates_blank_names_and_bad_modes():
    ts = _sets()
    assert not ts.add("Protrusion type", MODE_ONE, ["x"])
    assert not ts.add("  Protrusion type ", MODE_ONE, ["x"]), "names compare stripped"
    assert not ts.add("   ", MODE_ONE, ["x"])
    assert not ts.add("Fine", "sometimes", ["x"])
    assert ts.add(" Location ", MODE_ONE, [" head", "neck", "head", ""], {"head": " top "})
    assert ts.names()[-1] == "Location"
    assert ts.tags("Location") == ["head", "neck"]
    assert ts.description("Location", "head") == "top"


def test_edit_keeps_position_and_unspecified_fields():
    ts = _sets()
    assert ts.edit("Protrusion type", new_name="Protrusion", tags=["spine", "shaft"])
    assert ts.names() == ["Protrusion", "Qualifiers"], "a rename keeps the set's position"
    assert ts.mode("Protrusion") == MODE_ONE, "mode left None keeps its value"
    assert ts.get("Protrusion")["descriptions"] == {"spine": PROTRUSION["descriptions"]["spine"]}, (
        "descriptions left None are kept for the tags that remain"
    )
    assert not ts.edit("Protrusion", new_name="Qualifiers"), "cannot rename onto a taken name"
    assert not ts.edit("Missing", tags=["x"])
    assert not ts.edit("Protrusion", mode="whatever")
    assert ts.edit("Protrusion", mode=MODE_MANY)
    assert ts.mode("Protrusion") == MODE_MANY


def test_remove():
    ts = _sets()
    assert ts.remove("Qualifiers")
    assert not ts.remove("Qualifiers")
    assert ts.names() == ["Protrusion type"]


def test_rename_tag_keeps_description_and_position():
    ts = _sets()
    assert ts.renameTag("Protrusion type", "spine", "Spine")
    assert ts.tags("Protrusion type") == ["Spine", "shaft", "branched"]
    assert ts.description("Protrusion type", "Spine").startswith("A protrusion")
    assert not ts.renameTag("Protrusion type", "Spine", "shaft"), "cannot collide"
    assert not ts.renameTag("Protrusion type", "nope", "x")
    assert not ts.renameTag("Protrusion type", "Spine", "  ")


# ---------------------------------------------------------------------------
# apply: the only behavior that reaches trace data
# ---------------------------------------------------------------------------
def test_apply_pick_one_replaces_siblings_and_keeps_everything_else():
    ts = _sets()
    before = {"shaft", "estimated", "mine"}
    after = ts.apply(before, {"Protrusion type": "spine"})
    assert after == {"spine", "estimated", "mine"}
    assert before == {"shaft", "estimated", "mine"}, "the input set is not modified"


def test_apply_blank_clears_the_set_only():
    ts = _sets()
    assert ts.apply({"shaft", "estimated"}, {"Protrusion type": ""}) == {"estimated"}


def test_apply_none_leaves_the_set_alone():
    """The mixed-selection contract: None means the dialog showed nothing for
    this set, so nothing changes. A blank must never be inferred from None."""
    ts = _sets()
    assert ts.apply({"shaft", "estimated"}, {"Protrusion type": None}) == {"shaft", "estimated"}


def test_apply_ignores_pick_many_and_unknown_sets():
    ts = _sets()
    tags = {"shaft", "estimated"}
    assert ts.apply(tags, {"Qualifiers": "partial", "Nope": "x"}) == tags


def test_chosen_reads_the_value_a_trace_holds():
    ts = _sets()
    assert ts.chosen("Protrusion type", {"shaft", "estimated"}) == "shaft"
    assert ts.chosen("Protrusion type", {"estimated"}) == ""
    assert ts.chosen("Protrusion type", {"branched", "spine"}) == "spine", (
        "two values from a pick-one set: the first in set order shows"
    )


# ---------------------------------------------------------------------------
# resolve: the dialog's whole answer, per trace
# ---------------------------------------------------------------------------
def test_resolve_replaces_the_free_tags_and_applies_the_choices():
    ts = _sets()
    old = {"shaft", "estimated", "mine"}
    assert ts.resolve(old, {"partial"}, {"Protrusion type": "spine"}) == {"spine", "partial"}
    assert old == {"shaft", "estimated", "mine"}, "the input set is not modified"


def test_resolve_none_free_tags_leaves_them_and_still_applies_the_choices():
    ts = _sets()
    assert ts.resolve({"shaft", "mine"}, None, {"Protrusion type": "spine"}) == {"spine", "mine"}
    assert ts.resolve({"shaft", "mine"}, None, {"Protrusion type": None}) == {"shaft", "mine"}


def test_resolve_add_tags_adds_instead_of_replacing():
    ts = _sets()
    assert ts.resolve({"mine"}, {"partial"}, {"Protrusion type": ""}, add_tags=True) == {"mine", "partial"}


def test_resolve_keeps_an_undisplayed_pick_one_value_through_a_replacement():
    """The pin from the plan: a pick-one row the selection disagreed on (None)
    must not lose its value on a trace just because the free rows were edited.
    The dialog never showed that value, so the user could not have kept it."""
    ts = _sets()
    assert ts.resolve({"shaft", "old"}, {"new"}, {"Protrusion type": None}) == {"shaft", "new"}
    assert ts.resolve({"spine", "old"}, {"new"}, {"Protrusion type": None}) == {"spine", "new"}


def test_resolve_with_no_choices_is_the_old_contract():
    ts = _sets()
    assert ts.resolve({"a"}, {"b"}, {}) == {"b"}
    assert ts.resolve({"a"}, None, {}) == {"a"}
    assert ts.resolve({"a"}, set(), {}) == set()


def test_section_edit_resolves_each_trace_from_its_own_tags(tmp_path):
    """Section.editTraceAttributes with tag_choices works per trace, so two
    traces that disagree on a pick-one set each keep their own value."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes import Series, Trace

    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.tag_sets = _sets()
    section = series.loadSection(min(series.sections))

    a = Trace("probe", (1, 2, 3), True)
    a.points = [(0, 0), (1, 0), (1, 1)]
    a.tags = {"shaft", "old"}
    b = a.copy()
    b.tags = {"spine", "old"}
    section.addTrace(a, log_event=False)
    section.addTrace(b, log_event=False)

    section.editTraceAttributes(
        [a, b], None, None, {"new"}, None, log_event=False,
        tag_choices={"Protrusion type": None},
    )
    got = sorted(sorted(t.tags) for t in section.contours["probe"])
    assert got == [["new", "shaft"], ["new", "spine"]]

    traces = list(section.contours["probe"])
    section.editTraceAttributes(
        traces, None, None, None, None, log_event=False,
        tag_choices={"Protrusion type": "branched"},
    )
    got = [set(t.tags) for t in section.contours["probe"]]
    assert got == [{"branched", "new"}, {"branched", "new"}]
    assert got[0] is not got[1]
    series.close()


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------
def test_merge_unions_tags_keeps_my_mode_and_fills_descriptions():
    mine = TagSets({"Protrusion type": {"mode": "one", "tags": ["spine"], "descriptions": {"spine": "mine"}}})
    theirs = TagSets({
        "Protrusion type": {"mode": "many", "tags": ["shaft", "spine"], "descriptions": {"spine": "theirs", "shaft": "their shaft"}},
        "Location": {"mode": "one", "tags": ["head"], "descriptions": {}},
    })
    assert mine.merge(theirs)
    assert mine.mode("Protrusion type") == MODE_ONE, "this side's mode wins"
    assert mine.tags("Protrusion type") == ["spine", "shaft"], "first-seen order"
    assert mine.description("Protrusion type", "spine") == "mine", "this side's text wins"
    assert mine.description("Protrusion type", "shaft") == "their shaft", "missing text is filled"
    assert mine.names() == ["Protrusion type", "Location"]
    assert not mine.merge(theirs), "a second merge changes nothing"
    assert not mine.merge(TagSets({}))


def test_merge_copies_not_references():
    mine = TagSets({})
    theirs = _sets()
    mine.merge(theirs)
    theirs.edit("Qualifiers", tags=["changed"])
    assert mine.tags("Qualifiers") == ["estimated", "partial"]


# ---------------------------------------------------------------------------
# series wiring
# ---------------------------------------------------------------------------
def test_series_key_is_declared_last_and_written():
    from PyReconstruct.modules.datatypes import Series
    assert SERIES_KEYS[-1] == "tag_sets", "appended so earlier keys keep their byte positions"
    assert Series.getEmptyDict()["tag_sets"] == {}


def test_old_file_without_the_key_backfills_empty():
    from PyReconstruct.modules.datatypes import Series
    series_data = Series.getEmptyDict()
    del series_data["tag_sets"]
    Series.updateJSON(series_data)
    assert series_data["tag_sets"] == {}
    assert list(series_data)[-1] == "tag_sets", "canonical order places it last"


def _open_fixture(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes import Series
    return Series.openJser(fp), fp


def test_series_round_trip_keeps_sets(tmp_path):
    series, fp = _open_fixture(tmp_path)
    try:
        assert series.tag_sets.names() == [], "the fixture predates tag sets"
        assert series.addTagSet("Protrusion type", MODE_ONE, PROTRUSION["tags"], PROTRUSION["descriptions"])
        assert series.addTagSet("Qualifiers", MODE_MANY, QUALIFIERS["tags"])
        assert not series.addTagSet("Qualifiers", MODE_MANY, ["again"])
        series.saveJser()
    finally:
        series.close()

    with open(fp, encoding="utf-8") as f:
        on_disk = json.load(f)["series"]["tag_sets"]
    assert on_disk == {"Protrusion type": PROTRUSION, "Qualifiers": QUALIFIERS}

    from PyReconstruct.modules.datatypes import Series
    reopened = Series.openJser(fp)
    try:
        assert reopened.tag_sets.names() == ["Protrusion type", "Qualifiers"]
        assert reopened.tag_sets.mode("Protrusion type") == MODE_ONE
        assert reopened.tag_sets.description("Protrusion type", "spine") == PROTRUSION["descriptions"]["spine"]
        assert reopened.editTagSet("Qualifiers", tags=["estimated"])
        assert reopened.tag_sets.tags("Qualifiers") == ["estimated"]
        assert reopened.removeTagSet("Protrusion type")
        assert not reopened.removeTagSet("Protrusion type")
        assert reopened.tag_sets.names() == ["Qualifiers"]
    finally:
        reopened.close()


def test_series_edits_are_logged(tmp_path):
    series, fp = _open_fixture(tmp_path)
    try:
        before = len(series.log_set.getList())
        series.addTagSet("Location", MODE_ONE, ["head", "neck"])
        series.editTagSet("Location", new_name="Where")
        series.removeTagSet("Where")
        series.removeTagSet("Where")  # a refused remove logs nothing
        events = [row for row in series.log_set.getList()[before:]]
        assert len(events) == 3, events
        assert any("Add tag set Location" in e for e in events)
        assert any("Edit tag set Location as Where" in e for e in events)
        assert any("Delete tag set Where" in e for e in events)
    finally:
        series.close()


def test_series_import_merges_sets(tmp_path):
    series, fp = _open_fixture(tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other, _ = _open_fixture(other_dir)
    try:
        series.addTagSet("Protrusion type", MODE_ONE, ["spine"])
        other.addTagSet("Protrusion type", MODE_MANY, ["shaft"])
        other.addTagSet("Location", MODE_ONE, ["head"])
        before = len(series.log_set.getList())
        series.importTagSets(other)
        assert series.tag_sets.tags("Protrusion type") == ["spine", "shaft"]
        assert series.tag_sets.mode("Protrusion type") == MODE_ONE
        assert "Location" in series.tag_sets
        assert len(series.log_set.getList()) == before + 1
        series.importTagSets(other)
        assert len(series.log_set.getList()) == before + 1, "a no-change import logs nothing"
    finally:
        series.close()
        other.close()
