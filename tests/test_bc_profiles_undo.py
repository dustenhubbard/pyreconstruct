"""Regression tests: renaming or deleting a brightness/contrast profile must be undoable.

`Series > Brightness/contrast profiles...` (`MainWindow.changeBCProfiles`) lets the
user create, rename and delete profiles, and applies the result with
`Series.modifyBCProfiles`, which rewrites `section.bc_profiles` on every section
in the series. The caller passed `self.field.series_states`, so the call read as
undoable. It was not, twice over:

1. `modifyBCProfiles` had no `series_states` parameter at all. Its signature was
   `(self, profiles_dict, log_event=True)`, so the `SeriesStates` object bound to
   `log_event`, where it is merely truthy. Logging happened by accident and no
   undo state was recorded.
2. Threading the argument through to `enumerateSections` is not enough on its
   own, which is the part worth keeping in a test. `SeriesIterator` records a
   per-section undo state only when the section reports
   `getAllModifiedNames() or tformsModified() or flags_modified`, and rewriting
   `bc_profiles` trips none of those, so `SeriesState.undo_lens` stayed empty and
   `SeriesStates.undoState` skipped its section loop entirely. Separately,
   `FieldState` stores contours, ztraces, tforms and flags, and nothing else, so
   even a recorded per-section state would not have carried the profiles.
   Measured before the fix: with `series_states` threaded and nothing else
   changed, `canUndo()` reported a 3D undo as available and the undo left all 198
   sections renamed.

So the profiles are recorded on the `SeriesState` itself
(`SeriesState.recordBCProfiles`) and restored in `SeriesStates.undoState`
alongside the per-section states.

Why not put `bc_profiles` in `FieldState` next to `tforms`, which would have been
the symmetric change: brightness and contrast are the one piece of section data
this app deliberately does not treat as undoable. `FieldWidget.setBrightness` and
`setContrast` change them without calling `saveState()`, and
`MainWindow.optimizeBC` gates itself behind `noUndoWarning()`. A `FieldState`
that carried `bc_profiles` would make any later undo (of a trace drawn after the
slider was moved, say) silently roll the user's brightness back. That is covered
by `test_a_section_undo_leaves_brightness_alone`.

The tests assert on values reloaded from disk, not on call counts.
"""

import ast
import pathlib

import pytest

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.func.state_manager import (
    SeriesStates,
    SectionStates,
)
from PyReconstruct.modules.backend.progress import NullProgressReporter


EXTRA = "extra"
RENAMED = "renamed"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERIES_PY = _REPO_ROOT / "PyReconstruct" / "modules" / "datatypes" / "series.py"
_MAIN_WINDOW_PY = (
    _REPO_ROOT / "PyReconstruct" / "modules" / "gui" / "main" / "main_window.py"
)


@pytest.fixture
def series_with_two_profiles(series_jser):
    """A real series whose sections each carry a second, per-section-distinct profile.

    Distinct per section is what makes a partial or cross-wired restore visible:
    a fixture with the same values everywhere could not tell a correct undo from
    one that put section 3's brightness onto section 7.
    """
    series = Series.openJser(str(series_jser))
    series.setProgressReporter(NullProgressReporter)
    written = {}
    for i, snum in enumerate(sorted(series.sections)):
        section = series.loadSection(snum)
        section.bc_profiles[EXTRA] = (10 + i, -20 - i)
        section.save()
        written[snum] = (10 + i, -20 - i)
    series.save()
    yield series, written
    series.close()


def _snapshot(series):
    """section number -> {profile name: [brightness, contrast]}, read from disk."""
    return {
        snum: dict(series.loadSection(snum).bc_profiles)
        for snum in sorted(series.sections)
    }


def _assert_profiles_equal(got, expected, message):
    assert set(got) == set(expected), message
    for snum in expected:
        assert set(got[snum]) == set(expected[snum]), (
            f"{message} (section {snum}: profile names differ, "
            f"{sorted(got[snum])} != {sorted(expected[snum])})"
        )
        for name, value in expected[snum].items():
            assert tuple(got[snum][name]) == tuple(value), (
                f"{message} (section {snum}, profile {name}: "
                f"{got[snum][name]} != {value})"
            )


# --- the signature and the call site -----------------------------------------


