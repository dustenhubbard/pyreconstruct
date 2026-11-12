"""Trace attribute edits preserve geometry, selection, and independent tag sets."""

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, Trace


@pytest.fixture
def section(shapes1_jser):
    series = Series.openJser(str(shapes1_jser), progress=NullProgressReporter)
    series.setSettingsStore(DictSettingsStore())
    series.setProgressReporter(NullProgressReporter)
    try:
        section = series.loadSection(min(series.sections))
        section.deselectAllTraces()
        yield section
    finally:
        series.close()


def add_trace(section, name, x, tags):
    trace = Trace(name, (10, 20, 30), closed=True)
    trace.points = [(x, 0), (x + 2, 0), (x + 2, 2), (x, 2)]
    trace.tags = set(tags)
    trace.fill_mode = ("transparent", "selected")
    section.addTrace(trace, log_event=False)
    return trace


def test_renaming_selected_traces_merges_into_the_destination_contour(section):
    selected = add_trace(section, "source", 0, {"selected"})
    untouched = add_trace(section, "source", 10, {"untouched"})
    destination = add_trace(section, "destination", 20, {"existing"})
    section.addSelectedTrace(selected)

    section.editTraceAttributes(
        [selected], "destination", (40, 50, 60), None, ("solid", None),
        log_event=False,
    )

    assert list(section.contours["source"]) == [untouched]
    assert len(section.contours["destination"]) == 2
    assert section.contours["destination"][0] is destination
    edited = section.contours["destination"][1]
    assert edited.name == "destination"
    assert list(edited.points) == [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert edited.color == (40, 50, 60)
    assert edited.tags == {"selected"}
    assert edited.fill_mode == ("solid", "selected")
    assert section.selected_traces == [edited]
    assert untouched.tags == {"untouched"}
    assert destination.color == (10, 20, 30)
    assert destination.tags == {"existing"}
    assert {"source", "destination"} <= section.getAllModifiedNames()


@pytest.mark.parametrize(
    ("tags", "add_tags", "expected"),
    [
        (None, False, [{"a"}, {"b"}]),
        (set(), False, [set(), set()]),
        ({"new"}, False, [{"new"}, {"new"}]),
        ({"new"}, True, [{"a", "new"}, {"b", "new"}]),
    ],
)
def test_editing_tags_keeps_each_trace_independent(section, tags, add_tags, expected):
    a = add_trace(section, "tagged", 0, {"a"})
    b = add_trace(section, "tagged", 10, {"b"})
    section.addSelectedTrace(a)

    section.editTraceAttributes(
        [a, b], None, None, tags, (None, "always"),
        add_tags=add_tags, log_event=False,
    )

    edited_a, edited_b = section.contours["tagged"]
    assert [edited_a.tags, edited_b.tags] == expected
    assert [edited_a.fill_mode, edited_b.fill_mode] == [
        ("transparent", "always"), ("transparent", "always"),
    ]
    assert section.selected_traces == [edited_a]
    assert list(edited_b.points) == [(10, 0), (12, 0), (12, 2), (10, 2)]
    edited_a.tags.add("only-first")
    assert edited_b.tags == expected[1]
    if tags is not None:
        assert tags == (set() if not tags else {"new"})
    assert a.tags == {"a"}
    assert b.tags == {"b"}
