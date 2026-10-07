"""The progress bar while a series opens names that series, and a launch shows none.

PyReconstruct opens its bundled welcome series at launch, and the series-data
pass in `Series.__init__` put up a bar reading "Loading series data..." before
the user had chosen any series. A real open said "Opening series..." or
"Loading series data...", depending on the path, without saying which series.

Now the welcome series shows no bar: it is one section with no traces, and its
pass takes well under a millisecond, far less than the bar itself costs. Every
real open says "Opening <name>...", with the name the window title shows, on
each of its three paths: the .jser unpack, an already unpacked working folder,
and unsaved work recovered after a crash. An opening series still shows no time
estimate.

The fixture is copied to a name of its own: it is called `series.jser`, so
"Opening series..." would read as named and prove nothing.
"""
import shutil
import sys

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel, QProgressDialog

from PyReconstruct.modules.backend.progress import NullProgressReporter

NAME = "cortex_block_3"


class Capturing(NullProgressReporter):
    made = []

    def __init__(self, text="", cancel=True, eta=False):
        super().__init__(text, cancel, eta)
        Capturing.made.append((text, eta))


@pytest.fixture(autouse=True)
def clear_capture():
    Capturing.made = []
    yield


@pytest.fixture
def named_jser(series_jser):
    destination = series_jser.parent / f"{NAME}.jser"
    shutil.copy(series_jser, destination)
    return destination


@pytest.fixture
def default_reporter_is_capturing(monkeypatch):
    """The reporter a Series makes for itself, which `Series.__init__` uses."""
    from PyReconstruct.modules.datatypes import series as series_module
    monkeypatch.setattr(
        series_module, "_default_progress_reporter_factory", lambda: Capturing
    )


# ---------------------------------------------------------------------------
# the data model, one path at a time
# ---------------------------------------------------------------------------

def test_the_welcome_series_shows_no_bar_and_still_loads(default_reporter_is_capturing):
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.gui.utils import get_welcome_setup

    w_ser, w_secs, _ = get_welcome_setup()
    series = Series(w_ser, w_secs)
    assert series.isWelcomeSeries()
    assert Capturing.made == []
    # no bar, but the pass behind it still ran
    assert set(series.data["sections"]) == set(w_secs)


def test_unpacking_a_jser_names_the_series(named_jser):
    from PyReconstruct.modules.datatypes import Series

    series = Series.openJser(str(named_jser), progress=Capturing)
    try:
        assert Capturing.made == [(f"Opening {NAME}...", False)]
    finally:
        series.close()


def test_an_unpacked_working_folder_names_the_series(named_jser, default_reporter_is_capturing):
    from PyReconstruct.modules.datatypes import Series

    first = Series.openJser(str(named_jser), progress=NullProgressReporter)
    try:
        # the working folder is still there, so this open reads it instead
        second = Series.openJser(str(named_jser))
        second.leave_open = True
        assert Capturing.made == [(f"Opening {NAME}...", False)]
    finally:
        first.close()


def test_recovered_unsaved_work_names_the_series(named_jser, default_reporter_is_capturing):
    """The constructor `MainWindow._recoverUnsavedSeries` calls."""
    from PyReconstruct.modules.datatypes import Series

    first = Series.openJser(str(named_jser), progress=NullProgressReporter)
    try:
        recovered = Series(first.filepath, dict(first.sections))
        recovered.leave_open = True
        assert Capturing.made == [(f"Opening {NAME}...", False)]
    finally:
        first.close()


# ---------------------------------------------------------------------------
# the real window, from a cold launch to an open series
# ---------------------------------------------------------------------------

class ShownDialogs(QObject):
    """The label of every progress dialog that appears, in order."""

    def __init__(self):
        super().__init__()
        self.labels = []

    def eventFilter(self, obj, event):
        if isinstance(obj, QProgressDialog) and event.type() == QEvent.Show:
            self.labels.append(obj.labelText())
        return False


