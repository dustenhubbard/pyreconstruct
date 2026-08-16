import os
import re
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMenuBar,
    QMenu,
    QProgressDialog,
    QMessageBox,
    QLabel,
    QProxyStyle,
    QStyle,
    QStyleOptionMenuItem
)
from PySide6.QtGui import (
    QAction,
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
    QColor,
    QFont,
    QScreen
)
from PySide6.QtCore import Qt, QEvent, QObject

from PyReconstruct.modules.constants import welcome_series_dir


mainwindow = None
qt_offscreen = os.getenv("QT_QPA_PLATFORM") == "offscreen"

# Set to "1" by a caller that is driving the GUI with nobody at the keyboard: a
# click-test harness, a screenshot script, a computer-use agent. See
# `user_is_present`, the only reader.
UNATTENDED_ENV_VAR = "PYRECON_UNATTENDED"


def get_screen_info(screen: QScreen) -> dict:
    """Return screen information."""

    screen_rect = screen.size()

    screen_info = {
        "width"  : screen_rect.width(),
        "height" : screen_rect.height(),
        "dpi"    : round(screen.physicalDotsPerInch())
    }

    return screen_info


def get_window_size(window) -> tuple:
    """Return width and height of the mainwindow."""
    
    return (
        window.size().width(),
        window.size().height()
    )


def get_center_pixel(window) -> tuple:
    """Return the center pixel of the mainwindow."""

    width, height = get_window_size(window)

    return width // 2, height // 2


def get_clicked(event) -> tuple:
    """Return L, M, and R mouse clicks."""

    buttons = event.buttons()
    
    return (
        Qt.LeftButton in buttons,
        Qt.MiddleButton in buttons,
        Qt.RightButton in buttons
    )


def get_welcome_setup() -> tuple:
    """Return welcome series setup."""

    welcome_dir = Path(welcome_series_dir)
    welcome_ser = welcome_dir  / "welcome.ser"

    date = datetime.now().strftime("%m%d")
    welcome_src_today = welcome_dir.parent / f"dates/{date}"

    ## Check if date specific splash image exists
    if welcome_src_today.exists():

        welcome_src = str(welcome_src_today)

    else:

        welcome_src = str(welcome_dir.parent)

    welcome_setup = (
        str(welcome_ser),        # .ser
        {0: "welcome.0"},        # secs
        welcome_src              # src
    )

    return welcome_setup


class MenuShortcutSpacingStyle(QProxyStyle):
    """Give menu shortcut keybinds breathing room from their labels.

    Qt already right-justifies a menu item's shortcut against the item's right
    edge, but the native macOS style sizes the item so tightly that the widest
    label runs almost into the shortcut column (a ~5 px gap, measured). Menus
    here are always Qt-drawn -- the menubar is in-window, not the native macOS
    bar -- so the fix belongs in the style layer, on every platform.

    Widening CT_MenuItem pushes the shortcut column right while leaving all
    painting to the native style; a stylesheet on QMenu is NOT an option for
    the default theme, because any QMenu::item rule replaces the native item
    layout wholesale (it visibly strips the native left padding, among other
    things).

    The widening is applied to EVERY row of a menu that shows shortcuts, not
    just to the rows that have one. That is the whole subtlety: Qt lays a menu
    out at one width for all items -- QMenuPrivate::updateActionRects takes the
    maximum over items and only then adds the shortcut column -- so widening
    just the shortcut rows moves the column only when a shortcut row happens to
    be the widest row. Measured on the real menubar (macOS, native style), the
    first version of this class therefore did nothing at all to View, whose
    widest row is the shortcut-less "Set zoom when finding contours...", and
    only 12 of 14 px to Lists, where "Series history" nearly ties the widened
    rows. Widening every row makes the offset unconditional and uniform.

    The extra width is one line-height of the menu font, so the gap scales
    with the user's font size and lands near the item's own left padding.
    Menus that show no shortcut are left alone -- asked via Qt itself, see
    _shows_a_shortcut -- which covers both a menu whose actions have no
    shortcuts (File > Utilities) and the macOS default of hiding shortcuts in
    context menus, where the space would buy nothing. The qdark theme is
    unaffected either way: its stylesheet routes menu-item sizing through
    QStyleSheetStyle, which bypasses this proxy and already spaces items
    generously.
    """

    @staticmethod
    def _shows_a_shortcut(menu : QMenu) -> bool:
        """Whether this menu will actually render a shortcut column.

        Qt is the authority, so it is asked rather than second-guessed:
        QMenu.initStyleOption appends "\\t<shortcut>" to the option text only
        for a shortcut it is going to draw. Whether it does depends on more
        than the QAction (Qt.AA_DontShowShortcutsInContextMenus, which is on by
        default on macOS, and whether the menu was opened from a menubar), and
        none of that is reachable from a style -- but the resulting option text
        is.
        """
        option = QStyleOptionMenuItem()
        for action in menu.actions():
            if action.isSeparator() or action.shortcut().isEmpty():
                continue
            menu.initStyleOption(option, action)
            if "\t" in option.text:
                return True
        return False

    def sizeFromContents(self, contents_type, option, size, widget):
        size = super().sizeFromContents(contents_type, option, size, widget)
        if (
            contents_type == QStyle.ContentsType.CT_MenuItem
            and isinstance(option, QStyleOptionMenuItem)
            and option.menuItemType != QStyleOptionMenuItem.MenuItemType.Separator
            and isinstance(widget, QMenu)
            and self._shows_a_shortcut(widget)
        ):
            size.setWidth(size.width() + option.fontMetrics.height())
        return size


