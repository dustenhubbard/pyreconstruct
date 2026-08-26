"""Search the menus: find any menubar command by typing part of its name.

The Help menu carries a search field at its top (a QWidgetAction holding a
QLineEdit), the way macOS's own Help menu does. Typing filters every command
in the menubar into a popup list anchored under the field, each result shown
with the path that leads to it ("Object > Operations > Smooth object traces")
and its shortcut when it has one; Enter (or a click) runs the selected
command and closes the menu. This is the app's answer to the macOS Help-menu
search: the menubar here is Qt-drawn and in-window on every platform, so the
native macOS search never applies to it and the feature has to be built.

Results are NEVER injected into the open Help menu itself. Live-mutating an
open QMenu destroys it out from under its own event handling in this codebase
(the history is on branch fix/menu-rebuild-destroys-open-menu), so the results
live in their own popup window, a focusless tool-tip-flagged QListWidget that
neither steals the menu's grab nor becomes the active window.

The command list is collected fresh each time the Help menu opens, by walking
the live menubar. Fresh matters twice over: the menubar is rebuilt whenever a
series opens (createMenuBar), so cached actions would go stale and trigger
nothing, and enabled state is per-moment, so a command that cannot run right
now is shown grayed rather than hidden -- finding a command teaches where it
lives even when it is not currently applicable.

Menu labels carry two kinds of decoration the search must see through:
mnemonic ampersands ("&File") and the ellipsis convention ("...", opens a
dialog). Both are stripped for matching and kept for display, so typing
"file" finds "&File" and typing "hosts" finds "Set host(s)...".

Hovering or arrow-selecting a result REVEALS it: the real menu opens with the
item highlighted. That behavior lives in menu_reveal (merged separately, from
branch help-search/reveal); until it lands, the guarded import below falls
back to a no-op and the search works without the reveal.
"""

from PySide6.QtCore import QTimer, QEvent, QPoint, Qt
from shiboken6 import getCppPointer, isValid
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QWidget,
    QWidgetAction,
)

try:
    # Provided by the reveal integration (branch help-search/reveal); the
    # module is merged separately, so its absence is a supported state.
    from PyReconstruct.modules.gui.main.menu_reveal import (
        reveal_path,
        close_reveal,
    )
except ImportError:
    def reveal_path(menubar, path):
        """Fallback until menu_reveal lands: nothing is revealed."""
        return False

    def close_reveal(menubar):
        """Fallback until menu_reveal lands: nothing to close."""
        return None


def clean_label(text):
    """A menu label as a user would type it: no mnemonic '&', no trailing dots."""
    return text.replace("&", "").rstrip(".").strip()


