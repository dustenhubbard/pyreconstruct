"""The clean-up review lists, driven as real widgets.

``MalformedContoursDialog`` grew a column spec, a default sort column, a subclass
button hook and a sortable flag so the clean-up lists could reuse its selection,
navigation, deletion and export behavior instead of restating it.

Two properties are pinned here beyond the obvious ones.

``DuplicateTracesDialog`` puts a combo box in every row's Keep cell, and
``setCellWidget`` binds a widget to a row NUMBER: sorting moves the items between
rows and leaves the widgets where they were, so the choice would end up attached
to the wrong record. The dialog therefore turns sorting off, and
``test_the_duplicates_table_is_not_sortable`` is what stops that being quietly
undone.

The heading is one or two sentences, with the long explanation on a hover "?"
beside it. A wall of text above a table is skipped rather than read, and it
pushes the table off the top of a small window.
"""

import pytest

from PyReconstruct.modules.gui.dialog import (
    MalformedContoursDialog,
    PixelDustDialog,
    DuplicateTracesDialog,
)


@pytest.fixture
def parent(qapp):
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    yield widget
    widget.deleteLater()


def _dust_record(name="dust", snum=3, area=0.004):
    return {
        "name": name,
        "section": snum,
        "index": 0,
        "points": 4,
        "location": (20.0, 20.0),
        "reason": f"Area {area} um^2",
        "area": area,
        "match": {"color": (255, 0, 0), "points": [(20.0, 20.0)]},
    }


def _member(name, index, points=4, area=1.5):
    return {
        "name": name,
        "section": 3,
        "index": index,
        "points": points,
        "location": (20.0 + index / 10, 20.0),
        "reason": "",
        "area": area,
        "match": {"color": (255, 0, 0), "points": [(20.0 + index / 10, 20.0)]},
    }


def _group_record(names=("d01", "dendrite"), snum=3, ratio=0.98, keep=None):
    members = [_member(n, i) for i, n in enumerate(names)]
    keep = keep or members[0]["name"]
    kept = next(m for m in members if m["name"] == keep)
    record = dict(kept)
    record["section"] = snum
    record["reason"] = "Traced under " + ", ".join(f"'{n}'" for n in names)
    record["members"] = members
    record["names"] = sorted(set(names))
    record["names_text"] = ", ".join(sorted(set(names)))
    record["keep"] = keep
    record["ratio"] = ratio
    record["count"] = len(members)
    record["total_area"] = sum(m["area"] for m in members)
    for m in members:
        m["section"] = snum
    return record


# --------------------------------------------------------------------------
# the duplicates list: the Keep drop-down
# --------------------------------------------------------------------------

def test_every_row_offers_the_groups_own_names_to_keep(parent):
    dialog = DuplicateTracesDialog(parent, [_group_record(("dendrite", "d01"))])

    box = dialog.keep_boxes[0]
    assert [box.itemText(i) for i in range(box.count())] == ["d01", "dendrite"]


def test_the_drop_down_opens_on_the_records_default(parent):
    dialog = DuplicateTracesDialog(
        parent, [_group_record(("dendrite", "d01"), keep="dendrite")]
    )

    assert dialog.keep_boxes[0].currentText() == "dendrite"


def test_choosing_a_name_is_written_back_onto_the_record(parent):
    """Combining reads the record, so the widget cannot be the only place it lives."""
    record = _group_record(("dendrite", "d01"), keep="dendrite")
    dialog = DuplicateTracesDialog(parent, [record])

    dialog.keep_boxes[0].setCurrentText("d01")

    assert record["keep"] == "d01"


def test_the_drop_down_sits_in_the_keep_column(parent):
    dialog = DuplicateTracesDialog(parent, [_group_record()])

    assert dialog.COLUMNS[dialog.KEEP_COLUMN] == "Keep"
    assert dialog.table.cellWidget(0, dialog.KEEP_COLUMN) is dialog.keep_boxes[0]


def test_the_duplicates_table_is_not_sortable(parent):
    """setCellWidget binds to a row number; sorting would strand the drop-downs."""
    dialog = DuplicateTracesDialog(parent, [_group_record(), _group_record()])

    assert dialog.SORTABLE is False
    assert dialog.table.isSortingEnabled() is False