class KeepMenuOpenOnToggle(QObject):
    """Keep a menu on screen when one of its checkable rows is toggled.

    Qt closes a menu on any activation: QMenu's mouse release handler calls
    QMenuPrivate::activateAction, which calls hideUpToMenuBar() before the
    action is triggered, and it makes no distinction between a command ("Save
    as...", which is finished once it has run) and a toggle ("Hide image", which
    is one of a set the user is usually setting together). Setting three of the
    four palette visibility boxes therefore cost twelve interactions: three menus
    to walk down, one click, and the whole descent again. (Those four have since
    been hoisted to View itself, so the descent is gone as well as the reopening;
    this filter is what removed the reopening, and it still covers them there.)
    In the field's right-click menu it is worse, because reopening a context menu
    means finding somewhere safe to right-click again.

    So the release is intercepted before QMenu sees it, and a checkable action
    is triggered by hand instead. QAction.trigger() on a checkable action flips
    checked and emits triggered(checked), which is exactly what activateAction
    would have produced -- the handlers are connected to `triggered`, so they
    run unchanged and with the same argument -- minus the hide.

    Everything else is deliberately left to Qt by returning False:

      * a non-checkable row still closes the menu, because it is a command;
      * a *disabled* checkable row is ignored, matching Qt (it never becomes the
        current action, so a click on it does nothing and closes nothing);
      * a click that is not on a row (the frame, a separator, outside the menu)
        falls through, so clicking away still dismisses;
      * every key event falls through, so Esc still closes, arrow keys still
        navigate, and a keyboard shortcut still reaches its handler by the
        ordinary route (no menu is open in that case anyway);
      * a non-left button falls through, which keeps the platform rules for
        which buttons activate a menu row where Qt put them.

    The filter is stateless and holds no reference to anything, so one instance
    is installed on every menu that needs it (see keepMenuOpenOnToggle).

    The alternative -- wrapping each toggle in a QWidgetAction holding a
    QCheckBox -- was rejected: it swaps the platform's own menu-item painting
    for an embedded widget, which changes how these rows look and how they
    highlight, and this change is meant to be behavior-only.
    """

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False

        if not isinstance(watched, QMenu):
            return False

        if event.button() != Qt.MouseButton.LeftButton:
            return False

        action = watched.actionAt(event.position().toPoint())

        if action is None or not action.isCheckable() or not action.isEnabled():
            return False

        action.trigger()

        return True


_keep_menu_open_filter = None


def keepMenuOpenOnToggle(menu):
    """Make `menu` keep itself open when a checkable row in it is toggled.

    Called by newAction the moment it makes an action checkable, so every menu
    built through the shared builder gets this for free and no individual menu
    definition has to opt in. That is the whole point: the toggles the user
    complained about live in two different files (the palette visibility group
    in `main/menubar.py`, directly under View since the 2026-08-06 hoist, and the
    field right-click menu's visibility group in `main/context_menu_list.py`),
    and one change in the builder covers both, plus every other toggle the
    builder makes. Because the filter is installed per action rather than per
    menu, moving a row to another menu carries the behavior with it.

    Idempotent by construction. Installing the same filter object twice is
    harmless (Qt moves it to the front of the list rather than adding a second
    entry), so a menu with four checkable rows needs no bookkeeping. Qt also
    removes a destroyed menu from the filter's watch list on its own, which is
    why the single module-level instance can outlive any number of menus.
    """
    global _keep_menu_open_filter

    if not isinstance(menu, QMenu):
        return

    if _keep_menu_open_filter is None:
        _keep_menu_open_filter = KeepMenuOpenOnToggle()

    menu.installEventFilter(_keep_menu_open_filter)


