"""A save during a change to every section's profiles or alignments is refused.

Changing the brightness/contrast profiles or the alignments (renaming,
creating or deleting one) rewrites every section one by one under a progress
dialog. Every progress update runs the event loop, where a .jser opened from
the Finder asks to save this series. A save there wrote a file out of step:

  * profiles: the sections already rewritten carried the new name and the
    rest the old one, under a series file naming the old one. The series
    opened on the default profile, and Series.bc_profiles raised on it
  * alignments: the sections disagreed about which alignments exist, and the
    window raised "Sections have differently named alignments." opening it

What is pinned here:

  * a .jser save at a middle or the last progress update of either change is
    refused with a notice, as a save during a series undo is
    (SeriesSaveError), writes nothing, and the change finishes
  * a save after the change writes the sections and the series in step
  * a step inside another keeps the refusal until the outer one ends
  * in the window, a .jser opened from the Finder during either change is
    skipped with the notice and no save prompt, and the window keeps its
    series
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
WHY = {
    "profiles": "in the middle of changing its brightness/contrast profiles",
    "alignments": "in the middle of changing its alignments",
}
KINDS = list(WHY)

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
    _add_extra_profile(opened)
    opened.save()
    yield opened
    opened.leave_open = False
    opened.close()


def _add_extra_profile(series):
    for i, snum in enumerate(sorted(series.sections)):
        section = series.loadSection(snum)
        section.bc_profiles[EXTRA] = (10 + i, -20 - i)
        section.save()
    series.bc_profile = EXTRA


def _alignment_rename(series):
    """The dialog's dict for renaming the current alignment: every name it
    lists, the old one deleted and the new one made from it."""
    current = series.alignment
    names = series.data["sections"][min(series.sections)]["tforms"]
    adict = {a: a for a in names}
    adict[current] = None
    adict[RENAMED] = current
    return adict


def _rename(series, kind):
    """Rename the current profile or alignment, as the window does."""
    if kind == "profiles":
        series.modifyBCProfiles({"default": "default", EXTRA: None, RENAMED: EXTRA})
        series.bc_profile = RENAMED
    else:
        series.modifyAlignments(_alignment_rename(series))
        series.alignment = RENAMED


class _Notes:
    """A notifier that keeps every notice."""

    def __init__(self):
        self.seen = []

    def notify(self, message):
        self.seen.append(message)
        return True


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _saves_at(series, update):
    """Try a .jser save at the given progress update of the next pass."""
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

    series.setProgressReporter(SavesAt)
    return seen


def _as_saved(jser_fp, tmp_path):
    """Open a copy of the saved .jser as written: the profile it names is not
    repointed. Returns the series' profile and alignment, and the profile and
    alignment names on each section."""
    from PyReconstruct.modules.datatypes.series import Series
    copy_fp = tmp_path / "saved" / "saved.jser"
    copy_fp.parent.mkdir(exist_ok=True)
    shutil.copyfile(jser_fp, copy_fp)
    mp = pytest.MonkeyPatch()
    mp.setattr(Series, "_repointBCProfile", lambda self: None)
    try:
        saved = Series.openJser(str(copy_fp), progress=NullProgressReporter)
    finally:
        mp.undo()
    try:
        sections = saved.data["sections"].values()
        return (
            saved.bc_profile,
            saved.alignment,
            [set(d["bc_profiles"]) for d in sections],
            [set(d["tforms"]) for d in sections],
        )
    finally:
        saved.close()


def _in_step(jser_fp, tmp_path):
    """True if every section of the saved series has the same profile and
    alignment names, and they include the ones the series displays."""
    profile, alignment, profiles, alignments = _as_saved(jser_fp, tmp_path)
    return (
        all(p == profiles[0] for p in profiles)
        and all(a == alignments[0] for a in alignments)
        and profile in profiles[0]
        and alignment in alignments[0]
    )


@pytest.mark.parametrize("update", list(UPDATES))
@pytest.mark.parametrize("kind", KINDS)
def test_a_save_during_a_rename_is_refused(series, tmp_path, kind, update):
    notes = _Notes()
    series.setNotifier(notes)
    assert _in_step(series.jser_fp, tmp_path)
    before = _digest(series.jser_fp)
    seen = _saves_at(series, update)

    _rename(series, kind)

    # the file on disk was never written out of step
    assert _in_step(series.jser_fp, tmp_path)
    assert seen["tried"] and seen["running"]
    assert seen["raised"] == f"this series is {WHY[kind]}, so this save was skipped."
    assert notes.seen == [
        f"Save skipped: this series is {WHY[kind]}."
        f"\n\nThis save wrote nothing to:\n{series.jser_fp}"
    ]
    assert _digest(series.jser_fp) == before
    assert not series.seriesStepRunning()
    # the rename finished, and the next save is in step
    series.setProgressReporter(NullProgressReporter)
    series.saveJser()
    profile, alignment, profiles, alignments = _as_saved(series.jser_fp, tmp_path)
    if kind == "profiles":
        assert profile == RENAMED
        assert all(p == {"default", RENAMED} for p in profiles)
    else:
        assert alignment == RENAMED
        assert all(RENAMED in a and "default" not in a for a in alignments)
    assert _in_step(series.jser_fp, tmp_path)


def test_a_step_inside_another_keeps_the_refusal(series):
    from PyReconstruct.modules.datatypes.series import SeriesSaveError
    series.setNotifier(_Notes())
    with series.seriesStep():
        with series.seriesStep(WHY["alignments"]):
            pass
        assert series.seriesStepRunning()
        with pytest.raises(SeriesSaveError, match="undo or redo"):
            series.saveJser()
    assert not series.seriesStepRunning()


# --- in the window ------------------------------------------------------------


class _Accepts:
    """A profiles or alignments dialog the user accepts with the given dict."""

    def __init__(self, response):
        self.response = response

    def __call__(self, *args, **kwargs):
        return self

    def exec(self):
        return self.response, True


@pytest.mark.gui
@pytest.mark.parametrize("update", list(UPDATES))
@pytest.mark.parametrize("kind", KINDS)
def test_a_finder_open_during_a_rename_is_skipped(
    kind, update, main_window, main_window_dialogs, monkeypatch, tmp_path,
    qtbot,
    screen,  # noqa: F811
    finder,  # noqa: F811
):
    from PyReconstruct.modules.gui.main import main_window as main_window_module
    window = main_window
    first = window.series
    if kind == "profiles":
        _add_extra_profile(first)
        window.field.reload()
        monkeypatch.setattr(
            main_window_module, "BCProfilesDialog",
            _Accepts((RENAMED, {"default": "default", EXTRA: None, RENAMED: EXTRA})),
        )
    else:
        monkeypatch.setattr(
            main_window_module, "AlignmentDialog",
            _Accepts((RENAMED, _alignment_rename(first))),
        )
    # unsaved, so closing it would ask
    window.seriesModified(True)
    main_window_dialogs.save_response = "yes"
    _b_opens_during_the_combine(
        window, tmp_path, qtbot, update, _offer_copy_from_finder
    )

    if kind == "profiles":
        window.changeBCProfiles()
    else:
        window.modifyAlignments()

    assert window.series is first and not first.closed
    assert main_window_dialogs.save_prompts == 0
    assert screen.reports == []
    assert len(screen.notices) == 1
    assert screen.notices[0].startswith(f"Save skipped: this series is {WHY[kind]}.")
    assert first.jser_fp in screen.notices[0]
    assert not first.seriesStepRunning()
    # the rename finished on this series, and it saves in step
    if kind == "profiles":
        assert first.bc_profile == RENAMED
    else:
        assert first.alignment == RENAMED
    first.setProgressReporter(NullProgressReporter)
    assert window.saveToJser() is None
    assert _in_step(first.jser_fp, tmp_path)