# --------------------------------------------------------------------------
# the duplicates list: combining
# --------------------------------------------------------------------------

def test_combining_hands_over_the_selected_groups(parent, monkeypatch):
    # the confirmation prompt falls back to reading stdin without a GUI
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: True,
    )
    handed = []
    records = [
        _group_record(("a", "a2")),
        _group_record(("b", "b2")),
    ]
    dialog = DuplicateTracesDialog(
        parent, records,
        combine=lambda groups: (handed.extend(groups), groups)[1],
    )
    dialog.table.selectRow(0)

    dialog.combineSelectedGroups()

    assert [g["names_text"] for g in handed] == ["a, a2"]


def test_combining_all_hands_over_every_group(parent, monkeypatch):
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: True,
    )
    handed = []
    records = [_group_record(("a", "a2")), _group_record(("b", "b2"))]
    dialog = DuplicateTracesDialog(
        parent, records,
        combine=lambda groups: (handed.extend(groups), groups)[1],
    )

    dialog.combineAllGroups()

    assert len(handed) == 2


def test_a_declined_confirmation_combines_nothing(parent, monkeypatch):
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: False,
    )
    handed = []
    dialog = DuplicateTracesDialog(
        parent, [_group_record()],
        combine=lambda groups: (handed.extend(groups), groups)[1],
    )

    dialog.combineAllGroups()

    assert handed == []


def test_combined_rows_leave_the_table(parent, monkeypatch):
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: True,
    )
    records = [_group_record(("a", "a2")), _group_record(("b", "b2"))]
    dialog = DuplicateTracesDialog(
        parent, records, combine=lambda groups: groups
    )
    dialog.table.selectRow(0)

    dialog.combineSelectedGroups()

    assert dialog.table.rowCount() == 1
    assert len(dialog.records) == 1


def test_the_combine_buttons_are_absent_without_a_callback(parent):
    """Report-only stays possible: no callback, no way to change the series."""
    dialog = DuplicateTracesDialog(parent, [_group_record()])

    assert dialog.combine is None
    assert dialog.combine_selected_button is None
    assert dialog.combine_all_button is None


def test_combine_selected_is_off_until_a_row_is_selected(parent):
    dialog = DuplicateTracesDialog(
        parent, [_group_record()], combine=lambda groups: groups
    )

    assert dialog.combine_selected_button.isEnabled() is False
    assert dialog.combine_all_button.isEnabled() is True

    dialog.table.selectRow(0)

    assert dialog.combine_selected_button.isEnabled() is True


def test_the_duplicates_list_never_shows_delete_buttons(parent):
    """Combining is not deletion, so the Delete buttons would describe it wrongly."""
    dialog = DuplicateTracesDialog(
        parent, [_group_record()], combine=lambda groups: groups
    )

    assert dialog.delete is None
    assert dialog.delete_selected_button is None
    assert dialog.delete_all_button is None


# --------------------------------------------------------------------------
# the duplicates list: the row, and navigation
# --------------------------------------------------------------------------

def test_the_row_names_every_object_and_shows_the_overlap(parent):
    dialog = DuplicateTracesDialog(
        parent, [_group_record(("dendrite", "d01"), ratio=0.98)]
    )

    assert dialog.COLUMNS[:5] == [
        "Objects", "Keep", "Section", "Traces", "Overlap"
    ]
    texts = [
        dialog.table.item(0, col).text()
        for col in range(dialog.table.columnCount())
        if dialog.table.item(0, col) is not None
    ]
    assert "d01, dendrite" in texts
    assert any("0.98" in t for t in texts)


def test_every_trace_of_a_group_is_reachable(parent):
    """One button per press, cycling the group, so all of them can be compared."""
    visited = []
    dialog = DuplicateTracesDialog(
        parent,
        [_group_record(("aaa", "bbb", "ccc"), keep="aaa")],
        navigate=lambda snum, name, index: visited.append((snum, name, index)),
    )
    dialog.table.selectRow(0)

    dialog.goToSelectedContour()
    dialog.goToNextMemberContour()
    dialog.goToNextMemberContour()
    dialog.goToNextMemberContour()

    assert visited[0] == (3, "aaa", 0)
    assert {v[1] for v in visited} == {"aaa", "bbb", "ccc"}
    # wraps back round rather than running out
    assert visited[-1] == (3, "aaa", 0)


