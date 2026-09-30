"""Reorder sections after a crash-recovery reopen keeps every section's content.

Reopening a series whose working folder was left behind takes the fast path in
``Series.openJser``, which fills ``series.sections`` in ``os.listdir`` order.
Both reorder maps (``SectionTableWidget.reorderSections`` and the default in
``Series.reorderSections``) numbered sections by that dict order, so on a
recovered series they handed each section another one's number. The reopen
here is the real one, with ``os.listdir`` returning the files in reverse so the
order is not left to the file system.
"""

import os

import pytest

from conftest import StubTableManager

pytestmark = pytest.mark.gui


def reopen_from_working_folder(series_jser, monkeypatch):
    """Open the series again while its working folder is still there."""
    from PyReconstruct.modules.datatypes import Series

    real_listdir = os.listdir
    with monkeypatch.context() as m:
        m.setattr(os, "listdir", lambda p: sorted(real_listdir(p), reverse=True))
        series = Series.openJser(str(series_jser))
    assert series.leave_open  # the working-folder path, not a .jser read
    return series


@pytest.fixture
def recovered_series(real_series, series_jser, monkeypatch):
    """A series with a gap in its numbers, reopened from its working folder.

    Returns the reopened series and the section numbers it had, in order.
    Every section carries its own number in its image source.
    """
    keys = sorted(real_series.sections)
    assert len(keys) >= 5
    real_series.deleteSections([keys[2]])
    keys = sorted(real_series.sections)
    for n in keys:
        s = real_series.loadSection(n)
        s.src = f"ORIG_{n}.png"
        s.align_locked = False
        s.save()

    series = reopen_from_working_folder(series_jser, monkeypatch)
    assert list(series.sections) != keys  # the dict really is out of order
    return series, keys


def assert_renumbered_in_order(series, keys):
    assert sorted(series.sections) == list(range(len(keys)))
    for i, old in enumerate(keys):
        assert series.loadSection(i).src == f"ORIG_{old}.png"


def test_series_default_reorder_after_recovery(recovered_series):
    series, keys = recovered_series
    series.reorderSections()
    assert_renumbered_in_order(series, keys)


def test_section_list_reorder_after_recovery(
    recovered_series, stub_mainwindow, gui_dialogs
):
    from PyReconstruct.modules.gui.table.section import SectionTableWidget

    series, keys = recovered_series
    stub_mainwindow.series = series
    stub_mainwindow.field.section = series.loadSection(keys[0])
    widget = SectionTableWidget(series, stub_mainwindow, StubTableManager())
    try:
        widget.reorderSections()
    finally:
        widget.deleteLater()

    assert gui_dialogs.notices == []
    assert_renumbered_in_order(series, keys)