def newMenu(widget : QWidget, container, menu_dict : dict):
    """Create a menu.
    
        Params:
            widget (QWidget): the widget the menu is connected to
            container (QMenu or QMenuBar): the menu containing the new menu
            menu_dict (dict): the dictionary describing the menu
    """
    # create the menu attribute
    menu = container.addMenu(menu_dict["text"])
    setattr(widget, menu_dict["attr_name"], menu)
    # populate the menu
    for item in menu_dict["opts"]:
        addItem(widget, menu, item)


def newAction(widget : QWidget, container : QMenu, action_tuple : tuple):
    """Create an action within a menu.

        Params:
            widget (QWidget): the widget the action is connected to
            container (QMenu): the menu that contains the action
            action_tuple (tuple): the tuple describing the action
                (name, text, keyboard shortcut, function[, tooltip])
    """
    act_name, text, kbd, f = action_tuple[:4]
    tooltip = action_tuple[4] if len(action_tuple) > 4 else None
    # create the action attribute
    action : QAction = container.addAction(text, f, "")

    # optional fifth element: a hover tooltip. setToolTip alone does nothing in
    # a menu -- QMenu only shows action tooltips once the menu itself opts in
    # via setToolTipsVisible, so the containing menu is switched on here, and
    # only here. Menus with no tooltipped action are deliberately left opted
    # out: a QAction's toolTip defaults to its own text, so a blanket opt-in
    # would echo every label back as a redundant tooltip.
    if tooltip:
        action.setToolTip(tooltip)
        container.setToolTipsVisible(True)

    # create the shorcut or checkbox
    if type(kbd) is str:
        if "checkbox" in kbd:
            action.setCheckable(True)
            if "True" in kbd:
                action.setChecked(True)
        else:
            action.setShortcut(kbd)
    elif type(kbd) is tuple:
        # (series, "checkbox"): a checkable action whose shortcut is a
        # user-configurable series option (looked up by act_name). Lets a
        # toggle be a checkbox AND keep its keyboard shortcut -- the plain
        # "checkbox" string form cannot carry a shortcut. Initial checked
        # state is synced from live state on menu build (see checkActions).
        series, flag = kbd
        if "checkbox" in flag:
            action.setCheckable(True)
        action.setShortcut(series.getOption(act_name))
    else:  # assume series was passed in
        action.setShortcut(kbd.getOption(act_name))

    # A checkable row is a persistent on/off state, and states get set in
    # groups, so toggling one must not dismiss the menu the next one is in.
    # Asked of the action rather than of the kbd argument, so both spellings of
    # "checkbox" above are covered by the one question.
    if action.isCheckable():
        keepMenuOpenOnToggle(container)

    # remove previous action
    if act_name in dir(widget):
        widget.removeAction(getattr(widget, act_name))
    
    # attach to widget
    widget.addAction(action)
    setattr(widget, act_name, action)


def newQAction(widget : QWidget, container : QMenu, action : QAction):
    """Add an existing action to the menu.
    
        Params:
            widget (QWidget): the widget the action is connected to
            container (QMenu): the menu that contains the action
            action (QAction): the action to add to the menu
    """
    container.addAction(action)

    # same rule as newAction: a toggle keeps its menu open. Nothing in the app
    # currently reaches this branch with a checkable action, but the rule is a
    # property of checkable menu rows, not of one of the two ways to make one.
    if action.isCheckable():
        keepMenuOpenOnToggle(container)


def addItem(widget : QWidget, container, item):
    """Add an item to an existing menu or menubar
    
        Params:
            widget (QWidget): the widget to contain the attributes
            container: the menu or menubar
            item: the item to add
    """
    if type(item) is tuple:
        newAction(widget, container, item)
    elif type(item) is dict:
        newMenu(widget, container, item)
    elif type(item) is QAction:
        newQAction(widget, container, item)
    elif item is None:
        container.addSeparator()


