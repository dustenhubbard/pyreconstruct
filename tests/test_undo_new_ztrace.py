"""Undo on a section whose z-trace is newer than the section's states.

A z-trace created by a series-level operation (create-from-object) never
calls SectionStates.addState, so it is absent from the initial FieldState
snapshot. Move one of its points with a section edit afterwards and the
FIRST Ctrl+Z on that section indexed the missing name in the single-state
branch: KeyError instead of an undo (found 2026-08-28). The multi-state
branch already tolerated it; now both do.
"""

import pytest

pytestmark = pytest.mark.gui


def test_first_undo_survives_a_ztrace_newer_than_the_snapshot(real_series):
    from PyReconstruct.modules.backend.func.state_manager import SectionStates
    from PyReconstruct.modules.datatypes import Ztrace

    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)

    states = SectionStates(section, real_series)   # the initial snapshot

    # a series-level op creates a z-trace AFTER the snapshot...
    real_series.ztraces["born_late"] = Ztrace(
        "born_late", (255, 0, 255), [(0.0, 0.0, snum), (1.0, 1.0, snum)]
    )
    # ...then a section edit touches it, which records it as modified and
    # pushes the one undo state this test is about
    real_series.modified_ztraces.add("born_late")
    states.addState(section, real_series)

    assert len(states.undo_states) == 1             # the branch under test
    states.undoState(section, real_series)          # raised KeyError before

    # the late z-trace is simply left alone; the undo itself still happened
    assert "born_late" in real_series.ztraces
