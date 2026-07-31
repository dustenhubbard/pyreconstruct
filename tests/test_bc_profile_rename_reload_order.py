"""Regression tests: renaming the displayed brightness/contrast profile must not raise.

`Series > Brightness/contrast profiles...` (`MainWindow.changeBCProfiles`) applied
its result in this order:

    self.series.modifyBCProfiles(profiles_dict, series_states=...)
    self.field.reload()
    ...
    self.field.changeBCProfile(profile_name or self.series.bc_profile)

`series.bc_profile` names the profile the field is displaying, and
`Section.brightness`/`Section.contrast` index `section.bc_profiles` by that name.
`modifyBCProfiles` rewrites `bc_profiles` on every section, so renaming the
displayed profile deletes the key `series.bc_profile` points at. The reload came
next, `FieldWidget.reload` calls `mouse_palette.updateBC()`, and `updateBC` reads
`field.section.brightness`: `KeyError` on the forward path, before undo is
involved.

Swapping the two lines does not fix it. `FieldWidget.changeBCProfile` also calls
`mouse_palette.updateBC()`, and before the reload `field.section` is still the
stale in-memory object carrying the *old* profile names, so switching first
raises on the new name instead of the old one. Covered by
`test_switching_before_the_reload_would_also_raise`.

The fix remaps `series.bc_profile` through `profiles_dict` between the rewrite and
the reload, so the reload reads a key that exists. Deletion of the displayed
profile is the same failure with no forward target at all, so it falls back to
`default`, which the dialog refuses to remove or rename.

These tests drive the real `MainWindow.changeBCProfiles` with a stub `self`, not a
real window: constructing `MainWindow` headless hangs on a startup modal. The
stub's `reload`/`changeBCProfile` call the real `MousePalette.updateBC`, so the
`KeyError` is raised by the real reader rather than by a re-implementation of it,
and `test_the_stub_field_matches_the_real_reload` pins the stub to the real
methods it stands in for.
"""

import ast
import pathlib

import pytest

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.gui.main import main_window as main_window_module
from PyReconstruct.modules.gui.main.main_window import MainWindow
from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette


EXTRA = "extra"
RENAMED = "renamed"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUI_MAIN = _REPO_ROOT / "PyReconstruct" / "modules" / "gui" / "main"
_MAIN_WINDOW_PY = _GUI_MAIN / "main_window.py"
_FIELD_BASE_PY = _GUI_MAIN / "field_widget_1_base.py"
_FIELD_VIEW_PY = _GUI_MAIN / "field_widget_7_view.py"
_MOUSE_PALETTE_PY = (
    _REPO_ROOT / "PyReconstruct" / "modules" / "gui" / "palette" / "mouse_palette.py"
)


# --- the stub window ----------------------------------------------------------


class _StubWidget:
    """A button or a slider, as far as `MousePalette.updateBC` is concerned."""

    def __init__(self):
        self.text = None
        self.value = None

    def setText(self, text):
        self.text = text

    def setValue(self, value):
        self.value = value


class _StubPalette:
    """`MousePalette`, reduced to what `updateBC` touches.

    `updateBC` is the real method, called unbound. That is the point: the read
    that raises is the shipped one.
    """

    def __init__(self, mainwindow):
        self.mainwindow = mainwindow
        self.bc_widgets = [
            (_StubWidget(), _StubWidget()),
            (_StubWidget(), _StubWidget()),
        ]
        self.update_count = 0

    def updateBC(self):
        self.update_count += 1
        MousePalette.updateBC(self)


