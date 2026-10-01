"""Insert section and Reorder sections keep every section on an unsaved series.

Both actions rename the section files in the hidden dir and then call
``recreateTables``, which calls ``saveAllData``. When the series had unsaved
changes, that save wrote the field's section (and the flickered B section) back
to its old file name, which by then belonged to another section. Insert section
> Above on section 5 left the old section 5 at both 5 and 6 and lost the new
one; Reorder sections with a gap wrote an old section over its neighbor. A
saved series was not affected, because ``saveAllData`` returns early on one.

These drive a real ``MainWindow`` and a real section list. Only the modal
dialogs are scripted.
"""

import json
import os

import pytest

pytestmark = pytest.mark.gui


def disk_src(series, snum):
    """The image source stored in a section's hidden file, read straight from disk."""
    fp = os.path.join(series.hidden_dir, f"{series.name}.{snum}")
    with open(fp, "rb") as f:
        return json.loads(f.read())["src"]


def tag_sections(mw):
    """Give every section a unique source on disk and in the field copies."""
    series = mw.series
    for n in sorted(series.sections):
        s = series.loadSection(n)
        s.src = f"ORIG_{n}.png"
        s.align_locked = False
        s.save()
    for s in (mw.field.section, mw.field.b_section):
        if s is not None:
            s.src = f"ORIG_{s.n}.png"
            s.align_locked = False


def open_section_table(mw):
    mw.field.table_manager.newTable("section")
    return mw.field.table_manager.tables["section"][-1]


def select_section(widget, snum):
    table = widget.table
    table.clearSelection()
    for r in range(table.rowCount()):
        if int(table.item(r, 0).text().split()[0]) == snum:
            table.selectRow(r)
            return
    raise AssertionError(f"row for section {snum} not found")


def test_insert_above_current_section_on_unsaved_series(main_window, gui_dialogs):
    mw = main_window
    series = mw.series
    keys = sorted(series.sections)
    assert keys == list(range(len(keys))) and len(keys) >= 8

    n = keys[5]
    mw.changeSection(n + 1)
    mw.changeSection(n)  # section n + 1 is now the flickered B section
    tag_sections(mw)
    assert mw.field.section.n == n and mw.field.b_section.n == n + 1

    mw.seriesModified(True)

    widget = open_section_table(mw)
    select_section(widget, n)
    gui_dialogs.responses.append((["", n, 0.00254, 0.05], True))
    widget.insertSection(before=True)

    assert sorted(series.sections) == list(range(len(keys) + 1))
    expected = {k: f"ORIG_{k}.png" for k in keys if k < n}
    expected[n] = "no-image"
    expected.update({k + 1: f"ORIG_{k}.png" for k in keys if k >= n})
    assert {k: disk_src(series, k) for k in series.sections} == expected

    # the field follows its sections to their new numbers
    assert series.current_section == n + 1
    assert (mw.field.section.n, mw.field.section.src) == (n + 1, f"ORIG_{n}.png")
    assert (mw.field.b_section.n, mw.field.b_section.src) == (n + 2, f"ORIG_{n + 1}.png")


def test_reorder_with_gap_on_unsaved_series(main_window, gui_dialogs):
    mw = main_window
    series = mw.series
    keys = sorted(series.sections)
    assert len(keys) >= 6

    # make a gap at the start, then stand on the second remaining section with
    # the last one flickered away; every section shifts down by one, and the
    # last section number stops existing
    mw.changeSection(keys[3])
    series.deleteSections([keys[0]])
    mw.field.clearStates()
    keys = sorted(series.sections)
    last, cur = keys[-1], keys[1]
    mw.changeSection(last)
    mw.changeSection(cur)
    tag_sections(mw)
    assert mw.field.section.n == cur and mw.field.b_section.n == last

    mw.seriesModified(True)

    widget = open_section_table(mw)
    widget.manager.recreateTables(refresh_data=True)
    widget = mw.field.table_manager.tables["section"][-1]
    widget.reorderSections()

    assert gui_dialogs.notices == []
    assert sorted(series.sections) == list(range(len(keys)))
    expected = {i: f"ORIG_{old}.png" for i, old in enumerate(keys)}
    assert {k: disk_src(series, k) for k in series.sections} == expected

    assert series.current_section == 1
    assert (mw.field.section.n, mw.field.section.src) == (1, f"ORIG_{cur}.png")
    assert (mw.field.b_section.n, mw.field.b_section.src) == (
        len(keys) - 1, f"ORIG_{last}.png"
    )


def section_files(series):
    """The section numbers that have a file in the hidden dir."""
    prefix = f"{series.name}."
    return sorted(
        int(f[len(prefix):]) for f in os.listdir(series.hidden_dir)
        if f.startswith(prefix) and f[len(prefix):].isdigit()
    )


