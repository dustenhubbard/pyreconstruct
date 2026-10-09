"""A log row split across lines is rejoined as the older build wrote it.

Older builds wrote a newline in a name straight into existing_log.csv, so one
row reached ``LogSet.fromList`` as several physical lines. The join that puts
them back used to count bare commas to decide when the row was whole, while
``splitRow`` splits on ", " and reads a quoted name as one field. A field such
as "foo,bar,baz" made a partial row look whole, the join stopped a line early,
and the row raised. The join also put nothing where the line break was, so
"foo" and "bar" read as "foobar" while a name ending in a Return kept its
"\\n" or not depending on how the lines were read.

The join now puts a "\\n" back at each break, so the joined row is the text
the older build wrote, and the parser splits it the way it would have split
that row on one line. A name holding a break, in an event only a trace writes,
is then normalized the way a trace name is normalized on open. Any other name
is not: a z-trace keeps its name as written, and the group and alignment
events are written for z-traces too.
"""

import pytest

from PyReconstruct.modules.datatypes.log import Log, LogSet, quoteField
from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.datatypes.ztrace import Ztrace


def _readlines(text):
    """Lines the way getFullHistory hands them over: each keeps its "\\n"."""
    return text.splitlines(keepends=True)


def _bare(text):
    """Lines with no endings at all."""
    return text.split("\n")


def _crlf(text):
    """The file as readlines, written with CRLF endings."""
    return text.replace("\n", "\r\n").splitlines(keepends=True)


LINE_FORMS = {"readlines": _readlines, "bare": _bare, "crlf": _crlf}


def _line_forms(text):
    """The same file as readlines, as bare lines, and with CRLF endings."""
    return tuple(form(text) for form in LINE_FORMS.values())


def _older_build_row(user, obj_name, section, event):
    """The row an older build wrote: the same f-string, newlines left raw."""
    return f"26-01-01, 10:00, {user}, {obj_name}, {section}, {event}\n"


def _trace_named(name):
    return Trace(name, (255, 0, 0)).name


def _ztrace_named(name):
    return Ztrace.fromDict(name, {"color": [255, 0, 0], "points": []}).name


@pytest.mark.parametrize("lines", [
    ["26-01-01, 10:00, alice, foo,bar,baz\n", "qux, 1, Modify trace(s)\n"],
    ["26-01-01, 10:00, alice, foo,bar,baz", "qux, 1, Modify trace(s)"],
], ids=["readlines", "no-line-endings"])
def test_a_field_with_bare_commas_keeps_joining(lines):
    log_set = LogSet.fromList(lines)

    assert len(log_set.all_logs) == 1
    log = log_set.all_logs[0]
    assert log.user == "alice"
    assert log.obj_name == "foo_bar_baz_qux"
    assert log.obj_name == _trace_named("foo,bar,baz\nqux")
    assert log.section_ranges == [(1, 1)]
    assert log.event == "Modify trace(s)"


def test_a_quoted_name_holding_commas_keeps_joining():
    lines = [
        '26-01-01, 10:00, "a, b, c", foo\n',
        "bar, 1, Modify trace(s)\n",
    ]

    log = LogSet.fromList(lines).all_logs[0]

    assert log.user == "a, b, c"
    assert log.obj_name == "foo_bar"
    assert log.section_ranges == [(1, 1)]


def test_a_break_inside_a_quoted_field_stays_inside_it():
    lines = [
        '26-01-01, 10:00, "a, \n',
        'b", foo, 1, Modify trace(s)\n',
    ]

    log = LogSet.fromList(lines).all_logs[0]

    assert log.user == "a, \nb"
    assert log.obj_name == "foo"
    assert str(log) == '26-01-01, 10:00, "a, _b", foo, 1, Modify trace(s)'