def _submenus_by_title_action(widget):
    """Each direct child QMenu of a menu (or menubar), keyed by the C++
    address of the action that opens it.

    This is how the walk pairs a row with its submenu WITHOUT calling
    QAction.menu(). On this tree's PySide6 (6.5.2), QAction.menu() hands the
    QMenu wrapper to Python's lifetime management: the wrapper it returns
    can read as already deleted, and dropping it invalidates the wrappers of
    the menu and everything under it -- including the <act_name> attributes
    MainWindow holds, which the next createMenuBar reaches through to remove
    "previous" actions (measured here: one search, then opening a series,
    crashed the rebuild on its first leaf). QMenu.menuAction() through
    findChildren has no such transfer, and the tests' own menu-walking
    helpers in conftest.py document the same trap.

    Keyed by getCppPointer because wrapper identity is not pointer identity:
    the wrapper a walk creates need not be the wrapper the menu row is.
    """
    return {
        getCppPointer(child.menuAction())[0]: child
        for child in widget.findChildren(
            QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
        if isValid(child)
    }


def collect_menu_commands(menubar):
    """Every runnable command in the menubar: (path, shortcut, enabled, action).

    Walks submenus depth-first. Separators and the submenu titles themselves
    are not commands and are skipped; a submenu contributes its title to the
    PATH of everything inside it instead. Actions with no text (the menubar's
    structural artifacts, including the search field's own QWidgetAction) are
    skipped for the same reason. Submenus are paired with their title rows
    via _submenus_by_title_action, never QAction.menu() -- see that helper
    for the wrapper-invalidation trap the detour avoids.

    Everything the search DISPLAYS is snapshotted here, while the action is
    demonstrably alive: the menubar is rebuilt whenever a series opens
    (createMenuBar), so a stored QAction can be orphaned by the time it is
    wanted. Every later use therefore guards with isValid and re-resolves
    the command by its path instead of trusting a stored wrapper.
    """
    commands = []

    def walk(menu, trail):
        submenus = _submenus_by_title_action(menu)
        for action in menu.actions():
            if not isValid(action):
                continue
            if action.isSeparator():
                continue
            submenu = submenus.get(getCppPointer(action)[0])
            if submenu is not None:
                walk(submenu, trail + [clean_label(action.text())])
                continue
            if not action.text():
                continue
            path = " > ".join(trail + [clean_label(action.text())])
            commands.append(
                (path, action.shortcut().toString(), action.isEnabled(), action)
            )

    top_submenus = _submenus_by_title_action(menubar)
    for top in menubar.actions():
        if not isValid(top):
            continue
        submenu = top_submenus.get(getCppPointer(top)[0])
        if submenu is not None:
            walk(submenu, [clean_label(top.text())])
    return commands


def collect_all_commands(mainwindow):
    """The menubar's commands plus the field's right-click commands.

    Most of the app's day-to-day work lives in the FIELD's context menu (the
    Trace/Object/Ztrace operations), not the menubar, so a search that only
    reads the menubar misses exactly the commands people reach for. The field
    menu is a plain QMenu built onto the MainWindow (createContextMenus), so
    the same walker reads it; its paths are prefixed "Right-click" so a result
    says where the command actually lives. Reveal cannot open a context menu
    (there is nothing to anchor it to until the user right-clicks), so these
    entries list and run only -- reveal_path simply reports False for them.

    Duplicates are real and kept: a command that exists in both the menubar
    and the right-click menu appears twice, under the two places a user could
    actually find it.
    """
    commands = list(collect_menu_commands(mainwindow.menubar))
    field_menu = getattr(mainwindow, "field_menu", None)
    if field_menu is not None and isValid(field_menu):
        commands += _collect_from_menu(field_menu, ["Right-click"])
    return commands


def _collect_from_menu(menu, trail):
    """collect_menu_commands' walk, exposed for a menu that is not a menubar."""
    commands = []
    submenus = _submenus_by_title_action(menu)
    for action in menu.actions():
        if not isValid(action):
            continue
        if action.isSeparator():
            continue
        submenu = submenus.get(getCppPointer(action)[0])
        if submenu is not None:
            commands += _collect_from_menu(
                submenu, trail + [clean_label(action.text())]
            )
            continue
        if not action.text():
            continue
        path = " > ".join(trail + [clean_label(action.text())])
        commands.append(
            (path, action.shortcut().toString(), action.isEnabled(), action)
        )
    return commands


def resolve_command(menubar, path, mainwindow=None):
    """The live QAction for a path, looked up fresh. None when it is gone.

    With `mainwindow` given, right-click commands resolve too; the bare
    menubar form stays for callers (and tests) that predate the field menu
    joining the search.
    """
    if mainwindow is not None:
        source = collect_all_commands(mainwindow)
    else:
        source = collect_menu_commands(menubar)
    for cand_path, _sc, _en, action in source:
        if cand_path == path and isValid(action):
            return action
    return None


def matches(query, path):
    """Case-insensitive: every whitespace-separated word must appear in the path.

    Word-wise rather than substring-wise so "hide object" finds
    "Object > Operations > Hide" -- the words land in different segments, which
    is exactly how a user remembers a command they cannot place.
    """
    q = query.strip().lower()
    if not q:
        return True
    hay = path.lower()
    return all(word in hay for word in q.split())


class MenuSearchField(QWidgetAction):
    """The search field embedded at the top of the Help menu, plus its popup.

    The QWidgetAction's default widget is a padded QLineEdit; the results are
    a separate top-level QListWidget window positioned under the field.
    Results appear as you type (an empty field shows nothing: the closed
    popup IS the empty state, matching the macOS Help menu). Arrow keys move
    the selection without leaving the field, and each arrow move or mouse
    hover asks menu_reveal to open the real menu with the item highlighted.
    Enter runs the selected command; the command is re-resolved by path at
    that moment, never triggered through a stored wrapper (see
    collect_menu_commands for why the wrappers cannot be trusted). Triggering
    closes the menu FIRST and runs after, so a command that opens its own
    modal dialog is not stacked on top of an open menu.

    Keyboard split, and why: a QWidgetAction cannot carry the configurable
    shortcut machinery (newAction's series-form lookup builds plain QActions
    from the menu definition tuples, which are pure data that tests construct
    without a QApplication). So the remappable key (default Ctrl+K) stays on
    searchmenus_act, the visible "Search menus..." row, whose handler opens
    the Help menu and calls focusField() here.

    Lifetime: one instance is built per menubar rebuild (createMenuBar),
    parented to the Help menu, and dies with it; the popup is a window-flagged
    child of the field's container, so it is destroyed along with the action
    rather than leaking one list per rebuild.
    """

    MAX_VISIBLE_ROWS = 12
    MIN_POPUP_WIDTH = 480

    def __init__(self, mainwindow, menu):
        super().__init__(menu)
        self._mainwindow = mainwindow
        self._menu = menu
        self._commands = []
        # True while menu_reveal holds a menu open for the current selection.
        # The reveal closes the Help menu to open the target menu, so the
        # aboutToHide cleanup must stand down while a reveal is in flight or
        # it would tear the search down mid-gesture.
        self._reveal_active = False

        self._query = QLineEdit()
        self._query.setPlaceholderText("Search menus")
        self._query.setClearButtonEnabled(True)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(self._query)
        self.setDefaultWidget(container)

        # ToolTip-flagged: shows without activating and without taking the
        # menu's popup grab, so the Help menu stays open while results are up.
        self._results = QListWidget(container)
        self._results.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._results.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        self._results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._results.setMouseTracking(True)  # itemEntered needs it
        self._results.setAlternatingRowColors(True)

        # The cursor lands in the field whenever Help opens (his call,
        # 2026-08-26). Hooked to the CONTAINER's show, not the menu's
        # aboutToShow: the menu attribute the window holds is not always the
        # menu the menubar shows (measured on the View menu, 2026-08-26), and
        # the widget cannot be shown without its menu being open. The focus
        # is deferred one tick because the menu takes its own focus after the
        # show, and an earlier setFocus is simply dropped.
        container.installEventFilter(self)

        self._query.textChanged.connect(self._refilter)
        self._query.installEventFilter(self)
        self._results.itemEntered.connect(self._hover)
        self._results.itemClicked.connect(self._run)
        menu.aboutToShow.connect(self._snapshot)
        menu.aboutToHide.connect(self._menuHiding)

    def focusField(self):
        """Put the cursor in the field (the Ctrl+K landing point)."""
        self._query.setFocus()
        self._query.selectAll()

    # ----------------------------------------------------------------- #
    # menu lifecycle
    # ----------------------------------------------------------------- #
    def _snapshot(self):
        """Collect the commands fresh on every Help open (see module docs).

        Only the display columns are kept: running re-resolves by path (see
        _run), so retaining the walk's QAction wrappers here would only
        invite someone to trust them across a menubar rebuild.
        """
        self._commands = [
            (path, shortcut, enabled)
            for path, shortcut, enabled, _action
            in collect_all_commands(self._mainwindow)
        ]

    def _menuHiding(self):
        if self._reveal_active:
            # the reveal itself is closing the Help menu to open the target
            # menu; the popup and the query survive the handoff
            return
        self._dismiss()

    def _dismiss(self):
        """Back to the empty state: popup down, reveal closed, field cleared."""
        self._results.hide()
        self._closeReveal()
        self._query.clear()

    def _closeReveal(self):
        self._reveal_active = False
        close_reveal(self._mainwindow.menubar)

    # ----------------------------------------------------------------- #
    # filtering
    # ----------------------------------------------------------------- #
    def _refilter(self, text):
        # rendered from the walk-time snapshot only: the stored wrappers may
        # already be untouchable (see collect_menu_commands)
        self._results.clear()
        if not text.strip():
            # nothing typed, nothing shown: the plain Help menu is the UI
            self._results.hide()
            self._closeReveal()
            return
        for path, shortcut, enabled in self._commands:
            if not matches(text, path):
                continue
            label = f"{path}    ({shortcut})" if shortcut else path
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            if not enabled:
                # visible but not runnable: finding a command teaches where it
                # lives even when the current state cannot use it
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._results.addItem(item)
        if self._results.count():
            # preselect the top hit so Enter runs it, but do not reveal it:
            # revealing opens real menus, far too loud for every keystroke.
            # Reveal waits for a deliberate gesture (arrow key or hover).
            self._results.setCurrentRow(0)
            self._positionPopup()
            self._results.show()
        else:
            self._results.hide()
            self._closeReveal()

    def _positionPopup(self):
        """Anchor the popup directly under the field, sized to the rows."""
        rows = min(self._results.count(), self.MAX_VISIBLE_ROWS)
        row_height = self._results.sizeHintForRow(0)
        height = rows * row_height + 2 * self._results.frameWidth() + 4
        width = max(self._query.width(), self.MIN_POPUP_WIDTH)
        corner = self._query.mapToGlobal(QPoint(0, self._query.height()))
        self._results.setGeometry(corner.x(), corner.y() + 2, width, height)

    # ----------------------------------------------------------------- #
    # selection, reveal, run
    # ----------------------------------------------------------------- #
    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.Show
            and obj is self.defaultWidget()
        ):
            # Help just opened; see the container's installEventFilter above
            QTimer.singleShot(0, self.focusField)
            return False
        if obj is self._query and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            popup_up = self._results.isVisible()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and popup_up:
                row = self._results.currentRow()
                step = 1 if key == Qt.Key.Key_Down else -1
                row = max(0, min(self._results.count() - 1, row + step))
                self._results.setCurrentRow(row)
                self._revealCurrent()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if popup_up and self._results.currentItem() is not None:
                    self._run(self._results.currentItem())
                return True
            if key == Qt.Key.Key_Escape and popup_up:
                # first Escape clears the search; the next one falls through
                # to the menu and closes it
                self._dismiss()
                return True
        return super().eventFilter(obj, event)

    def _hover(self, item):
        self._results.setCurrentItem(item)
        self._revealCurrent()

    def _revealCurrent(self):
        """Ask menu_reveal to open the real menu on the selected command."""
        item = self._results.currentItem()
        if item is None:
            self._closeReveal()
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        self._reveal_active = bool(
            reveal_path(self._mainwindow.menubar, path)
        )

    def _run(self, item):
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        # always re-resolved by path, never the snapshot wrapper: the wrapper
        # may be dead (see collect_menu_commands), and the menubar itself may
        # have been rebuilt since the snapshot was taken
        action = resolve_command(
            self._mainwindow.menubar, path, mainwindow=self._mainwindow
        )
        if action is None or not action.isEnabled():
            return
        self._closeReveal()
        self._results.hide()
        self._query.clear()
        # isValid guard: a menubar rebuild between snapshot and run deletes
        # the Help menu this field was built into; the command must still run
        if isValid(self._menu):
            self._menu.close()
        # after the menu is down, so a command that opens a modal dialog
        # stands alone
        action.trigger()
