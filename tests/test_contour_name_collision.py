"""Object names that differ only in spaces or commas.

An object name cannot hold whitespace or a comma. That is not decoration: the
log is a ``", "``-delimited CSV whose fourth field is the object name
(``Log.__str__`` / ``Log.fromStr``), so a name holding that pair shifts every
field after it and ``Log.fromStr`` raises on the section range it then reads.
``test_comma_and_space_in_a_name_makes_its_log_entry_unreadable`` below is the
proof, and it is what justifies keeping the rule.

Enforcing it costs something on load. ``Section.updateJSON`` rewrites the
contour keys of a file written before the rule existed, and it only ever sees
one section. Everything the *series* knows about an object -- groups, comment,
curation, alignment, user column values, hosts -- is keyed by the object name in
the series file, and was left behind pointing at a name no section holds any
more. Measured against ``shapes1.jser``: renaming one object 'my star' ->
'my_star' dropped its comment, its curation and its group membership, with no
collision involved at all. Where two names normalize to the same thing the two
objects also become one, and the second one's traces are kept but its identity
is not.

So:

* ``applyContourRenames`` carries the rename into ``obj_attrs``,
  ``object_groups`` and ``host_tree``, which fixes the no-collision case for
  everything the series keys by name in its JSON;
* ``contourNameCollisions`` finds the merges before the hidden directory is
  created, and ``openJser`` asks first, so the one case that genuinely cannot
  keep both objects is not silent.

The top-level ``log`` is a fourth structure keyed by object name and it is
deliberately not repointed. A renamed object's history stays under the old name,
and a legacy row whose name holds ``", "`` still fails to parse on open, which
is the very case the first paragraph above uses to justify the rule. That is
unchanged from ``main``: this module neither causes nor worsens it. It is left
because repointing rewrites recorded history rather than metadata, and because
the rows that most need it are exactly the ones ``Log.fromStr`` cannot locate
the object name in by field index, so it needs its own change rather than a
field swap here.

Flag names are deliberately left alone, and
``test_flag_names_are_not_normalized`` pins that as intended rather than
missed: a flag is never a log object name, and the flag table's CSV export
strips commas from a cell when it writes one.
"""

import json
import os
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import Notifier, NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.flag import Flag
from PyReconstruct.modules.datatypes.log import Log
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.series import (
    applyContourRenames,
    contourMergeWarning,
    contourNameCollisions,
)
from PyReconstruct.modules.datatypes.trace import Trace, normalizeObjectName

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "PyReconstruct", "assets", "checker", "files", "shapes1.jser",
)


def a_trace(x0):
    """A trace in the on-disk list shape: x, y, color, closed, ... , tags."""
    return [
        [x0, x0 + 1, x0 + 2], [0, 1, 2], [255, 0, 0],
        True, False, False, ["none", "none"], [],
    ]


# ---------------------------------------------------------------------------
# why the rule exists
# ---------------------------------------------------------------------------

def test_comma_and_space_in_a_name_makes_its_log_entry_unreadable():
    """An object name holding ``", "`` produces a log line that cannot be read.

    ``Log.fromStr`` splits on ``", "`` and repairs a comma in the *event* by
    rejoining the tail. There is no such repair for the object name, so the
    extra field shifts the section range one place and the parse raises. This is
    the constraint the normalization protects, so it is asserted here rather
    than asserted about.

    Measured, not assumed: a comma with no space after it survives the split,
    and so does a space with no comma. It is the pair that is fatal, and either
    character alone is one edit away from it, which is why the rule covers both.
    """
    entry = Log("24-01-01", "1200", "u", "my, trace", 3, "Create trace(s)")
    with pytest.raises(ValueError):
        Log.fromStr(str(entry))

    for survivable in ("my,trace", "my trace"):
        line = Log("24-01-01", "1200", "u", survivable, 3, "Create trace(s)")
        assert Log.fromStr(str(line)).obj_name == survivable

    # the normalized name round trips
    clean = Log("24-01-01", "1200", "u", "my__trace", 3, "Create trace(s)")
    assert Log.fromStr(str(clean)).obj_name == "my__trace"
    assert Log.fromStr(str(clean)).section_ranges == clean.section_ranges