@pytest.mark.gui
def test_a_launch_shows_no_bar_and_opening_a_series_names_it(
    qapp, named_jser, qsettings_snapshot, main_window_dialogs, monkeypatch
):
    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP,
        ORG,
        current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main import main_window as mw
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY
    from PyReconstruct.modules.gui.utils import utils

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    # Real dialogs, from the state a fresh process starts in: no window has
    # registered itself as their parent yet. A window left registered by an
    # earlier test is dead, and getProgbar falls back to the text-mode bar,
    # which would make "no dialog" pass for the wrong reason.
    monkeypatch.setattr(mw, "getProgbar", utils.getProgbar)
    monkeypatch.setattr(utils, "mainwindow", None)

    shown = ShownDialogs()
    qapp.installEventFilter(shown)
    previous_excepthook = sys.excepthook
    window = None
    try:
        window = MainWindow(None)
        assert window.series.isWelcomeSeries()
        assert shown.labels == []

        window.openSeries(jser_fp=str(named_jser))
        assert window.series.name == NAME
        assert shown.labels == [f"Opening {NAME}..."]
    finally:
        qapp.removeEventFilter(shown)
        sys.excepthook = previous_excepthook
        if window is not None:
            window.series.modified = False
            window.close()
            window.deleteLater()
            QApplication.processEvents()


# ---------------------------------------------------------------------------
# the name as the dialog draws it
# ---------------------------------------------------------------------------

def _drawsLiterally(label, text):
    """True if the label lays text out as typed: one line per line of text,
    each as wide as its characters. Read as markup, "<br>" breaks the line
    and "<b>x</b>" draws a bold x with no tags, so both tests fail."""
    metrics = label.fontMetrics()
    lines = text.split("\n")
    size = label.sizeHint()
    widest = max(metrics.horizontalAdvance(line) for line in lines)
    return (
        size.height() < (len(lines) + 1) * metrics.lineSpacing()
        and size.width() >= widest
    )


class ShownLabels(QObject):
    """Whether each progress dialog that appears draws its label as typed."""

    def __init__(self):
        super().__init__()
        self.shown = []

    def eventFilter(self, obj, event):
        if isinstance(obj, QProgressDialog) and event.type() == QEvent.Show:
            label = obj.findChild(QLabel)
            self.shown.append(
                (obj.labelText(), _drawsLiterally(label, obj.labelText()))
            )
        return False


@pytest.mark.gui
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows file names cannot hold < or >"
)
def test_a_file_name_that_looks_like_markup_is_drawn_as_typed(
    qtbot, series_jser, monkeypatch
):
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.backend.progress import QtProgressReporter
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.gui.utils import utils

    name = "cortex<br>3"
    destination = series_jser.parent / f"{name}.jser"
    shutil.copy(series_jser, destination)

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    monkeypatch.setattr(utils, "mainwindow", parent)

    shown = ShownLabels()
    QApplication.instance().installEventFilter(shown)
    try:
        series = Series.openJser(str(destination), progress=QtProgressReporter)
        series.close()
    finally:
        QApplication.instance().removeEventFilter(shown)
    assert shown.shown == [(f"Opening {name}...", True)]


@pytest.mark.gui
def test_a_progress_label_set_later_is_drawn_as_typed(qtbot, monkeypatch):
    """A running bar rewrites its label, with a time estimate or a percent,
    and other bars name a group or a branch the user typed."""
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.gui.utils import utils

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    monkeypatch.setattr(utils, "mainwindow", parent)

    bar = utils.getProgbar("Converting <b>dendrites</b> to contours...")
    try:
        label = bar.findChild(QLabel)
        assert _drawsLiterally(label, bar.labelText())
        bar.setLabelText("Converting <b>dendrites</b> to contours...\nabout 1 min left")
        assert _drawsLiterally(label, bar.labelText())
    finally:
        bar.close()