def populateMenu(widget : QWidget, menu : QMenu, menu_list : list):
    """Create a menu.
    
        Params:
            widget (QWidget): the widget the menu belongs to
            menu (QMenu): the menu object to contain the list objects
            menu_list (list): formatted list describing the menu
    """
    for item in menu_list:
        addItem(widget, menu, item)


def populateMenuBar(widget : QWidget, menu : QMenuBar, menubar_list : list):
    """Create a menubar for a widget.
    
        Params:
            widget (QWidget): the widget containing the menu bar
            menubar (QMenuBar): the menubar object to add menus to
            menubar_list (list): the list of menus on the menubar
    """
    # populate menubar
    for menu_dict in menubar_list:
        newMenu(widget, menu, menu_dict)


def clearMenuBar(widget : QWidget, menubar : QMenuBar):
    """Clear a menubar and let go of the generation of objects it owned.

    Use this instead of a bare `menubar.clear()` anywhere a menubar is rebuilt
    in place, because clearing it is not the whole teardown.

    `newAction` leaves two references to every action it builds: the action is
    added to `widget` (for the shortcut), and it is stored as a `<name>_act`
    attribute on `widget`. Both outlive `menubar.clear()`, which invalidates
    the wrappers for that generation of menus and actions -- clearing drops the
    menubar's claim on them while `widget` is still pointing at them. The next
    build's "remove previous action" step in `newAction` then calls
    `removeAction` on a dead wrapper and raises `RuntimeError: Internal C++
    object (PySide6.QtGui.QAction) already deleted`, halfway through
    repopulating the menubar. Whatever triggered the rebuild -- a checkable row
    in one of these menus, typically -- is left with an error dialog and a
    half-built menubar.

    So drop `widget`'s references first, while the objects are still alive, and
    only then clear. Menus and actions are matched by identity against what the
    menubar actually holds, so attributes belonging to other surfaces (context
    menus in particular, which are rebuilt separately) are left alone.
    """
    # walk the menubar for everything this generation owns
    doomed_actions = []
    doomed_menus = []
    stack = list(menubar.actions())
    while stack:
        action = stack.pop()
        doomed_actions.append(action)
        submenu = action.menu()
        if submenu is not None:
            doomed_menus.append(submenu)
            stack.extend(submenu.actions())

    # detach the actions from the widget while they are still valid
    for action in doomed_actions:
        widget.removeAction(action)

    # forget the attributes pointing into this generation
    doomed_ids = set(map(id, doomed_actions + doomed_menus))
    for attr_name, value in list(vars(widget).items()):
        if id(value) in doomed_ids:
            delattr(widget, attr_name)

    menubar.clear()


def setMainWindow(mw):
    """Set the main window for the gui functions."""
    global mainwindow
    mainwindow = mw


def user_is_present() -> bool:
    """Whether a real user can see and answer a blocking dialog.

    The predicate `notify` and `notifyConfirm` were already applying inline,
    named once so callers outside this module can ask it too.

    False when there is no `QApplication`, and false under
    `QT_QPA_PLATFORM=offscreen`: offscreen has no window manager and no user, so
    a modal dialog spins an event loop that nothing ever dismisses. That is not
    a slow dialog, it is a permanent stall, which is why the callers below fall
    back to the console instead.

    False as well when `PYRECON_UNATTENDED=1`, which is the same stall arriving
    by the other road. Those first two conditions are about *how Qt is drawing*,
    and that is only a proxy for the question actually being asked. A scripted
    GUI session -- a click-test harness, a screenshot run, a computer-use agent
    driving the app -- launches on a real platform with a real `QApplication`,
    so both proxies say "a user is there" and the startup prompts in
    `MainWindow.openSeries` fire into a window nothing will ever click. Opening
    a series whose `src_dir` does not resolve hangs such a run indefinitely on
    "Images Not Found", and `setSeriesCode`'s non-cancelable dialog and the
    unscaled-zarr question sit right behind it. Nothing Qt can observe
    distinguishes that session from a real user's, so the caller has to say so,
    and this is where it says it: every prompt guarded by this predicate already
    has a designed non-blocking answer for "nobody is there" (see `saveNotify`,
    `unsavedNotify` and `linkedUndoNotify` below), and those answers are the
    right ones here for the same reason.

    Exactly `"1"`, matching `PYRECON_FORCE_FROZEN` and `PYRECON_JSER_PRETTY`, so
    a stale `PYRECON_UNATTENDED=0` cannot quietly suppress a real user's
    dialogs. Unset, which is every ordinary launch and the whole existing test
    suite, this changes nothing.

    Both `qt_offscreen` and the environment variable are read at call time (a
    module global and an `os.environ` lookup, not default arguments) so a test
    can flip either to exercise the other branch.
    """
    if os.environ.get(UNATTENDED_ENV_VAR) == "1":
        return False
    return bool(QApplication.instance()) and not qt_offscreen


