"""Suite-wide pytest configuration.

Four jobs, all deliberately small:

1. Default the Qt platform to ``offscreen`` so the suite runs headless without
   the caller having to remember an environment variable. The datatypes import
   PySide6 transitively, so a handful of modules had grown their own
   module-scope ``os.environ.setdefault`` for this; hoisting it here makes it
   uniform and makes a bare ``uv run pytest`` behave the way CI does. It is a
   *setdefault*, so an explicit ``QT_QPA_PLATFORM`` in the environment still
   wins, and tests that deliberately strip the variable from a subprocess
   environment (``test_qt_free_core.py``) are unaffected.

2. Register the suite's custom markers. Registration is what makes
   ``pytest --markers`` self-documenting and what stops a typo'd marker from
   being silently ignored under ``--strict-markers``.

3. Turn a missing ``pytest-qt`` into a collection-time error rather than a
   silent skip, for gui-marked tests only. See
   ``pytest_collection_modifyitems`` for the mechanism and the reason.

4. Provide the shared fixtures for *real-widget* GUI tests: a Series opened
   from a copy of a checked-in .jser, a live data-list dock widget, and a
   recorder that stands in for the modal dialogs. See the fixture docstrings.

4. Print the settings notice, if there is one, below the result line. See
   ``pytest_terminal_summary`` and ``tests/qsettings_isolation.py``.

4. Provide the menu-tree helpers (`menu_leaf_paths`, `menu_action`,
   `menu_shortcut`) and `local_series_settings`. Both exist for tests that check
   a *live* menu rather than the dicts that built it; see the comment above
   `menu_leaf_paths` for why that is a different check.

Note on (2): the ``needs_data``/``needs_pr2`` markers are **scaffolding, and
nothing carries them yet**. That is intentional. The suite currently has no test
that depends on an external corpus or on a second interpreter, so there is
nothing to mark today. Registering the vocabulary now costs three lines;
retrofitting it across 4,000+ tests later does not. The collection-time gating
hooks that will consume these markers (resolving a corpus path, probing a
reference interpreter) belong with the work that introduces the first test
needing them, not here -- a hook that gates on nothing is harder to review and
easier to get wrong than one written against a real first caller. ``gui`` is
different: it is carried from the day it lands, by the tests that use the
fixtures below.
"""

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

# Must run before any test module imports PySide6, which conftest collection
# guarantees: pytest imports this file before it imports any test module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Redirects every `QSettings` in the session to a throwaway location, and watches
# the real one, so no test can edit the developer's own application preferences.
# Imported here, next to the line above, because both have to happen
# before any test module imports PySide6: this one rebinds the `QSettings` name,
# and a module that already imported it keeps its own reference. `isolated_qsettings`
# is an autouse session fixture, so importing the name is what registers it -- it
# is not unused. See tests/qsettings_isolation.py for the mechanism and for the
# two Qt-sanctioned alternatives that were measured and do not work on macOS.
import qsettings_isolation  # noqa: E402
from qsettings_isolation import isolated_qsettings  # noqa: E402,F401


def pytest_terminal_summary(terminalreporter):
    """Print the settings notice under the pass count, where it gets read.

    The session fixture already warns, but a warnings-summary entry two screens
    above the result line is easy to miss in a four-thousand-test run, and this
    is the one thing about a run that the developer has to actually read. Says
    nothing when the real store is untouched, which is the normal case.
    """
    note = qsettings_isolation.terminal_note
    if not note:
        return
    terminalreporter.write_sep("=", "real application settings", yellow=True)
    terminalreporter.write_line(note)

# A small, real, multi-section series that ships with the repo (198 sections,
# used by the checker's own tests). Real enough to exercise loadSection/save
# round-trips; small enough to copy per test.
SERIES_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "PyReconstruct" / "assets" / "checker" / "files" / "class_series.jser"
)

# The data-list modules that import `notify` (and, bar `object`, `QuickDialog`)
# into their own namespace. `from ... import notify` binds the function in the
# importing module, so patching the helper at its source has no effect on code
# already holding a reference -- each module has to be patched by name.
_TABLE_MODULES = ("section", "trace", "ztrace", "flag", "object")


def pytest_configure(config):
    """Register the suite's custom markers."""
    for marker in (
        "needs_data: requires an external image/series corpus that is not in "
        "the repository. Not run in CI; gated on a corpus path supplied by the "
        "environment.",
        "needs_pr2: requires a separate reference interpreter with the "
        "pyrecon2 package installed. Cannot be an importorskip -- this project "
        "pins python <3.12 and pyrecon2 requires >=3.12, so the two never share "
        "a process and availability is an external-resource fact, not an "
        "import fact.",
        "slow: takes long enough that it should be skippable in the tight "
        "edit/test loop. Excluded by `make fast`, included by `make test`.",
        "gui: constructs real Qt widgets and drives them through their real "
        "slots, rather than stubbing the widget out. Needs a QApplication "
        "(supplied by pytest-qt's `qapp`) and the offscreen platform; runs in "
        "CI, but is the first thing to suspect if the suite ever hangs.",
    ):
        config.addinivalue_line("markers", marker)