def test_normalize_is_idempotent_and_shared_with_trace():
    """One function, applied twice, is the same as applied once."""
    for name in ("my trace", "my,trace", " my  trace ", "a,b c", "ok_name"):
        once = normalizeObjectName(name)
        assert normalizeObjectName(once) == once
        # the Trace setter and the load-path migration must agree, or a file
        # could be rewritten to a name the setter would change again
        assert Trace(name, [0, 0, 0]).name == once

    assert normalizeObjectName("my trace") == "my_trace"
    assert normalizeObjectName("my,trace") == "my_trace"
    assert normalizeObjectName("\tmy \t trace\n") == "my_trace"


# ---------------------------------------------------------------------------
# what the merge does to a section
# ---------------------------------------------------------------------------

def test_update_json_merges_names_and_keeps_every_trace():
    """Four contour names become one object; all seven traces survive."""
    sd = Section.getEmptyDict()
    sd["contours"] = {
        "my trace":   [a_trace(0), a_trace(10)],
        "my,trace":   [a_trace(20)],
        "my_trace":   [a_trace(30), a_trace(40), a_trace(50)],
        " my trace ": [a_trace(60)],
    }
    before = sum(len(v) for v in sd["contours"].values())

    renamed = Section.updateJSON(sd, 0)

    assert list(sd["contours"]) == ["my_trace"]
    assert sum(len(v) for v in sd["contours"].values()) == before == 7
    assert renamed == {
        "my trace": "my_trace",
        "my,trace": "my_trace",
        " my trace ": "my_trace",
    }


def test_update_json_reports_nothing_for_clean_names():
    """A section already satisfying the rule reports no rename."""
    sd = Section.getEmptyDict()
    sd["contours"] = {"star": [a_trace(0)], "square": [a_trace(9)]}

    assert Section.updateJSON(sd, 0) == {}
    assert sorted(sd["contours"]) == ["square", "star"]


# ---------------------------------------------------------------------------
# finding the collisions before anything is written
# ---------------------------------------------------------------------------

def test_collisions_are_found_across_sections():
    """Two names can collide without ever meeting inside one section."""
    jser = {"sections": [
        {"contours": {"my trace": [a_trace(0)], "alone": [a_trace(1)]}},
        None,
        {"contours": {"my,trace": [a_trace(2)]}},
    ]}

    assert contourNameCollisions(jser) == {
        "my_trace": ["my trace", "my,trace"],
    }


def test_a_plain_rename_is_not_a_collision():
    """One source name is a rename, not a merge, and is not reported."""
    jser = {"sections": [{"contours": {"my star": [a_trace(0)]}}]}

    assert contourNameCollisions(jser) == {}


def test_merge_warning_names_the_objects():
    """The text a user is shown says which names become which."""
    text = contourMergeWarning({"my_trace": ["my trace", "my,trace"]})

    assert "'my trace', 'my,trace' -> 'my_trace'" in text
    assert "Cancel" in text


# ---------------------------------------------------------------------------
# carrying the rename into the series data
# ---------------------------------------------------------------------------

def test_rename_carries_attrs_groups_and_hosts():
    """A rename with no collision loses nothing."""
    series_data = {
        "obj_attrs": {"my star": {"comment": "keep me", "curation": ["x"]}},
        "object_groups": {"shapes": ["my star", "square"]},
        "host_tree": {"square": ["my star"]},
    }

    applyContourRenames(series_data, {"my star": "my_star"}, {})

    assert series_data["obj_attrs"] == {
        "my_star": {"comment": "keep me", "curation": ["x"]}
    }
    assert series_data["object_groups"] == {"shapes": ["my_star", "square"]}
    assert series_data["host_tree"] == {"square": ["my_star"]}


