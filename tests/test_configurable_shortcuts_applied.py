"""Every configurable shortcut must actually reach the action it is listed for.

A keyboard shortcut in this app has three separate places it has to agree:

1. a default in ``PyReconstruct/modules/datatypes/default_settings.py``, which is
   what makes the key user-configurable at all (``Series.getOption`` reads it
   from the settings store, falling back to the default);
2. a row in ``help_shortcuts`` in ``PyReconstruct/modules/gui/dialog/shortcuts.py``,
   which is what puts an editable field in front of the user; and
3. the third element of the action tuple that builds the menu item, which is what
   ``newAction`` turns into ``QAction.setShortcut``.

Only (3) binds anything. Pass a ``Series`` there and ``newAction`` looks the key
up by ``act_name`` (``action.setShortcut(kbd.getOption(act_name))``); pass a
string and the string wins; pass ``""`` and the action has no key at all. So an
action can carry a documented, editable, defaulted shortcut in (1) and (2) and
still be dead, and nothing in the codebase noticed. That is the class of bug
these tests exist to make impossible to ship silently.

The sweep is ``test_menu_actions_honor_a_user_configured_shortcut``. It sets every
configurable shortcut to a distinct sentinel key in a *temporary* settings store,
builds the real menubar, field menu and label menu through the real
``MainWindow.createMenuBar`` / ``createContextMenus``, and then asserts that every
action that came out carries the key the settings say it should. Using a sentinel
rather than the shipped default is the point: a site that hardcodes the same
string as its own default passes an equality check against the default and fails
this one.

Two names are grandfathered in ``KNOWN_UNAPPLIED``, with the reason and the open
question for each. ``test_known_unapplied_registry_is_current`` fails if either
one starts working, so the entry is deleted by whoever fixes it rather than
rotting into a permanent exemption.

Settings scoping, and why it is not optional. ``Series.getOption`` writes the
default back into the settings store on a miss, and the production store is
``QSettings("KHLab", "PyReconstruct")``, which is machine-wide and holds the real
user's real preferences. Every test here injects a ``DictSettingsStore`` before
touching an option, so nothing in this file can reach that domain.
"""

import pytest

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.dialog.shortcuts import help_shortcuts

pytestmark = pytest.mark.gui


