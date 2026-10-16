"""A log row split across lines is read by the block rule.

Older builds wrote a line break in a name or event as it was, so one row
reached ``LogSet.fromList`` as several physical lines. The reader used to join
lines until the row had six bare commas, which stopped early on a name such as
``foo,bar,baz`` and raised, and joined with no break, which read
``foo`` and ``bar`` as ``foobar``.

The block rule: a row starts at a line with the date stamp and runs to the next
such line. The block is joined with the breaks put back and parsed once. A block
that does not parse is set aside whole and reported; nothing is guessed or
renamed. Each shape below is one way an older row can be split, named for where
it was found, and is read the way the block rule reads it.
"""

import json
import os
import shutil
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.datatypes import log as log_module
from PyReconstruct.modules.datatypes.log import Log, LogSet, quoteField

STAMP = "26-01-01, 10:00, "
NEXT = "26-01-02, 11:00, carol, obj_c, 9, Modify trace(s)"


def _lf(lines):
    """Lines the way getFullHistory hands them over: each keeps its "\\n"."""
    return [line + "\n" for line in lines]


def _crlf(lines):
    return [line + "\r\n" for line in lines]


def _bare(lines):
    return list(lines)


LINE_FORMS = {"lf": _lf, "crlf": _crlf, "bare": _bare}


def row(user, obj_name, sections, event):
    return (user, obj_name, sections, event)


# name -> (physical lines, the row read, or None when the block is set aside)
SHAPES = {
    "issue_169_bare_commas": (
        [STAMP + "alice, foo,bar,baz", "qux, 1, Modified trace(s)"],
        row("alice", "foo,bar,baz\nqux", [(1, 1)], "Modified trace(s)"),
    ),
    "r1_1a_whole_fallback_row": (
        [STAMP + '"alice, axon", 3, Modify trace(s)'],
        row('"alice', 'axon"', [(3, 3)], "Modify trace(s)"),
    ),
    "r1_1b_fallback_row_plus_fragment": (
        [STAMP + '"alice, axon", 3, 1', ", Changed event"],
        row("alice, axon", "3", [(1, 1)], "Changed event"),
    ),
    "r1_2_break_in_quoted_user": (
        [STAMP + '"a, ', 'b", foo, 1, Modified trace(s)'],
        row("a, \nb", "foo", [(1, 1)], "Modified trace(s)"),
    ),
    "r1_3_ztrace_trailing_break": (
        [STAMP + "alice, foo", ", -, Modify ztrace"],
        row("alice", "foo\n", None, "Modify ztrace"),
    ),
    "r1_4_trace_double_break": (
        [STAMP + "alice, foo", "", "bar, 1, Modify trace(s)"],
        row("alice", "foo\n\nbar", [(1, 1)], "Modify trace(s)"),
    ),
    "r2_1_shared_event": (
        [STAMP + "alice, foo", ", -, Add to group 'g'"],
        row("alice", "foo\n", None, "Add to group 'g'"),
    ),
    "r2_2_open_quote_six_fields": (
        [STAMP + 'alice, "a,b, c, d, e, ', 'f", 1, Modified trace(s)'],
        row("alice", "a,b, c, d, e, \nf", [(1, 1)], "Modified trace(s)"),
    ),
    "r3_1_empty_bare_line": (
        [STAMP + "alice, foo", "", "bar, -, Modify ztrace"],
        row("alice", "foo\n\nbar", None, "Modify ztrace"),
    ),
    "r4_1_open_quote_early_parse": (
        [
            STAMP + 'alice, "foo,bar,baz',
            ", 1, Mark as curated",
            'tail", 2, Modify ztrace',
        ],
        row("alice", "foo,bar,baz\n, 1, Mark as curated\ntail", [(2, 2)],
            "Modify ztrace"),
    ),
    "r4_cr_two_line_numeric": (
        [STAMP + 'alice, "foo, 1, tail', 'end", 2, Modify ztrace'],
        row("alice", "foo, 1, tail\nend", [(2, 2)], "Modify ztrace"),
    ),
    # ambiguous: a break in the object and one in the event give these lines.
    # Read one way, and counted as rebuilt so a user is told.
    "x1_r4_shape_old_writer": (
        [STAMP + "alice, foo", ", 1, Mark as curated", "tail, 2, Modify ztrace"],
        row("alice", "foo\n", [(1, 1)],
            "Mark as curated\ntail, 2, Modify ztrace"),
    ),
    "x2_break_in_event": (
        [STAMP + "alice, -, -, Rename object to foo", "bar"],
        row("alice", None, None, "Rename object to foo\nbar"),
    ),
    "x3_broken_row_then_a_good_row": (
        [STAMP + "alice, foo", "bar, x, Modify trace(s)"],
        None,
    ),
}


