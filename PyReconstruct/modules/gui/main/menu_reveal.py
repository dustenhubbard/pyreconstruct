"""Reveal a menu command in place: open the real menus and highlight it.

This is the macOS Help-menu behavior applied to the app's Qt-drawn, in-window
menubar. Given a path like "Object > Operations > Smooth object traces" (the
" > "-joined trail of cleaned labels that menu_search.collect_menu_commands
produces), reveal_path opens the top-level menu, walks down the chain opening
each submenu, and leaves the final action highlighted so the user can SEE
where the command lives, not just read its path in a list.

Two Qt facts this module leans on, both measured on this codebase under the
offscreen platform rather than assumed:

  * QMenuBar.setActiveAction(topAction) pops the top-level QMenu open, and on
    an already-open QMenu, setActiveAction(submenuAction) both highlights the
    row and pops its submenu, synchronously enough that one processEvents
    settles it. That is why the walk below is plain synchronous calls with no
    QTimer chains: the caller (the Help search field) cannot await a timer,
    and none is needed.
  * PySide's Python wrappers for menu actions can be invalidated the moment
    the references that produced them lapse (see the collect_menu_commands
    docstring for the measurement). So nothing here is cached across calls:
    every reveal re-walks the live menubar, and every wrapper access is
    guarded with shiboken6.isValid. Within a single call the local chain list
    keeps its wrappers alive, which is the one lifetime that IS reliable.

Both entry points must never raise: they run inside the search field's
keyboard handling, where an exception would take the whole palette down over
a cosmetic feature. Failures degrade to "nothing revealed" instead.
"""

from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from PyReconstruct.modules.gui.main.menu_search import clean_label


def _settle():
    """Flush pending events so a just-opened menu is actually shown.

    Menu popping schedules work on the event loop; without a flush,
    isVisible checks (ours and the tests') would race it.
    """
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _find(owner, label):
    """The first action under owner (QMenuBar or QMenu) with this cleaned label.

    Matching mirrors collect_menu_commands exactly, separator-skipping
    included, so any path that walker can produce resolves here and the two
    modules cannot drift on what a label "is".
    """
    for action in owner.actions():
        if not isValid(action):
            continue
        if action.isSeparator():
            continue
        if clean_label(action.text()) == label:
            return action
    return None


def _resolve_chain(menubar, labels):
    """The actions along the path, top to leaf, or None if the trail breaks.

    Resolved in full BEFORE anything opens: an unknown path must return False
    with no side effects, and popping menus is the side effect. Every
    intermediate must own a submenu; a trail that crosses a plain command
    ("File > Save > deeper") is broken by definition.
    """
    chain = []
    owner = menubar
    for position, label in enumerate(labels):
        action = _find(owner, label)
        if action is None:
            return None
        chain.append(action)
        if position < len(labels) - 1:
            owner = action.menu()
            if owner is None or not isValid(owner):
                return None
    return chain


def reveal_path(menubar, path: str) -> bool:
    """Open the real menus along path and highlight the final item.

    Returns True when the item was found and highlighted, False otherwise
    (unknown path, or the trail crosses something that is not a menu). A
    disabled item is revealed without the highlight, because Qt will not
    make a disabled action active; that still returns True (see _reveal).
    Safe to call repeatedly: each reveal closes the previous one first, so
    the caller can drive it from a selection-changed signal. Never raises.
    """
    try:
        return _reveal(menubar, path)
    except Exception:
        # A half-opened menu chain with no owner is worse than no reveal at
        # all, so even the failure path tidies up before reporting False.
        try:
            close_reveal(menubar)
        except Exception:
            pass
        return False


def _reveal(menubar, path):
    if not isinstance(path, str) or menubar is None or not isValid(menubar):
        return False
    labels = [segment.strip() for segment in path.split(" > ")]
    if len(labels) < 2 or not all(labels):
        # collect_menu_commands only produces paths with a top-level menu AND
        # a command under it; anything shorter names a menu, not an item
        return False

    chain = _resolve_chain(menubar, labels)
    if chain is None:
        return False

    # Only now, with the whole trail known to exist, is opening safe. Closing
    # first makes back-to-back reveals deterministic: Qt auto-closes a sibling
    # top-level menu when another activates, but a still-open grandchild from
    # the previous reveal would not be ours anymore once the walk moves on.
    close_reveal(menubar)

    # Opens the top-level QMenu (measured under offscreen, see module docstring)
    menubar.setActiveAction(chain[0])
    _settle()

    menu = chain[0].menu()
    for action in chain[1:]:
        if menu is None or not isValid(menu) or not menu.isVisible():
            close_reveal(menubar)
            return False
        menu.setActiveAction(action)
        _settle()
        submenu = action.menu()
        if submenu is None:
            break  # the leaf: highlighted, nothing further to open
        if not submenu.isVisible():
            # Belt for a platform where setActiveAction highlights the row
            # without popping the submenu (not observed offscreen, but menu
            # popping is exactly where platforms differ). popup at the row's
            # right edge is where the submenu would appear anyway.
            submenu.popup(
                menu.mapToGlobal(menu.actionGeometry(action).topRight())
            )
            _settle()
        if not submenu.isVisible():
            # Partial reveal: the submenu action that leads onward stays
            # highlighted. The user still sees where to go next, which beats
            # tearing the menus down over an unpoppable submenu.
            return True
        menu = submenu

    active = menu.activeAction() if isValid(menu) else None
    if (
        active is not None
        and isValid(active)
        and clean_label(active.text()) == labels[-1]
    ):
        return True
    # QMenu.setActiveAction refuses disabled actions outright (measured on
    # Qt 6.5.2: activeAction() stays None). The search palette lists disabled
    # commands on purpose, because finding one teaches where it lives, so a
    # disabled item still counts as revealed: its menu is open and the grayed
    # row is on screen, which is all the reveal a disabled command can get.
    final = chain[-1]
    return (
        isValid(menu)
        and menu.isVisible()
        and isValid(final)
        and not final.isEnabled()
    )


def close_reveal(menubar) -> None:
    """Close anything reveal_path opened. Never raises.

    Stateless on purpose: rather than remember what was opened (cached
    wrappers, the trap above), it re-walks the tree and closes every visible
    menu. Children close before parents so no floating grandchild is
    orphaned when its parent disappears out from under it.
    """
    try:
        if menubar is None or not isValid(menubar):
            return
        for top in menubar.actions():
            if not isValid(top):
                continue
            menu = top.menu()
            if menu is not None and isValid(menu):
                _close_tree(menu)
        menubar.setActiveAction(None)
        _settle()
    except Exception:
        pass


def _close_tree(menu):
    for action in menu.actions():
        if not isValid(action):
            continue
        submenu = action.menu()
        if submenu is not None and isValid(submenu):
            _close_tree(submenu)
    if menu.isVisible():
        menu.close()
