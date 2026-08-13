"""A z-trace pinned to a deleted or renamed alignment must not break the list.

The crash this pins, from a user's error report against v1.21.2 on macOS::

    File ".../gui/main/field_widget_1_base.py", ... in openList
    File ".../backend/table/manager.py", ... in newTable
    File ".../gui/table/ztrace.py", ... in __init__
    File ".../gui/table/data_table.py", ... in createTable
    File ".../gui/table/ztrace.py", ... in setRow
    File ".../gui/table/ztrace.py", ... in getItems
    File ".../modules/datatypes/series_data.py", ... in getZtraceDist
    File ".../modules/datatypes/ztrace.py", ... in getDistance
    KeyError: 'D004_2024-10-28_DDH'

The key is an alignment name, not a section. Objects and z-traces may pin
themselves to a named alignment, and ``Series.modifyAlignments`` rewrote every
section's tforms on a rename or a delete while leaving those stored attributes
naming an alignment that no longer existed anywhere in the series.

Objects survived that and z-traces did not, and the asymmetry is the whole bug.
The object path self-heals: ``SeriesData.addTrace`` sees a name that is not in
``section.tforms``, clears the attribute, and falls back to the series
alignment. The z-trace path had no equivalent check at any of its five tform
lookups, so the bare dict lookup raised. Severity came from where it raised:
the z-trace list computes a distance for every row while the table is being
built, so a single z-trace with a dangling alignment made the entire list
impossible to open, and the same dangling name also broke smoothing that
z-trace and generating it in 3D.

Fixed in two layers, both pinned here, because either alone is unsatisfying:

* ``Series.remapStoredAlignments`` follows renames and clears deletes, so the
  dangling state stops being created. Following the rename rather than clearing
  is what keeps the user's intent: clearing would silently drop a z-trace back
  to the series alignment while the alignment it asked for still existed under
  a new name.
* ``transform.alignment_tform`` degrades instead of raising, so a series saved
  before the first layer existed still opens. That is the layer the reporter
  needs, since his series already carries the dangling name.
"""

import pytest

pytestmark = pytest.mark.gui

from PyReconstruct.modules.datatypes.ztrace import Ztrace
from PyReconstruct.modules.datatypes.transform import alignment_tform

PINNED = "D004_2024-10-28_DDH"   # the reporter's alignment name
GREEN = [0, 255, 0]


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _alignment_dict(series, **changes):
    """Every existing alignment mapped to itself, plus the requested changes.

    The shape ``MainWindow.modifyAlignments`` passes once its dialog is
    confirmed: each resulting alignment name maps to the old name it comes
    from, and a deletion maps to None.
    """
    d = {a: a for a in series.alignments}
    d.update(changes)
    return d


def _add_alignment(series, name, series_states=None):
    series.modifyAlignments(
        _alignment_dict(series, **{name: series.alignment}), series_states
    )


def _add_ztrace(series, name="zt", alignment=None):
    """A two-point z-trace on the series' first two sections."""
    snums = sorted(series.sections.keys())[:2]
    if len(snums) < 2:
        pytest.skip("fixture series has fewer than two sections")
    points = [(1.0, 1.0, snums[0]), (2.0, 2.0, snums[1])]
    series.ztraces[name] = Ztrace(name, GREEN, points)
    if alignment is not None:
        series.setAttr(name, "alignment", alignment, ztrace=True)
    return name


def _stored(series, name, ztrace=True):
    return series.getAttr(name, "alignment", ztrace=ztrace)


# --------------------------------------------------------------------------- #
# the reported crash, end to end through the real list widget                   #
# --------------------------------------------------------------------------- #
def test_ztrace_list_opens_with_a_dangling_alignment(main_window):
    """The reporter's scenario, driven through the widget that crashed.

    The dangling attribute is written directly, which is the state his saved
    series is in: pinned to an alignment that no longer exists. Before the fix
    this raised KeyError inside createTable and the list never appeared.
    """
    series = main_window.series
    _add_ztrace(series, "zt", alignment=PINNED)
    assert PINNED not in series.alignments, "the name must not exist for this test"

    main_window.field.openList("ztrace")

    table = main_window.field.table_manager.tables["ztrace"][-1]
    assert table.table.rowCount() >= 1


def test_distance_falls_back_instead_of_raising(main_window):
    """The exact call in the traceback, at the layer that raised."""
    series = main_window.series
    _add_ztrace(series, "zt", alignment=PINNED)

    pinned = series.data.getZtraceDist("zt")
    unpinned = Ztrace("plain", GREEN, series.ztraces["zt"].points).getDistance(series)

    assert pinned == pytest.approx(unpinned), (
        "a dangling alignment should compute the distance the series alignment "
        "gives, not raise"
    )


