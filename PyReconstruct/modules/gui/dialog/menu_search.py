"""Search the menus: find any menubar command by typing part of its name.

Help > "Search menus..." opens a small palette: a line edit over a results
list. Typing filters every command in the menubar, each shown with the path
that leads to it ("Object > Operations > Smooth object traces") and its
shortcut when it has one; Enter or a double-click runs the command and closes
the palette. This is the app's answer to the macOS Help-menu search: the
menubar here is Qt-drawn and in-window on every platform, so the native macOS
search never applies to it and the feature has to be built.

The command list is collected fresh each time the palette opens, by walking
the live menubar. Fresh matters twice over: the menubar is rebuilt whenever a
series opens (createMenuBar), so cached actions would go stale and trigger
nothing, and enabled state is per-moment, so a command that cannot run right
now is shown grayed rather than hidden -- finding a command teaches where it
lives even when it is not currently applicable.

Menu labels carry two kinds of decoration the search must see through:
mnemonic ampersands ("&File") and the ellipsis convention ("...", opens a
dialog). Both are stripped for matching and kept for display, so typing
"file" finds "&File" and typing "hosts" finds "Set host(s)...".
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


def clean_label(text):
    """A menu label as a user would type it: no mnemonic '&', no trailing dots."""
    return text.replace("&", "").rstrip(".").strip()


def collect_menu_commands(menubar):
    """Every runnable command in the menubar: (path, shortcut, enabled, action).

    Walks submenus depth-first. Separators and the submenu titles themselves
    are not commands and are skipped; a submenu contributes its title to the
    PATH of everything inside it instead. Actions with no text (the menubar's
    structural artifacts) are skipped for the same reason.

    Everything the palette DISPLAYS is snapshotted here, while the wrapper is
    demonstrably alive: PySide's Python wrappers for these actions can be
    invalidated the moment the walk's own references lapse (measured on this
    codebase: valid inside the loop, dead immediately after the function
    returns), so a stored QAction may not be touchable later. The wrapper is
    still kept for triggering, but every later access guards with isValid and
    falls back to re-resolving the command by its path.
    """
    commands = []

    def walk(menu, trail):
        for action in menu.actions():
            if not isValid(action):
                continue
            if action.isSeparator():
                continue
            submenu = action.menu()
            if submenu is not None:
                walk(submenu, trail + [clean_label(action.text())])
                continue
            if not action.text():
                continue
            path = " > ".join(trail + [clean_label(action.text())])
            commands.append(
                (path, action.shortcut().toString(), action.isEnabled(), action)
            )

    for top in menubar.actions():
        if not isValid(top):
            continue
        submenu = top.menu()
        if submenu is not None:
            walk(submenu, [clean_label(top.text())])
    return commands


def resolve_command(menubar, path):
    """The live QAction for a path, looked up fresh. None when it is gone."""
    for cand_path, _sc, _en, action in collect_menu_commands(menubar):
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


class MenuSearchDialog(QDialog):
    """The palette. Line edit on top, filtered results under it.

    Arrow keys move the selection without leaving the line edit (the events are
    forwarded), Enter runs the selected command, Escape closes. Triggering
    closes FIRST and runs after, so a command that opens its own modal dialog
    is not stacked on top of the palette.
    """

    def __init__(self, mainwindow):
        super().__init__(mainwindow)
        self._mainwindow = mainwindow
        self.setWindowTitle("Search menus")
        self.setModal(True)
        self._commands = collect_menu_commands(mainwindow.menubar)

        self._query = QLineEdit(self)
        self._query.setPlaceholderText("Type to search every menu...")
        self._results = QListWidget(self)
        self._results.setAlternatingRowColors(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._query)
        layout.addWidget(self._results)
        self.resize(520, 380)

        self._query.textChanged.connect(self._refilter)
        self._query.installEventFilter(self)
        self._results.itemActivated.connect(self._run)
        self._refilter("")
        self._query.setFocus()

    def _refilter(self, text):
        # rendered from the walk-time snapshot only: the stored wrappers may
        # already be untouchable (see collect_menu_commands)
        self._results.clear()
        for path, shortcut, enabled, _action in self._commands:
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
            self._results.setCurrentRow(0)

    def eventFilter(self, obj, event):
        if obj is self._query and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self._results.currentRow()
                step = 1 if key == Qt.Key.Key_Down else -1
                row = max(0, min(self._results.count() - 1, row + step))
                self._results.setCurrentRow(row)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self._results.currentItem()
                if item is not None:
                    self._run(item)
                return True
        return super().eventFilter(obj, event)

    def _run(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        action = next(
            (a for p, _sc, _en, a in self._commands if p == path and isValid(a)),
            None,
        ) or resolve_command(self._mainwindow.menubar, path)
        if not isinstance(action, QAction) or not isValid(action):
            return
        if not action.isEnabled():
            return
        self.accept()
        # after accept, so a command that opens a modal dialog stands alone
        action.trigger()
