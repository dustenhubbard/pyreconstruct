"""Shortcut-bearing rows must print their key in the field's right-click menu.

Qt hides shortcut text in CONTEXT menus when
Qt.AA_DontShowShortcutsInContextMenus is set, and macOS sets it by default.
Menubar menus are unaffected, so before this the app had a split only Mac users
saw: "Hide selected traces" printed Ctrl+H in the menubar and nothing beside the
same row in the field menu -- the surface where the row is actually used, and
the surface the frequency-first redesign built a top strip for so the keys would
be "on display".

These tests run against a real QApplication so the platform attribute is the
live one, and they assert the outcome (does Qt put the shortcut in the text it
is about to draw) rather than the mechanism, so they stay honest if the opt-in
moves.
"""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QWidget, QStyleOptionMenuItem

from PyReconstruct.modules.gui.utils import populateMenu


@pytest.fixture
def widget(qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    return w


def _drawn_text(menu, action):
    """What Qt will actually paint for this row.

    QMenu.initStyleOption appends "\\t<shortcut>" to the option text only for a
    shortcut it has decided to draw, taking the application attribute and the
    menu's provenance into account. Asking it is the only honest check -- the
    QAction having a shortcut proves nothing about whether the user sees it.
    """
    option = QStyleOptionMenuItem()
    menu.initStyleOption(option, action)
    return option.text


def test_a_keyed_row_prints_its_key_in_a_context_menu(widget, qtbot):
    menu = QMenu(widget)
    populateMenu(widget, menu, [
        ("keyed_act", "Hide selected traces", "Ctrl+H", lambda: None),
    ])
    assert "\t" in _drawn_text(menu, widget.keyed_act), (
        "the shortcut is bound but not drawn -- on macOS this is the "
        "AA_DontShowShortcutsInContextMenus default, and the row has not opted "
        "out of it"
    )
    # The key itself, not its spelling: Qt renders Ctrl as the platform's own
    # glyph (a literal "Ctrl+" on Windows and Linux, the command symbol on
    # macOS), so asserting one spelling would pass on one platform and fail on
    # the others for a menu that is drawing exactly the right thing.
    assert _drawn_text(menu, widget.keyed_act).split("\t")[1].endswith("H")


def test_the_platform_default_is_what_this_defends_against(widget, qtbot):
    """The bug reproduces on an action that did NOT go through populateMenu.

    Pins the premise: if this ever stops failing, the platform default changed
    and the opt-in above is no longer load-bearing (it is still harmless).
    """
    hidden_by_default = QApplication.testAttribute(
        Qt.ApplicationAttribute.AA_DontShowShortcutsInContextMenus
    )
    menu = QMenu(widget)
    raw = QAction("Hide selected traces", widget)
    raw.setShortcut("Ctrl+H")
    menu.addAction(raw)
    if hidden_by_default:
        assert "\t" not in _drawn_text(menu, raw)
    else:
        assert "\t" in _drawn_text(menu, raw)


def test_an_unkeyed_row_prints_no_column(widget, qtbot):
    """Opting in must not invent a shortcut for a row that has none."""
    menu = QMenu(widget)
    populateMenu(widget, menu, [
        ("plain_act", "Leave object comment...", "", lambda: None),
    ])
    assert "\t" not in _drawn_text(menu, widget.plain_act)


def test_a_checkable_keyed_row_prints_its_key_too(widget, qtbot):
    """The (series, "checkbox") form: a toggle that also carries a key.

    Its shortcut is set through a different branch of newAction, so it needs its
    own case or the View submenu's toggles would silently stay blank.
    """
    class _Series:
        def getOption(self, name):
            return "Ctrl+F"

    menu = QMenu(widget)
    populateMenu(widget, menu, [
        ("focus_like_act", "Focus mode", (_Series(), "checkbox"), lambda: None),
    ])
    assert widget.focus_like_act.isCheckable()
    assert "\t" in _drawn_text(menu, widget.focus_like_act)


def test_a_reused_menubar_action_prints_its_key(widget, qtbot):
    """The field menu borrows the menubar's cut/copy/paste QActions.

    They go through newQAction, not newAction, and they are the rows a user is
    most likely to already know a key for -- so they need the opt-in too.
    """
    menu = QMenu(widget)
    borrowed = QAction("Cut", widget)
    borrowed.setShortcut("Ctrl+X")
    populateMenu(widget, menu, [borrowed])
    assert "\t" in _drawn_text(menu, borrowed)


def test_a_row_inside_a_submenu_prints_its_key(widget, qtbot):
    """Submenus are built by a different path (newMenu -> populateMenu again),
    so a fix applied only at the top level would leave "Set hosts..." blank."""
    menu = QMenu(widget)
    populateMenu(widget, menu, [
        {
            "attr_name": "submenu",
            "text": "Object attributes",
            "opts": [("nested_act", "Set hosts...", "Ctrl+Shift+H", lambda: None)],
        },
    ])
    assert "\t" in _drawn_text(widget.submenu, widget.nested_act)