# pytest-qt lives in the `test` extra, not in the runtime dependencies, and it is
# the only thing that supplies the session-scoped `qapp` fixture that
# `stub_mainwindow` and `section_table` below depend on. A .venv synced without
# `--extra test` therefore has pytest but no pytest-qt, which is a state that
# occurs in practice: a worktree synced with a bare `uv sync` reaches it.
#
# `find_spec` rather than an import: this runs at conftest import time, before
# any test module is imported, and importing pytest-qt here would register its
# plugin twice.
_HAS_PYTEST_QT = importlib.util.find_spec("pytestqt") is not None

_NO_PYTEST_QT = """\
pytest-qt is not installed, so the `qapp` fixture that gui-marked tests depend
on does not exist. {count} gui test(s) were collected and cannot run.

This aborts the run instead of skipping those tests. Skipping was the previous
behavior and it is what made the failure dangerous: the suite still reported
green, one line of "N passed" with the widget tests silently absent, and a
reviewer reads green as tested.

Install the test extra:
    uv sync --frozen --no-default-groups --extra test

Or run the suite the way `make test` and CI run it, which cannot reach this
state:
    uv run --frozen --no-default-groups --extra test python -m pytest

To exclude the widget tests deliberately, pass -m "not gui". That is a
supported invocation and it does not trip this guard.
"""


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Abort the run if gui tests were collected but pytest-qt is missing.

    Deliberately an error and not a skip. The gui-marked modules used to guard
    themselves with a module-scope ``pytest.importorskip("pytestqt")``, which
    meant a run in an environment without the `test` extra dropped every widget
    test and still exited 0. Measured on this tree: 4228 tests collected with
    pytest-qt present, 4157 without it, and the difference reported as "2
    skipped" because the skips are per-module, not per-test.

    ``trylast=True`` is load-bearing. Conftest hook implementations run *before*
    the builtin plugins' by default, and it is ``_pytest.mark``'s own
    ``pytest_collection_modifyitems`` that applies ``-m``. Running last means
    `items` has already had the mark expression applied, so a deliberate
    ``-m "not gui"`` has no gui items left and this guard stays quiet. Anything
    that would actually have tried to run a gui test raises.
    """
    if _HAS_PYTEST_QT:
        return
    gui_items = [item for item in items if item.get_closest_marker("gui")]
    if gui_items:
        raise pytest.UsageError(_NO_PYTEST_QT.format(count=len(gui_items)))


class DialogRecorder:
    """Stand-in for the blocking dialog helpers, for real-widget tests.

    Why this is not optional. The list widgets call ``notify()``,
    ``noUndoWarning()`` and ``QuickDialog.get()`` straight from their slots, and
    every one of those spins a *modal* event loop. Under
    ``QT_QPA_PLATFORM=offscreen`` there is no user and no window manager to
    dismiss it, so the loop never returns: an early version of these tests hung
    until it was killed at 300s rather than failing. Any test that drives a real
    slot has to replace them, and asserting on what *would* have been shown is
    strictly more informative than a screenshot nobody looks at anyway.

    Attributes:
        notices (list): every message passed to ``notify()``, in order.
        dialogs (list): the title of every ``QuickDialog.get()`` call.
        responses (list): queue of ``(response, confirmed)`` pairs handed to
            successive ``QuickDialog.get()`` callers. Empty means "the user
            cancelled", which is the safe default -- a test that forgets to
            script a dialog gets a no-op, not an exception and not a hang.
        undo_warning_accepted (bool): what ``noUndoWarning()`` returns.
    """

    def __init__(self):
        self.notices = []
        self.dialogs = []
        self.responses = []
        self.undo_warning_accepted = True
        # used only by the extra MainWindow surface further down
        self.confirm_accepted = True
        self.save_response = "no"
        self.save_prompts = 0
        self.unsaved_prompts = 0
        self.message_boxes = []
        self.message_box_response = None

    def notify(self, message, *args, **kwargs):
        self.notices.append(message)

    def noUndoWarning(self, *args, **kwargs):
        return self.undo_warning_accepted

    def quickDialogGet(self, *args, **kwargs):
        # QuickDialog.get(parent, structure, title, ...) -- title is positional
        # third in every caller, but read it defensively.
        title = args[2] if len(args) > 2 else kwargs.get("title", "")
        self.dialogs.append(title)
        if self.responses:
            return self.responses.pop(0)
        return None, False

    def progbar(self, *args, **kwargs):
        return _NullProgbar()

    # -- the extra surface MainWindow binds (see the main_window fixture) ------

    def notifyConfirm(self, message, *args, **kwargs):
        self.notices.append(message)
        return self.confirm_accepted

    def saveNotify(self, *args, **kwargs):
        self.save_prompts += 1
        return self.save_response

    def unsavedNotify(self, *args, **kwargs):
        self.unsaved_prompts += 1
        return False

    def messageBox(self, *args, **kwargs):
        """Stand-in for the QMessageBox statics. Records (title, text)."""
        self.message_boxes.append(tuple(args[1:3]))
        return self.message_box_response

    def inputText(self, *args, **kwargs):
        self.dialogs.append(args[1] if len(args) > 1 else "")
        return "", False

    def inputNumber(self, *args, **kwargs):
        self.dialogs.append(args[1] if len(args) > 1 else "")
        return 0, False

    def fileDialogGet(self, *args, **kwargs):
        self.dialogs.append(args[2] if len(args) > 2 else "")
        return ""


class _NullProgbar:
    """A progress bar that is not a window. getProgbar() returns a real
    QProgressDialog once a QApplication exists, and a QProgressDialog is modal.
    """

    def setValue(self, value):
        pass

    def wasCanceled(self):
        return False

    def close(self):
        pass


@pytest.fixture
def gui_dialogs(monkeypatch):
    """Neutralise the blocking dialogs in every data-list module.

    Returns the DialogRecorder, so a test can assert on `.notices` instead of
    on a modal that offscreen Qt will never dismiss.
    """
    import importlib

    recorder = DialogRecorder()
    for name in _TABLE_MODULES:
        module = importlib.import_module(
            f"PyReconstruct.modules.gui.table.{name}"
        )
        for attr, replacement in (
            ("notify", recorder.notify),
            ("noUndoWarning", recorder.noUndoWarning),
            ("getProgbar", recorder.progbar),
        ):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, replacement)
        if hasattr(module, "QuickDialog"):
            monkeypatch.setattr(
                module.QuickDialog, "get", recorder.quickDialogGet
            )
    return recorder


@pytest.fixture
def series_jser(tmp_path):
    """Path to a *writable copy* of the checked-in series fixture.

    The copy is the point. These tests call Section.save(), which rewrites the
    series' backing files in place; pointing them at the asset would leave a
    dirty tree (and a series whose brightness values drift with every run).
    """
    if not SERIES_FIXTURE.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"series fixture missing: {SERIES_FIXTURE}")
    destination = tmp_path / "series.jser"
    shutil.copy(SERIES_FIXTURE, destination)
    return destination


@pytest.fixture
def real_series(series_jser):
    """A real Series, opened from the copied fixture."""
    from PyReconstruct.modules.datatypes import Series

    series = Series.openJser(str(series_jser))
    yield series
    series.close()


class StubField:
    """The two attributes of MainWindow.field that the list slots touch."""

    def __init__(self, section):
        self.section = section
        self.reload_count = 0

    def reload(self):
        self.reload_count += 1

    def clearStates(self):
        pass

    def notifyLocked(self, *args, **kwargs):
        return False


class StubTableManager:
    """The manager surface DataTable and its slots actually use.

    Deliberately a stub and not the real TableManager: the real one owns every
    list in the app plus the undo stack, and building it would drag in the whole
    main window. What the widgets need from it is this small.
    """

    def __init__(self):
        self.series_states = {}
        self.tables = {
            "section": [], "trace": [], "ztrace": [], "flag": [], "object": [],
        }
        self.updated_sections = []

    def updateSections(self, section_numbers, *args, **kwargs):
        self.updated_sections.append(list(section_numbers))

    def updateObjects(self, *args, **kwargs):
        pass

    def refresh(self):
        pass

    def recreateTable(self, table=None):
        pass

    def recreateTables(self, refresh_data=False):
        pass


@pytest.fixture
def stub_mainwindow(qapp, real_series):
    """A QWidget standing in for MainWindow.

    It must be a real QWidget: DataTable is a QDockWidget and passes this in as
    its parent. Everything beyond that is the handful of methods the list slots
    call back into.
    """
    from PySide6.QtWidgets import QWidget

    class StubMainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.series = real_series
            first = sorted(real_series.sections)[0]
            self.field = StubField(real_series.loadSection(first))
            self.optimized = []
            self.modified = False

        def saveAllData(self):
            pass

        def seriesModified(self, modified=True):
            self.modified = modified

        def optimizeBC(self, section_numbers, *args, **kwargs):
            self.optimized.append(list(section_numbers))

        def changeSection(self, snum, save=False):
            self.changed_to = snum

        def checkActions(self, *args, **kwargs):
            pass

    window = StubMainWindow()
    yield window
    window.deleteLater()


@pytest.fixture
def section_table(qapp, real_series, stub_mainwindow, gui_dialogs):
    """A real, populated SectionTableWidget.

    Depends on `gui_dialogs` so that no test using this widget can accidentally
    trip a modal and hang the suite.
    """
    from PyReconstruct.modules.gui.table.section import SectionTableWidget

    widget = SectionTableWidget(
        real_series, stub_mainwindow, StubTableManager()
    )
    yield widget
    widget.deleteLater()


@pytest.fixture
def unlocked_section_table(section_table):
    """`section_table`, with every section unlocked.

    Sections in the fixture series ship locked, and the B/C slots refuse to
    touch a locked section ("Unlock section(s) before modifying."), which would
    mask what these tests are actually measuring. Note that clearing
    `series.data["sections"][n]["locked"]` directly does *not* work: the next
    Section.save() writes `align_locked` back over it. The attribute is the
    source of truth.
    """
    series = section_table.series
    for snum in list(series.sections):
        section = series.loadSection(snum)
        section.align_locked = False
        section.save()
    return section_table


# --- the top-level window ----------------------------------------------------
#
# Everything below builds a real MainWindow. Two things had to change in the app
# before that was possible offscreen; both are in the PR that added this
# fixture, and neither is a test-only hack:
#
#   1. `gui.utils.utils.user_is_present()` names the predicate `notify` and
#      `notifyConfirm` were already applying inline (a QApplication exists and
#      the platform is not `offscreen`).
#   2. `MainWindow.openSeries` consults it before raising the three prompts it
#      uses to finish opening an incomplete series: "Images Not Found"
#      (`changeSrcDir`), the non-cancelable "Series Code" dialog
#      (`setSeriesCode`), and the unscaled-zarr question. `notifyNewEditor`
#      does the same. Offscreen those are permanent stalls, not slow dialogs.
#
# What is left here is hygiene, not bypass: leave the developer's real QSettings
# as they were found, and stop the window's own teardown from asking to save.


# Every global QSettings key a MainWindow can write between construction and
# closeEvent. Enumerated rather than discovered because `allKeys()` on macOS also
# returns the whole global NSUserDefaults domain (`AppleLanguages`,
# `com/apple/trackpad/*`, ...), and restoring *that* by clear-and-rewrite would
# copy ~80 unrelated system defaults into the app's own plist. Verified by
# reading the call sites, not by grepping for the string: `main_window.py`
# (`window/geometry`, `username`, `last_folder`) and `mouse_palette.py`
# (`PALETTE_VIS_KEYS` and `palette/<group>_<axis>`).
_MAIN_WINDOW_SETTINGS_KEYS = (
    "window/geometry",
    "username",
    "last_folder",
    # `openSeries` pushes the opened path onto this list, so every test that uses
    # the `main_window` fixture adds one `tmp_path` entry to the developer's real
    # recent-series list. Harmless in the app (`getOpenRecentMenu` prunes paths
    # that no longer exist) but it is still a write, and the list grows by one per
    # test. Measured before adding it here: five runs of the menu-verification
    # module left ten dead pytest paths behind.
    "recently_opened_series",
    # `applyUpdateCheckDefaultStartup` runs the one-time correction that turns
    # the launch-time update check on for a machine that inherited it off. Both
    # keys are global, both are written during construction, and the marker in
    # particular has to go back: left set, it would tell every later launch in
    # the session that the correction had already run.
    "update_check_on_startup",
    "update_check_on_startup_default_applied",
    "palette/trace_hidden",
    "palette/inc_hidden",
    "palette/bc_hidden",
    "palette/sb_hidden",
) + tuple(
    f"palette/{group}_{axis}"
    for group in ("mode", "trace", "inc", "bc", "sb")
    for axis in ("x", "y")
)


@pytest.fixture
def qsettings_snapshot():
    """Leave `QSettings("KHLab", "PyReconstruct")` as the test found it.

    MainWindow reads and writes the developer's real user settings on the way up
    and down: `window/geometry` (`__init__` and `closeEvent`), `username`
    (`resolveUsernameStartup`), `last_folder` (`openSeries`), plus the mouse
    palette's positions and visibility. Left alone, a test run edits the
    developer's own preferences and its results depend on them.

    This restores rather than redirects, deliberately. Redirecting is the tidier
    idea and does not work: `QSettings.setDefaultFormat(IniFormat)` plus
    `setPath` leaves the two-argument organization/application constructor on
    macOS' NativeFormat plist (verified: `format()` still reports
    `NativeFormat` and `fileName()` still points into `~/Library/Preferences`).
    Patching the name in each module that builds one is the other option, but the
    constructor is inline in `main_window`, `mouse_palette` and `file_dialog`.

    Values go back as the exact QVariants they were read as, so this is lossless
    for the `QByteArray` geometry blob as well as the plain strings. A key that
    did not exist before is removed rather than written back as None.
    """
    from PySide6.QtCore import QSettings

    settings = QSettings("KHLab", "PyReconstruct")
    before = {
        key: settings.value(key)
        for key in _MAIN_WINDOW_SETTINGS_KEYS
        if settings.contains(key)
    }
    yield settings
    restore = QSettings("KHLab", "PyReconstruct")
    for key in _MAIN_WINDOW_SETTINGS_KEYS:
        if key in before:
            restore.setValue(key, before[key])
        else:
            restore.remove(key)
    restore.sync()


@pytest.fixture
def main_window_dialogs(monkeypatch):
    """Neutralize every blocking dialog `MainWindow` can reach from a slot.

    The construction path no longer needs this (see the note above), but a test
    that *drives* a menu action does: `main_window.py` binds `notify`,
    `notifyConfirm`, `saveNotify`, `unsavedNotify`, `noUndoWarning` and
    `getProgbar` into its own namespace, and calls `QMessageBox`, `QInputDialog`,
    `QuickDialog` and `FileDialog` directly.

    Offscreen, `notify` and `notifyConfirm` now fall through to their console
    branch, whose `input()` raises under pytest's capture and *hangs* under
    `-s`. The rest are raw modals with no offscreen branch at all
    (`saveNotify` and `unsavedNotify` included) and stall outright. Recording
    what would have been shown is also more useful to assert on.
    """
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from PyReconstruct.modules.gui.dialog import FileDialog, QuickDialog
    from PyReconstruct.modules.gui.main import main_window as mw

    recorder = DialogRecorder()

    for attr, replacement in (
        ("notify", recorder.notify),
        ("notifyConfirm", recorder.notifyConfirm),
        ("saveNotify", recorder.saveNotify),
        ("unsavedNotify", recorder.unsavedNotify),
        ("noUndoWarning", recorder.noUndoWarning),
        ("getProgbar", recorder.progbar),
    ):
        monkeypatch.setattr(mw, attr, replacement)

    for name in ("question", "information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox, name, staticmethod(recorder.messageBox)
        )
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(recorder.inputText)
    )
    for name in ("getDouble", "getInt"):
        monkeypatch.setattr(
            QInputDialog, name, staticmethod(recorder.inputNumber)
        )
    monkeypatch.setattr(
        QuickDialog, "get", staticmethod(recorder.quickDialogGet)
    )
    monkeypatch.setattr(
        FileDialog, "get", staticmethod(recorder.fileDialogGet)
    )
    return recorder


# --- walking a real menu tree -------------------------------------------------
#
# The reusable half of menu verification. `menu_leaf_paths` and `menu_action`
# take a *live* QMenuBar or QMenu and address it the way the user does, by the
# path they read off the screen ("Series > Options..."), so a test can say what
# a menu contains without knowing which dict in `menubar.py` produced it.
#
# Why this is not the same as the existing menu tests. `test_menubar_labels.py`,
# `test_menu_restructure.py` and `test_context_menu_frequency.py` read the
# *definition*: the nested lists and dicts `return_menubar` and
# `get_context_menu_list_*` return. That catches a wrong label or a row deleted
# from the source. It cannot catch anything `populateMenu` does with those
# dicts, because it never runs it: a menu silently dropped, a row wired to a
# different QAction than the attribute other code gates, a shortcut that the
# option lookup resolved to the empty string. Those need the widget, and the
# widget needs a MainWindow.
#
# ---------------------------------------------------------------------------
# READ THIS BEFORE WALKING A LIVE MENU. Two PySide6 6.5.2 behaviors make the
# obvious code wrong, both measured on this tree, both silent:
#
#   1. `QWidget.actions()` and `QAction.menu()` hand back wrappers whose
#      lifetime Python manages. Drop them and the *wrapper* is invalidated even
#      though the C++ object is still in the menu. A walk that keeps only the
#      leaves it was asked for therefore leaves invalid wrappers behind it, and
#      the next call through one raises
#      `RuntimeError: Internal C++ object ... already deleted`. Measured: walk
#      the menubar keeping only the leaf dict, and all 8 top-level `QMenu`
#      wrappers come back invalid while `menubar.actions()` still reports 8 live
#      menus. `menu_leaf_paths` therefore pins every wrapper it creates for as
#      long as the root widget lives (see `_KEEPALIVE_ATTR`).
#
#   2. The wrappers a walk creates are *not* the wrappers `MainWindow` holds in
#      its `<act_name>` attributes, and creating them can invalidate those. So
#      `menu_action(menubar, "Edit > Cut") is main_window.cut_act` is not a
#      reliable comparison: it can be False for the same C++ QAction, and
#      reading the attribute afterwards can raise. Compare with `same_action`,
#      which compares the C++ addresses, and read anything you need off a
#      `MainWindow` attribute *before* walking, not after.
#
# The consequence for tests: do not call `createMenuBar()` after walking the
# menubar in the same test. `newAction` reaches through the old attributes to
# remove the previous action, and that raises. Verified.
# ---------------------------------------------------------------------------

_KEEPALIVE_ATTR = "_menu_walk_keepalive"


def _cpp_address(obj) -> int:
    """The C++ address behind a PySide wrapper."""
    import shiboken6

    return shiboken6.Shiboken.getCppPointer(obj)[0]


def same_action(first, second) -> bool:
    """Whether two wrappers refer to the same C++ `QAction`.

    Use instead of `is`. Two live wrappers for one C++ object compare unequal
    under `is` in PySide6 6.5.2, so `is` gives false negatives on exactly the
    check a menu test most wants to make (this row is that named action).
    """
    if first is None or second is None:
        return False
    return _cpp_address(first) == _cpp_address(second)


def menu_leaf_paths(root) -> dict:
    """Map ``"A > B > C"`` to the `QAction` at that path, for every leaf.

    Args:
        root: a live `QMenuBar` or `QMenu`.

    Separators are skipped (they have no label, and two adjacent ones would
    collide). Submenus contribute their children rather than themselves, so
    every key names something clickable. A duplicated path raises rather than
    overwriting: two rows with the same label under one parent is itself a
    defect, and silently keeping the last one would hide it.

    Every intermediate wrapper is appended to a list stashed on ``root``, for
    the reason in the block comment above: without it the walk invalidates the
    submenu wrappers it passed through and leaves the tree unreadable.
    """
    from PySide6.QtWidgets import QMenuBar

    keepalive = getattr(root, _KEEPALIVE_ATTR, None)
    if keepalive is None:
        keepalive = []
        setattr(root, _KEEPALIVE_ATTR, keepalive)

    leaves = {}

    def walk(menu, prefix):
        actions = menu.actions()
        keepalive.append(actions)
        for action in actions:
            keepalive.append(action)
            if action.isSeparator():
                continue
            submenu = action.menu()
            if submenu is not None:
                keepalive.append(submenu)
                walk(submenu, prefix + [action.text()])
                continue
            path = " > ".join(prefix + [action.text()])
            if path in leaves:
                raise AssertionError(f"duplicate menu path: {path!r}")
            leaves[path] = action

    if isinstance(root, QMenuBar):
        top = root.actions()
        keepalive.append(top)
        for action in top:
            keepalive.append(action)
            submenu = action.menu()
            if submenu is not None:
                keepalive.append(submenu)
                walk(submenu, [action.text()])
    else:
        walk(root, [])
    return leaves


def menu_action(root, path: str):
    """The `QAction` at ``path`` under ``root``, or None if there is none.

    None rather than an exception, so a test can assert absence as easily as
    presence. A path naming a *submenu* returns None too: a submenu is not
    clickable, and conflating the two is how a test ends up passing against a
    menu whose only entry is another menu.
    """
    return menu_leaf_paths(root).get(path)


def menu_shortcut(root, path: str) -> str:
    """The shortcut string carried by the action at ``path``.

    Empty string for an action with no shortcut, which is what
    `QKeySequence.toString()` returns. Raises `KeyError` for a path that is not
    there, because "no such row" and "row with no shortcut" are different
    answers and a test asking for a shortcut has already assumed the row.
    """
    return menu_leaf_paths(root)[path].shortcut().toString()


def submenu_at(root, path: str):
    """The `QMenu` at ``path`` under ``root``, or None.

    The counterpart to `menu_action`: `menu_action` deliberately refuses to
    return a submenu, and a test that wants to walk one needs a way to name it.
    """
    parts = path.split(" > ")
    menu = root
    for part in parts:
        found = None
        actions = menu.actions()
        keepalive = getattr(root, _KEEPALIVE_ATTR, None)
        if keepalive is None:
            keepalive = []
            setattr(root, _KEEPALIVE_ATTR, keepalive)
        keepalive.append(actions)
        for action in actions:
            keepalive.append(action)
            if action.text() == part and action.menu() is not None:
                found = action.menu()
                keepalive.append(found)
                break
        if found is None:
            return None
        menu = found
    return menu


@pytest.fixture
def local_series_settings():
    """Redirect one series' option reads and writes into memory.

    Required by any test that writes a `Series` option. The global-scope options
    (every ``*_act`` keyboard shortcut among them) live in the developer's real
    `QSettings`, and `Series.getOption` writes the default back whenever a key is
    absent, so even *reading* an option can leave a key behind. `qsettings_snapshot`
    does not cover these: it restores the four keys `main_window.py` writes plus the
    mouse palette's, not the ~60 shortcut keys.

    `DictSettingsStore` is the seam the data model already exposes for this
    (`Series.setSettingsStore`), so this is injection rather than patching. Both
    scopes are covered by the one store, global and per-series-code.

    Yields a callable: pass it the window, and it swaps the store on that
    window's series and rebuilds the menus so the actions pick the new store's
    values up. The real store is restored on teardown.

    Both menus are rebuilt, in the order `MainWindow.__init__` uses them.
    `createMenuBar` alone is not enough: a dozen `<name>_act` attributes are
    owned by the *context* menus (`sethosts_act`, `edittrace_act`, ...), so
    rebuilding only the menubar leaves them carrying shortcuts from the previous
    store.
    """
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    swapped = []

    def redirect(window):
        window.series.setSettingsStore(DictSettingsStore())
        swapped.append(window.series)
        window.createMenuBar()
        window.createContextMenus()
        return window.series

    yield redirect

    for series in swapped:
        series.setSettingsStore(None)


@pytest.fixture
def main_window(qapp, series_jser, qsettings_snapshot, main_window_dialogs):
    """A live `MainWindow` opened on a writable copy of the fixture series.

    Real in every part that matters: a real `FieldWidget`, a real `MousePalette`,
    a real populated menubar, real context menus, real shortcuts. The fixture
    series ships no images, so `field.section_layer.image_found` is False and the
    image layer is blank. That is the one thing tests here cannot assert on.

    Costs roughly a second to build, so ask for it per test rather than
    per assertion.

    Teardown, in order and each for a reason:

      * restore `sys.excepthook`. `MainWindow.__init__` installs
        `customExcepthook` process-wide; left in place it would swallow
        tracebacks for every later test in the session.
      * clear `series.modified`. `closeEvent` calls
        `saveToJser(notify=True, close=True)`, which raises the "save before
        exiting?" prompt when the series is dirty. Discarding is correct here:
        the series is a per-test copy under `tmp_path`.
      * `close()` rather than only `deleteLater()`, so `closeEvent` runs and the
        series' hidden working directory is cleaned up the way it is in the app.

    The What's-new gate is closed before the window is built, and that is load
    bearing rather than tidy-minded. `MainWindow.__init__` ends with
    `QTimer.singleShot(750, self.showWhatsNewStartup)`, and the redirected
    settings store starts every session empty, so on the first window built in a
    session that handler is due. The timer belongs to the window, but teardown
    only calls `deleteLater()`, so whether the window is destroyed before 750 ms
    elapse depends on when a later test happens to run `processEvents`. Lose the
    race and a modeless `WhatsNewDialog` opens in the middle of an unrelated
    test, parented to a window that test never asked for.

    What that costs is not cosmetic. The dialog becomes
    `QApplication.activeWindow()` and never closes, and Qt resolves a
    `Qt::WindowShortcut` against the active window, so every later `QTest`
    keystroke aimed at the `MainWindow` is silently dropped; a popup showing at
    that moment is dismissed by the activation change as well. Measured on
    `tests/test_menu_stays_open_on_toggle.py`, which failed 15 of 30 full-file
    runs on this alone, in three different tests, and passed every time in
    isolation.

    Recording the running version as already seen makes the handler a no-op for
    every test that does not want it, and the tests that do
    (`test_whats_new_once_per_version.py`, `test_welcome_update_note.py`) set the
    key themselves and call the handler directly, so they are unaffected. The
    write lands in the session's throwaway store, never the real one.
    """
    import sys as _sys

    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP,
        ORG,
        current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())

    previous_excepthook = _sys.excepthook
    window = MainWindow(str(series_jser))
    try:
        yield window
    finally:
        _sys.excepthook = previous_excepthook
        window.series.modified = False
        window.close()
        window.deleteLater()


# ---------------------------------------------------------------------------
# Latched keyboard modifiers, and why every test gets cleaned up whether or not
# it presses a key.
#
# `QApplication.keyboardModifiers()` is process-wide state, and under PySide6
# 6.5.2 a synthetic modified key press leaves it set after the press is over.
# Both spellings do it, measured on this platform:
#
#     QTest.keyClick(w, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
#         -> keyboardModifiers() == Qt.ShiftModifier, and stays there
#     QTest.keySequence(w, QKeySequence("Ctrl+Shift+O"))
#         -> Qt.ShiftModifier
#     QTest.keySequence(w, QKeySequence("Ctrl+G"))
#         -> Qt.ControlModifier
#
# Nothing resets it at the end of the test, the end of the module, or the end of
# the fixture that owned the widget: `qapp` is session-scoped, so the residue
# outlives every widget and reaches every later test in the run.
#
# The damage is done to tests that press no keys at all, and it does not need a
# mouse event to reach them. `QAbstractItemViewPrivate::extendedSelectionCommand`
# is passed the originating event when there is one and falls back to
# `QGuiApplication::keyboardModifiers()` when there is not, so the *programmatic*
# selection calls inherit the latch:
#
#     table.clearSelection(); table.selectRow(0)
#         no latch          -> row 0 selected, 3 indexes
#         ShiftModifier     -> NOTHING selected, 0 indexes
#         ControlModifier   -> row 0 selected, 3 indexes
#
# Shift means "extend from the current index", and after `clearSelection()` there
# is no current index to extend from, so the selection call silently does
# nothing. `tests/test_section_list_real_widget.py` uses `selectRow` and presses
# no keys, and it fails 7 of 46 with a `ShiftModifier` latch standing. Control is
# "toggle", which from an empty selection lands on the same answer, which is why
# a run can be green purely because its last key press was `Ctrl+G` rather than
# `Ctrl+Shift+O`. `setCurrentCell` is unaffected by either.
#
# So this is cleared centrally rather than at the call sites. Per-press cleanup
# is exactly the kind of thing a new test forgets, and the failure it causes
# lands in a different file.
#
# On the mechanism:
#
#   * It takes a key *press* to reset the mask. `QApplication::notify` records
#     the modifiers of a `KeyPress` it delivers, so a `KeyRelease` on its own
#     leaves the latch standing, whether it comes from `QTest` or from
#     `QApplication.sendEvent`. `QTest.keyClick` sends both, in that order.
#   * The target widget need not be shown, focused, or parented. A bare
#     throwaway `QWidget` works, which is what makes this safe to run from a
#     teardown after the test's own window has already been closed.
#
# A fresh widget per call, deliberately: caching one would leave a PySide
# wrapper alive across the session, and stale-wrapper ownership is the other
# 6.5.2 trap this suite already works around (see the note above
# `menu_leaf_paths`).
# ---------------------------------------------------------------------------


def clear_latched_modifiers() -> None:
    """Reset `QApplication.keyboardModifiers()` to `Qt.NoModifier`.

    Safe and cheap to call unconditionally: a no-op when PySide6 has not been
    imported, when no `QApplication` exists, and when no modifier is latched. It
    does not create a `QApplication` and does not import PySide6, so a Qt-free
    test run stays Qt-free.

    Called automatically for every test by `_no_latched_modifiers` below. Call
    it directly only from *within* a test that presses a modified sequence and
    then clicks something in the same test, where the automatic cleanup has not
    run yet.
    """
    widgets = sys.modules.get("PySide6.QtWidgets")
    if widgets is None or widgets.QApplication.instance() is None:
        return

    from PySide6.QtCore import Qt

    if widgets.QApplication.keyboardModifiers() == Qt.NoModifier:
        return

    from PySide6.QtTest import QTest

    # An unmodified press through QTest clears the whole mask, whichever
    # modifiers are standing. Key_Shift produces no text, so a focused editor
    # elsewhere in the session cannot be corrupted by it, and the event is
    # addressed to the throwaway widget rather than to whatever has focus.
    QTest.keyClick(widgets.QWidget(), Qt.Key_Shift, Qt.NoModifier)


@pytest.fixture(autouse=True)
def _no_latched_modifiers():
    """Guarantee every test starts and ends with no keyboard modifier latched.

    Autouse and suite-wide on purpose. The tests that suffer are not the tests
    that press keys, so scoping this to the GUI files would leave the hazard in
    place for the next real-widget file somebody adds.

    Cleared on setup as well as teardown so that residue from anything outside a
    test's own teardown (a session-scoped finalizer, an aborted run resumed with
    `--lf`) cannot reach the next test either.
    """
    clear_latched_modifiers()
    yield
    clear_latched_modifiers()
