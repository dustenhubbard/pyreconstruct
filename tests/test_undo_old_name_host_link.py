"""Undoing the step that reused an old object's name gives the old object
its host link back.

H hosts T. T is deleted on one section, then H on another, so H's copy has no
traveler and only the record of dropped links keeps the link
(recordDroppedHostLinks). A new object named H hides that link, so it does
not take it. Undoing the new H shows the link again, and undoing both
deletes brings back T hosted by H.
"""
import pytest

from test_undo_object_followups import (
    _delete, _draw, _traces, NAME, OTHER,
)

pytestmark = pytest.mark.gui

HOST, TRAVELER, SPARE = NAME, OTHER, "undofu_spare"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _setup(window, host_first=False):
    """H on the first section, T on the second, a spare on the third; T is
    hosted by H. Delete T, then H (or H, then T)."""
    series = window.series
    first, second, third = sorted(series.sections)[:3]
    window.changeSection(first)
    _draw(window, HOST)
    window.changeSection(second)
    _draw(window, TRAVELER)
    window.changeSection(third)
    _draw(window, SPARE)
    series.host_tree.add(TRAVELER, [HOST])

    order = [(first, HOST), (second, TRAVELER)]
    if not host_first:
        order.reverse()
    for snum, name in order:
        window.changeSection(snum)
        _delete(window, _traces(window, name))
    return first, second, third


def _undo_both_deletes(window, first, second):
    series = window.series
    window.changeSection(second)
    window.undo()
    window.changeSection(first)
    window.undo()
    assert HOST in series.data["objects"]
    assert TRAVELER in series.data["objects"]
    return series.host_tree.getHosts(TRAVELER)


@pytest.mark.parametrize("redo", [False, True])
def test_undoing_a_draw_of_the_old_name_gives_the_link_back(window, redo):
    series = window.series
    first, second, third = _setup(window)
    window.changeSection(third)
    _draw(window, HOST, offset=0.5)
    window.undo()
    if redo:
        window.undo(redo=True)
        window.undo()
    assert HOST not in series.data["objects"]
    assert _undo_both_deletes(window, first, second) == [HOST]


def test_a_redone_draw_of_the_old_name_still_does_not_take_the_link(window):
    """H is deleted first, so T's copy has no host and only the record
    could link T to the new H."""
    series = window.series
    first, second, third = _setup(window, host_first=True)
    window.changeSection(third)
    _draw(window, HOST, offset=0.5)
    window.undo()
    window.undo(redo=True)
    assert HOST in series.data["objects"]

    window.changeSection(second)
    window.undo()
    assert TRAVELER in series.data["objects"]
    assert series.host_tree.getHosts(TRAVELER) == []


def test_a_draw_that_leaves_the_new_object_in_place_keeps_it_unlinked(window):
    """The new H is on two sections; undoing one draw leaves it in place, so
    the link stays forgotten."""
    series = window.series
    first, second, third = _setup(window, host_first=True)
    fourth = sorted(series.sections)[3]
    window.changeSection(third)
    _draw(window, HOST, offset=0.5)
    window.changeSection(fourth)
    _draw(window, HOST, offset=0.5)
    window.changeSection(third)
    window.undo()
    assert HOST in series.data["objects"]

    window.changeSection(second)
    window.undo()
    assert TRAVELER in series.data["objects"]
    assert series.host_tree.getHosts(TRAVELER) == []


def test_undoing_a_rename_to_the_old_name_gives_the_link_back(
        window, main_window_dialogs):
    series = window.series
    first, second, third = _setup(window)
    window.saveAllData()
    series.editObjectAttributes([SPARE], name=HOST,
                                series_states=window.field.series_states)
    window.field.reload()
    assert HOST in series.data["objects"]

    main_window_dialogs.linked_undo_responses = ["all"]
    window.changeSection(third)
    window.undo()
    assert HOST not in series.data["objects"]
    assert SPARE in series.data["objects"]
    assert _undo_both_deletes(window, first, second) == [HOST]


