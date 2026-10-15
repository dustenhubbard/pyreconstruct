"""A save during a series undo or redo is refused, so the saved series stays in step.

A series undo or redo (SeriesStates.undoState) restores and writes its
sections one by one under a progress dialog, and puts the series attributes
back only after the last section. Every progress update runs the event loop,
where a .jser opened from the Finder asks to save this series. A save there
wrote the restored sections with the series attributes from before the step.
Undoing a brightness/contrast profile rename that way saved sections carrying
the old profile name under a series file still naming the new one, and
Section.brightness raised KeyError on the next open.

What is pinned here:

  * a .jser save at a middle or the last progress update of a series undo
    or redo is refused with a notice, as a save during a save is
    (SeriesSaveError), writes nothing, and the step finishes
  * a save after the step writes the sections and the displayed profile in
    step, and every section of the saved series reads its brightness
  * the refusal ends with the step, also when the step stops part-way
  * a series already saved out of step opens: the displayed profile is
    pointed at the default profile, or at the first profile every section
    has; a series whose sections share no profile is left as it is
  * in the window, a .jser opened from the Finder during a series undo is
    skipped with the notice and no save prompt, the window keeps its
    series, and the undo finishes; Save As and a backup during the undo
    are skipped the same way, with no file dialog and no error report
"""
import hashlib
import shutil

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from tests.test_cleanup_lists_series_switch import (  # noqa: F401  (fixture)
    finder,
)
from tests.test_combine_duplicates_series_switch import (
    _b_opens_during_the_combine,
    _offer_copy_from_finder,
)
from tests.test_nested_save_notice import screen  # noqa: F401  (fixture)

EXTRA = "extra"
RENAMED = "renamed"
SKIPPED = "Save skipped: this series is in the middle of an undo or redo."
REFUSED = "this series is in the middle of an undo or redo, so this save was skipped."

UPDATES = {
    "middle": lambda percent: 0 < percent < 100,
    "last": lambda percent: percent >= 100,
}


@pytest.fixture
def series(series_jser):
    """The fixture series with a second profile on every section, displayed."""
    from PyReconstruct.modules.datatypes.series import Series
    opened = Series.openJser(str(series_jser), progress=NullProgressReporter)
    opened.setProgressReporter(NullProgressReporter)
    for i, snum in enumerate(sorted(opened.sections)):
        section = opened.loadSection(snum)
        section.bc_profiles[EXTRA] = (10 + i, -20 - i)
        section.save()
    opened.bc_profile = EXTRA
    opened.save()
    yield opened
    opened.leave_open = False
    opened.close()


class _Notes:
    """A notifier that keeps every notice."""

    def __init__(self):
        self.seen = []

    def notify(self, message):
        self.seen.append(message)
        return True


def _rename_extra(series, states):
    """Rename the displayed profile, as the profiles dialog does."""
    series.modifyBCProfiles(
        {"default": "default", EXTRA: None, RENAMED: EXTRA},
        series_states=states,
    )
    series.bc_profile = RENAMED


def _profiles_on_disk(series):
    return {
        snum: set(series.loadSection(snum).bc_profiles)
        for snum in sorted(series.sections)
    }


def _reads_brightness_everywhere(jser_fp, tmp_path):
    """Open a copy of the saved .jser, read every section's brightness, and
    return the profile it displays. A copy: the series that wrote it still
    holds the working folder beside it."""
    from PyReconstruct.modules.datatypes.series import Series
    copy_fp = tmp_path / "saved" / "saved.jser"
    copy_fp.parent.mkdir(exist_ok=True)
    shutil.copyfile(jser_fp, copy_fp)
    saved = Series.openJser(str(copy_fp), progress=NullProgressReporter)
    try:
        for snum in sorted(saved.sections):
            saved.loadSection(snum).brightness
        return saved.bc_profile
    finally:
        saved.close()


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _saves_at(series, update, then=None):
    """Try a .jser save at the given progress update of the next pass.

    Records whether the step was running then and what the save raised.
    then runs after the save, as the rest of opening another series does.
    """
    from PyReconstruct.modules.datatypes.series import SeriesSaveError
    seen = {"tried": False, "running": None, "raised": None}

    class SavesAt(NullProgressReporter):
        def set_progress(self, percent):
            if seen["tried"] or not UPDATES[update](percent):
                return
            seen["tried"] = True
            seen["running"] = series.seriesStepRunning()
            try:
                series.saveJser()
            except SeriesSaveError as e:
                seen["raised"] = str(e)
            if then is not None:
                then()

    series.setProgressReporter(SavesAt)
    return seen


@pytest.mark.parametrize("update", list(UPDATES))
@pytest.mark.parametrize("redo", [False, True], ids=["undo", "redo"])
def test_a_save_during_a_series_step_is_refused(
    series, tmp_path, redo, update
):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    states = SeriesStates(series)
    _rename_extra(series, states)
    if redo:
        states.undoState()
        assert series.bc_profile == EXTRA
    expected = RENAMED if redo else EXTRA
    notes = _Notes()
    series.setNotifier(notes)
    before = _digest(series.jser_fp)
    seen = _saves_at(series, update)

    states.undoState(redo=redo)

    assert seen["tried"] and seen["running"]
    assert seen["raised"] == REFUSED
    assert notes.seen == [
        f"{SKIPPED}\n\nThis save wrote nothing to:\n{series.jser_fp}"
    ]
    assert _digest(series.jser_fp) == before
    assert not series.seriesStepRunning()
    # the step finished: every section and the displayed profile
    assert series.bc_profile == expected
    assert all(expected in names for names in _profiles_on_disk(series).values())
    # and the next save is in step
    series.setProgressReporter(NullProgressReporter)
    series.saveJser()
    assert _reads_brightness_everywhere(series.jser_fp, tmp_path) == expected