def notify(message, title="PyReconstruct"):
    """Show an informational message to the user."""

    if user_is_present():

        QMessageBox.information(
            mainwindow,
            title,
            message,
            QMessageBox.Ok
        )

        mainwindow.activateWindow()  # focus on mainwindow

    else:

        print(message)
        input("Press Enter to continue...")


def notifyConfirm(message, yn=False, title="Confirm"):
    """Ask the user to confirm. Returns True if they accept (Yes / OK)."""

    if yn:

        if user_is_present():

            response = QMessageBox.question(
                mainwindow,
                title,
                message,
                QMessageBox.Yes,
                QMessageBox.No
            )
            
            return response == QMessageBox.Yes

        else:

            print(message)
            return ask_yes_no()
        
    else:

        if user_is_present():

            response = QMessageBox.warning(
                mainwindow,
                title,
                message,
                QMessageBox.Ok,
                QMessageBox.Cancel
            )
            
            return response == QMessageBox.Ok


def noUndoWarning():
    """Inform the user of an action that can't be undone."""
    return notifyConfirm("WARNING: This action cannot be undone.")


def saveNotify():
    """Ask whether to save before exiting. Returns "yes", "no" or "cancel".

    With no user present the answer is "yes", because it is the only one of the
    three that neither loses work nor stalls. `saveToJser(notify=True)` treats
    "no" as discard-and-close: it calls `Series.close()`, which deletes the
    hidden working directory holding every unsaved edit, and that is
    unrecoverable. "cancel" makes `MainWindow.closeEvent` call `event.ignore()`,
    so the window never closes, which offscreen is the same stall by another
    route. "yes" writes the series to the `.jser` it was opened from.
    """
    if not user_is_present():
        print(
            "This series has been modified and there is nobody to ask about "
            "saving; saving it before exit."
        )
        return "yes"

    response = QMessageBox.question(
        mainwindow,
        "Exit",
        "This series has been modified.\nWould you like save before exiting?",
        buttons=(
            QMessageBox.Yes |
            QMessageBox.No |
            QMessageBox.Cancel
        )
    )
    
    if response == QMessageBox.Yes:
        return "yes"
    elif response == QMessageBox.No:
        return "no"
    else:
        return "cancel"


def unsavedNotify():
    """Ask whether to open a recovered series. Returns True to open it.

    With no user present the answer is True, for the same reason: False is the
    destructive branch. `openSeries` responds to False by deleting every file in
    the hidden directory and removing it, and that directory is the only copy of
    the work the previous session did not save. True opens it and deletes
    nothing, leaving the saved `.jser` on disk untouched as well.
    """
    if not user_is_present():
        print(
            "An unsaved version of this series was found and there is nobody "
            "to ask about it; opening it rather than discarding it."
        )
        return True

    response = QMessageBox.question(
        mainwindow,
        "Unsaved Series",
        "An unsaved version of this series has been found.\nWould you like to open it?",
        QMessageBox.Yes,
        QMessageBox.No
    )

    return response == QMessageBox.Yes


