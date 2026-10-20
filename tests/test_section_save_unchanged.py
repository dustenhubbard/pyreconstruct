"""A section save leaves the file alone when it would write the same bytes.

Every section change saves the section being left and the B section, and
once anything in the series is edited that save runs on every step. It used
to rewrite both files and rebuild both stores each time, which on a large
series was most of a section change. Now `Section.save` still builds the
bytes, and writes them only when they differ from the bytes in the file,
read back to compare. It still rebuilds the store on every save: equal bytes
do not mean the store matches the traces.

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
    assert rebuilds == [section.n, section.n]


def test_a_repeat_save_after_an_edit_writes_once(section, rebuilds):
    section.brightness = (section.brightness + 7) % 100
    section.save(update_series_data=False)
    written = _state(section.filepath)
    assert rebuilds == [section.n]
    section.save(update_series_data=False)
    assert _state(section.filepath) == written
    assert rebuilds == [section.n, section.n]


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


def test_a_file_rewritten_in_place_with_its_stamp_kept_is_written_again(section):
    # another program writes other bytes of the same length and puts the
    # times back: size, mtime and inode all match what this section saw
    mine = _bytes(section.filepath)
    st = os.stat(section.filepath)
    other = mine.replace(b"{", b"[", 1)
    assert other != mine and len(other) == len(mine)
    with open(section.filepath, "r+b") as f:
        f.write(other)
    os.utime(section.filepath, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert _state(section.filepath) == (st.st_ino, st.st_size, st.st_mtime_ns)
    section.save(update_series_data=False)
    assert _bytes(section.filepath) == mine


def test_a_file_replaced_while_the_store_rebuilds_is_written_again(
        section, monkeypatch):
    # another program replaces the file just after this section wrote it,
    # while the save is still rebuilding the store
    from PyReconstruct.modules.datatypes.section import Section

    real = Section._rebuildColumnarStoreForSave
    written = []

    def replaced(self):
        written.append(_bytes(self.filepath))
        other = self.filepath + ".other"
        with open(other, "wb") as f:
            f.write(written[0].replace(b"{", b"[", 1))
        os.replace(other, self.filepath)
        return real(self)

    section.brightness = (section.brightness + 9) % 100
    monkeypatch.setattr(Section, "_rebuildColumnarStoreForSave", replaced)
    section.save(update_series_data=False)
    monkeypatch.setattr(Section, "_rebuildColumnarStoreForSave", real)
    assert _bytes(section.filepath) != written[0]
    section.save(update_series_data=False)
    assert _bytes(section.filepath) == written[0]


def test_a_store_edited_then_put_back_outside_the_section_is_rebuilt(section):
    # hidden through Section (the store hears of it), shown again outside it
    # (the store does not): the bytes match the file, the store does not
    trace = section.tracesAsList()[0]
    was = trace.hidden
    section.hideTraces([trace], hide=not was, log_event=False)
    trace.setHidden(was)
    before = _bytes(section.filepath)
    section.save(update_series_data=False)
    assert _bytes(section.filepath) == before
    section._assertColumnsMatchObjectModel("test")


def _saveSameBytes(section):
    """Save, and check that the file kept its bytes and was not written."""
    before = _state(section.filepath)
    section.save(update_series_data=False)
    assert _state(section.filepath) == before


def test_a_contour_swapped_for_a_copy_of_itself_is_rebuilt(section):
    # new trace objects with the same values: the bytes match the file, and
    # the store's rows still point at the old traces
    name = section.tracesAsList()[0].name
    section.contours[name] = section.contours[name].copy()
    _saveSameBytes(section)
    section._assertColumnsMatchObjectModel("test")
    trace = section.contours[name][0]
    section.hideTraces([trace], hide=not trace.hidden, log_event=False)
    section._assertColumnsMatchObjectModel("test")


def test_a_point_moved_below_the_rounding_is_rebuilt(section):
    # a new points list, moved by less than the 7 places the file keeps
    trace = section.tracesAsList()[0]
    x, y = trace.points[0]
    trace.points = [(x + 1e-10, y)] + list(trace.points[1:])
    _saveSameBytes(section)
    section._assertColumnsMatchObjectModel("test")


def test_a_point_moved_in_place_below_the_rounding_is_rebuilt(section):
    # the same points list, one item replaced: no list or trace changes identity
    trace = section.tracesAsList()[0]
    points = trace.points
    x, y = points[0]
    points[0] = (x + 1e-10, y)
    assert trace.points is points
    _saveSameBytes(section)
    section._assertColumnsMatchObjectModel("test")


def test_a_store_column_written_directly_is_rebuilt(section):
    # a write through the store's column view moves no generation
    trace = section.tracesAsList()[0]
    row = section._column_rows[trace]
    hidden = section._columns.flagColumn("hidden")
    generation = section._columns.generation
    hidden[row] = not hidden[row]
    assert section._columns.generation == generation
    _saveSameBytes(section)
    section._assertColumnsMatchObjectModel("test")


def test_every_save_rebuilds_the_store(section, rebuilds):
    section.save(update_series_data=False)
    trace = section.tracesAsList()[0]
    section.hideTraces([trace], hide=not trace.hidden, log_event=False)
    section.hideTraces([trace], hide=not trace.hidden, log_event=False)
    section.save(update_series_data=False)
    section.save(update_series_data=False)
    assert rebuilds == [section.n] * 3


def test_a_failed_write_raises_and_keeps_the_file(section, monkeypatch):
    # out of disk space at the replace: the save raises, the file keeps its
    # bytes, and no temp file is left beside it
    from PyReconstruct.modules.backend.func import atomic_io

    mine = _bytes(section.filepath)

    def full(src, dst, *args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(atomic_io, "replace_with_retry", full)
    section.brightness = (section.brightness + 11) % 100
    with pytest.raises(OSError):
        section.save(update_series_data=False)
    assert _bytes(section.filepath) == mine
    assert not os.path.exists(section.filepath + ".tmp")
