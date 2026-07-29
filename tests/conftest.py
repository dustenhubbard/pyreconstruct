"""Suite-wide pytest configuration.

Three jobs, all deliberately small:

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

3. Provide the shared fixtures for *real-widget* GUI tests: a Series opened
   from a copy of a checked-in .jser, a live data-list dock widget, and a
   recorder that stands in for the modal dialogs. See the fixture docstrings.

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

import os
import shutil
from pathlib import Path

import pytest

# Must run before any test module imports PySide6, which conftest collection
# guarantees: pytest imports this file before it imports any test module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