def linkedUndoNotify(redo=False):
    """Ask how far a linked undo/redo should reach. Returns "all", "section" or
    "cancel".

    The action being undone touched more than one section, and the current
    section's own undo state is part of it, so there are two defensible answers
    and only the user knows which they meant.

    This lives here rather than inline in `MainWindow.undo` for the reason every
    other prompt in this module does: the call sites are slots, and a modal has
    to have somewhere to go when there is no user. It was written inline as a
    constructed `QMessageBox(self).exec()`, which is the one shape the test
    fixture cannot reach. The fixture replaces the `QMessageBox` *statics* and
    the helpers `main_window.py` imports by name; an instance built inside a
    method is neither, so offscreen the `exec()` spun a modal event loop nothing
    could dismiss and `undo()` never returned. That put every operation leaving
    both a series undo and a section-only undo out of reach of the test suite.

    With no user present the answer is "all". It is the complete inverse of the
    action the user last took, it is what the dialog's Yes button does, and it
    is not lossy: `SeriesStates.undoState` moves the state onto the redo stack
    rather than discarding it. "cancel" would be safe in the same sense but
    makes a headless `undo()` a silent no-op, which is worse to debug than an
    undo that went one step further than intended.

        Params:
            redo (bool): True if the pending action is a redo
    """
    if not user_is_present():
        return "all"

    mbox = QMessageBox(mainwindow)
    mbox.setWindowTitle("Redo" if redo else "Undo")
    mbox.setText("This action is linked to multiple sections.\nPlease select how you would like to proceed.")
    mbox.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
    mbox.setButtonText(QMessageBox.Yes, "All sections")
    mbox.setButtonText(QMessageBox.No, "Only this section")
    mbox.setButtonText(QMessageBox.Cancel, "Cancel")

    response = mbox.exec()

    if response == QMessageBox.Yes:
        return "all"
    elif response == QMessageBox.No:
        return "section"
    else:
        return "cancel"


def drawOutlinedText(
        painter : QPainter, 
        x : int, y : int, 
        text : str, 
        c1 : tuple = (255, 255, 255), 
        c2 : tuple = (0, 0, 0),
        size : int = 0, 
        right_justify=False
    ):
    """Draw outlined text using a QPainter object.
    
        Params:
            painter (QPainter): the QPainter object to use
            x (int): the x-pos of the text
            y (int): the y-pos of the text
            text (str): the text to write to the screen
            c1 (tuple): the primary color of the text
            c2 (tuple): the outline color of the text
            size (int): the size of the text
    """
    # create the font
    if not size: size = painter.font().pixelSize()
    font = QFont("Courier New", size, QFont.Bold)

    if right_justify:
        l = QLabel(text=text)
        l.setFont(font)
        l.adjustSize()
        x -= l.width()
        l.close()
    
    w = 1  # outline thickness
    path = QPainterPath()
    if "\n" in text:
        l = QLabel(text="X")
        l.setFont(font)
        l.adjustSize()
        h = l.height()
        l.close()
        split_text = text.split("\n")
        for line in split_text:
            path.addText(x, y, font, line)
            y += h + 1
    else:
        path.addText(x, y, font, text)
    
    # determine outline color if not provided
    if not c2:
        black_outline = c1[0] + 3*c1[1] + c1[2] > 400
        c2 = (0, 0, 0) if black_outline else (255, 255, 255)

    pen = QPen(QColor(*c2), w * 2)
    brush = QBrush(QColor(*c1))
    painter.strokePath(path, pen)
    painter.fillPath(path, brush)


# PROGRESS BAR
class BasicProgbar():
    def __init__(self, text : str, maximum=100):
        """Create a 'vanilla' progress indicator.
        
        Params:
            text (str): the text to display by the indicator
        """
        self.text = text
        self.max = maximum
        if self.max == 0:
            print(f"{text} | Loading...", end="\r")
        else:
            print(f"{text} | 0.0%", end="\r")
    
    def setValue(self, n):
        """Update the progress indicator.
        
            Params:
                p (float): the percentage of progress made
        """
        if self.max == 0:
            return
        print(f"{self.text} | {n / self.max * 100 :.1f}%", end="\r")
        if n == self.max:
            self.close()
    
    def wasCanceled(self):
        """Dummy function -- do nothing!"""
        return False
    
    def close(self):
        """Force finish the progbar."""
        print()


def getProgbar(text, cancel=True, maximum=100):
    """Create a progress bar (either for pyqt or in cmd text).
    
        Params:
            text (str): the text for the progress bar
            cancel (bool): True if progress bar is cancelable
            maximum (int): the max value for the progress bar
    """
    use_basic = False

     # check if PySide6 has benn initialized
    if not QApplication.instance():
        use_basic = True
    else:
        try:
            progbar = QProgressDialog(
                    text,
                    "Cancel",
                    0, maximum,
                    mainwindow
                )
            progbar.setMinimumDuration(1500)
            progbar.setWindowTitle("PyReconstruct")
            progbar.setWindowModality(Qt.WindowModal)
            if not cancel:
                progbar.setCancelButton(None)
        except:
            use_basic = True

    if use_basic:
        progbar = BasicProgbar(text, maximum)
    
    return progbar


