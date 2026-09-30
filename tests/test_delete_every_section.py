"""Deleting every section is refused before anything is deleted.

A series with no sections cannot be saved (``saveJser`` refuses it) and a .jser
with none cannot be reopened. Before this change the section list deleted the
files, cleared undo, and then raised ``IndexError`` looking for a section to
switch to, leaving an open series with nothing in it and no way to save.

Both layers refuse: the section list before its no-undo warning, and
``Series.deleteSections`` before it removes a file, so no other caller can empty
a series either.
"""

import os

import pytest

from test_delete_sections_duplicate_input import (
    assert_consistent,
    logged_deletions,
    open_fixture,
)


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    s.close()


# --------------------------------------------------------------------------
# the datatype
# --------------------------------------------------------------------------

def test_deleting_every_section_raises_and_deletes_nothing(series):
    everything = sorted(series.sections)

    with pytest.raises(ValueError):
        series.deleteSections(everything)

    assert_consistent(series, everything)
    assert not logged_deletions(series)


def test_repeats_that_cover_every_section_are_refused_too(series):
    everything = sorted(series.sections)

    with pytest.raises(ValueError):
        series.deleteSections(everything + everything[:2])

    assert_consistent(series, everything)


def test_deleting_all_but_one_section_still_works(series):
    everything = sorted(series.sections)

    series.deleteSections(everything[1:])

    assert_consistent(series, everything[:1])


# --------------------------------------------------------------------------
# the section list
# --------------------------------------------------------------------------

@pytest.mark.gui
def test_the_list_refuses_before_the_undo_warning(
    unlocked_section_table, gui_dialogs, monkeypatch
):
    from PyReconstruct.modules.gui.table import section as section_module

    warnings = []
    monkeypatch.setattr(
        section_module, "noUndoWarning", lambda *a, **k: warnings.append(1) or True
    )
    widget = unlocked_section_table
    series = widget.series
    before = sorted(series.sections)
    files = {snum: os.path.join(series.getwdir(), f) for snum, f in series.sections.items()}

    widget.table.selectAll()
    assert sorted(widget.getSelected()) == before
    widget.deleteSections()  # must not raise

    assert sorted(series.sections) == before
    assert all(os.path.exists(fp) for fp in files.values())
    assert not warnings, "the no-undo warning was shown for a delete that cannot happen"
    assert gui_dialogs.notices == [
        "Cannot delete every section. A series needs at least one."
    ]