class _StubField:
    """`FieldWidget`, reduced to what `changeBCProfiles` calls.

    `reload` and `changeBCProfile` reproduce only the part of the real methods
    that reads brightness/contrast, which is the `mouse_palette.updateBC()` call
    both of them make. `test_the_stub_field_matches_the_real_reload` asserts that
    both real methods still make it.
    """

    def __init__(self, series, mainwindow):
        self.series = series
        self.mainwindow = mainwindow
        self.series_states = SeriesStates(series)
        self.section = series.loadSection(series.current_section)
        self.reload_count = 0
        self.switched_to = []

    def reload(self, clear_states=False):
        self.reload_count += 1
        self.section = self.series.loadSection(self.series.current_section)
        self.mainwindow.mouse_palette.updateBC()

    def changeBCProfile(self, new_profile):
        self.switched_to.append(new_profile)
        self.series.bc_profile = new_profile
        self.mainwindow.mouse_palette.updateBC()


class _StubWindow:
    """`self` for the real `MainWindow.changeBCProfiles`."""

    changeBCProfiles = MainWindow.changeBCProfiles

    def __init__(self, series):
        self.series = series
        self.mouse_palette = _StubPalette(self)
        self.field = _StubField(series, self)
        self.save_count = 0

    def saveAllData(self):
        self.save_count += 1


class _StubDialog:
    """`BCProfilesDialog`, scripted with the response the user would have made.

    `main_window.py` pulls the dialog in through `from .main_imports import *`, so
    the name has to be patched on `main_window` itself. Patching it at its source
    module would leave the star-imported binding in place.
    """

    response = None
    confirmed = True

    def __init__(self, *args, **kwargs):
        self.args = args

    def exec(self):
        return type(self).response, type(self).confirmed


@pytest.fixture
def profiled_series(series_jser):
    """A real series displaying a second, non-`default` profile.

    Per-section-distinct values so that a wrong-section read is visible rather
    than accidentally correct.
    """
    series = Series.openJser(str(series_jser))
    series.setProgressReporter(NullProgressReporter)
    written = {}
    for i, snum in enumerate(sorted(series.sections)):
        section = series.loadSection(snum)
        section.bc_profiles[EXTRA] = (10 + i, -20 - i)
        section.save()
        written[snum] = (10 + i, -20 - i)
    series.current_section = min(series.sections)
    series.bc_profile = EXTRA
    series.save()
    yield series, written
    series.close()


@pytest.fixture
def scripted_dialog(monkeypatch):
    """Install the stub dialog and return a callable that scripts its response."""
    monkeypatch.setattr(main_window_module, "BCProfilesDialog", _StubDialog)

    def script(profile_name, profiles_dict, confirmed=True):
        _StubDialog.response = (profile_name, profiles_dict)
        _StubDialog.confirmed = confirmed

    yield script
    _StubDialog.response = None
    _StubDialog.confirmed = True


# --- the reported crash -------------------------------------------------------


def test_renaming_the_displayed_profile_does_not_raise(
    profiled_series, scripted_dialog
):
    """The reported case.

    The dialog rebuilds its table on a rename, which clears the selection, so
    `profile_name` comes back `None` and nothing switches the profile before the
    reload. Before the fix this raised `KeyError: 'extra'` from
    `MousePalette.updateBC`.
    """
    series, written = profiled_series
    window = _StubWindow(series)
    scripted_dialog(None, {"default": "default", EXTRA: None, RENAMED: EXTRA})

    window.changeBCProfiles()

    assert window.field.reload_count == 1
    assert series.bc_profile == RENAMED, (
        "the displayed profile must follow the rename"
    )
    snum = series.current_section
    section = series.loadSection(snum)
    assert tuple(section.bc_profiles[RENAMED]) == written[snum]
    assert EXTRA not in section.bc_profiles
    b_bttn, _ = window.mouse_palette.bc_widgets[0]
    assert b_bttn.text == str(written[snum][0]), (
        "the palette must show the renamed profile's brightness"
    )


def test_renaming_the_displayed_profile_with_it_still_selected(
    profiled_series, scripted_dialog
):
    """Same rename, with the new name selected in the list on OK.

    The user can click the renamed row before pressing OK, which makes
    `profile_name` the new name. That does not save the forward path: the reload
    still runs first.
    """
    series, written = profiled_series
    window = _StubWindow(series)
    scripted_dialog(RENAMED, {"default": "default", EXTRA: None, RENAMED: EXTRA})

    window.changeBCProfiles()

    assert series.bc_profile == RENAMED
    assert window.field.switched_to == [RENAMED]