# --------------------------------------------------------------------------- #
# the two known offenders
# --------------------------------------------------------------------------- #
KNOWN_UNAPPLIED = {
    # Built once, in `get_context_menu_list_obj` in
    # `PyReconstruct/modules/gui/main/context_menu_list.py`, with `""` as its
    # shortcut argument. There is no other construction site, so `Ctrl+Shift+H`
    # has never bound anything: "Set hosts..." is listed in the shortcuts dialog
    # with a key that does nothing. The fix is to pass the series (one word), and
    # it is not in this PR because that file is being edited by another open PR.
    "sethosts_act": "no construction site passes a series (context_menu_list.py)",
    # Built in `return_view_menu` in `PyReconstruct/modules/gui/main/menubar.py`
    # with the literal `"Home"`. The key therefore works out of the box, and a
    # rebind in the shortcuts dialog is stored but silently discarded on the next
    # menubar rebuild. Which side is wrong is a decision, not a bug fix:
    # `docs/USER_GUIDE.md` states that `Home` is one of four *fixed* menu
    # shortcuts, but it is the only one of those four that also has a default in
    # `default_settings.py` and an editable row in the shortcuts dialog. Either
    # the literal goes (making it rebindable, as the settings and the dialog
    # already promise) or the default and the dialog row go (making it fixed, as
    # the guide says). Left alone until that is settled.
    "homeview_act": "hardcoded 'Home' in menubar.py; docs call the key fixed",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _dialog_rows():
    """The ``act_name``s the shortcuts dialog puts an editable field in front of."""
    return [
        item[0]
        for item in help_shortcuts
        if isinstance(item, tuple) and item[0].endswith("_act")
    ]


def _configurable():
    """Dialog rows that are also settings keys, so they resolve to a real key."""
    return [name for name in _dialog_rows() if name in Series.qsettings_defaults]


def _sentinels(names):
    """A distinct, valid, unlikely-to-be-hardcoded key sequence per name.

    Uniqueness across names is only cosmetic (nothing here presses these keys),
    but it keeps a failure message unambiguous about which action reported which
    other action's key.
    """
    return {name: f"Ctrl+Alt+F{(i % 30) + 1}" for i, name in enumerate(names)}


@pytest.fixture
def scoped_series(real_series):
    """``real_series``, with its settings redirected into memory.

    See the module docstring: without this, reading an option can write to the
    machine-wide ``QSettings`` domain that holds the real user's preferences.
    """
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    real_series.setSettingsStore(DictSettingsStore())
    return real_series


def _main_window_stub(series):
    """A QWidget carrying the surface the two real menu builders touch.

    It has to be a real QWidget: ``QMenu(self)``, ``QMenuBar(self)`` and
    ``widget.addAction`` are all real Qt calls, and ``newAction`` hangs each
    built QAction off this object under its ``act_name``, which is exactly what
    the assertions read back.

    ``menubar`` is pre-built so ``createMenuBar`` takes its "already have one"
    branch instead of calling ``QMainWindow.menuBar()``, which a QWidget has not
    got. The field is the shared stub from ``test_context_menu_frequency``, whose
    three entity submenus really are the shared builders, so the object submenu
    (where the "Set hosts..." tuple lives) is built by production code.
    """
    from PySide6.QtWidgets import QMenuBar, QWidget

    from test_context_menu_frequency import _FieldStub

    class _Reaches:
        """Answers any attribute chain and any call.

        The menu definitions reach two deep in places
        (``self.mouse_palette.modifyAllPaletteButtons``), so a flat
        ``lambda *a, **k: []`` is not enough.

        Dunder names must still raise. ``newAction`` hands the handler to
        ``QMenu.addAction(text, receiver, shortcut)``, and shiboken picks its
        overload by probing the object's special attributes: an object that
        answers ``__self__`` and ``__func__`` with more of itself resolves to the
        C++ ``(QObject*, const char*)`` overload and segfaults the interpreter.
        """

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return _Reaches()

        def __call__(self, *a, **k):
            return []

    class Stub(QWidget):
        def __getattr__(self, name):
            # changeAlignment / mouse_palette / toggleZtraces / ... -- the menu
            # definitions only need these to exist, not to do anything.
            return _Reaches()

    stub = Stub()
    stub.series = series
    stub.field = _FieldStub(series)
    stub.menubar = QMenuBar(stub)
    return stub


@pytest.fixture
def menu_stub(qapp, scoped_series):
    """A stub main window, with the keyboard state restored on the way out.

    The modifier reset is the load-bearing part, and it is a suite-wide hazard
    rather than anything specific to these tests. Measured with PySide6 6.5.2 on
    the offscreen platform: ``QTest.keyClick(w, key, Ctrl | Shift)`` leaves
    ``QApplication.keyboardModifiers()`` reporting ``ShiftModifier`` for the rest
    of the process. Every later test that clicks a table row then gets a
    shift-extended selection instead of a single-row one, and without this
    teardown a single ``Ctrl+Shift+H`` in the last test below made 15 tests in
    ``test_section_list_real_widget.py`` fail, none of which touch this file or
    press a key. Any unmodified key event clears the stuck state.

    Destroying the widget is ordinary hygiene by comparison: the real menus hang
    roughly 190 QActions off it, all with the default ``WindowShortcut`` context.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    stub = _main_window_stub(scoped_series)
    yield stub

    QTest.keyRelease(stub, Qt.Key_Shift)
    qapp.processEvents()
    assert qapp.keyboardModifiers() == Qt.KeyboardModifier.NoModifier, (
        "a modifier is still latched in QApplication; later widget tests will "
        "see extended selections. Send an unmodified key event to clear it."
    )

    stub.hide()
    for action in list(stub.actions()):
        stub.removeAction(action)
    stub.setParent(None)
    stub.deleteLater()
    qapp.processEvents()


def _build_real_menus(stub):
    """Run the real menu construction, in the real order.

    ``createContextMenus`` embeds the four clipboard QActions the menubar owns
    (``self.cut_act`` and friends), so the menubar has to be built first.
    """
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    MainWindow.createMenuBar(stub)
    MainWindow.createContextMenus(stub)
    return stub


def _built_actions(stub, names):
    """The subset of ``names`` that ended up as QActions on ``stub``."""
    from PySide6.QtGui import QAction

    out = {}
    for name in names:
        action = getattr(stub, name, None)
        if isinstance(action, QAction):
            out[name] = action
    return out


# --------------------------------------------------------------------------- #
# 1. the three places a shortcut lives have to agree about which keys exist
# --------------------------------------------------------------------------- #
def test_every_dialog_row_is_a_real_settings_key():
    """A dialog row with no default has nothing to read or write.

    ``ShortcutsDialog`` builds each row as
    ``QKeySequenceEdit(self.series.getOption(sc), self)``, and ``getOption``
    returns ``None`` for a name it does not know. So a row whose ``act_name`` is
    missing from ``default_settings`` is a field that starts blank and, on OK,
    writes a key that ``setOption`` then drops on the floor.
    """
    orphans = [name for name in _dialog_rows() if name not in Series.qsettings_defaults]
    assert not orphans, (
        "shortcuts dialog rows with no entry in default_settings.py, so "
        f"getOption returns None for them: {orphans}"
    )


def test_no_dialog_row_appears_twice():
    """``ShortcutsDialog.act_widgets`` is keyed by ``act_name``.

    A duplicated row would silently collapse to whichever field was built last,
    and the earlier one would accept input that is then thrown away.
    """
    rows = _dialog_rows()
    duplicates = sorted({name for name in rows if rows.count(name) > 1})
    assert not duplicates, f"duplicated rows in help_shortcuts: {duplicates}"


# --------------------------------------------------------------------------- #
# 2. the sweep
# --------------------------------------------------------------------------- #
def test_menu_actions_honor_a_user_configured_shortcut(qapp, scoped_series, menu_stub):
    """Every built action must carry the key its settings entry says it carries.

    The sentinel keys are the mechanism of the test. Comparing against the
    shipped default would pass for an action whose menu tuple hardcodes a copy of
    that default, which is precisely one of the two bugs in
    ``KNOWN_UNAPPLIED``. Setting the option to something no source file contains
    means only a real ``getOption`` lookup can produce the expected value.
    """
    names = _configurable()
    sentinels = _sentinels(names)
    for name, key in sentinels.items():
        scoped_series.setOption(name, key)

    stub = _build_real_menus(menu_stub)
    built = _built_actions(stub, names)
    assert built, "no configurable actions were built; the harness is broken"

    unapplied = sorted(
        name
        for name, action in built.items()
        if action.shortcut().toString() != sentinels[name]
    )
    unexpected = [name for name in unapplied if name not in KNOWN_UNAPPLIED]
    assert not unexpected, (
        "these actions are listed in the shortcuts dialog with a configurable "
        "default but ignore it, so the key a user sets does nothing: "
        + ", ".join(
            f"{name} (settings say {sentinels[name]!r}, action has "
            f"{built[name].shortcut().toString()!r})"
            for name in unexpected
        )
        + ". Pass the series as the third element of the action tuple so "
        "newAction resolves the key by act_name."
    )


def test_known_unapplied_registry_is_current(qapp, scoped_series, menu_stub):
    """``KNOWN_UNAPPLIED`` must not outlive the bugs it describes.

    Without this, fixing one of the two would leave a permanent exemption behind
    that quietly re-opens the hole for the next action to fall into.
    """
    names = _configurable()
    sentinels = _sentinels(names)
    for name, key in sentinels.items():
        scoped_series.setOption(name, key)

    stub = _build_real_menus(menu_stub)
    built = _built_actions(stub, names)

    fixed = sorted(
        name
        for name in KNOWN_UNAPPLIED
        if name in built and built[name].shortcut().toString() == sentinels[name]
    )
    assert not fixed, (
        f"{fixed} now honor their configured shortcut. Delete them from "
        "KNOWN_UNAPPLIED in this file."
    )

    missing = sorted(name for name in KNOWN_UNAPPLIED if name not in built)
    assert not missing, (
        f"{missing} are in KNOWN_UNAPPLIED but are no longer built by the "
        "menus this test constructs. Re-check where they live, or drop them."
    )


# --------------------------------------------------------------------------- #
# 3. the palette mode keys, which are bound outside the menus
# --------------------------------------------------------------------------- #
def test_palette_mode_shortcuts_are_read_from_settings(qapp, scoped_series, menu_stub):
    """The nine ``use*_act`` mode keys never appear in a menu tuple.

    They are bound in ``MainWindow.createPaletteShortcuts`` via
    ``self.addAction("", self.series.getOption(act_name), act)``, which is a
    different code path from ``newAction`` and so needs its own guard. They are
    the only configurable rows the menu sweep above cannot see.
    """
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    modes = [name for name in _configurable() if name.startswith("use")]
    assert len(modes) == 9, f"expected the nine mouse-mode keys, got {modes}"

    sentinels = _sentinels(modes)
    for name, key in sentinels.items():
        scoped_series.setOption(name, key)

    stub = menu_stub
    MainWindow.createPaletteShortcuts(stub)

    built = _built_actions(stub, modes)
    assert set(built) == set(modes), (
        f"mouse-mode actions not built: {sorted(set(modes) - set(built))}"
    )
    wrong = {
        name: action.shortcut().toString()
        for name, action in built.items()
        if action.shortcut().toString() != sentinels[name]
    }
    assert not wrong, f"mouse-mode keys not read from settings: {wrong}"


# --------------------------------------------------------------------------- #
# 4. why nobody reported it: the dialog papers over it, until the next rebuild
# --------------------------------------------------------------------------- #
def test_the_shortcuts_dialog_temporarily_repairs_an_unapplied_key(qapp, scoped_series, menu_stub):
    """Opening the shortcuts dialog and pressing OK makes a dead key fire.

    ``MainWindow.resetShortcuts`` walks the dialog's rows and calls
    ``getattr(self, act_name).setShortcut(kbd)`` on the very QAction the menu
    built, so it overwrites the ``""`` the menu tuple supplied. That is the whole
    explanation for why an action listed with a key that does nothing was never
    reported: anyone who went looking at the shortcuts list repaired it on the way
    past, for as long as that menu object lived.

    ``createContextMenus`` then rebuilds the menu from the same tuples, and
    ``newAction`` re-applies the ``""``. Hence "temporarily".
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from PyReconstruct.modules.gui.main.main_window import MainWindow

    dead = "sethosts_act"
    if dead not in KNOWN_UNAPPLIED:  # pragma: no cover - registry kept current
        pytest.skip(f"{dead} has been fixed; this test has nothing to demonstrate")

    fired = []
    stub = menu_stub
    stub.field.setHosts = lambda *a, **k: fired.append("setHosts")
    _build_real_menus(stub)
    stub.show()
    qapp.processEvents()

    key = scoped_series.getOption(dead)
    assert key == "Ctrl+Shift+H", f"unexpected default for {dead}: {key!r}"
    assert stub.sethosts_act.shortcut().toString() == "", (
        "premise gone: the menu now binds a key for this action"
    )

    def press():
        fired.clear()
        QTest.keyClick(stub, Qt.Key_H, Qt.ControlModifier | Qt.ShiftModifier)
        qapp.processEvents()
        return list(fired)

    assert press() == [], "Ctrl+Shift+H fired before the dialog repaired it"

    # what pressing OK does, for the rows the dialog offers
    MainWindow.resetShortcuts(stub, {dead: key})
    assert stub.sethosts_act.shortcut().toString() == "Ctrl+Shift+H"
    assert press() == ["setHosts"], (
        "resetShortcuts did not make the key work, so the workaround this test "
        "documents does not exist and the docstring is wrong"
    )

    # and what the next menu rebuild does to it
    MainWindow.createContextMenus(stub)
    assert stub.sethosts_act.shortcut().toString() == "", (
        "the rebuilt action kept the repaired key; re-read newAction"
    )
    assert press() == [], "the repair survived a menu rebuild"
