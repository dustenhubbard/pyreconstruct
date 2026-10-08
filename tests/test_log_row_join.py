"""A log row split across lines is rejoined by the parser's own field rule.

Older builds wrote a newline in a name straight into existing_log.csv, so one
row reached ``LogSet.fromList`` as several physical lines. The join that puts
them back used to count bare commas to decide when the row was whole, while
``splitRow`` splits on ", " and reads a quoted name as one field. A field such
as "foo,bar,baz" made a partial row look whole, the join stopped a line early,
and the row raised. The join also put nothing where the line break was, so
"foo" and "bar" read as "foobar" while a name ending in a Return kept its
"\\n" or not depending on how the lines were read.
"""

import pytest

from PyReconstruct.modules.datatypes.log import Log, LogSet
from PyReconstruct.modules.datatypes.trace import normalizeObjectName


def _readlines(text):
    """Lines the way getFullHistory hands them over: each keeps its "\\n"."""
    return text.splitlines(keepends=True)


def _older_build_row(user, obj_name, section, event):
    """The row an older build wrote: the same f-string, newlines left raw."""
    return f"26-01-01, 10:00, {user}, {obj_name}, {section}, {event}\n"


@pytest.mark.parametrize("lines", [
    ["26-01-01, 10:00, alice, foo,bar,baz\n", "qux, 1, Modified trace(s)\n"],
    ["26-01-01, 10:00, alice, foo,bar,baz", "qux, 1, Modified trace(s)"],
], ids=["readlines", "no-line-endings"])
def test_a_field_with_bare_commas_keeps_joining(lines):
    log_set = LogSet.fromList(lines)

    assert len(log_set.all_logs) == 1
    log = log_set.all_logs[0]
    assert log.user == "alice"
    assert log.obj_name == "foo,bar,baz_qux"
    assert log.section_ranges == [(1, 1)]
    assert log.event == "Modified trace(s)"


def test_a_quoted_name_holding_commas_keeps_joining():
    lines = [
        '26-01-01, 10:00, "a, b, c", foo\n',
        "bar, 1, Modified trace(s)\n",
    ]

    log = LogSet.fromList(lines).all_logs[0]

    assert log.user == "a, b, c"
    assert log.obj_name == "foo_bar"
    assert log.section_ranges == [(1, 1)]


@pytest.mark.parametrize("obj_name, read_as", [
    ("foo\nbar", "foo_bar"),
    ("a\nb\nc", "a_b_c"),
    ("d001sp003\n", "d001sp003"),
    ("\nfoo", "foo"),
    ("\nfoo\n", "foo"),
])
def test_a_split_name_reads_as_its_object_is_named(obj_name, read_as):
    text = _older_build_row("alice", obj_name, 1, "Modified trace(s)")
    assert text.count("\n") > 1, "the older row really is split"

    for lines in (_readlines(text), text.split("\n")):
        log_set = LogSet.fromList(lines)

        assert len(log_set.all_logs) == 1
        log = log_set.all_logs[0]
        assert log.obj_name == read_as
        assert log.obj_name == normalizeObjectName(obj_name)
        assert log.section_ranges == [(1, 1)]
        assert log.event == "Modified trace(s)"


def test_a_break_inside_a_name_reads_as_this_build_writes_it():
    text = _older_build_row("alice", "a\nb\nc", 1, "Modified trace(s)")

    log = LogSet.fromList(_readlines(text)).all_logs[0]

    written_now = Log("26-01-01", "10:00", "alice", "a\nb\nc", 1, "Modified trace(s)")
    assert str(log) == str(written_now)


def test_a_short_row_before_another_row_still_raises():
    lines = [
        "26-01-01, 10:00, alice, foo\n",
        "26-01-01, 10:05, bob, bar, 2, Modified trace(s)\n",
    ]

    with pytest.raises(ValueError):
        LogSet.fromList(lines)

    log_set = LogSet.fromList(lines, skip_corrupt=True)
    assert log_set.skipped_rows == [lines[0]]
    assert [log.user for log in log_set.all_logs] == ["bob"]


def test_a_short_final_row_still_runs_off_the_end():
    lines = [
        "26-01-01, 10:05, bob, bar, 2, Modified trace(s)\n",
        "26-01-01, 10:00, alice, foo\n",
    ]

    with pytest.raises(IndexError):
        LogSet.fromList(lines)

    log_set = LogSet.fromList(lines, skip_corrupt=True)
    assert log_set.skipped_rows == [lines[1]]
    assert [log.user for log in log_set.all_logs] == ["bob"]
