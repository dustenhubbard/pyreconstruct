"""The status bar's three clickable segments.

The readout names the section, the alignment and the brightness/contrast
profile -- the three things a user switches most often -- and until now naming
them was all it did: changing any of the three meant a trip to a menu at the
opposite end of the window. Each is now its own widget and a left-click on it
offers the switch in place.

What these tests drive is the whole path, not the widgets' existence: a real
``QTest`` mouse click on the segment, the popup that click produces, a real
mouse click on an entry in that popup, and then the two things that must
follow -- the series actually switched, and the readout says so.

Nothing here reaches ``QMenu.exec()``, and that is a property of the code
under test rather than of the test: ``MainWindow.statusQuickSwitch`` uses
``popup()``, which shows the menu without spinning a nested modal event loop.
An ``exec()`` here would hang offscreen exactly the way the dialogs described
in ``conftest.DialogRecorder`` do.

The section segment is the odd one out: it has no popup of its own, because
"Go To Section" already exists as ``MainWindow.changeSection``'s
``QInputDialog``. Reusing it is the point -- one dialog, one validation rule,
one place to change. It is a blocking modal, so it is driven through the
``QInputDialog.getText`` patch the ``main_window`` fixture already installs.
"""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

pytestmark = pytest.mark.gui


def click(qtbot, widget, button=Qt.LeftButton):
    qtbot.mouseClick(widget, button)


def popup_of(segment):
    """The menu a click on ``segment`` left behind, or None."""
    menus = segment.findChildren(QMenu)
    assert len(menus) <= 1, "a segment must not accumulate menus"
    return menus[0] if menus else None


def entry_texts(menu):
    return [action.text() for action in menu.actions()]


def checked_texts(menu):
    return [action.text() for action in menu.actions() if action.isChecked()]


def choose(qtbot, menu, text):
    """Click the entry reading ``text``, the way a user picks one.

    ``QAction.trigger()`` would fire the same slot, but it would leave the menu
    open and skip the hit-testing entirely. Clicking the action's own rectangle
    inside the menu is what a user does and is what closes the menu.
    """
    action = next(a for a in menu.actions() if a.text() == text)
    qtbot.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center())


# ---- section: the bounded list popup, reached from the bar -------------------
# The center-screen Go To Section dialog left this path on his call
# (2026-08-22); the menu-bar route and a right-click on the segment still own
# the dialog. The popup is a jump field over a scrollable list of the whole
# series (SectionListPopup), because a QMenu cannot scroll inside a bounded
# height.

def open_section_popup(main_window):
    """Open via the segment's signal and read the popup off the window: the
    offscreen platform neither holds a popup grab through a synthesized click
    nor reports Qt.Popup windows visible, so neither mouseClick nor scanning
    topLevelWidgets can reach it there. The press/release emission mechanics
    have their own pins in test_field_status_readout."""
    main_window.status_readout.section_segment.clicked.emit()
    return main_window._section_popup


def test_clicking_the_section_segment_opens_the_list_popup(qtbot, main_window):
    popup = open_section_popup(main_window)
    assert popup is not None
    assert popup.field is not None and popup.list.count() > 0
    popup.hide()


def test_choosing_a_section_number_moves_the_field_and_the_readout(
    qtbot, main_window
):
    """Click -> popup -> a row -> the field is there and the bar says so."""
    popup = open_section_popup(main_window)
    target = next(
        int(popup.list.item(i).text()) for i in range(popup.list.count())
        if popup.list.item(i).text() != str(main_window.series.current_section)
    )
    matches = popup.list.findItems(str(target), Qt.MatchExactly)
    popup._rowChosen(matches[0])

    assert main_window.series.current_section == target
    assert main_window.status_readout.section_segment.text() == f"Section: {target}"
    assert main_window.status_readout.text().startswith(f"Section: {target}")


def test_dismissing_the_section_popup_changes_nothing(qtbot, main_window):
    before = main_window.series.current_section
    readout_before = main_window.status_readout.text()

    popup = open_section_popup(main_window)
    popup.hide()

    assert main_window.series.current_section == before
    assert main_window.status_readout.text() == readout_before



# ---- alignment -------------------------------------------------------------

def test_clicking_the_alignment_segment_lists_the_series_alignments(
    qtbot, main_window
):
    """Every alignment the series has, and the current one marked."""
    expected = sorted(main_window.field.section.tforms.keys())
    assert len(expected) > 1, "fixture series must have alignments to switch between"

    click(qtbot, main_window.status_readout.alignment_segment)

    menu = popup_of(main_window.status_readout.alignment_segment)
    assert menu is not None and menu.isVisible()
    # the trailing separator ("" in entry_texts) and the management row were
    # added on his click test call (2026-08-25)
    assert entry_texts(menu) == expected + ["", "New or edit alignments..."]
    assert checked_texts(menu) == [main_window.series.alignment]


def test_choosing_an_alignment_switches_it_and_updates_the_readout(
    qtbot, main_window
):
    """The whole path: click, popup, click an entry, series and bar follow."""
    current = main_window.series.alignment
    target = next(
        a for a in sorted(main_window.field.section.tforms.keys()) if a != current
    )

    click(qtbot, main_window.status_readout.alignment_segment)
    choose(qtbot, popup_of(main_window.status_readout.alignment_segment), target)

    assert main_window.series.alignment == target
    assert (
        main_window.status_readout.alignment_segment.text() == f"Alignment: {target}"
    )
    assert f"Alignment: {target}" in main_window.status_readout.text()