def test_modify_bc_profiles_accepts_series_states():
    """The parameter has to exist, and has to sit where its siblings' does.

    Without it the `SeriesStates` the caller passes lands on `log_event`, which
    is the whole bug: truthy, so nothing raises and nothing is recorded.
    """
    import inspect

    params = list(inspect.signature(Series.modifyBCProfiles).parameters)
    assert params == ["self", "profiles_dict", "series_states", "log_event"], (
        "modifyBCProfiles must take series_states in the same position as "
        f"modifyAlignments, got {params}"
    )
    assert (
        list(inspect.signature(Series.modifyAlignments).parameters)[2:]
        == params[2:]
    ), "modifyBCProfiles and modifyAlignments must agree on their tail arguments"


def test_change_bc_profiles_passes_series_states_by_keyword():
    """The call site must name the argument.

    A positional call is what let the object land on `log_event` unnoticed, and a
    positional call would do it again the next time the signature changes.
    """
    tree = ast.parse(_MAIN_WINDOW_PY.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "modifyBCProfiles"
    ]
    assert calls, "expected MainWindow to call modifyBCProfiles"
    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "series_states" in keywords, (
            f"main_window.py:{call.lineno} must pass series_states by keyword"
        )
        assert len(call.args) <= 1, (
            f"main_window.py:{call.lineno} passes {len(call.args)} positional "
            "arguments to modifyBCProfiles; only profiles_dict may be positional"
        )


def test_field_state_does_not_store_bc_profiles():
    """Guards the design decision, not an accident.

    If a later change moves `bc_profiles` into `FieldState`, every per-section
    undo starts reverting brightness and contrast, which this app deliberately
    does not treat as undoable. Change this test only alongside making
    `setBrightness`/`setContrast` record their own states.
    """
    from PyReconstruct.modules.backend.func.state_manager import FieldState

    assert not any(
        "bc_profile" in name for name in FieldState.__init__.__code__.co_varnames
    ), (
        "FieldState must not carry bc_profiles: see "
        "test_a_section_undo_leaves_brightness_alone"
    )


# --- the behavior -------------------------------------------------------------


def test_renaming_a_profile_is_undoable(series_with_two_profiles):
    """The reported case: rename a profile, undo, get the old name and values back."""
    series, written = series_with_two_profiles
    before = _snapshot(series)

    series_states = SeriesStates(series)
    series.modifyBCProfiles(
        {"default": "default", EXTRA: None, RENAMED: EXTRA},
        series_states=series_states,
    )

    after = _snapshot(series)
    for snum, value in written.items():
        assert RENAMED in after[snum], f"section {snum} must carry the new name"
        assert tuple(after[snum][RENAMED]) == value
        assert EXTRA not in after[snum]

    can_3D, _, _ = series_states.canUndo()
    assert can_3D, "a profile rename must leave an undoable series state"

    series_states.undoState()

    _assert_profiles_equal(
        _snapshot(series), before,
        "undo must restore every section's profiles exactly",
    )
    assert EXTRA in series.bc_profiles
    assert RENAMED not in series.bc_profiles


def test_deleting_a_profile_is_undoable(series_with_two_profiles):
    """Deletion is the destructive case: the values are gone, not just the name."""
    series, written = series_with_two_profiles
    before = _snapshot(series)

    series_states = SeriesStates(series)
    series.modifyBCProfiles(
        {"default": "default", EXTRA: None},
        series_states=series_states,
    )

    for snum in written:
        assert EXTRA not in series.loadSection(snum).bc_profiles, (
            f"section {snum}'s profile must have been deleted"
        )

    series_states.undoState()

    _assert_profiles_equal(
        _snapshot(series), before,
        "undo must give back the deleted profile's values on every section",
    )
    for snum, value in written.items():
        assert tuple(series.loadSection(snum).bc_profiles[EXTRA]) == value, (
            f"section {snum} must get its own values back, not another section's"
        )


def test_redo_reapplies_the_profile_change(series_with_two_profiles):
    """Undo then redo puts the change back, so the undo is not a one-way door."""
    series, _ = series_with_two_profiles
    before = _snapshot(series)

    series_states = SeriesStates(series)
    series.modifyBCProfiles(
        {"default": "default", EXTRA: None, RENAMED: EXTRA},
        series_states=series_states,
    )
    modified = _snapshot(series)

    series_states.undoState()
    _assert_profiles_equal(_snapshot(series), before, "undo must restore")

    can_3D, _, _ = series_states.canUndo(redo=True)
    assert can_3D, "a redo must be available after the undo"
    series_states.undoState(redo=True)

    _assert_profiles_equal(
        _snapshot(series), modified,
        "redo must re-apply the renamed profile",
    )


