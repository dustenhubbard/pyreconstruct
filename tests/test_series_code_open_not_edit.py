"""Setting the series code at open is not an edit.

A series with no code gets one at open: ``MainWindow._ensureSeriesCode``
reads it from the series name and, with a user present, shows it in the
Series Code dialog. The open used to mark the whole series modified at that
point, and ``saveAllData`` saves every section it holds whenever the series
is modified, so on a large series every later section change serialized
both sections before the user had edited anything. It also marked the
series modified when no code was found and nobody was asked.

Now a code the name supplies is written to the series file and nothing is
marked modified. A code the user types over it is an edit, as before, so the
series is saved with it. The fixture series ships with no code, so the
``main_window`` fixture runs this path on every build.
"""
import json

import pytest

from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.gui.main import main_window as mw

pytestmark = pytest.mark.gui

# series_code_pattern [0-9A-Za-z]+ on the fixture copy's name, "series"
DERIVED = "series"


@pytest.fixture
def launch(qapp, series_jser, qsettings_snapshot, main_window_dialogs):
    """Build a MainWindow the way the main_window fixture does, on a .jser
    the test names, after the test has patched what the open consults."""
    import sys as _sys

    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import (
        APP, ORG, current_version_str,
    )
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    windows = []
    previous_excepthook = _sys.excepthook

    def start(jser=series_jser):
        QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
        window = MainWindow(str(jser))
        window._captureListLayout = lambda: None
        windows.append(window)
        return window

    yield start

    _sys.excepthook = previous_excepthook
    for window in windows:
        window.series.modified = False
        window.close()
        window.deleteLater()


def _series_file(series):
    with open(series.filepath, "rb") as f:
        return json.loads(f.read())


def test_a_code_from_the_name_is_not_an_edit(main_window):
    series = main_window.series
    assert series.code == DERIVED
    assert series.modified is False
    assert not main_window.windowTitle().endswith("*")
    assert _series_file(series)["code"] == DERIVED


def test_a_section_change_with_no_edits_saves_no_section(main_window, monkeypatch):
    saved = []
    monkeypatch.setattr(Section, "save", lambda self, *a, **k: saved.append(self.n))
    current = main_window.series.current_section
    other = next(n for n in sorted(main_window.series.sections) if n != current)
    main_window.changeSection(other)
    assert main_window.series.current_section == other
    assert saved == []
    assert main_window.series.modified is False


def test_no_code_and_nobody_asked_changes_nothing(launch, series_jser, main_window_dialogs):
    """Offscreen, user_is_present() is False and the dialog is not raised."""
    nameless = series_jser.with_name("___.jser")
    series_jser.rename(nameless)
    window = launch(nameless)
    assert window.series.code in ("", None)
    assert window.series.modified is False
    assert "Series Code" not in main_window_dialogs.dialogs


def test_confirming_the_code_from_the_name_is_not_an_edit(launch, monkeypatch):
    offered = []

    def confirm(parent, structure, title, *args, **kwargs):
        offered.append(structure[2][1][2])
        return [structure[2][1][2]], True

    monkeypatch.setattr(mw, "user_is_present", lambda: True)
    monkeypatch.setattr(mw.QuickDialog, "get", staticmethod(confirm))
    window = launch()
    assert offered == [DERIVED]
    assert window.series.code == DERIVED
    assert window.series.modified is False
    assert _series_file(window.series)["code"] == DERIVED


def test_a_typed_code_is_an_edit(launch, monkeypatch, main_window_dialogs):
    monkeypatch.setattr(mw, "user_is_present", lambda: True)
    main_window_dialogs.responses = [(["XY7"], True)]
    window = launch()
    assert window.series.code == "XY7"
    assert window.series.modified is True
    assert window.windowTitle().endswith("*")
