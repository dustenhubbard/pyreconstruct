"""A checkable menu row toggles without dismissing the menu it lives in.

Qt closes a menu on any activation, toggle or not. Nine rows in this app are
toggles the user sets in combination, and they are spread over two files:

  * the ``View`` menu in ``PyReconstruct/modules/gui/main/menubar.py`` -- trace
    palette, section increment buttons, brightness/contrast sliders, scale bar.
    These sat under ``View > Palette > Visibility`` when this file was written,
    three levels down, so setting three of them was twelve interactions; the
    keep-open filter here removed the reopening and the 2026-08-06 hoist removed
    the descent.
  * the field right-click menu's ``View`` group in
    ``PyReconstruct/modules/gui/main/context_menu_list.py`` -- focus mode, hide
    trace layer, show all traces, hide image, section blend. Worse in practice:
    a dismissed context menu costs a right-click to get back.

The fix is one change in the shared builder (``newAction`` in
``PyReconstruct/modules/gui/utils/utils.py``), so both surfaces are covered by
the same code and any future toggle is covered on the day it is written. That is
what makes the two-surface split below load-bearing rather than decorative: a
per-menu fix would pass one half of this file and fail the other.

Everything here drives the menus the running app builds --
``MainWindow.createMenuBar`` and ``MainWindow.createContextMenus`` via the
``main_window`` fixture -- with synthetic mouse releases on the real
``QAction`` rectangles. Nothing calls ``trigger()`` directly, because a direct
``trigger()`` cannot tell "the menu stayed open" from "the menu was never open".

No test here writes a ``Series`` option or a ``QSettings`` key.
"""

from contextlib import contextmanager

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import menu_leaf_paths, submenu_at

pytestmark = pytest.mark.gui


# the four menubar toggles and the five field-menu toggles, by attribute name
MENUBAR_VISIBILITY = {
    "Trace palette": "togglepalette_act",
    "Section increment buttons": "toggleinc_act",
    "Brightness/contrast sliders": "togglebc_act",
    "Scale bar": "togglesb_act",
}