def _rename_spare_on_two_sections(window):
    """Put the spare on a fourth section too, then rename it to H on all
    sections."""
    series = window.series
    fourth = sorted(series.sections)[3]
    window.changeSection(fourth)
    _draw(window, SPARE)
    window.saveAllData()
    series.editObjectAttributes([SPARE], name=HOST,
                                series_states=window.field.series_states)
    window.field.reload()
    assert HOST in series.data["objects"]
    return fourth


def test_undoing_a_rename_on_two_sections_gives_the_link_back(
        window, main_window_dialogs):
    """Only the first section of the rename forgot the link; the undo of
    the last section is the one that deletes the new H."""
    series = window.series
    first, second, third = _setup(window)
    _rename_spare_on_two_sections(window)

    main_window_dialogs.linked_undo_responses = ["all"]
    window.changeSection(third)
    window.undo()
    assert HOST not in series.data["objects"]
    assert _undo_both_deletes(window, first, second) == [HOST]


def test_a_redone_section_of_a_rename_does_not_take_the_link(
        window, main_window_dialogs):
    """Undo the rename on each section, the last section first, so the link
    is back in the record. A redo on the last section alone creates a new H
    again, and it does not take the link."""
    series = window.series
    first, second, third = _setup(window)
    fourth = _rename_spare_on_two_sections(window)

    main_window_dialogs.linked_undo_responses = ["section"]
    window.changeSection(fourth)
    window.undo()
    assert HOST in series.data["objects"]
    window.changeSection(third)
    window.undo()
    assert HOST not in series.data["objects"]
    window.changeSection(second)
    window.undo()
    assert TRAVELER in series.data["objects"]
    assert series.host_tree.getHosts(TRAVELER) == []

    window.changeSection(fourth)
    window.undo(redo=True)
    assert HOST in series.data["objects"]
    assert series.host_tree.getHosts(TRAVELER) == []


def test_undoing_two_draws_of_the_old_name_gives_the_link_back(window):
    """The new H is drawn on two sections as two actions; only the first one
    created it. Undoing the first draw leaves H on the other section, and
    undoing the second draw deletes it."""
    series = window.series
    first, second, third = _setup(window)
    fourth = sorted(series.sections)[3]
    window.changeSection(third)
    _draw(window, HOST, offset=0.5)
    window.changeSection(fourth)
    _draw(window, HOST, offset=0.5)

    window.changeSection(third)
    window.undo()
    assert HOST in series.data["objects"]
    window.changeSection(fourth)
    window.undo()
    assert HOST not in series.data["objects"]
    assert _undo_both_deletes(window, first, second) == [HOST]


def test_a_redo_that_adds_to_the_old_object_keeps_its_link(
        window, main_window_dialogs):
    """After the rename is undone and the old H is back, a redo on one
    section adds traces to that H rather than creating a new one, so the
    old link stays saved for T."""
    series = window.series
    first, second, third = _setup(window, host_first=True)
    fourth = _rename_spare_on_two_sections(window)

    main_window_dialogs.linked_undo_responses = ["all", "section"]
    window.changeSection(third)
    window.undo()
    assert HOST not in series.data["objects"]
    window.changeSection(first)
    window.undo()
    assert HOST in series.data["objects"]

    window.changeSection(fourth)
    window.undo(redo=True)
    window.undo()
    window.changeSection(second)
    window.undo()
    assert TRAVELER in series.data["objects"]
    assert series.host_tree.getHosts(TRAVELER) == [HOST]


def test_the_old_link_does_not_reach_a_new_traveler(
        window, main_window_dialogs):
    """A new T is drawn while the new H exists. Undoing the rename and the
    old H's delete brings back the old H, and the new T stays unlinked."""
    series = window.series
    first, second, third = _setup(window)
    _rename_spare_on_two_sections(window)
    fifth = sorted(series.sections)[4]
    window.changeSection(fifth)
    _draw(window, TRAVELER, offset=0.5)

    main_window_dialogs.linked_undo_responses = ["all"]
    window.changeSection(third)
    window.undo()
    assert HOST not in series.data["objects"]
    window.changeSection(first)
    window.undo()
    assert HOST in series.data["objects"]
    assert series.host_tree.getHosts(TRAVELER) == []
