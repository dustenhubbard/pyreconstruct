"""Bulk section-list operations report progress instead of freezing silently.

Reported by a user after a long session: setting the thickness of 277 sections
took "almost a minute" with nothing on screen to say the app was working. There
is no cheaper way to do that edit -- every section has to be loaded, have all of
its contours flagged, and be written back -- so the fix is to say so while it
happens.

Three handlers in the section list load and save one section at a time.
`lockSections` already had a hand-rolled QProgressDialog; `setBC` and
`editThickness` had nothing. All three now go through
`Series.enumerateSections`, which loads each section, drives the bar, and routes
through the series' progress-reporter seam -- so a headless caller gets the null
reporter rather than a Qt dialog. That seam is what lets these tests watch the
progress without a Qt event loop.

The tests assert the OUTCOME (was progress reported, over which sections, under
what label) rather than which helper produced it, so replacing the iterator
again does not require rewriting them.
"""
import shutil
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import ProgressReporter
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.table.section import SectionTableWidget


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "parity_series.jser"


class _RecordingReporter(ProgressReporter):
    """Captures what a real progress dialog would have shown.

    One instance per operation, exactly as the Qt reporter is constructed per
    operation, so `created` below is a record of how many bars the user saw.
    """

    created = []

    def __init__(self, text="", cancel=True):
        super().__init__(text, cancel)
        self.values = []
        _RecordingReporter.created.append(self)

    def set_progress(self, percent):
        self.values.append(percent)

    def was_canceled(self):
        return False


class _Stub:
    """Stands in for whatever the handler reaches through, recording the calls.

    The handlers are called as unbound methods with this as `self` -- the idiom
    the other menu and table tests use -- so no Qt widget is constructed.
    """

    def __init__(self, series, selected):
        self.series = series
        self._selected = selected
        self.updated_sections = []
        self.updated_objects = []
        self.reloaded = 0

        table_self = self

        class _Manager:
            def updateSections(self, snums, **kw):
                table_self.updated_sections.append(list(snums))

            def updateObjects(self, names, **kw):
                table_self.updated_objects.append(set(names))

            def updateZtraces(self, *a, **kw):
                pass

        class _Field:
            def reload(self):
                table_self.reloaded += 1

        class _MainWindow:
            field = _Field()

            def saveAllData(self):
                pass

            def seriesModified(self, *a):
                pass

        self.manager = _Manager()
        self.mainwindow = _MainWindow()

    def getSelected(self, single=False):
        return list(self._selected)


@pytest.fixture
def series(tmp_path):
    """The real 3-section fixture, with progress routed to the recorder."""
    destination = tmp_path / "progress.jser"
    shutil.copyfile(FIXTURE, destination)
    s = Series.openJser(str(destination))
    s.setProgressReporter(_RecordingReporter)
    # The fixture ships every section locked, and all three handlers refuse to
    # modify a locked section (correctly). Unlock before exercising them, so a
    # failure here means the progress change broke something rather than that
    # the fixture stopped us at the door.
    for snum in s.sections:
        s.data["sections"][snum]["locked"] = False
    _RecordingReporter.created = []
    yield s
    s.close()


def _section_numbers(series):
    return sorted(series.sections.keys())


# --------------------------------------------------------------------------- #
# the reported case
# --------------------------------------------------------------------------- #
def test_editing_thickness_across_sections_reports_progress(series, monkeypatch):
    """The user's report: a long silent wait becomes a labeled progress bar."""
    snums = _section_numbers(series)
    assert len(snums) > 1, "fixture must hold enough sections to show a bar"
    stub = _Stub(series, snums)

    # the handler asks for the new thickness through QInputDialog
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("0.075", True)),
    )

    SectionTableWidget.editThickness(stub, log_event=False)

    assert len(_RecordingReporter.created) == 1, "expected exactly one progress bar"
    bar = _RecordingReporter.created[0]
    assert "thickness" in bar.text.lower(), bar.text
    assert bar.values, "the bar was created but never advanced"
    assert bar.values[-1] == 100, "the bar never reached 100"
    assert bar.values == sorted(bar.values), "progress went backwards"


def test_editing_thickness_actually_sets_every_selected_section(series, monkeypatch):
    """Progress reporting must not have changed what the edit does."""
    snums = _section_numbers(series)
    stub = _Stub(series, snums)
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("0.075", True)),
    )

    SectionTableWidget.editThickness(stub, log_event=False)

    for snum in snums:
        assert series.data["sections"][snum]["thickness"] == pytest.approx(0.075)


def test_editing_thickness_collects_the_modified_contours(series, monkeypatch):
    """The accumulator used to stay empty, so the post-loop refresh was a no-op.

    `modified_contours.union(...)` returns a new set and discards it; the fix is
    `|=`. The symptom was invisible because the loop also refreshes per section,
    which is why this needs its own test rather than trusting the read.
    """
    snums = _section_numbers(series)
    stub = _Stub(series, snums)
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("0.075", True)),
    )

    SectionTableWidget.editThickness(stub, log_event=False)

    # the last updateObjects call is the post-loop one, over the accumulator
    assert stub.updated_objects, "nothing was ever refreshed"
    assert stub.updated_objects[-1], (
        "the post-loop refresh ran over an empty set -- the accumulator is "
        "still being discarded"
    )


# --------------------------------------------------------------------------- #
# the two siblings with the same shape
# --------------------------------------------------------------------------- #
def test_setting_brightness_contrast_reports_progress(series):
    snums = _section_numbers(series)
    stub = _Stub(series, snums)

    SectionTableWidget.setBC(stub, section_numbers=snums, b=10, c=5, log_event=False)

    assert len(_RecordingReporter.created) == 1
    bar = _RecordingReporter.created[0]
    assert "brightness" in bar.text.lower(), bar.text
    assert bar.values[-1] == 100
    # brightness is a Section attribute (data["sections"] carries thickness,
    # locked, src, tforms and the bc PROFILES, not the live b/c values)
    for snum in snums:
        assert series.loadSection(snum).brightness == 10


def test_locking_sections_reports_progress(series):
    snums = _section_numbers(series)
    stub = _Stub(series, snums)

    SectionTableWidget.lockSections(stub, section_numbers=snums, log_event=False)

    assert len(_RecordingReporter.created) == 1
    bar = _RecordingReporter.created[0]
    assert "lock" in bar.text.lower(), bar.text
    assert bar.values[-1] == 100


# --------------------------------------------------------------------------- #
# the guard that keeps a one-section edit from flashing a dialog
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("handler,kwargs", [
    ("lockSections", {"log_event": False}),
    ("setBC", {"b": 10, "c": 5, "log_event": False}),
])
def test_a_single_section_shows_no_progress_bar(series, handler, kwargs):
    """A lock checkbox toggle is one section and is instant.

    Flashing a progress dialog for it is worse than showing nothing, which is
    why lockSections guarded this before the change; the guard has to survive
    the move to the shared iterator, and now covers its siblings too.
    """
    one = _section_numbers(series)[:1]
    stub = _Stub(series, one)

    getattr(SectionTableWidget, handler)(stub, section_numbers=one, **kwargs)

    assert _RecordingReporter.created == [], (
        f"{handler} showed a progress bar for a single section"
    )


def test_the_single_section_edit_still_happens(series):
    """The no-bar path must not be a no-op path."""
    one = _section_numbers(series)[:1]
    stub = _Stub(series, one)

    SectionTableWidget.lockSections(stub, section_numbers=one, log_event=False)

    # Section.align_locked is persisted as the "locked" key
    assert series.data["sections"][one[0]]["locked"] is True