def test_renaming_a_profile_that_is_not_displayed_is_unaffected(
    profiled_series, scripted_dialog
):
    """The case that always worked: the displayed profile keeps its name."""
    series, _ = profiled_series
    series.bc_profile = "default"
    window = _StubWindow(series)
    scripted_dialog(None, {"default": "default", EXTRA: None, RENAMED: EXTRA})

    window.changeBCProfiles()

    assert series.bc_profile == "default"


def test_deleting_the_displayed_profile_falls_back_to_default(
    profiled_series, scripted_dialog
):
    """Deletion has no forward target, so the display has to go somewhere valid.

    `default` is that somewhere: `BCProfilesDialog.removeProfiles` and
    `ProfileList.removeProfile` both refuse to remove it, and
    `ProfileList.renameProfile` refuses to rename it, so it survives every
    round trip through the dialog.
    """
    series, _ = profiled_series
    window = _StubWindow(series)
    scripted_dialog(None, {"default": "default", EXTRA: None})

    window.changeBCProfiles()

    assert series.bc_profile == "default", (
        "deleting the displayed profile must fall back to default"
    )
    assert EXTRA not in series.loadSection(series.current_section).bc_profiles


def test_adding_a_profile_leaves_the_displayed_one_alone(
    profiled_series, scripted_dialog
):
    """A new profile copies the current one; `pdict` then maps two names to it.

    `{extra: extra, new: extra}` must resolve to `extra`, not to `new`, or
    creating a profile would silently switch the display to it.
    """
    series, _ = profiled_series
    window = _StubWindow(series)
    scripted_dialog(
        None, {"default": "default", EXTRA: EXTRA, "fresh": EXTRA}
    )

    window.changeBCProfiles()

    assert series.bc_profile == EXTRA
    profiles = series.loadSection(series.current_section).bc_profiles
    assert "fresh" in profiles and EXTRA in profiles


def test_cancelling_the_dialog_changes_nothing(profiled_series, scripted_dialog):
    """Cancel must not reload and must not move the pointer."""
    series, _ = profiled_series
    window = _StubWindow(series)
    scripted_dialog(RENAMED, {"default": "default", RENAMED: EXTRA}, confirmed=False)

    window.changeBCProfiles()

    assert window.field.reload_count == 0
    assert series.bc_profile == EXTRA


def test_an_unmodified_ok_only_switches(profiled_series, scripted_dialog):
    """OK with a selection but no edits: switch, no rewrite, no reload."""
    series, _ = profiled_series
    window = _StubWindow(series)
    scripted_dialog("default", {"default": "default", EXTRA: EXTRA})

    window.changeBCProfiles()

    assert window.field.reload_count == 0
    assert window.field.switched_to == ["default"]
    assert series.bc_profile == "default"


# --- why the ordering is what it is -------------------------------------------


def test_switching_before_the_reload_would_also_raise(profiled_series):
    """Proves the fix is not "call changeBCProfile first".

    After `modifyBCProfiles`, the on-disk sections carry the new names but
    `field.section` is still the object loaded before the dialog, carrying the
    old ones. `changeBCProfile` reads brightness through the same
    `mouse_palette.updateBC()`, so switching before the reload raises on the new
    name. Only remapping the pointer and *then* reloading reads a key that
    exists.
    """
    series, _ = profiled_series
    window = _StubWindow(series)

    series.modifyBCProfiles(
        {"default": "default", EXTRA: None, RENAMED: EXTRA},
        series_states=window.field.series_states,
    )

    with pytest.raises(KeyError):
        window.field.changeBCProfile(RENAMED)