def notifyLocked(obj_names, series, series_states):
    """Open a dialog when the user tries to interact with a locked object."""
    if len(obj_names) > 1:
        s = "These objects are locked.\nWould you like to unlock them?"
    else:
        s = "This object is locked.\nWould you like to unlock it?"
    
    response = QMessageBox.question(
        mainwindow,
        "Locked Object",
        s,
        QMessageBox.Yes,
        QMessageBox.No
    )

    if response == QMessageBox.Yes:
        series_states.addState()
        for obj_name in obj_names:
            series.setAttr(obj_name, "locked", False)
        return True
    else:
        return False


def checkMag(s_series, o_series):
    """Check the magnification between the two series. If different, prompt user for response."""
    if abs(o_series.avg_mag - s_series.avg_mag) > 1e-8:
        response = QMessageBox.question(
            mainwindow,
            "Calibration Mismatch",
            (
                "The series have different calibrations.\n" +
                f"Current series: {round(s_series.avg_mag, 8)}\n" +
                f"Importing series: {round(o_series.avg_mag, 8)}\n" + 
                "Would you like to continue?"
            ),
            QMessageBox.Yes,
            QMessageBox.No
        )
        if response != QMessageBox.Yes:
            return False
        
    return True


def importHistoryWarning(s_series, o_series):
    """The warning to show before an import that asked for the history check
    but cannot use it. None when `last_shared_index >= 0`.

    That is not the same as "None when the history check will work". The gate in
    `Section.importTraces` is `not complete_match and last_shared_index >= 0`,
    so two identical non-empty logs skip the history block as well, and this
    function stays silent there. Covering that would mean warning on every
    import of two copies whose logs match, which is a false alarm when they
    genuinely have not diverged; the logs alone do not separate that from two
    sides trimmed to the same prefix. Deliberately left, and pinned in
    `test_no_warning_when_the_two_logs_are_identical`.

    "Check history" compares the two series' logs, keeps their longest matching
    opening run, and treats everything after it as work done since the copies
    diverged. That is what lets the import honor a deletion or a rename instead
    of treating the missing object as something the other person has not drawn
    yet. When the logs have no matching opening run at all, `last_shared_index`
    is -1, there is no divergence point to measure anything against, and
    `Section.importTraces` skips the whole history block: the import goes ahead
    as a plain union of the two series.

    That skip is the thing worth saying out loud. It cannot be inferred from the
    result (the import reports success either way), it undoes the reason the box
    was checked, and the checkbox itself stays checked. Measured on the series
    that ships with this repository, whose log is empty: copy it, delete an
    object in the copy, import the original back with the history check on, and
    the deleted object is present again afterwards.

    A -1 needs only one of the two logs to start differently from the other, so
    an empty log on either side is enough. Series converted from another format
    start with no log, and `LogSet.exportLogHistory` moves old entries out to a
    CSV, so trimming one side and not the other guarantees it.

    This returns the text rather than showing it so that the caller owns the
    dialog. `MainWindow` binds `notifyConfirm`, which is guarded by
    `user_is_present()` and which the test fixtures already stand in for; a
    modal opened from in here would be reachable by neither.

        Params:
            s_series (Series): the current series
            o_series (Series): the series being imported from
        Returns:
            (str or None): the warning text, or None if the history is usable
    """
    from PyReconstruct.modules.datatypes.log import LogSetPair

    s_logs = s_series.getFullHistory()
    o_logs = o_series.getFullHistory()

    if LogSetPair(s_logs, o_logs).last_shared_index >= 0:
        return None

    if not s_logs.all_logs and not o_logs.all_logs:
        cause = "Neither series has a log of its edits."
    elif not s_logs.all_logs:
        cause = "The current series has no log of its edits."
    elif not o_logs.all_logs:
        cause = "The series being imported from has no log of its edits."
    else:
        cause = "The two series' logs have no shared starting point."

    return (
        "The history check cannot be used for this import.\n\n"
        f"{cause} Checking history means comparing the two logs to find where "
        "the series diverged, and there is nothing here to compare. A series "
        "has no usable log if it was converted from another format, or if its "
        "log was exported and trimmed on one side only.\n\n"
        "The traces will still be imported, but as a plain merge of the two "
        "series: an object deleted in one of them can come back, and an object "
        "renamed in one of them can end up under both names. Nothing will be "
        "deleted.\n\n"
        "Continue with the import?"
    )


def get_menu_dict(attr_name: str, title: str, options: list):
    """Return a menu dictionary."""

    return {
        "attr_name": attr_name,
        "text": title,
        "opts": options
    }


