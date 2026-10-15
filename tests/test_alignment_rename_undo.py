"""Renaming an alignment is one undo step, on every section.

A rename keeps each section's transform under a new name, so the values do not
change. `Section.tformsModified` compared only the values, the rename looked
like no change, and no section undo state was saved. Undo then left the new
name on every section, and undoing the next alignment change put the old name
back along with it.

The rename here is the two calls `MainWindow.modifyAlignments` makes once the
dialog has been confirmed.
"""
import pytest

pytestmark = pytest.mark.gui


def _modify(window, alignment_dict):
    window.series.modifyAlignments(alignment_dict, window.field.series_states)
    window.createContextMenus()


def _add(window, name):
    alignment_dict = {a: a for a in window.series.alignments}
    alignment_dict[name] = window.series.alignment
    _modify(window, alignment_dict)


def _rename(window, old, new):
    alignment_dict = {a: a for a in window.series.alignments}
    alignment_dict[new] = old
    alignment_dict[old] = None
    _modify(window, alignment_dict)


def _names_on_disk(window):
    """Section number -> sorted alignment names, read from the section files."""
    series = window.series
    return {
        snum: sorted(series.loadSection(snum).tforms)
        for snum in sorted(series.sections)
    }


def _section_undo_count(window):
    states = window.field.series_states
    return sum(
        len(states[snum].undo_states)
        for snum in window.series.sections
        if states[snum].initialized
    )


@pytest.fixture
def renamed(main_window):
    """A series with an extra alignment, renamed from "extra" to "extra2"."""
    window = main_window
    _add(window, "extra")
    before = _section_undo_count(window)
    _rename(window, "extra", "extra2")
    return window, before


def test_renaming_records_one_section_undo_per_section(renamed):
    window, before = renamed
    sections = window.series.sections

    assert _section_undo_count(window) - before == len(sections)
    assert sorted(window.field.series_states.undos[-1].undo_lens) == sorted(sections)


def test_undo_restores_the_old_name_on_every_section(renamed):
    window, _ = renamed

    window.undo()

    for snum, names in _names_on_disk(window).items():
        assert "extra" in names, snum
        assert "extra2" not in names, snum
    assert "extra" in window.field.section.tforms


def test_redo_renames_it_again(renamed):
    window, _ = renamed
    window.undo()
    assert "extra" in window.field.section.tforms

    window.undo(True)

    for snum, names in _names_on_disk(window).items():
        assert "extra2" in names, snum
        assert "extra" not in names, snum


def test_undoing_the_next_change_keeps_the_new_name(renamed):
    window, _ = renamed
    _add(window, "copy")

    window.undo()

    for snum, names in _names_on_disk(window).items():
        assert "copy" not in names, snum
        assert "extra2" in names, snum
        assert "extra" not in names, snum


def test_a_rename_alone_is_not_a_scaling_change(main_window):
    section = main_window.series.loadSection(min(main_window.series.sections))
    current = main_window.series.alignment
    section.tforms = {
        ("renamed" if a == current else a): t for a, t in section.tforms.items()
    }

    assert section.tformsModified()
    assert not section.tformsModified(scaling_only=True)
