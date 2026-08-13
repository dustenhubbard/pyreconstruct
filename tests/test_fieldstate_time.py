"""Every field state carries a time, so Ctrl+Z can always compare two of them.

The crash this pins, from a user's error report against v1.21.2 on macOS::

    File ".../gui/main/menubar.py", line 110, in <lambda>
    File ".../gui/main/main_window.py", line 3129, in undo
    File ".../backend/func/state_manager.py", line 731, in favor3D
    AttributeError: 'FieldState' object has no attribute 'time'

``favor3D`` decides which undo a Ctrl+Z should take when a series-wide undo and
a section-only undo are both available and unlinked, by comparing the newest
state on each stack: ``if state_3D.time > state_2D.time``. ``SeriesState`` sets
``time`` in its constructor, so the 3D side was always fine. ``FieldState`` did
not: the attribute was created only by ``updateTime()``, and the whole codebase
called that from exactly one place, ``SectionStates.addState``.

Two routes therefore put a field state on a stack with no ``time`` at all:

* ``undoState`` pushes ``current_state`` straight onto ``redo_states``, and
  ``current_state`` was built either by ``initialize`` or by the tail of
  ``addState``, neither of which stamps it.
* the state ``undoState`` pops back becomes ``current_state`` through
  ``copy()``, which rebuilds through ``__init__`` and so loses the stamp its
  original had. A later ``redoState`` then pushes that onto ``undo_states``.

So a Ctrl+Z that came after an undo could read ``.time`` off a state that never
had one, and raise instead of undoing anything. It survived a long time because
``favor3D`` only reaches the comparison when a series undo and a section undo
are both available AND unlinked, which needs series-wide and section-level edits
interleaved.

The fix is a floor rather than a patch of the one read: ``__init__`` stamps
every state at birth, and the two pushes that skipped ``updateTime`` now call
it, matching what ``addState`` always did. The tests below pin the invariant
(no state reaches a stack unstamped, by any route) rather than only the reported
call, because the reported call was one of several readers of a partial object.

Not a v1.21.2 regression: that release touched the object list, the color
button, the trace dialog and ``series_data``, and this file was not part of it.
"""

from PyReconstruct.modules.backend.func.state_manager import (
    SectionStates,
    SeriesStates,
)


def _states_for(series):
    """A `SectionStates` on the series' first section, with one edit recorded."""
    snum = min(series.sections)
    section = series.loadSection(snum)
    states = SectionStates(section, series)
    section.modified_contours.add("undo-probe")
    states.addState(section, series)
    return states, section


def _every_state(states):
    """Both stacks plus the live state, which is where the gaps appeared."""
    return [*states.undo_states, *states.redo_states, states.current_state]


# --------------------------------------------------------------------------- #
# the invariant: no state reaches a stack unstamped, by any route              #
# --------------------------------------------------------------------------- #
def test_a_fresh_state_is_already_stamped(real_series):
    """`initialize` builds `current_state`, and an undo pushes it as it is."""
    snum = min(real_series.sections)
    section = real_series.loadSection(snum)

    states = SectionStates(section, real_series)

    assert isinstance(states.current_state.time, int)


def test_states_stay_stamped_through_an_undo(real_series):
    states, section = _states_for(real_series)

    states.undoState(section, real_series)

    for state in _every_state(states):
        assert hasattr(state, "time"), "an undo left an unstamped state on a stack"


def test_states_stay_stamped_through_an_undo_then_a_redo(real_series):
    """The route that put an unstamped state back onto the *undo* stack."""
    states, section = _states_for(real_series)

    states.undoState(section, real_series)
    states.redoState(section, real_series)

    for state in _every_state(states):
        assert hasattr(state, "time"), "a redo left an unstamped state on a stack"


def test_a_copy_is_stamped(real_series):
    """`undoState` pops through `copy()`, which rebuilds through `__init__`."""
    states, _section = _states_for(real_series)

    duplicate = states.undo_states[-1].copy()

    assert isinstance(duplicate.time, int)


def test_a_push_restamps_rather_than_keeping_the_birth_time(real_series):
    """The stamp means "when this went onto a stack", which is what favor3D wants.

    The birth time is only the floor that makes the attribute total. A state
    pushed by an undo must carry the time of that undo, or the comparison
    against the series stack would be made on a number unrelated to the
    operation the user just performed.
    """
    states, section = _states_for(real_series)
    live = states.current_state
    birth = live.time
    live.time = birth - 100        # pretend it was born much earlier

    states.undoState(section, real_series)

    assert states.redo_states[-1] is live
    assert live.time >= birth, "the push did not restamp the state"


# --------------------------------------------------------------------------- #
# the reported call: favor3D's comparison                                      #
# --------------------------------------------------------------------------- #
def test_favor3d_compares_instead_of_raising(real_series, monkeypatch):
    """The line from the traceback, with both stacks populated.

    `canUndo` is forced to the one verdict that reaches the comparison, a
    series undo and a section undo both available and unlinked. Constructing
    that verdict from real edits needs a specific interleaving of series-wide
    and section-level operations; forcing it keeps this test about the
    comparison itself, which is what raised.
    """
    series_states = SeriesStates(real_series)
    series_states.addState()                       # series undos: 1

    snum = min(real_series.sections)
    real_series.current_section = snum
    states, section = _states_for(real_series)     # section undo_states: 1
    section.modified_contours.add("second-probe")
    states.addState(section, real_series)          # section undo_states: 2
    states.undoState(section, real_series)         # 1 undo, 1 redo: both stacks live
    series_states.section_states_dict[snum] = states

    monkeypatch.setattr(
        SeriesStates, "canUndo", lambda self, *a, **k: (True, True, False)
    )

    assert series_states.favor3D(snum) in (True, False)

    # the transfer a real series undo performs, so the redo branch has a state
    series_states.redos.append(series_states.undos.pop())

    assert series_states.favor3D(snum, redo=True) in (True, False)