def test_the_go_to_buttons_are_off_until_a_row_is_selected(parent):
    dialog = DuplicateTracesDialog(
        parent, [_group_record()], navigate=lambda *a: None
    )

    assert dialog.goto_button.isEnabled() is False
    assert dialog.goto_next_button.isEnabled() is False

    dialog.table.selectRow(0)

    assert dialog.goto_button.isEnabled() is True
    assert dialog.goto_next_button.isEnabled() is True


def test_the_duplicates_list_titles_itself_for_both_cases(parent):
    """Not "named differently" any more: one entry covers both."""
    dialog = DuplicateTracesDialog(parent, [_group_record()])

    assert dialog.windowTitle() == "Duplicate traces"


# --------------------------------------------------------------------------
# the heading is short, and the "?" carries the rest
# --------------------------------------------------------------------------

@pytest.mark.parametrize("build", [
    lambda parent: MalformedContoursDialog(parent, [_dust_record()]),
    lambda parent: PixelDustDialog(parent, [_dust_record()], delete=lambda r: r),
    lambda parent: DuplicateTracesDialog(
        parent, [_group_record()], combine=lambda g: g
    ),
])
def test_the_heading_is_short_enough_to_read(parent, build):
    dialog = build(parent)

    assert len(dialog.heading.text()) < 200, dialog.heading.text()
    assert "\n\n" not in dialog.heading.text()


@pytest.mark.parametrize("build", [
    lambda parent: MalformedContoursDialog(parent, [_dust_record()]),
    lambda parent: PixelDustDialog(parent, [_dust_record()], delete=lambda r: r),
    lambda parent: DuplicateTracesDialog(
        parent, [_group_record()], combine=lambda g: g
    ),
])
def test_the_full_explainer_is_on_the_question_mark(parent, build):
    dialog = build(parent)

    assert dialog.heading_help is not None
    assert dialog.heading_help.text() == "?"
    assert len(dialog.heading_help.toolTip()) > len(dialog.heading.text())


@pytest.mark.parametrize("build", [
    lambda parent: MalformedContoursDialog(parent, [_dust_record()]),
    lambda parent: PixelDustDialog(parent, [_dust_record()], delete=lambda r: r),
    lambda parent: DuplicateTracesDialog(
        parent, [_group_record()], combine=lambda g: g
    ),
])
def test_the_explainer_is_rich_text_so_the_tooltip_wraps(parent, build):
    """QToolTip wraps rich text only.

    A plain-text tooltip is laid out as given, so each paragraph rendered as one
    line running off the side of the screen. setWordWrap on the label does not
    help: it wraps the label's own text, which is a single "?".
    """
    dialog = build(parent)
    tip = dialog.heading_help.toolTip()

    assert tip.startswith("<qt>") and tip.endswith("</qt>")
    assert "<br>" in tip
    assert "\n" not in tip


def test_the_explainer_escapes_rather_than_interprets_its_text(parent):
    """Rich text means markup, so the detail must not be able to inject any."""
    class Sneaky(DuplicateTracesDialog):
        def _headingDetail(self):
            return "a < b & c > d"

    dialog = Sneaky(parent, [_group_record()])

    assert "a &lt; b &amp; c &gt; d" in dialog.heading_help.toolTip()


def test_the_question_mark_says_combining_can_be_undone(parent):
    dialog = DuplicateTracesDialog(
        parent, [_group_record()], combine=lambda g: g
    )

    assert "undoable" in dialog.heading_help.toolTip()


def test_a_report_only_duplicates_list_says_nothing_was_changed(parent):
    dialog = DuplicateTracesDialog(parent, [_group_record()])

    assert "Nothing in the series has been changed" in (
        dialog.heading_help.toolTip()
    )


def test_the_question_mark_goes_away_with_the_rows_it_described(parent, monkeypatch):
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: True,
    )
    records = [_group_record()]
    dialog = DuplicateTracesDialog(
        parent, records, combine=lambda groups: groups
    )

    dialog.combineAllGroups()

    assert dialog.records == []
    assert dialog.heading_help.toolTip() == ""
    assert dialog.heading_help.isVisibleTo(dialog) is False