def test_merge_keeps_the_union_of_groups_and_hosts():
    """Group and host membership is additive, so a merge unions it."""
    series_data = {
        "obj_attrs": {},
        "object_groups": {"a": ["my trace"], "b": ["my,trace"], "c": ["other"]},
        "host_tree": {"my trace": ["h1"], "my,trace": ["h2"]},
    }

    applyContourRenames(
        series_data,
        {"my trace": "my_trace", "my,trace": "my_trace"},
        {"my_trace": ["my trace", "my,trace"]},
    )

    assert series_data["object_groups"] == {
        "a": ["my_trace"], "b": ["my_trace"], "c": ["other"]
    }
    assert series_data["host_tree"] == {"my_trace": ["h1", "h2"]}


def test_merge_does_not_duplicate_a_group_member():
    """Both sources in one group leaves one member, not two."""
    series_data = {"object_groups": {"a": ["my trace", "my,trace", "other"]}}

    applyContourRenames(
        series_data,
        {"my trace": "my_trace", "my,trace": "my_trace"},
        {"my_trace": ["my trace", "my,trace"]},
    )

    assert series_data["object_groups"] == {"a": ["my_trace", "other"]}


def test_merge_cannot_make_an_object_its_own_host():
    """A host that merges onto its own guest is dropped, not written."""
    series_data = {"host_tree": {"my trace": ["my,trace", "h"]}}

    applyContourRenames(
        series_data,
        {"my trace": "my_trace", "my,trace": "my_trace"},
        {"my_trace": ["my trace", "my,trace"]},
    )

    assert series_data["host_tree"] == {"my_trace": ["h"]}


def test_merge_attr_winner_is_the_name_that_was_not_renamed():
    """An object whose name already obeyed the rule keeps its own attributes.

    It was not renamed, so nothing about it should change; the name that had to
    move is the one that gives way. Keys the winner does not have are filled
    from the loser, which can only add information.
    """
    series_data = {"obj_attrs": {
        "my_trace": {"comment": "already clean"},
        "my trace": {"comment": "renamed", "curation": ["only here"]},
    }}

    applyContourRenames(
        series_data,
        {"my trace": "my_trace"},
        {"my_trace": ["my trace", "my_trace"]},
    )

    assert series_data["obj_attrs"] == {
        "my_trace": {"comment": "already clean", "curation": ["only here"]}
    }


def test_no_renames_leaves_the_series_data_alone():
    """The common case does not touch anything."""
    series_data = {
        "obj_attrs": {"star": {"comment": "c"}},
        "object_groups": {"g": ["star"]},
        "host_tree": {"square": ["star"]},
    }
    before = json.loads(json.dumps(series_data))

    applyContourRenames(series_data, {}, {})

    assert series_data == before


# ---------------------------------------------------------------------------
# the whole load, against the checked-in fixture
# ---------------------------------------------------------------------------

def build_jser(tmp_path, renames, series_patch, name="probe"):
    """A copy of shapes1.jser with its contour keys renamed in the raw file."""
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    with open(FIXTURE) as f:
        data = json.load(f)
    for section_data in data["sections"]:
        if not section_data:
            continue
        for old, new in renames.items():
            if old in section_data["contours"]:
                section_data["contours"][new] = section_data["contours"].pop(old)
    data["series"].update(series_patch)
    fp = str(tmp_path / f"{name}.jser")
    with open(fp, "w") as f:
        json.dump(data, f)
    return fp


def object_names(series):
    names = set()
    for snum in sorted(series.sections):
        names.update(series.loadSection(snum).contours)
    return names


def trace_count(series, name):
    total = 0
    for snum in sorted(series.sections):
        contour = series.loadSection(snum).contours.get(name)
        if contour:
            total += len(contour.getTraces())
    return total


@pytest.mark.gui
def test_open_carries_a_rename_through_the_series(tmp_path):
    """The teeth: on origin/main this open dropped the comment and the group."""
    fp = build_jser(
        tmp_path,
        {"star": "my star"},
        {
            "obj_attrs": {"my star": {"comment": "keep me"}},
            "object_groups": {"solo": ["my star"]},
        },
    )

    series = Series.openJser(fp, progress=NullProgressReporter)
    try:
        assert "my_star" in object_names(series)
        assert series.getAttr("my_star", "comment") == "keep me"
        assert series.object_groups.getGroupDict() == {"solo": ["my_star"]}
        assert sorted(series.obj_attrs) == ["my_star"]
    finally:
        series.close()