def fields(log):
    return (log.user, log.obj_name, log.section_ranges, log.event)


@pytest.mark.parametrize("form", LINE_FORMS)
@pytest.mark.parametrize("shape", SHAPES)
def test_each_shape_reads_by_the_block_rule(shape, form):
    lines, expected = SHAPES[shape]
    log_list = LINE_FORMS[form](lines + [NEXT])

    salvaged = LogSet.fromList(log_list, skip_corrupt=True)

    assert fields(salvaged.all_logs[-1]) == fields(Log.fromStr(NEXT)), (
        "the row after the shape is read as itself"
    )
    if expected is None:
        with pytest.raises(ValueError):
            LogSet.fromList(log_list)
        assert len(salvaged.all_logs) == 1
        assert salvaged.skipped_rows == log_list[:len(lines)]
        assert salvaged.skipped_indexes == list(range(len(lines)))
        return

    strict = LogSet.fromList(log_list)
    assert [fields(log) for log in strict.all_logs] == [
        fields(log) for log in salvaged.all_logs
    ]
    assert len(salvaged.all_logs) == 2
    assert fields(salvaged.all_logs[0]) == expected
    assert salvaged.skipped_rows == []


def test_the_issue_169_row_loads():
    lines = _lf(SHAPES["issue_169_bare_commas"][0])

    log = LogSet.fromList(lines).all_logs[0]

    assert log.obj_name == "foo,bar,baz\nqux"
    assert log.section_ranges == [(1, 1)]


@pytest.mark.parametrize("shape", ["r1_1b_fallback_row_plus_fragment", "x1_r4_shape_old_writer"])
def test_an_ambiguous_row_is_counted_as_rebuilt(shape):
    lines = _lf(SHAPES[shape][0] + [NEXT])

    log_set = LogSet.fromList(lines)

    assert log_set.rebuilt_logs == [log_set.all_logs[0]]


def test_a_row_on_one_line_is_not_counted_as_rebuilt():
    lines = _lf(SHAPES["r1_1a_whole_fallback_row"][0] + [NEXT])

    assert LogSet.fromList(lines).rebuilt_logs == []


def test_a_set_aside_block_records_each_of_its_lines():
    # --check-history prints one line number per skipped_rows entry
    lines = _lf([NEXT, STAMP + "alice, foo", "bar, x, Modify trace(s)", "more", NEXT])

    log_set = LogSet.fromList(lines, skip_corrupt=True)

    assert log_set.skipped_rows == lines[1:4]
    assert log_set.skipped_indexes == [1, 2, 3]
    assert len(log_set.all_logs) == 2


def test_a_fragment_of_a_failed_block_is_never_read_alone():
    # read alone, the second line is a whole six-field row naming "w"
    lines = [STAMP + "alice, x", "y, z, w, v, 1, event", NEXT]
    assert Log.fromStr(lines[1]).user == "w"

    log_set = LogSet.fromList(lines, skip_corrupt=True)

    assert [log.user for log in log_set.all_logs] == ["carol"]
    assert log_set.skipped_rows == lines[:2]