def test_the_pointer_is_remapped_before_the_reload(profiled_series, scripted_dialog):
    """Order, asserted directly rather than inferred from the absence of a raise.

    A future refactor could make `updateBC` tolerate a missing key, which would
    make the crash tests pass while leaving the pointer stale. This one fails on
    that.
    """
    series, _ = profiled_series
    window = _StubWindow(series)
    seen = []

    original = _StubField.reload

    def recording_reload(self, clear_states=False):
        seen.append(self.series.bc_profile)
        return original(self, clear_states)

    window.field.reload = recording_reload.__get__(window.field, _StubField)
    scripted_dialog(None, {"default": "default", EXTRA: None, RENAMED: EXTRA})

    window.changeBCProfiles()

    assert seen == [RENAMED], (
        "series.bc_profile must already name the renamed profile when reload runs"
    )


# --- the resolver, in isolation ------------------------------------------------


def test_remapped_bc_profile_cases():
    """Table of the `profiles_dict` shapes the dialog can produce."""
    remap = main_window_module.remappedBCProfile

    assert remap("a", {"a": "a"}) == "a", "untouched"
    assert remap("a", {"a": None, "b": "a"}) == "b", "renamed"
    assert remap("a", {"a": "a", "b": "a"}) == "a", "copied to a new profile"
    assert remap("a", {"default": "default", "a": None}) == "default", "deleted"
    assert remap("a", {"a": None, "b": "c"}) == "b", (
        "deleted with no default: any surviving profile beats a dangling name"
    )
    assert remap("a", {"a": None}) == "a", (
        "nothing survives: unreachable through the dialog, so leave it be"
    )


def test_remapped_bc_profile_prefers_default_over_alphabetical():
    """`default` is the fallback, not "the first surviving name"."""
    remap = main_window_module.remappedBCProfile

    assert remap("z", {"a": "a", "default": "default", "z": None}) == "default"


# --- guards on the stub and on the call site ----------------------------------


def test_the_stub_field_matches_the_real_reload():
    """The stub is only evidence while the real methods still read through updateBC.

    Both `FieldWidget.reload` and `FieldWidget.changeBCProfile` call
    `mouse_palette.updateBC()`, and `MousePalette.updateBC` reads
    `field.section.brightness`. If any of the three stops being true this test
    fails, rather than the crash tests quietly becoming vacuous.
    """
    def calls_update_bc(path, function_name):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        func = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        return any(
            getattr(node.func, "attr", None) == "updateBC"
            for node in ast.walk(func) if isinstance(node, ast.Call)
        )

    assert calls_update_bc(_FIELD_BASE_PY, "reload"), (
        "FieldWidget.reload must still refresh the b/c palette"
    )
    assert calls_update_bc(_FIELD_VIEW_PY, "changeBCProfile"), (
        "FieldWidget.changeBCProfile must still refresh the b/c palette"
    )
    palette_source = _MOUSE_PALETTE_PY.read_text(encoding="utf-8")
    tree = ast.parse(palette_source)
    update_bc = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "updateBC"
    )
    read = ast.get_source_segment(palette_source, update_bc)
    assert ".section.brightness" in read and ".section.contrast" in read, (
        "MousePalette.updateBC must still be the reader that indexes bc_profiles"
    )


def test_change_bc_profiles_remaps_before_it_reloads():
    """Static guard on statement order inside `changeBCProfiles`.

    The behavioral tests above cover the crash; this one names the mistake, so a
    reviewer moving the reload back up gets a message rather than a `KeyError`
    three tests away.
    """
    tree = ast.parse(_MAIN_WINDOW_PY.read_text(encoding="utf-8"))
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "changeBCProfiles"
    )
    remap_line = None
    reload_line = None
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            if getattr(node.func, "id", None) == "remappedBCProfile":
                remap_line = node.lineno
            elif getattr(node.func, "attr", None) == "reload":
                reload_line = node.lineno
    assert remap_line is not None, (
        "changeBCProfiles must resolve the displayed profile's new name"
    )
    assert reload_line is not None, "changeBCProfiles must still reload the field"
    assert remap_line < reload_line, (
        "the profile pointer must be remapped before field.reload() reads it"
    )