def test_smoothing_survives_a_dangling_alignment(main_window):
    """The second unguarded lookup pair, in Ztrace.smooth."""
    series = main_window.series
    _add_ztrace(series, "zt", alignment=PINNED)

    series.ztraces["zt"].smooth(series, 2)   # raised KeyError before the fix

    assert len(series.ztraces["zt"].points) == 2


# --------------------------------------------------------------------------- #
# alignment_tform: the degrading resolver                                       #
# --------------------------------------------------------------------------- #
def test_a_known_alignment_is_returned_unchanged(main_window):
    series = main_window.series
    _add_alignment(series, "extra")
    snum = sorted(series.sections.keys())[0]

    assert alignment_tform(series, snum, "extra") is (
        series.data["sections"][snum]["tforms"]["extra"]
    )


def test_none_means_the_series_alignment(main_window):
    series = main_window.series
    snum = sorted(series.sections.keys())[0]

    assert alignment_tform(series, snum) is (
        series.data["sections"][snum]["tforms"][series.alignment]
    )


def test_a_dangling_name_degrades_to_the_series_alignment(main_window):
    series = main_window.series
    snum = sorted(series.sections.keys())[0]

    assert alignment_tform(series, snum, PINNED) is (
        series.data["sections"][snum]["tforms"][series.alignment]
    )


def test_the_last_resort_is_the_identity(main_window):
    """With both the stored name and the series alignment missing.

    ``no-alignment`` is always present: the tform container seeds it with the
    identity transform in its constructor, which is what makes this resolver
    total rather than merely lucky.
    """
    series = main_window.series
    snum = sorted(series.sections.keys())[0]
    series.alignment = "also-gone"

    tform = alignment_tform(series, snum, PINNED)

    assert tform.equals(series.data["sections"][snum]["tforms"]["no-alignment"])


# --------------------------------------------------------------------------- #
# remapStoredAlignments: stop creating the dangling state                      #
# --------------------------------------------------------------------------- #
def test_a_rename_carries_the_ztrace_attribute_forward(main_window):
    """Intent preserved: the z-trace still points at the alignment it asked for."""
    series = main_window.series
    _add_alignment(series, "before")
    _add_ztrace(series, "zt", alignment="before")

    series.modifyAlignments(
        {a: a for a in series.alignments if a != "before"} | {"after": "before"}
    )

    assert "after" in series.alignments
    assert _stored(series, "zt") == "after"


def test_a_delete_clears_the_ztrace_attribute(main_window):
    series = main_window.series
    _add_alignment(series, "doomed")
    _add_ztrace(series, "zt", alignment="doomed")

    series.modifyAlignments(_alignment_dict(series, doomed=None))

    assert "doomed" not in series.alignments
    assert _stored(series, "zt") is None


def test_objects_are_remapped_the_same_way(main_window):
    """Objects pin themselves to alignments too, through the same attributes."""
    series = main_window.series
    _add_alignment(series, "before")
    obj = sorted(series.data["objects"].keys())[0]
    series.setAttr(obj, "alignment", "before")

    series.modifyAlignments(
        {a: a for a in series.alignments if a != "before"} | {"after": "before"}
    )

    assert _stored(series, obj, ztrace=False) == "after"


def test_an_ambiguous_rename_clears_rather_than_guessing(main_window):
    """One old name feeding two new ones has no single honest answer."""
    series = main_window.series
    _add_alignment(series, "source")
    _add_ztrace(series, "zt", alignment="source")

    series.modifyAlignments(
        {a: a for a in series.alignments if a != "source"}
        | {"copy_one": "source", "copy_two": "source"}
    )

    assert _stored(series, "zt") is None


def test_a_surviving_name_is_left_alone(main_window):
    series = main_window.series
    _add_alignment(series, "kept")
    _add_ztrace(series, "zt", alignment="kept")

    _add_alignment(series, "unrelated")

    assert _stored(series, "zt") == "kept"


def test_an_already_dangling_attribute_self_heals(main_window):
    """A series saved before the fix is repaired by any alignment edit.

    The reporter's series is in exactly this state, so confirming the
    Alignments dialog once is a second route out of it, independent of the
    resolver that stops the crash.
    """
    series = main_window.series
    _add_ztrace(series, "zt", alignment=PINNED)

    _add_alignment(series, "unrelated")

    assert _stored(series, "zt") is None