def flicker_then_drop_b(mw, cur, b):
    """Stand on cur with b flickered away, then remove b from the series only.

    ``Series.deleteSections`` leaves the field alone, so the field still holds
    a flickered section whose number is gone.
    """
    mw.changeSection(b)
    mw.changeSection(cur)
    tag_sections(mw)
    assert mw.field.section.n == cur and mw.field.b_section.n == b
    mw.series.deleteSections([b])
    mw.field.clearStates()
    mw.seriesModified(True)


def test_reorder_after_flickered_section_was_deleted(main_window, gui_dialogs):
    mw = main_window
    series = mw.series
    keys = sorted(series.sections)
    cur, b = keys[2], keys[3]
    flicker_then_drop_b(mw, cur, b)
    keys = sorted(series.sections)

    widget = open_section_table(mw)
    widget.reorderSections()

    assert gui_dialogs.notices == []
    assert sorted(series.sections) == list(range(len(keys)))
    assert section_files(series) == sorted(series.sections)
    expected = {i: f"ORIG_{old}.png" for i, old in enumerate(keys)}
    assert {k: disk_src(series, k) for k in series.sections} == expected

    new_cur = keys.index(cur)
    assert series.current_section == new_cur
    assert (mw.field.section.n, mw.field.section.src) == (new_cur, f"ORIG_{cur}.png")
    assert mw.field.b_section is None


def test_insert_after_flickered_section_was_deleted(main_window, gui_dialogs):
    mw = main_window
    series = mw.series
    keys = sorted(series.sections)
    n = keys[5]
    flicker_then_drop_b(mw, n, n + 1)
    keys = sorted(series.sections)

    widget = open_section_table(mw)
    select_section(widget, n)
    gui_dialogs.responses.append((["", n, 0.00254, 0.05], True))
    widget.insertSection(before=True)

    expected = {k: f"ORIG_{k}.png" for k in keys if k < n}
    expected[n] = "no-image"
    expected.update({k + 1: f"ORIG_{k}.png" for k in keys if k >= n})
    assert sorted(series.sections) == sorted(expected)
    assert section_files(series) == sorted(expected)
    assert {k: disk_src(series, k) for k in series.sections} == expected

    assert series.current_section == n + 1
    assert (mw.field.section.n, mw.field.section.src) == (n + 1, f"ORIG_{n}.png")
    assert mw.field.b_section is None


def test_delete_flickered_section_drops_it_from_the_field(main_window, gui_dialogs):
    mw = main_window
    series = mw.series
    keys = sorted(series.sections)
    cur, b = keys[2], keys[3]
    mw.changeSection(b)
    mw.changeSection(cur)
    tag_sections(mw)
    mw.seriesModified(True)

    widget = open_section_table(mw)
    select_section(widget, b)
    widget.deleteSections()

    assert b not in series.sections
    assert mw.field.b_section is None
    # the save after the delete does not write the deleted section back
    assert section_files(series) == sorted(series.sections)
    assert (mw.field.section.n, mw.field.section.src) == (cur, f"ORIG_{cur}.png")


@pytest.mark.parametrize("op", ["insert", "reorder"])
def test_renumber_with_ztraces_shown(main_window, gui_dialogs, op):
    """The field redraws z-traces from series.data, which has to follow the
    renumbering before the field loads again."""
    from PyReconstruct.modules.datatypes import Ztrace

    mw = main_window
    series = mw.series
    if op == "reorder":
        series.deleteSections([sorted(series.sections)[0]])
        mw.field.clearStates()
        series.data.refresh()
    keys = sorted(series.sections)
    cur = keys[2]
    mw.changeSection(cur)
    tag_sections(mw)
    series.ztraces["zprobe"] = Ztrace(
        "zprobe", (255, 0, 0), [(1.0, 1.0, k) for k in keys]
    )
    series.setOption("show_ztraces", True)
    series.data.refresh()
    mw.field.generateView()
    mw.seriesModified(True)

    widget = open_section_table(mw)
    if op == "insert":
        n = keys[1]
        select_section(widget, n)
        gui_dialogs.responses.append((["", n, 0.00254, 0.05], True))
        widget.insertSection(before=True)
        expected = {k: f"ORIG_{k}.png" for k in keys if k < n}
        expected[n] = "no-image"
        expected.update({k + 1: f"ORIG_{k}.png" for k in keys if k >= n})
    else:
        widget.reorderSections()
        expected = {i: f"ORIG_{old}.png" for i, old in enumerate(keys)}

    assert gui_dialogs.notices == []
    assert section_files(series) == sorted(expected)
    assert {k: disk_src(series, k) for k in series.sections} == expected
    assert sorted(series.data["sections"]) == sorted(expected)
    mw.field.generateView()

    # the section list was rebuilt with the new numbers
    widget = mw.field.table_manager.tables["section"][-1]
    rows = sorted(
        int(widget.table.item(r, 0).text().split()[0])
        for r in range(widget.table.rowCount())
    )
    assert rows == sorted(expected)