def getUserColsMenu(series, newUserCol, setUserCol, editUserCol):
    """Create submenu for editing categorical columns."""
    
    def getSetCall(col_name, opt):
        return (lambda : setUserCol(col_name=col_name, opt=opt))
    
    def getEditCall(col_name):
        return (lambda : editUserCol(col_name=col_name))
    
    custom_categories = []
    menu_i = 0  # keep track of numbers for unique attribute
    opts_i = 0

    for col_name, opts in series.user_columns.items():

        d = get_menu_dict(
            f"user_col_{menu_i}_menu",
            col_name,
            [
                (f"edit_user_col_{menu_i}_act", "Edit...", "", getEditCall(col_name)),
                (f"user_col_{opts_i}_act", "(blank)", "", getSetCall(col_name, "")),
            ]
        )
        
        menu_i += 1
        opts_i += 1

        for opt in opts:

            d["opts"].append(
                (f"user_col_{opts_i}_act", opt, "", getSetCall(col_name, opt))
            )

            opts_i += 1

        custom_categories.append(d)

    opts_list = [("newusercol_act", "New...", "", newUserCol)] + custom_categories
        
    return get_menu_dict(
        "customcategoriesmenu", "Custom categories", opts_list
    )


def getAlignmentsMenu(series, setAlignment):
    """Create submenu for switching alignments."""

    def getCall(alignment):
        return (lambda : setAlignment(alignment))
    
    opts_list = []

    for alignment in sorted(series.alignments):
        opts_list.append(
            (f"{alignment}_alignment_act", alignment, "checkbox", getCall(alignment))
        )
    
    return get_menu_dict("alignmentsmenu", "Series alignment", opts_list)


def getGroupsMenu(self):
    """Create submenu for group visibility."""

    group_viz = self.series.groups_visibility

    
    def getCall(group):
        return lambda: self.toggleGroupViz(group)
    
    opts_list = []

    obj_groups = self.series.groups_visibility

    for group in sorted(obj_groups.keys()):

        opts_list.append(
            (f"{group}_viz_act", group, "checkbox", getCall(group))
        )
    
    return get_menu_dict("groupsvizmenu", "Groups", opts_list)


def getOpenRecentMenu(series, openSeries, clearRecents=None):
    """Create the submenu for opening a recently opened series.

    Rows are listed most-recently-opened first: MainWindow.addToRecentSeries
    inserts at index 0 and the list is walked in order here, so the order is
    reverse-chronological by *open* time (not by file mtime). Paths that no
    longer exist are pruned from the stored option as a side effect, and the
    series currently open is skipped (there is nothing to reopen).

        Params:
            series (Series): the series holding the recently-opened option
            openSeries (callable): MainWindow.openSeries
            clearRecents (callable): handler for "Clear recents"; the row is
                                     omitted when no handler is supplied, so
                                     existing callers keep the old menu.
    """
    def getCall(fp):
        return (lambda : openSeries(jser_fp=fp))

    opts_list = []
    filepaths = series.getOption("recently_opened_series")
    for fp in filepaths.copy():
        if not os.path.isfile(fp):  # remove if not a file
            filepaths.remove(fp)
        elif fp != series.jser_fp:
            opts_list.append(
                (f"openrecent{len(opts_list)}_act", fp, "", getCall(fp))
            )
    series.setOption("recently_opened_series", filepaths)

    if clearRecents is not None:
        # separated from the paths so it cannot be hit by a mis-click aimed at
        # the last remembered series; no separator when the list is empty, which
        # would otherwise open the submenu with a rule above its only row
        if opts_list:
            opts_list.append(None)
        opts_list.append(("clearrecents_act", "Clear recents", "", clearRecents))

    return {
        "attr_name": "openrecentmenu",
        "text": "Open recent series",
        "opts": opts_list
    }


def ask_yes_no(prompt="Please enter y/[n]: "):
    
    valid_responses = {
        'yes' : True,
        'y'   : True,
        'no'  : False,
        'n'   : False
    }

    pattern = r'\[(.*?)\]'
    default = re.findall(pattern, prompt)
    
    if default:
        
        default = default[0]
        
    while True:
        
        response = input(prompt).strip().lower()
        
        if not response and default is not None:
            
            return valid_responses[default.lower()]
        
        elif response in valid_responses:
            
            return valid_responses[response]
        
        else:
            
            print("Please enter 'y' or 'n'.")
