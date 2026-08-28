"""Four GUI-tail findings from the review fleet (2026-08-28).

The palette-button collision is pinned in test_palette_hide_menus.py; this
file carries the rest: the plotter's leaked series, the sticky restart flag,
and the Reset Defaults button that reset nothing.
"""

import os

import pytest

pytestmark = pytest.mark.gui


def test_place_in_scene_closes_a_borrowed_series(main_window, series_jser, tmp_path):
    """The 3D flow removes the working copy it opened, once meshes exist.

    Left open, the hidden dir outlived the app and later greeted whoever
    opened that jser normally with the unsaved-work prompt: a stale snapshot
    frozen at 3D time, overwriting real edits on a yes.
    """
    import shutil

    from PyReconstruct.modules.datatypes import Series

    other_fp = tmp_path / "colleague.jser"
    shutil.copy(series_jser, other_fp)
    other = Series.openJser(str(other_fp))
    hidden = other.hidden_dir
    assert os.path.isdir(hidden)

    # placeInScene is exercised UNBOUND on a stand-in: VPlotter's vedo base
    # recurses on attribute access before __init__, so a half-built
    # instance cannot exist, and a full one needs a GL context
    from types import SimpleNamespace

    from PyReconstruct.modules.gui.popup.custom_plotter import VPlotter

    plt = SimpleNamespace(series=main_window.series, objs=None, render=lambda: None)
    VPlotter.placeInScene(plt, ([], other))     # no meshes: just ownership

    assert not os.path.isdir(hidden), "the borrowed series' hidden dir leaked"


def test_place_in_scene_never_closes_the_plotters_own_series(main_window):
    from types import SimpleNamespace

    from PyReconstruct.modules.gui.popup.custom_plotter import VPlotter

    plt = SimpleNamespace(series=main_window.series, objs=None, render=lambda: None)
    VPlotter.placeInScene(plt, ([], main_window.series))

    assert os.path.isdir(main_window.series.hidden_dir)


def test_a_canceled_close_forgets_the_pending_restart(main_window, main_window_dialogs):
    """restart() then Cancel at the save prompt must not arm a later quit.

    The flag used to survive: hours later a normal quit relaunched the app
    instead of exiting.
    """
    window = main_window
    window.seriesModified(True)
    window.restart_mainwindow = True                 # what restart() sets
    main_window_dialogs.save_response = "cancel"

    assert window.close() is False                   # the close was refused
    assert window.restart_mainwindow is False        # and the restart unarmed


def test_reset_defaults_reaches_the_shipped_bindings(main_window):
    """Remap a key, save it, reopen the dialog: Reset Defaults must show the
    factory binding, not the stored remap it already shows."""
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    series = main_window.series
    default = series.getOption("save_act", get_default=True)
    assert default, "the fixture series ships no default for save_act"
    series.setOption("save_act", "Ctrl+Shift+F12")   # the user's remap, stored

    dialog = ShortcutsDialog(main_window, series)
    try:
        row = dialog.act_widgets["save_act"]
        assert row.keySequence().toString() == "Ctrl+Shift+F12"

        dialog.resetDefaults()

        assert row.keySequence().toString() == default
    finally:
        dialog.deleteLater()