@pytest.mark.gui
def test_open_merges_colliding_names_without_losing_traces(tmp_path):
    """Two objects become one; all ten traces and both groups survive."""
    fp = build_jser(
        tmp_path,
        {"star": "my trace", "square": "my,trace"},
        {
            "obj_attrs": {
                "my trace": {"comment": "space"},
                "my,trace": {"curation": ["comma"]},
            },
            "object_groups": {"a": ["my trace"], "b": ["my,trace"]},
        },
    )

    series = Series.openJser(fp, progress=NullProgressReporter)
    try:
        names = object_names(series)
        assert "my_trace" in names
        assert "my trace" not in names and "my,trace" not in names
        assert trace_count(series, "my_trace") == 10
        assert series.getAttr("my_trace", "comment") == "space"
        assert series.getAttr("my_trace", "curation") == ["comma"]
        assert series.object_groups.getGroupDict() == {
            "a": ["my_trace"], "b": ["my_trace"]
        }
        # nothing points at a name the series no longer has
        assert sorted(series.obj_attrs) == ["my_trace"]
    finally:
        series.close()


class Decliner(Notifier):
    """A user who says no."""

    def __init__(self):
        self.asked = []

    def notify(self, message):
        return False

    def confirm(self, message, title="Confirm"):
        self.asked.append(message)
        return False


@pytest.mark.gui
def test_declining_the_merge_leaves_the_file_untouched(tmp_path):
    """Cancel means no series and no hidden directory, not a half-open one."""
    fp = build_jser(tmp_path, {"star": "my trace", "square": "my,trace"}, {})
    before = os.stat(fp).st_mtime_ns
    notifier = Decliner()

    result = Series.openJser(
        fp, progress=NullProgressReporter, notifier=notifier
    )

    assert result is None
    assert len(notifier.asked) == 1
    assert "my_trace" in notifier.asked[0]
    assert not os.path.isdir(os.path.join(tmp_path, ".probe"))
    assert os.stat(fp).st_mtime_ns == before


@pytest.mark.gui
def test_nobody_to_ask_still_opens(tmp_path):
    """A script has no user, so the load proceeds as it did before."""
    fp = build_jser(tmp_path, {"star": "my trace", "square": "my,trace"}, {})

    series = Series.openJser(
        fp, progress=NullProgressReporter, notifier=NullNotifier()
    )
    try:
        assert series is not None
        assert trace_count(series, "my_trace") == 10
    finally:
        series.close()


@pytest.mark.gui
def test_a_clean_series_is_never_asked_about(tmp_path):
    """No collision, no question."""
    fp = str(tmp_path / "clean.jser")
    shutil.copyfile(FIXTURE, fp)
    notifier = Decliner()

    series = Series.openJser(
        fp, progress=NullProgressReporter, notifier=notifier
    )
    try:
        assert series is not None
        assert notifier.asked == []
    finally:
        series.close()


# ---------------------------------------------------------------------------
# the asymmetry with flags, and why it stays
# ---------------------------------------------------------------------------

def test_flag_names_are_not_normalized():
    """A flag keeps a comma in its name, deliberately.

    A flag is never written as a log object name (every flag event logs with
    ``obj_name=None``), so it cannot break the log the way an object name can,
    and the flag table's CSV export strips commas from a cell as it writes.
    Normalizing flag names would rewrite user text to protect a format that
    never sees it.
    """
    flag = Flag("my, flag", 0, 0, 1, [255, 0, 0])

    assert flag.name == "my, flag"
    assert Flag.fromList(flag.getList(), 1).name == "my, flag"


def test_flag_event_logs_carry_no_object_name():
    """The reason the flag asymmetry is safe, asserted rather than asserted about."""
    entry = Log("24-01-01", "1200", "u", None, 3, "Create flag(s)")
    parsed = Log.fromStr(str(entry))

    assert parsed.obj_name is None
    assert parsed.section_ranges == entry.section_ranges