@pytest.mark.parametrize("obj_name", [
    "foo\nbar",
    "a\nb\nc",
    "spine1\n",
    "\nfoo",
    "\nfoo\n",
    "foo\n\nbar",
    "foo\n bar",
])
def test_a_split_trace_name_reads_as_the_trace_is_named(obj_name):
    text = _older_build_row("alice", obj_name, 1, "Modify trace(s)")
    assert text.count("\n") > 1, "the older row really is split"

    for lines in _line_forms(text):
        log_set = LogSet.fromList(lines)

        assert len(log_set.all_logs) == 1
        log = log_set.all_logs[0]
        assert log.obj_name == _trace_named(obj_name)
        assert log.section_ranges == [(1, 1)]
        assert log.event == "Modify trace(s)"


@pytest.mark.parametrize("obj_name", [
    "foo\n",
    "foo\nbar",
    "\nfoo",
    "foo\n bar",
    "foo\n\nbar",
])
def test_a_split_ztrace_name_reads_as_the_ztrace_is_named(obj_name):
    text = _older_build_row("alice", obj_name, "-", "Modify ztrace")

    for lines in _line_forms(text):
        log = LogSet.fromList(lines).all_logs[0]

        assert log.obj_name == obj_name
        assert log.obj_name == _ztrace_named(obj_name)
        assert log.section_ranges is None
        assert log.event == "Modify ztrace"


@pytest.mark.parametrize("event", [
    "Add to group 'g'",
    "Remove from group 'g'",
    "Remove from all object groups",
    "Edit default alignment",
])
@pytest.mark.parametrize("obj_name", ["foo\n", "foo\nbar", "foo\n\nbar"])
def test_a_name_in_an_event_ztraces_share_stays_as_written(event, obj_name):
    # Written for a trace object and for a z-trace alike, so the row cannot
    # say which kind it names, and a z-trace keeps its name as written.
    text = _older_build_row("alice", obj_name, "-", event)

    for lines in _line_forms(text):
        log = LogSet.fromList(lines).all_logs[0]

        assert log.obj_name == obj_name
        assert log.obj_name == _ztrace_named(obj_name)
        assert log.section_ranges is None
        assert log.event == event


def test_a_quoted_name_left_open_by_a_break_keeps_joining():
    # Read the old way, the first line alone already holds six fields.
    lines = [
        '26-01-01, 10:00, alice, "a,b, c, d, e, \n',
        'f", 1, Modified trace(s)\n',
    ]

    log_set = LogSet.fromList(lines, skip_corrupt=True)

    assert log_set.skipped_rows == []
    assert len(log_set.all_logs) == 1
    log = log_set.all_logs[0]
    assert log.user == "alice"
    assert log.obj_name == "a,b, c, d, e, \nf"
    assert log.section_ranges == [(1, 1)]
    assert log.event == "Modified trace(s)"
    assert LogSet.fromList(lines).all_logs == log_set.all_logs


def test_a_break_inside_a_name_reads_as_this_build_writes_it():
    text = _older_build_row("alice", "a\nb\nc", 1, "Modify trace(s)")

    log = LogSet.fromList(_readlines(text)).all_logs[0]

    written_now = Log("26-01-01", "10:00", "alice", "a\nb\nc", 1, "Modify trace(s)")
    assert str(log) == str(written_now)


def test_a_whole_row_read_the_old_way_is_not_joined():
    # Short of six fields read with quoting, but whole read the old way,
    # which Log.fromStr falls back to.
    lines = ['26-06-29, 12:00, "alice, axon", 3, Modify trace(s)\n']

    log_set = LogSet.fromList(lines)

    assert log_set.all_logs == [Log.fromStr(lines[0])]
    assert log_set.all_logs[0].user == '"alice'
    assert log_set.skipped_rows == []


