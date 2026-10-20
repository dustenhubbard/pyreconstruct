"""A section save leaves the file alone when it would write the same bytes.

Every section change saves the section being left and the B section, and
once anything in the series is edited that save runs on every step. It used
to rewrite both files and rebuild both stores each time, which on a large
series was most of a section change. Now `Section.save` still builds the
bytes, and writes them (and rebuilds the store) only when they differ from
what the file holds: what this section last read from it or wrote to it, in
a file nothing has replaced since.

The fixture series is in an older file format, so the first save of each of
its sections writes new bytes, as it always has. The tests save a section
once and read it back before they start.
"""
import os

import pytest

from PyReconstruct.modules.datatypes.trace import Trace


def _state(path):
    st = os.stat(path)
    return st.st_ino, st.st_size, st.st_mtime_ns


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _normalize(series, n):
    """Save section n once, so its file holds the bytes a save writes."""
    series.loadSection(n).save(update_series_data=False)


@pytest.fixture
def section(real_series):
    n = next(
        n for n in sorted(real_series.sections)
        if real_series.loadSection(n).tracesAsList()
    )
    _normalize(real_series, n)
    return real_series.loadSection(n)


@pytest.fixture
def rebuilds(monkeypatch):
    from PyReconstruct.modules.datatypes.section import Section

    calls = []
    real = Section._rebuildColumnarStoreForSave

    def counted(self):
        calls.append(self.n)
        return real(self)
    monkeypatch.setattr(Section, "_rebuildColumnarStoreForSave", counted)
    return calls


def test_an_unchanged_section_is_not_rewritten(section, rebuilds):
    before = _state(section.filepath)
    section.save(update_series_data=False)
    section.save(update_series_data=False)
    assert _state(section.filepath) == before
    assert rebuilds == []


def test_a_repeat_save_after_an_edit_writes_once(section, rebuilds):
    section.brightness = (section.brightness + 7) % 100
    section.save(update_series_data=False)
    written = _state(section.filepath)
    assert rebuilds == [section.n]
    section.save(update_series_data=False)
    assert _state(section.filepath) == written
    assert rebuilds == [section.n]


def test_an_edit_is_written(real_series, section, rebuilds):
    trace = Trace("save_unchanged_probe", (255, 0, 0))
    trace.points = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]
    section.addTrace(trace)
    before = _state(section.filepath)
    section.save(update_series_data=False)
    assert _state(section.filepath) != before
    assert rebuilds == [section.n]
    again = real_series.loadSection(section.n)
    assert "save_unchanged_probe" in again.contours


def test_an_edit_made_outside_the_section_methods_is_written(real_series, section):
    # a trace hidden in place: the section's change tracking never hears of
    # it, and the bytes still differ
    trace = section.tracesAsList()[0]
    hidden = sum(t.hidden for t in section.contours[trace.name])
    trace.hidden = not trace.hidden
    section.save(update_series_data=False)
    again = real_series.loadSection(section.n)
    assert sum(t.hidden for t in again.contours[trace.name]) == hidden + (
        1 if trace.hidden else -1)


def test_a_file_replaced_by_another_writer_is_written_again(real_series, section):
    mine = _bytes(section.filepath)
    other = real_series.loadSection(section.n)
    other.brightness = (other.brightness + 13) % 100
    other.save(update_series_data=False)
    assert _bytes(section.filepath) != mine
    section.save(update_series_data=False)
    assert _bytes(section.filepath) == mine


def test_a_file_changed_in_place_is_written_again(section):
    mine = _bytes(section.filepath)
    with open(section.filepath, "ab") as f:
        f.write(b" ")
    section.save(update_series_data=False)
    assert _bytes(section.filepath) == mine


def test_a_missing_file_is_written_again(section):
    mine = _bytes(section.filepath)
    os.remove(section.filepath)
    section.save(update_series_data=False)
    assert _bytes(section.filepath) == mine


@pytest.mark.gui
def test_paging_after_an_edit_rewrites_no_unchanged_section(main_window):
    series = main_window.series
    nums = sorted(series.sections)
    paths = {n: os.path.join(series.getwdir(), series.sections[n]) for n in nums}
    # an edit anywhere marks the series modified, and from then on every
    # section change saves the section left and the B section
    for n in nums:
        _normalize(series, n)
    main_window.field.reload()
    series.modified = True
    before = {n: _state(p) for n, p in paths.items()}
    for n in nums[1:] + nums[:1]:
        main_window.changeSection(n)
    assert {n: _state(p) for n, p in paths.items()} == before