def test_lines_before_the_first_stamp_are_set_aside():
    lines = ["", "orphan, text", NEXT]

    with pytest.raises(ValueError):
        LogSet.fromList(lines)
    log_set = LogSet.fromList(lines, skip_corrupt=True)
    assert log_set.skipped_rows == ["orphan, text"]
    assert log_set.skipped_indexes == [1]


def test_blank_lines_between_rows_are_not_part_of_either():
    lines = _lf([STAMP + "alice, a, 1, Modify trace(s)", "", NEXT, ""])

    log_set = LogSet.fromList(lines)

    assert [log.user for log in log_set.all_logs] == ["alice", "carol"]
    assert log_set.rebuilt_logs == []


def test_a_one_line_row_is_parsed_once(monkeypatch):
    calls = []
    real = log_module.splitRow

    def counting(s, decode=True):
        calls.append(s)
        return real(s, decode)

    monkeypatch.setattr(log_module, "splitRow", counting)

    LogSet.fromList(_lf([STAMP + "alice, a, 1, Modify trace(s)", NEXT]))

    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# every way an older build could split a row, read every way the lines arrive.
# The idea of this matrix comes from closed pull request 844; the expected read
# is now the row as written, with no name repaired.
# --------------------------------------------------------------------------- #
BREAKS = {
    "inside": lambda plain, quoted: plain[:2] + "\n" + plain[2:],
    "at-start": lambda plain, quoted: "\n" + plain,
    "at-end": lambda plain, quoted: plain + "\n",
    "inside-quoted": lambda plain, quoted: quoted.replace(", ", ", \n", 1),
    "empty-line": lambda plain, quoted: plain[:2] + "\n\n" + plain[2:],
    "two-empty-lines": lambda plain, quoted: plain[:2] + "\n\n\n" + plain[2:],
    "several": lambda plain, quoted: plain[:1] + "\n" + plain[1:3] + "\n\n" + plain[3:],
}

TRACE_ROW = ("alice", "foo", "1", "Modify trace(s)")
ZTRACE_ROW = ("alice", "foo", "-", "Modify ztrace")
SHARED_ROW = ("alice", "foo", "-", "Add to group 'g'")

# field -> (row, index of the field in it, value holding ", ")
FIELDS = {
    "user": (TRACE_ROW, 0, "smith, jo"),
    "trace-object": (TRACE_ROW, 1, "dendrite 1, spine a"),
    "ztrace-object": (ZTRACE_ROW, 1, "dendrite 1, spine a"),
    "shared-object": (SHARED_ROW, 1, "dendrite 1, spine a"),
    "event": (
        ("alice", "foo", "1", "Rename object to spine"),
        3,
        "Add to group 'dendrite 1, spine a'",
    ),
}


@pytest.mark.parametrize("form", LINE_FORMS)
@pytest.mark.parametrize("where", BREAKS)
@pytest.mark.parametrize("field", FIELDS)
def test_every_split_row_reads_as_written(field, where, form):
    base, index, quoted = FIELDS[field]
    values = list(base)
    values[index] = BREAKS[where](base[index], quoted)
    user, obj_name, sections, event = values
    text = (
        f"{STAMP}{quoteField(user)}, {quoteField(obj_name)}, {sections}, {event}"
    )
    assert "\n" in text, "the older row really is split"
    log_list = LINE_FORMS[form](text.split("\n") + [NEXT])

    log_set = LogSet.fromList(log_list)

    assert len(log_set.all_logs) == 2
    assert fields(log_set.all_logs[0]) == (
        user,
        obj_name,
        None if sections == "-" else [(int(sections), int(sections))],
        event.strip(),
    )
    # a break at the very end of the event leaves only a blank line, which
    # holds no field, so nothing was rebuilt
    split = "\n" in text.rstrip("\n")
    assert log_set.rebuilt_logs == ([log_set.all_logs[0]] if split else [])


# --------------------------------------------------------------------------- #
# what the history view shows
# --------------------------------------------------------------------------- #
FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