def test_the_refusal_ends_with_a_step_that_stops_part_way(series):
    """Another series opened at a middle update closes this one after the
    refused save, and the step stops at the next section."""
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    states = SeriesStates(series)
    _rename_extra(series, states)
    series.setNotifier(_Notes())
    seen = _saves_at(series, "middle", then=series.close)

    with pytest.raises(SeriesClosedError, match="part-way"):
        states.undoState()

    assert seen["running"] and seen["raised"] == REFUSED
    assert series.closed and not series.seriesStepRunning()


@pytest.mark.parametrize("names, pointer, expected", [
    ({"default", EXTRA}, RENAMED, "default"),
    ({EXTRA, "zeta"}, RENAMED, EXTRA),
    ({"default", EXTRA}, EXTRA, EXTRA),
], ids=["default", "first every section has", "kept"])
def test_a_series_saved_out_of_step_opens(
    series, tmp_path, names, pointer, expected
):
    """The first case is the file the interrupted undo saved: the sections
    have their old profiles back, the series still names the new one."""
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        section.bc_profiles = {
            name: section.bc_profiles.get(name, (0, 0)) for name in names
        }
        section.save()
    series.bc_profile = pointer
    series.saveJser()

    assert _reads_brightness_everywhere(series.jser_fp, tmp_path) == expected


def test_sections_sharing_no_profile_are_left_as_they_are(series, tmp_path):
    from PyReconstruct.modules.datatypes.series import Series
    snums = sorted(series.sections)
    for snum in snums:
        section = series.loadSection(snum)
        section.bc_profiles = {"a" if snum == snums[0] else "b": (0, 0)}
        section.save()
    series.bc_profile = RENAMED
    series.saveJser()
    copy_fp = tmp_path / "saved" / "saved.jser"
    copy_fp.parent.mkdir()
    shutil.copyfile(series.jser_fp, copy_fp)

    saved = Series.openJser(str(copy_fp), progress=NullProgressReporter)
    try:
        assert saved.bc_profile == RENAMED
        with pytest.raises(KeyError, match=RENAMED):
            saved.loadSection(snums[0]).brightness
    finally:
        saved.close()


# --- in the window ------------------------------------------------------------


def _window_renames_default(window):
    """Rename the displayed profile, as the profiles dialog does, so a series
    undo is available."""
    window.series.modifyBCProfiles(
        {RENAMED: "default"}, series_states=window.field.series_states
    )
    window.series.bc_profile = RENAMED
    window.field.reload()
    assert window.field.series_states.canUndo()[0]


@pytest.mark.gui
@pytest.mark.parametrize("update", list(UPDATES))
def test_a_finder_open_during_a_series_undo_is_skipped(
    update, main_window, main_window_dialogs, tmp_path, qtbot,
    screen,  # noqa: F811
    finder,  # noqa: F811
):
    window = main_window
    first = window.series
    _window_renames_default(window)
    # unsaved, so closing it would ask
    window.seriesModified(True)
    main_window_dialogs.save_response = "yes"
    _b_opens_during_the_combine(
        window, tmp_path, qtbot, update, _offer_copy_from_finder
    )

    window.undo()

    assert window.series is first and not first.closed
    assert main_window_dialogs.save_prompts == 0
    assert screen.reports == []
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(SKIPPED)
    assert first.jser_fp in screen.notices[0]
    # the undo finished on this series
    assert not first.seriesStepRunning()
    assert first.bc_profile == "default"
    assert all(names == {"default"} for names in _profiles_on_disk(first).values())
    assert set(window.field.section.bc_profiles) == {"default"}
    # and the series saves and opens again in step
    first.setProgressReporter(NullProgressReporter)
    assert window.saveToJser() is None
    assert _reads_brightness_everywhere(first.jser_fp, tmp_path) == "default"


@pytest.mark.gui
@pytest.mark.parametrize("action", ["save as", "backup"])
def test_save_as_and_backup_during_a_series_undo_are_skipped(
    action, main_window, main_window_dialogs, monkeypatch,
    screen,  # noqa: F811
):
    window = main_window
    first = window.series
    _window_renames_default(window)
    written = []
    monkeypatch.setattr(
        type(first), "_saveJser", lambda self, *a, **k: written.append(a)
    )
    dialogs_before = len(main_window_dialogs.dialogs)
    seen = {}

    class Inside(NullProgressReporter):
        def set_progress(self, percent):
            if seen or not UPDATES["middle"](percent):
                return
            seen["running"] = first.seriesStepRunning()
            if action == "save as":
                seen["result"] = window.saveAsToJser()
            else:
                seen["result"] = window.backup()

    first.setProgressReporter(Inside)

    window.undo()

    assert seen["running"]
    assert seen["result"] == ("cancel" if action == "save as" else None)
    assert written == []
    assert len(main_window_dialogs.dialogs) == dialogs_before
    assert screen.reports == []
    assert [n.splitlines()[0] for n in screen.notices] == [SKIPPED]
    assert first.bc_profile == "default"
    assert all(names == {"default"} for names in _profiles_on_disk(first).values())