def test_the_alignment_switch_keeps_the_menu_actions_in_step(qtbot, main_window):
    """``MainWindow.changeAlignment`` also owns the context menu's checkboxes.

    It is reached by a bare ``getattr(self, f"{name}_alignment_act")`` on both
    the old and the new name, so a quick switch that bypassed it would leave
    the "Series alignment" submenu ticking the wrong entry -- and would raise
    ``AttributeError`` the next time either route was used. Going through
    ``changeAlignment`` is what this pins.
    """
    current = main_window.series.alignment
    target = next(
        a for a in sorted(main_window.field.section.tforms.keys()) if a != current
    )

    click(qtbot, main_window.status_readout.alignment_segment)
    choose(qtbot, popup_of(main_window.status_readout.alignment_segment), target)

    assert getattr(main_window, f"{target}_alignment_act").isChecked()
    assert not getattr(main_window, f"{current}_alignment_act").isChecked()


# ---- brightness/contrast profile -------------------------------------------

@pytest.fixture
def second_bc_profile(main_window):
    """Give the fixture series a second brightness/contrast profile.

    Created through ``Series.modifyBCProfiles``, which is the app's own
    creation path (``BCProfilesDialog`` hands it exactly this shape: the new
    name mapped to the profile it was copied from). Writing the key straight
    onto ``field.section`` would not survive the reload a profile switch does.
    """
    main_window.series.modifyBCProfiles(
        {"default": "default", "dim": "default"}, log_event=False
    )
    main_window.field.reload()
    return "dim"


def test_clicking_the_bc_segment_lists_the_profiles(
    qtbot, main_window, second_bc_profile
):
    expected = sorted(main_window.field.section.bc_profiles.keys())
    assert second_bc_profile in expected

    click(qtbot, main_window.status_readout.bc_profile_segment)

    menu = popup_of(main_window.status_readout.bc_profile_segment)
    assert menu is not None and menu.isVisible()
    assert entry_texts(menu) == expected + ["", "New or edit profiles..."]
    assert checked_texts(menu) == [main_window.series.bc_profile]


def test_choosing_a_bc_profile_switches_it_and_updates_the_readout(
    qtbot, main_window, second_bc_profile
):
    assert main_window.series.bc_profile != second_bc_profile

    click(qtbot, main_window.status_readout.bc_profile_segment)
    choose(
        qtbot,
        popup_of(main_window.status_readout.bc_profile_segment),
        second_bc_profile,
    )

    assert main_window.series.bc_profile == second_bc_profile
    assert (
        main_window.status_readout.bc_profile_segment.text()
        == f"B/C Profile: {second_bc_profile}"
    )
    assert f"B/C Profile: {second_bc_profile}" in main_window.status_readout.text()


# ---- the segments themselves -----------------------------------------------

def test_a_right_click_on_a_segment_opens_nothing(qtbot, main_window):
    """Only the left button is a click here; the right one is not swallowed."""
    segment = main_window.status_readout.alignment_segment

    click(qtbot, segment, Qt.RightButton)

    assert popup_of(segment) is None


def test_the_detail_part_of_the_readout_is_not_clickable(main_window):
    """Coordinates and the closest trace name nothing to switch to."""
    from PyReconstruct.modules.gui.main.status_readout import StatusSegment

    assert not isinstance(main_window.status_readout.detail_label, StatusSegment)


def test_a_second_click_does_not_leave_the_first_menu_behind(qtbot, main_window):
    """Repeated clicks must not accumulate menus parented to the segment.

    A press arriving right after a popup hides is the dismissing press and is
    swallowed by design (the explicit toggle), so the re-click here backdates
    the hide stamp the way real time passing would."""
    segment = main_window.status_readout.alignment_segment

    click(qtbot, segment)
    first = popup_of(segment)
    assert first is not None
    choose(qtbot, first, main_window.series.alignment)
    qtbot.waitUntil(lambda: popup_of(segment) is None, timeout=2000)

    segment._popup_hidden_at = 0.0
    click(qtbot, segment)
    assert popup_of(segment) is not None


def test_pill_menus_offer_the_management_dialog(qapp, main_window):
    """The pills must offer a road to CREATING a profile or alignment, not
    only switching (his click test, 2026-08-25): a separated final row opens
    the matching management dialog."""
    menu = main_window.quickSwitchBCProfile()
    try:
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert labels[-1] == "New or edit profiles..."
        assert menu.actions()[-2].isSeparator()
    finally:
        menu.hide()

    menu = main_window.quickSwitchAlignment()
    try:
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert labels[-1] == "New or edit alignments..."
        assert menu.actions()[-2].isSeparator()
    finally:
        menu.hide()


def test_pill_menus_clear_the_pill_by_the_section_gap(qapp, main_window, qtbot):
    """The alignment and B/C menus sat flush against their pill and read as
    crowded; the section popup's own 2px lift is the approved spacing (his
    call, 2026-08-26), so both menus use it."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    for open_menu, segment in (
        (main_window.quickSwitchAlignment,
         main_window.status_readout.alignment_segment),
        (main_window.quickSwitchBCProfile,
         main_window.status_readout.bc_profile_segment),
    ):
        menu = open_menu()
        try:
            pill_top = segment.mapToGlobal(segment.rect().topLeft()).y()
            gap = pill_top - (menu.pos().y() + menu.sizeHint().height())
            assert gap == MainWindow.PILL_MENU_GAP
        finally:
            menu.hide()