BROKEN_LOG = [
    "Date, Time, User, Obj, Sections, Event",
    *SHAPES["x3_broken_row_then_a_good_row"][0],
    *SHAPES["x1_r4_shape_old_writer"][0],
    *SHAPES["issue_169_bare_commas"][0],
    NEXT,
]


@pytest.fixture
def series(tmp_path):
    from PyReconstruct.modules.backend.notifier import NullNotifier
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    from PyReconstruct.modules.datatypes.series import Series

    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)
    s = Series.openJser(fp, progress=NullProgressReporter, notifier=NullNotifier())
    s.setSettingsStore(DictSettingsStore())
    with open(os.path.join(s.hidden_dir, "existing_log.csv"), "w", encoding="utf-8") as f:
        f.write("\n".join(BROKEN_LOG) + "\n")
    yield s
    s.leave_open = False
    s.close()


def _shown(parent):
    from PyReconstruct.modules.gui.table import HistoryTableWidget

    (widget,) = parent.findChildren(HistoryTableWidget)
    table = widget.table
    rows = [
        [table.item(r, c).text() for c in range(table.columnCount())]
        for r in range(table.rowCount())
    ]
    return widget, rows


def test_the_series_history_shows_what_was_set_aside_and_rebuilt(qapp, series):
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.gui.main.main_window import MainWindow

    parent = QWidget()
    parent.series = series
    MainWindow.viewSeriesHistory(parent)

    widget, rows = _shown(parent)
    assert [r[2] for r in rows] == ["carol", "alice", "alice"]
    assert widget.notice.text() == (
        "2 lines of this series' history could not be read and are not shown. "
        "The series file still holds them. "
        "2 rows were rebuilt from an entry an older version split across lines. "
        "Line breaks show as _."
    )
    # the name is shown as written, not renamed to a trace name
    assert rows[1][3] == "foo,bar,baz_qux"
    widget.close()
    parent.deleteLater()


def test_the_object_history_counts_only_its_own_rebuilt_rows(qapp, series):
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.gui.main.field_widget_3_object import FieldWidgetObject

    mainwindow = QWidget()
    mainwindow.saveAllData = lambda: None
    field = SimpleNamespace(
        series=series,
        mainwindow=mainwindow,
        table_manager=SimpleNamespace(hasFocus=lambda: None),
        section=SimpleNamespace(
            selected_traces=[SimpleNamespace(name="foo,bar,baz\nqux")]
        ),
    )
    FieldWidgetObject.viewHistory(field)

    widget, rows = _shown(mainwindow)
    assert len(rows) == 1
    assert widget.notice.text() == (
        "2 lines of this series' history could not be read and are not shown. "
        "The series file still holds them. "
        "1 row was rebuilt from an entry an older version split across lines. "
        "Line breaks show as _."
    )
    widget.close()
    mainwindow.deleteLater()


def test_a_clean_history_shows_no_notice(qapp):
    from PySide6.QtWidgets import QWidget

    from PyReconstruct.modules.gui.table import HistoryTableWidget

    parent = QWidget()
    widget = HistoryTableWidget(LogSet.fromList([NEXT]), parent)
    assert widget.notice is None
    assert widget.widget() is widget.table
    widget.close()
    parent.deleteLater()


def test_opening_a_series_says_how_many_lines_were_set_aside(
    main_window, main_window_dialogs, shapes1_jser
):
    from PyReconstruct.modules.constants import fast_loads

    with open(shapes1_jser, "rb") as f:
        data = fast_loads(f.read())
    data["log"] = "\n".join(BROKEN_LOG)
    shapes1_jser.write_text(json.dumps(data), encoding="utf-8")

    main_window_dialogs.notices.clear()
    main_window.openSeries(jser_fp=str(shapes1_jser), query_prev=False)

    assert main_window_dialogs.notices == [
        "2 lines of this series' history could not be read and are not shown. "
        "The series file still holds them. Nothing in the file was changed."
    ]
    with open(shapes1_jser, encoding="utf-8") as f:
        assert json.load(f)["log"] == "\n".join(BROKEN_LOG)