# --------------------------------------------------------------------------
# the pixel-dust list still deletes, and the base class is unchanged
# --------------------------------------------------------------------------

def test_the_pixel_dust_list_deletes_what_was_reviewed(parent, monkeypatch):
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: True,
    )
    handed = []
    records = [_dust_record("dust"), _dust_record("other")]
    dialog = PixelDustDialog(
        parent, records, delete=lambda recs: (handed.extend(recs), recs)[1]
    )

    assert dialog.delete_all_button is not None
    dialog._deleteRecords([records[0]])

    assert [r["name"] for r in handed] == ["dust"]


def test_a_declined_confirmation_deletes_nothing(parent, monkeypatch):
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: False,
    )
    handed = []
    records = [_dust_record("dust")]
    dialog = PixelDustDialog(
        parent, records, delete=lambda recs: (handed.extend(recs), recs)[1]
    )

    dialog._deleteRecords(records)

    assert handed == []


def test_the_pixel_dust_list_shows_an_area_column(parent):
    dialog = PixelDustDialog(parent, [_dust_record(area=0.004)])

    assert "Area (um^2)" in dialog.COLUMNS
    col = dialog.COLUMNS.index("Area (um^2)")
    assert "0.004" in dialog.table.item(0, col).text()


def test_neither_list_grows_a_button_the_base_class_did_not_ask_for(parent):
    """The hook is opt-in, so the smoothing report is unaffected by it."""
    base = MalformedContoursDialog(parent, [_dust_record()])
    dust = PixelDustDialog(parent, [_dust_record()])

    assert base.extra_buttons == []
    assert dust.extra_buttons == []


def test_the_base_class_defines_its_explainer_exactly_once(parent):
    """A second definition would silently shadow the first."""
    import inspect

    from PyReconstruct.modules.gui.dialog import malformed_contours as mc

    src = inspect.getsource(mc.MalformedContoursDialog)

    assert src.count("def _headingDetail(self)") == 1


def test_the_base_class_explainer_describes_smoothing(parent):
    base = MalformedContoursDialog(parent, [_dust_record()])

    assert "smoothed" in base.heading_help.toolTip()


def test_the_next_trace_cursor_survives_a_removed_row(parent, monkeypatch):
    """The cursor is keyed by the record, not by a row number that shifts.

    Three members, so continuing and restarting give different answers: keyed by
    row, the surviving group would inherit the deleted row's cursor and start
    over instead of carrying on.
    """
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.malformed_contours.notifyConfirm",
        lambda *args, **kwargs: True,
    )
    visited = []
    first = _group_record(("a", "a2"))
    second = _group_record(("aaa", "bbb", "ccc"), keep="aaa")
    dialog = DuplicateTracesDialog(
        parent, [first, second],
        navigate=lambda snum, name, index: visited.append(name),
        combine=lambda groups: groups,
    )

    # advance the second group once: aaa (kept) -> bbb
    dialog.table.selectRow(1)
    dialog.goToNextMemberContour()
    assert visited[-1] == "bbb"

    # remove the first group's row; the second group moves to row 0
    dialog.table.selectRow(0)
    dialog.combineSelectedGroups()
    assert dialog.table.rowCount() == 1

    dialog.table.selectRow(0)
    dialog.goToNextMemberContour()

    assert visited[-1] == "ccc", "the cursor restarted instead of carrying on"


def test_go_to_next_starts_from_the_trace_go_to_trace_frames(parent):
    """"Go to trace" frames the kept member, so cycling starts there."""
    visited = []
    record = _group_record(("aaa", "bbb"), keep="bbb")
    dialog = DuplicateTracesDialog(
        parent, [record],
        navigate=lambda snum, name, index: visited.append(name),
    )
    dialog.table.selectRow(0)

    dialog.goToSelectedContour()
    dialog.goToNextMemberContour()

    assert visited == ["bbb", "aaa"]


def test_the_base_class_still_sorts_by_section_and_titles_itself(parent):
    base = MalformedContoursDialog(parent, [_dust_record()])

    assert base.DEFAULT_SORT_COLUMN == 1
    assert base.COLUMNS[1] == "Section"
    assert base.windowTitle() == "Traces skipped during smoothing"
    assert base.SORTABLE is True
    assert base.table.isSortingEnabled() is True
