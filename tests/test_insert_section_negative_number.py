"""Inserting a section refuses a negative section number.

Insert section > Above or Below took any integer. On a five-section series, -1
made ``s.-1`` in the hidden dir and the list showed sections -1 to 4, but the
save kept only the original five: ``saveJser`` uses the section number as a list
index, so -1 wrote into the last slot and the highest section overwrote it. The
log line for the insert carried -1 as well, and the working folder could not be
read back.

The fix refuses the number in two places: the section list dialog says so and
stops, and ``Series.insertSection`` raises before it writes any file.

No ``gui`` marker: the datatype tests build no widgets, and the dialog test
drives the slot on a stub with the dialog patched out. The dialog test also
replaces ``Series.insertSection``, so each guard is tested on its own.
"""

import os
import shutil
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.gui.table.section import SectionTableWidget

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)


def reopen_at(fp):
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


@pytest.fixture
def series(tmp_path):
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    s = reopen_at(fp)
    yield s
    if os.path.isdir(s.hidden_dir):
        s.close()


def hidden_files(series):
    return sorted(os.listdir(series.hidden_dir))


def round_trip(series):
    """Save, close (which removes the hidden dir), and reopen from the .jser."""
    fp = series.jser_fp
    series.saveJser()
    series.close()
    return reopen_at(fp)


def test_the_fixture_has_five_sections(series):
    assert sorted(series.sections) == [0, 1, 2, 3, 4]


def test_negative_section_number_is_refused_before_any_file_is_written(series):
    before_files = hidden_files(series)
    before_sections = dict(series.sections)

    with pytest.raises(ValueError):
        series.insertSection(-1, "no-image", 0.00254, 0.05)

    assert hidden_files(series) == before_files
    assert series.sections == before_sections


def test_refused_insert_round_trips_with_every_section(series):
    with pytest.raises(ValueError):
        series.insertSection(-1, "no-image", 0.00254, 0.05)

    reopened = round_trip(series)
    try:
        assert sorted(reopened.sections) == [0, 1, 2, 3, 4]
    finally:
        reopened.close()


def test_insert_at_zero_round_trips(series):
    """Zero is still allowed, and the new section survives save and reopen."""
    series.insertSection(0, "new-image", 0.00254, 0.05)
    assert sorted(series.sections) == [0, 1, 2, 3, 4, 5]

    reopened = round_trip(series)
    try:
        assert sorted(reopened.sections) == [0, 1, 2, 3, 4, 5]
        assert reopened.loadSection(0).src == "new-image"
    finally:
        reopened.close()


def test_dialog_refuses_a_negative_number_and_changes_nothing(series, monkeypatch):
    messages = []
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.notify",
        lambda message, *a, **k: messages.append(message),
    )
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.QuickDialog.get",
        staticmethod(lambda *a, **k: (("", -1, 0.00254, 0.05), True)),
    )
    # Stand in for Series.insertSection so this test checks the dialog's own
    # guard and does not pass on the one in Series.
    inserted = []
    monkeypatch.setattr(
        series, "insertSection", lambda *a, **k: inserted.append(a)
    )
    saved = []
    stub = SimpleNamespace(
        series=series,
        getSelected=lambda: [0],
        mainwindow=SimpleNamespace(
            field=SimpleNamespace(
                section=SimpleNamespace(mag=0.00254, thickness=0.05),
                clearStates=lambda: None,
                reload=lambda: None,
            ),
            saveAllData=lambda: saved.append(True),
        ),
        manager=SimpleNamespace(
            recreateTables=lambda **k: None,
            refresh=lambda: None,
        ),
    )
    before_files = hidden_files(series)

    SectionTableWidget.insertSection(stub, before=True)

    assert messages, "the user was not told why nothing happened"
    assert not inserted
    assert not saved
    assert hidden_files(series) == before_files
    assert sorted(series.sections) == [0, 1, 2, 3, 4]
