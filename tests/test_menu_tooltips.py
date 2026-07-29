"""Hover tooltips for the File > Utilities items.

The Utilities submenu collects niche, user-requested features, so its two
entries (Randomize / De-randomize project) now carry hover tooltips that
explain what each one actually does. The copy was written against the scripts
the handlers run (``assets/scripts/projects/randomize.py`` and
``derandomize.py``), and the facts it states are pinned here.

The mechanism is general, not hand-wired: ``newAction`` accepts an optional
fifth tuple element, the tooltip. The catch this module exists to prove:
``QAction.setToolTip()`` alone does NOTHING in a menu. QMenu only surfaces
action tooltips after ``setToolTipsVisible(True)`` on the menu itself, so
``newAction`` opts the containing menu in whenever it sets a tooltip -- and
leaves every other menu opted out, because a QAction's toolTip defaults to its
own text and a blanket opt-in would echo every label back redundantly.
"""

import pytest

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QMenu, QToolTip, QWidget


# --------------------------------------------------------------------------- #
# stubs -- the same minimal Series/MainWindow surface test_menubar_labels uses
# --------------------------------------------------------------------------- #
class _Anything:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _SeriesStub(_Anything):
    def __init__(self):
        super().__init__(jser_fp="/nonexistent/current.jser")
        self.opts = {"recently_opened_series": []}

    def getOption(self, name, get_default=False):
        return self.opts.get(name, "")

    def setOption(self, name, value):
        self.opts[name] = value


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def file_menu_widget(qapp):
    """The real File menu built through the real Qt helpers onto a QWidget.

    addItem -> newMenu is used (not populateMenu) so the top-level ``filemenu``
    attribute is created too, exactly as populateMenuBar would.
    """
    from PyReconstruct.modules.gui.main.menubar import return_file_menu
    from PyReconstruct.modules.gui.utils.utils import addItem

    mw = _Anything(series=_SeriesStub())
    widget = QWidget()
    container = QMenu(widget)
    addItem(widget, container, return_file_menu(mw))
    yield widget
    widget.deleteLater()


# --------------------------------------------------------------------------- #
# 1. both halves of the Qt requirement
# --------------------------------------------------------------------------- #
def test_utilities_actions_have_tooltips_and_their_menu_shows_them(file_menu_widget):
    """The text alone is not enough; toolTipsVisible is what makes it appear."""
    w = file_menu_widget
    assert w.random_act.toolTip() not in ("", w.random_act.text())
    assert w.derandom_act.toolTip() not in ("", w.derandom_act.text())
    assert w.projectsmenu.toolTipsVisible() is True


def test_tooltip_surfaces_through_the_real_qmenu_event_path(file_menu_widget):
    """Drive QMenu's own QEvent.ToolTip handling, not just the properties.

    With toolTipsVisible on, a hover (QHelpEvent) over the action's row makes
    QMenu call QToolTip.showText with the action's tooltip. With it off -- the
    Qt default, and the whole trap -- the very same event shows nothing.
    """
    menu = file_menu_widget.projectsmenu
    # Lay the menu out without showing it. The resize matters: QMenu.actionAt
    # sanity-checks the point against the widget's CURRENT rect, and a
    # never-shown child QMenu still has the default 100x30 geometry.
    menu.resize(menu.sizeHint())
    pos = menu.actionGeometry(file_menu_widget.random_act).center()

    # showText("") hides synchronously; hideText() only starts a fade timer,
    # after which text() still reports the fading tip
    QToolTip.showText(QPoint(), "")
    assert QToolTip.text() == ""

    # the counterfactual first: without the menu-level opt-in (the Qt default),
    # the very same hover event surfaces nothing
    menu.setToolTipsVisible(False)
    QApplication.sendEvent(
        menu, QHelpEvent(QEvent.Type.ToolTip, pos, menu.mapToGlobal(pos))
    )
    assert QToolTip.text() == ""

    # and with it (as newAction leaves the menu), the tooltip appears
    menu.setToolTipsVisible(True)
    QApplication.sendEvent(
        menu, QHelpEvent(QEvent.Type.ToolTip, pos, menu.mapToGlobal(pos))
    )
    assert QToolTip.text() == file_menu_widget.random_act.toolTip()
    QToolTip.showText(QPoint(), "")


def test_menus_without_explicit_tooltips_stay_opted_out(file_menu_widget):
    """A QAction's toolTip defaults to its own text (Qt behavior, pinned here
    because it is why newAction must not enable toolTipsVisible wholesale)."""
    w = file_menu_widget
    assert w.filemenu.toolTipsVisible() is False
    assert w.backupmenu.toolTipsVisible() is False
    # Qt derives the default from the label (mnemonics and the trailing
    # ellipsis stripped) -- i.e. it just parrots the label back.
    assert w.open_act.toolTip() == "Open series"


# --------------------------------------------------------------------------- #
# 2. the copy tells the truth about the scripts
# --------------------------------------------------------------------------- #
def test_randomize_tooltip_states_the_scripts_facts(file_menu_widget):
    """randomize.py pools every series subfolder's images under uuid names,
    builds a single coded.jser, and appends the mapping to decode.txt."""
    tip = file_menu_widget.random_act.toolTip()
    assert "blind" in tip
    assert "decode.txt" in tip
    assert "coded .jser" in tip
    assert "keep it" in tip  # losing decode.txt makes the coding irreversible


def test_derandomize_tooltip_states_the_scripts_facts(file_menu_widget):
    """derandomize.py reads decode.txt, splits the coded jser into one series
    per original subfolder, and moves the coded files to decoded-<date>/."""
    tip = file_menu_widget.derandom_act.toolTip()
    assert "decode.txt" in tip
    assert "one series per original subfolder" in tip
    assert "decoded-" in tip


# --------------------------------------------------------------------------- #
# 3. the mechanism generalises and the 4-tuple form is untouched
# --------------------------------------------------------------------------- #
def test_newaction_accepts_a_plain_4_tuple_unchanged(qapp):
    from PyReconstruct.modules.gui.utils.utils import newAction

    widget = QWidget()
    menu = QMenu(widget)
    newAction(widget, menu, ("plain_act", "Plain", "", lambda: None))
    assert widget.plain_act.text() == "Plain"
    assert menu.toolTipsVisible() is False
    widget.deleteLater()


def test_newaction_5_tuple_sets_tooltip_on_any_menu(qapp):
    """Any future menu gains a tooltip by adding a fifth element; nothing about
    the mechanism is specific to Utilities."""
    from PyReconstruct.modules.gui.utils.utils import newAction

    widget = QWidget()
    menu = QMenu(widget)
    newAction(
        widget, menu,
        ("tipped_act", "Tipped", "", lambda: None, "What this really does."),
    )
    assert widget.tipped_act.toolTip() == "What this really does."
    assert menu.toolTipsVisible() is True
    widget.deleteLater()


def test_utilities_rows_are_5_tuples_in_the_menu_definition():
    """The definition itself carries the tooltip as data (no Qt needed)."""
    from PyReconstruct.modules.gui.main.menubar import return_file_menu

    mw = _Anything(series=_SeriesStub())
    file_menu = return_file_menu(mw)
    utilities = next(
        item for item in file_menu["opts"]
        if isinstance(item, dict) and item["attr_name"] == "projectsmenu"
    )
    rows = {row[0]: row for row in utilities["opts"] if isinstance(row, tuple)}
    assert set(rows) == {"random_act", "derandom_act"}
    for row in rows.values():
        assert len(row) == 5
        assert isinstance(row[4], str) and row[4]
