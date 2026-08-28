"""Right-click a palette group to hide it.

The View menu keeps every visibility toggle; this adds the direct road from
the widget itself (his ask, 2026-08-26): right-click the scale bar, the
section increment buttons, or the brightness/contrast sliders and hide that
group without a trip to the menu bar.

Driven through the REAL MousePalette on the real main window: the menus are
installed per widget, and the point of the feature is which widget carries
which menu.
"""

import pytest

pytestmark = pytest.mark.gui


def _menu_for(palette, widget):
    """Fire the widget's custom context-menu request and return the menu."""
    from PySide6.QtCore import QPoint

    palette._hide_menu = None
    widget.customContextMenuRequested.emit(QPoint(2, 2))
    return palette._hide_menu


def test_palette_buttons_keep_their_edit_right_click(qapp, main_window, gui_dialogs):
    """A palette button's right-click is the attributes editor, documented in
    the palette help. Arming the hide menu on the buttons too made the two
    fight over one click (macOS: the editor silently stopped opening;
    Windows: both fired). The buttons must carry NO custom context menu."""
    from PySide6.QtCore import Qt

    palette = main_window.mouse_palette
    for button in palette.palette_buttons:
        assert button.contextMenuPolicy() != Qt.CustomContextMenu, (
            "a palette button was armed with the hide menu"
        )
        assert not button.property("pyrecon_hide_menu")


def test_every_group_offers_its_own_hide(qapp, main_window, gui_dialogs):
    palette = main_window.mouse_palette
    cases = [
        (palette.sb, "Hide the scale bar"),
        (palette.inc_buttons[0], "Hide the section increment buttons"),
        (palette.bc_widgets[0][1], "Hide the brightness/contrast sliders"),
        # the LABEL, not a button: buttons keep their documented right-click
        # (edit attributes), so the hide menu must never be armed on them
        (palette.label, "Hide the trace palette"),
    ]
    for widget, label in cases:
        menu = _menu_for(palette, widget)
        assert menu is not None, f"no hide menu on {label}"
        assert [a.text() for a in menu.actions()] == [label]
        menu.hide()


def test_the_hide_action_actually_hides_that_group(qapp, main_window, gui_dialogs):
    palette = main_window.mouse_palette
    assert not palette.sb_hidden
    menu = _menu_for(palette, palette.sb)
    menu.actions()[0].trigger()
    qapp.processEvents()
    assert palette.sb_hidden
    assert palette.sb.isHidden()
    # and the View menu toggle brings it back: same flag, one owner
    palette.toggleSB()
    qapp.processEvents()
    assert not palette.sb_hidden


def test_arming_is_idempotent_across_rebuilds(qapp, main_window, gui_dialogs):
    """resize() re-arms so a rebuilt slider is covered; a second pass must
    not stack a second connection (two menus on one click)."""
    palette = main_window.mouse_palette
    palette.installHideMenus()
    palette.resize()
    qapp.processEvents()

    menu = _menu_for(palette, palette.sb)
    assert menu is not None
    assert len(menu.actions()) == 1
    menu.hide()


def test_view_checkmarks_follow_a_right_click_hide(qapp, main_window, gui_dialogs):
    """The bug his click test found: hiding a group from its own right-click
    left the View checkbox still ticked. Every visibility change now pushes a
    resync (MousePalette.saveVisibilityState), so both roads agree."""
    palette = main_window.mouse_palette
    assert main_window.togglesb_act.isChecked()

    menu = _menu_for(palette, palette.sb)
    menu.actions()[0].trigger()          # "Hide the scale bar"
    qapp.processEvents()
    assert palette.sb_hidden

    qapp.processEvents()
    assert not main_window.togglesb_act.isChecked()

    # and back the other way: the View toggle shows it again
    main_window.togglesb_act.trigger()
    qapp.processEvents()
    assert not palette.sb_hidden
    assert main_window.togglesb_act.isChecked()


def test_every_palette_group_stays_in_sync(qapp, main_window, gui_dialogs):
    palette = main_window.mouse_palette
    cases = (
        (palette.label, "togglepalette_act", "palette_hidden"),
        (palette.inc_buttons[0], "toggleinc_act", "inc_hidden"),
        (palette.bc_widgets[0][1], "togglebc_act", "bc_hidden"),
    )
    for widget, action_name, flag in cases:
        action = getattr(main_window, action_name)
        menu = _menu_for(palette, widget)
        menu.actions()[0].trigger()
        qapp.processEvents()
        assert getattr(palette, flag) is True, action_name
        assert action.isChecked() is False, action_name