def test_a_whole_row_read_the_old_way_does_not_swallow_a_fragment():
    lines = [
        '26-06-29, 12:00, "alice, axon", 3, 1\n',
        ", Changed event\n",
    ]

    with pytest.raises(ValueError):
        LogSet.fromList(lines)

    log_set = LogSet.fromList(lines, skip_corrupt=True)
    assert log_set.all_logs == [Log.fromStr(lines[0])]
    assert log_set.skipped_rows == [lines[1]]


def test_a_short_row_before_another_row_still_raises():
    lines = [
        "26-01-01, 10:00, alice, foo\n",
        "26-01-01, 10:05, bob, bar, 2, Modify trace(s)\n",
    ]

    with pytest.raises(ValueError):
        LogSet.fromList(lines)

    log_set = LogSet.fromList(lines, skip_corrupt=True)
    assert log_set.skipped_rows == [lines[0]]
    assert [log.user for log in log_set.all_logs] == ["bob"]


def test_a_short_final_row_still_runs_off_the_end():
    lines = [
        "26-01-01, 10:05, bob, bar, 2, Modify trace(s)\n",
        "26-01-01, 10:00, alice, foo\n",
    ]

    with pytest.raises(IndexError):
        LogSet.fromList(lines)

    log_set = LogSet.fromList(lines, skip_corrupt=True)
    assert log_set.skipped_rows == [lines[1]]
    assert [log.user for log in log_set.all_logs] == ["bob"]


## Every way an older build could split a row, read every way a reader hands
## the lines over. A row is (user, object, sections, event); FIELDS says which
## of them the break goes into, BREAKS where in it, LINE_FORMS how the lines
## arrive. A trace's name is the only one normalized on open. A break in the
## event leaves a head that parses, so text after it is not joined: it is a
## loss the reader reports, as tests/test_editors_from_corrupt_history.py pins
## for a line that follows a whole row.

# (plain value, value holding the ", " quoteField quotes) -> value with breaks
BREAKS = {
    "inside": lambda plain, quoted: plain[:2] + "\n" + plain[2:],
    "at-start": lambda plain, quoted: "\n" + plain,
    "at-end": lambda plain, quoted: plain + "\n",
    "inside-quoted": lambda plain, quoted: quoted.replace(", ", ", \n", 1),
    "empty-line": lambda plain, quoted: plain[:2] + "\n\n" + plain[2:],
    "two-empty-lines": lambda plain, quoted: plain[:2] + "\n\n\n" + plain[2:],
    "empty-line-at-start": lambda plain, quoted: "\n\n" + plain,
    "empty-line-at-end": lambda plain, quoted: plain + "\n\n",
    "empty-line-quoted": lambda plain, quoted: quoted.replace(", ", ", \n\n", 1),
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
def test_every_split_row_reads_as_the_older_build_meant(field, where, form):
    row, index, quoted = FIELDS[field]
    fields = list(row)
    fields[index] = BREAKS[where](row[index], quoted)
    user, obj_name, section, event = fields
    text = (
        f"26-01-01, 10:00, {quoteField(user)}, {quoteField(obj_name)}, "
        f"{section}, {event}\n"
    )
    assert text.count("\n") > 1, "the older row really is split"

    lines = LINE_FORMS[form](text)
    log_set = LogSet.fromList(lines, skip_corrupt=True)

    if field == "trace-object":
        obj_name = _trace_named(obj_name)
    event_head, _, event_tail = event.partition("\n")
    if event_tail.strip():
        with pytest.raises(ValueError):
            LogSet.fromList(lines)
        assert [row.strip() for row in log_set.skipped_rows] == [
            line for line in event_tail.split("\n") if line
        ]
        event = event_head
    else:
        assert log_set.skipped_rows == []
    meant = Log(
        "26-01-01", "10:00", user, obj_name,
        None if section == "-" else int(section), event.strip(),
    )
    assert len(log_set.all_logs) == 1
    log = log_set.all_logs[0]
    assert (log.user, log.obj_name, log.section_ranges, log.event) == (
        meant.user, meant.obj_name, meant.section_ranges, meant.event,
    )