def test_undo_restores_the_selected_profile(series_with_two_profiles):
    """Undo must also restore `series.bc_profile`, or the next read raises.

    `Section.brightness` indexes `bc_profiles` by `series.bc_profile`. Renaming
    the profile the series is displaying and then undoing leaves that name
    pointing at a key that no longer exists, and `MainWindow.undo` calls
    `field.reload()` straight afterwards. The current alignment is stored in the
    series state for exactly this reason.
    """
    series, _ = series_with_two_profiles
    series.bc_profile = EXTRA

    series_states = SeriesStates(series)
    series.modifyBCProfiles(
        {"default": "default", EXTRA: None, RENAMED: EXTRA},
        series_states=series_states,
    )
    series.bc_profile = RENAMED  # what changeBCProfiles does after the rename

    series_states.undoState()

    assert series.bc_profile == EXTRA, (
        "undo must restore the profile the series was displaying"
    )
    section = series.loadSection(min(series.sections))
    assert section.brightness == 10, (
        "reading brightness after the undo must not raise"
    )


def test_a_2D_undo_cannot_dissolve_the_profile_change(series_with_two_profiles):
    """A per-section undo must not break the series-wide profile state.

    `breakable=False`. A series where some sections have the renamed profile and
    others do not is not merely wrong: `Series.bc_profiles` raises
    "Sections have differently named brightness/contrast profiles" on it.
    """
    series, _ = series_with_two_profiles
    snum = min(series.sections)
    series.current_section = snum
    before = _snapshot(series)

    series_states = SeriesStates(series)
    # give the current section a per-section undo of its own first, so that a 2D
    # undo is genuinely available and the guard is actually exercised
    section = series.loadSection(snum)
    series_states[section]
    section.modified_contours.add("undo-probe")
    series_states[snum].addState(section, series)
    section.save()

    series.modifyBCProfiles(
        {"default": "default", EXTRA: None, RENAMED: EXTRA},
        series_states=series_states,
    )
    assert len(series_states.undos) == 1
    assert not series_states.undos[-1].breakable, (
        "a series-wide profile change must record an unbreakable state"
    )

    can_3D, can_2D, _ = series_states.canUndo()
    assert can_2D, "the section's own undo must still be available"
    series_states.undoSection(series.loadSection(snum))

    assert len(series_states.undos) == 1, (
        "the 2D undo must not have dissolved the series-wide profile state"
    )
    series_states.undoState()
    _assert_profiles_equal(
        {s: p for s, p in _snapshot(series).items()},
        {s: p for s, p in before.items()},
        "the profile undo must still restore every section after a 2D undo",
    )


def test_a_section_undo_leaves_brightness_alone(series_with_two_profiles):
    """An unrelated undo must not revert a brightness adjustment.

    This is why `bc_profiles` is recorded on the series state rather than in
    `FieldState`. `setBrightness` does not call `saveState()`, so the app treats
    the sliders as not undoable, and a `FieldState` carrying `bc_profiles` would
    have made the undo of a later trace edit throw the adjustment away.
    """
    series, _ = series_with_two_profiles
    snum = min(series.sections)
    section = series.loadSection(snum)

    states = SectionStates(section, series)
    section.modified_contours.add("undo-probe")
    states.addState(section, series)

    # the user then nudges the brightness slider, which records nothing
    section.bc_profiles["default"] = (42, 7)

    states.undoState(section, series)

    assert tuple(section.bc_profiles["default"]) == (42, 7), (
        "a section undo must leave the brightness/contrast profiles untouched"
    )


def test_modify_bc_profiles_without_series_states_still_works(
    series_with_two_profiles,
):
    """The no-GUI path (`series_states=None`) must be unaffected."""
    series, written = series_with_two_profiles

    series.modifyBCProfiles({"default": "default", EXTRA: None, RENAMED: EXTRA})

    for snum, value in written.items():
        profiles = series.loadSection(snum).bc_profiles
        assert tuple(profiles[RENAMED]) == value
        assert EXTRA not in profiles


def test_modify_bc_profiles_threads_series_states_into_enumerate_sections():
    """Static guard: the argument must reach `enumerateSections`, unbreakably.

    `Series.importTransforms` accepted a `series_states` and never forwarded it,
    which is the same bug with a different shape. A signature check alone would
    not have caught that.
    """
    tree = ast.parse(_SERIES_PY.read_text(encoding="utf-8"))
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "modifyBCProfiles"
    )
    calls = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "enumerateSections"
    ]
    assert len(calls) == 1
    keywords = {
        kw.arg: kw.value
        for kw in calls[0].keywords
    }
    assert "series_states" in keywords
    assert isinstance(keywords["series_states"], ast.Name)
    assert keywords["series_states"].id == "series_states"
    assert "breakable" in keywords
    assert keywords["breakable"].value is False, (
        "a series-wide profile change must not record a breakable state"
    )