FIELD_VIEW_TOGGLES = {
    "Focus mode": "focus_act",
    "Hide trace layer": "hideall_act",
    "Show all traces (ignore hidden)": "showall_act",
    "Hide image": "hideimage_act",
    "Section blend": "blend_act",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@contextmanager
def opened(menu):
    """Show `menu` for the body of the block and close it afterwards.

    `processEvents` before the body, not as a ritual: showing a popup produces a
    `WindowActivate`/`ActivationChange` pair on the offscreen platform, and a
    click delivered while that is still queued was observed to leave the menu
    hidden a few runs in fifty. Draining the queue first makes the click land on
    a settled menu, which is the state a real user's click always finds.

    A popped-up `QMenu` holds a mouse grab, so one left open by a failing
    assertion would follow the rest of the session around. `close()` in a
    `finally` keeps a failure here from turning into failures elsewhere.
    """
    menu.popup(QPoint(0, 0))
    QApplication.processEvents()
    try:
        yield menu
    finally:
        menu.close()
        QApplication.processEvents()


def click(menu, action, qapp):
    """Left-click the middle of `action`'s row in `menu`, as a user would.

    `actionGeometry` needs the menu laid out, so the menu must already be
    showing. The click is a real press/release pair through `QTest`, which is
    the whole point: the change under test is an event filter on the release,
    and a `trigger()` call would bypass it in both directions.
    """
    assert menu.isVisible(), "the menu must be showing before a row can be clicked"
    QTest.mouseClick(
        menu,
        Qt.LeftButton,
        Qt.NoModifier,
        menu.actionGeometry(action).center(),
    )
    qapp.processEvents()


def menubar_visibility_menu(main_window):
    """The real `View` menu of the menubar, which is where the four palette
    visibility toggles live directly as of the 2026-08-06 hoist.

    They were under `View > Palette > Visibility` when this file was written.
    The move does not change what is being tested here: `newAction` installs the
    keep-open filter on the action, not on one particular menu, so the behavior
    follows the rows to their new home. That is the same property the field
    right-click half of this file exercises.
    """
    menu = submenu_at(main_window.menubar, "View")
    assert menu is not None, "View is gone from the menubar"
    return menu


def field_view_menu(main_window):
    """The real `View` submenu of the field right-click menu."""
    menu = submenu_at(main_window.field_menu, "View")
    assert menu is not None, "View is gone from the field right-click menu"
    return menu


def select_a_trace(main_window):
    """Put one trace in the selection, so `focus_act` is enabled.

    `MainWindow.checkActions` disables "Focus mode" when nothing is selected
    (focus mode needs an object to focus on). A disabled row cannot be clicked,
    and a click on one leaves the menu open for Qt's own reasons -- which would
    make this file pass without testing anything. So the selection is real and
    `checkActions` is allowed to run on it.
    """
    field = main_window.field
    traces = field.section.tracesAsList()
    assert traces, "the fixture series has no traces to select"
    field.section.selected_traces = traces[:1]
    main_window.checkActions()
    assert main_window.focus_act.isEnabled()


# --------------------------------------------------------------------------- #
# the menubar surface
# --------------------------------------------------------------------------- #
def test_menubar_visibility_toggles_leave_their_submenu_open(main_window, qapp):
    """Setting three of the four boxes is one trip down the menu, not three.

    Asserted on the app state as well as on the checkmark, so a row that keeps
    the menu open and stops doing its job fails here.
    """
    menu = menubar_visibility_menu(main_window)
    palette = main_window.mouse_palette

    with opened(menu) as shown:
        before = {
            "palette": palette.palette_hidden,
            "inc": palette.inc_hidden,
            "sb": palette.sb_hidden,
        }

        for label, attr in (
            ("Trace palette", "palette"),
            ("Section increment buttons", "inc"),
            ("Scale bar", "sb"),
        ):
            action = getattr(main_window, MENUBAR_VISIBILITY[label])
            checked_before = action.isChecked()

            click(shown, action, qapp)

            assert shown.isVisible(), f"toggling {label!r} closed the menu"
            assert action.isChecked() is not checked_before
            assert getattr(palette, f"{attr}_hidden") is not before[attr]


def test_every_menubar_visibility_toggle_keeps_the_menu_open(main_window, qapp):
    """All four, individually, and each one put back the way it was found."""
    menu = menubar_visibility_menu(main_window)

    with opened(menu) as shown:
        for label, attr_name in MENUBAR_VISIBILITY.items():
            action = getattr(main_window, attr_name)
            assert action.isCheckable()
            was_checked = action.isChecked()

            click(shown, action, qapp)
            assert shown.isVisible(), f"toggling {label!r} closed the menu"
            assert action.isChecked() is not was_checked

            click(shown, action, qapp)
            assert shown.isVisible(), f"untoggling {label!r} closed the menu"
            assert action.isChecked() is was_checked


def test_a_plain_menubar_row_still_closes_its_menu(main_window, qapp):
    """The negative control, in a menu that also holds a toggle.

    The menubar's `View` menu contains the checkable "Show z-traces", so it is a
    menu the change reaches. A command in it must still dismiss the menu: a fix
    that keeps every menu open on every click would pass every other test here.
    """
    view = submenu_at(main_window.menubar, "View")
    assert view is not None
    assert main_window.toggleztraces_act.isCheckable()

    home = menu_leaf_paths(view)["Set view to image"]
    assert not home.isCheckable()

    with opened(view) as shown:
        click(shown, home, qapp)
        assert not shown.isVisible(), "a plain row no longer closes the menu"


# --------------------------------------------------------------------------- #
# the field right-click surface
# --------------------------------------------------------------------------- #
def test_field_menu_view_toggles_leave_the_menu_open(main_window, qapp):
    """Hide the image and blend the section without re-summoning the menu."""
    select_a_trace(main_window)
    menu = field_view_menu(main_window)
    field = main_window.field

    with opened(menu) as shown:
        hide_image = main_window.hideimage_act
        blend = main_window.blend_act
        hidden_before, blend_before = field.hide_image, field.blend_sections

        click(shown, hide_image, qapp)
        assert shown.isVisible(), "toggling 'Hide image' closed the menu"
        assert field.hide_image is not hidden_before

        click(shown, blend, qapp)
        assert shown.isVisible(), "toggling 'Section blend' closed the menu"
        assert field.blend_sections is not blend_before


def test_every_field_menu_view_toggle_keeps_the_menu_open(main_window, qapp):
    """All five, individually, and each one put back the way it was found."""
    select_a_trace(main_window)
    menu = field_view_menu(main_window)

    with opened(menu) as shown:
        for label, attr_name in FIELD_VIEW_TOGGLES.items():
            action = getattr(main_window, attr_name)
            assert action.isCheckable()
            assert action.isEnabled(), f"{label!r} is disabled; the click would prove nothing"
            was_checked = action.isChecked()

            click(shown, action, qapp)
            assert shown.isVisible(), f"toggling {label!r} closed the menu"
            assert action.isChecked() is not was_checked

            click(shown, action, qapp)
            assert shown.isVisible(), f"untoggling {label!r} closed the menu"
            assert action.isChecked() is was_checked


def test_a_plain_row_in_the_field_view_menu_still_closes_it(main_window, qapp):
    """"Unhide all traces" is a one-shot and sits among the five toggles.

    Same menu, same event filter, opposite outcome. This is the row that proves
    the filter discriminates on the action rather than on the menu.
    """
    menu = field_view_menu(main_window)
    unhide = main_window.unhideall_act
    assert not unhide.isCheckable()

    with opened(menu) as shown:
        click(shown, unhide, qapp)
        assert not shown.isVisible(), "a plain row no longer closes the menu"


# --------------------------------------------------------------------------- #
# the two things the change must not break
# --------------------------------------------------------------------------- #
def test_checked_state_still_syncs_from_live_state(main_window, qapp):
    """`MainWindow.checkActions` still owns the checkmarks.

    The menus are built once and reopened forever, and the state behind them can
    change from a keyboard shortcut, another menu, or code. Both surfaces are
    checked: the palette group reads the `MousePalette`, the field group reads
    the `FieldWidget`.
    """
    field = main_window.field
    palette = main_window.mouse_palette

    field.hide_image = True
    field.blend_sections = True
    field.hide_trace_layer = True
    field.show_all_traces = True
    palette.sb_hidden = True

    main_window.checkActions()

    assert main_window.hideimage_act.isChecked() is True
    assert main_window.blend_act.isChecked() is True
    assert main_window.hideall_act.isChecked() is True
    assert main_window.showall_act.isChecked() is True
    assert main_window.togglesb_act.isChecked() is False  # sb_hidden -> unchecked

    field.hide_image = False
    field.blend_sections = False
    field.hide_trace_layer = False
    field.show_all_traces = False
    palette.sb_hidden = False

    main_window.checkActions()

    assert main_window.hideimage_act.isChecked() is False
    assert main_window.blend_act.isChecked() is False
    assert main_window.hideall_act.isChecked() is False
    assert main_window.showall_act.isChecked() is False
    assert main_window.togglesb_act.isChecked() is True


def test_a_toggle_clicked_in_the_menu_survives_the_next_resync(main_window, qapp):
    """Toggling through the menu and resyncing agree on the answer.

    The two halves of the feature meeting: the click sets the state, and the
    next `checkActions` pass must read that same state back rather than undo it.
    """
    select_a_trace(main_window)
    menu = field_view_menu(main_window)
    field = main_window.field
    action = main_window.hideimage_act

    with opened(menu) as shown:
        before = field.hide_image
        click(shown, action, qapp)
        assert field.hide_image is not before

    main_window.checkActions()
    assert action.isChecked() is field.hide_image


def test_the_shortcut_for_a_checkable_row_still_fires_its_handler(
    main_window, qapp
):
    """A real key press still reaches the toggle, with no menu involved.

    The `(series, "checkbox")` form of the third tuple element is what lets a
    toggle be a checkbox and keep a user-configurable key. The change under test
    is on the mouse path only, and this is what says so.

    `Qt::WindowShortcut` resolves against `QApplication.activeWindow()`. On the
    offscreen platform, after many preceding window create/show/close cycles (one
    per test), the application has no active window when this test's fixture
    builds a new one. `activateWindow()` sets it explicitly so the shortcut
    dispatch is deterministic regardless of run order.
    """
    field = main_window.field
    action = main_window.hideimage_act
    sequence = action.shortcut()
    assert not sequence.isEmpty(), "'Hide image' lost its configurable shortcut"

    main_window.activateWindow()
    QApplication.processEvents()

    before = field.hide_image
    QTest.keySequence(main_window, sequence)
    qapp.processEvents()

    assert field.hide_image is not before

    QTest.keySequence(main_window, sequence)
    qapp.processEvents()

    assert field.hide_image is before


def test_escape_still_closes_a_menu_after_a_toggle(main_window, qapp):
    """The menu stays open until the user says otherwise, and Esc is a way to say it."""
    menu = menubar_visibility_menu(main_window)
    action = main_window.togglesb_act

    with opened(menu) as shown:
        click(shown, action, qapp)
        assert shown.isVisible()

        QTest.keyClick(shown, Qt.Key_Escape)
        qapp.processEvents()

        assert not shown.isVisible(), "Esc no longer closes the menu"
