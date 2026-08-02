"""A two-point trace's ``closed`` flag is corrected on disk, not only in memory.

Two points enclose no area, so every reader forces such a trace open:
``Section.__init__``, ``Section.addTrace``, and the undo baseline in
``state_manager.getContours``. The stored flag used to be left alone, which
``docs/JSER_FORMAT.md`` recorded as reader/writer divergence 4.

What made it worth changing is not that the file was "wrong" -- it is that the
file was **unstable**. Measured on ``origin/main``:

  * open a ``.jser`` carrying ``closed: true`` on a two-point row and save it
    without touching that section, and the stale ``true`` round-trips **byte for
    byte**. Byte-idempotence was never broken, so the correction never arrived.
  * take the same section back through the model once (``Section.save``, which
    is what visiting or editing the section does) and the writer emits
    ``self.closed`` -- the coerced value -- so the flag flips to ``false`` and
    the bytes change.

So the flag flipped at an unpredictable later save rather than never: a
byte-level diff of a ``.jser`` in version control showed a change that no edit
accounts for, which is the same class of problem the canonical-ordering work
addressed. Correcting on unpack makes it happen once, for every section alike.

The divergent row does not require a hand-edited file. A Reconstruct XML import
writes ``trace.getList()`` straight into the section file with no arity check
(``xml_json_conversions.py``), and ``Trace.fromXMLObj`` takes the XML contour's
``closed`` verbatim, so a two-point closed contour keeps ``closed: true`` across
the import. ``reducePoints`` cannot take it below two points.

The fix lives in ``Section.updateJSON``, beside the existing removal of traces
with fewer than two points -- the disk-side twin of the same screen -- and for
the same reason the tag sort next to it lives there: ``saveJser`` copies the
hidden directory verbatim, so a normalization that only runs in the model never
reaches a section the user did not save.
"""
import hashlib
import json
import os

import pytest

from PyReconstruct.modules.datatypes.section import Section


FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)

# 8 elements, no name: contour rows are named by their dict key.
# [x, y, color, closed, negative, hidden, fill_mode, tags]
CLOSED = 3


def _row(n_points, closed):
    xs = [float(i) for i in range(n_points)]
    ys = [0.0] * n_points
    return [xs, ys, [255, 0, 0], closed, False, False, ["none", "none"], []]


# --------------------------------------------------------------------------
# unit: the normalization itself
# --------------------------------------------------------------------------

def test_updatejson_forces_a_two_point_row_open():
    sd = Section.getEmptyDict()
    sd["contours"] = {"twopt": [_row(2, True)]}
    Section.updateJSON(sd, 0)
    assert sd["contours"]["twopt"][0][CLOSED] is False


def test_updatejson_leaves_a_three_point_closed_row_alone():
    """Only two points are coerced. Three points can enclose an area."""
    sd = Section.getEmptyDict()
    sd["contours"] = {"tri": [_row(3, True)]}
    Section.updateJSON(sd, 0)
    assert sd["contours"]["tri"][0][CLOSED] is True


def test_updatejson_still_drops_a_one_point_row():
    """The coercion is chained onto the defective-trace screen; keep that screen."""
    sd = Section.getEmptyDict()
    sd["contours"] = {"onept": [_row(1, True)], "keep": [_row(3, True)]}
    Section.updateJSON(sd, 0)
    assert "onept" not in sd["contours"]
    assert len(sd["contours"]["keep"]) == 1


def test_updatejson_coerces_a_legacy_nine_element_row():
    """A 9-element contour row carries a trailing history object, popped first.

    The index the coercion writes is only correct after that pop, so a legacy
    row is the case that catches an off-by-one.
    """
    sd = Section.getEmptyDict()
    sd["contours"] = {"legacy": [_row(2, True) + [{"history": "x"}]]}
    Section.updateJSON(sd, 0)
    row = sd["contours"]["legacy"][0]
    assert len(row) == 8
    assert row[CLOSED] is False


def test_in_memory_coercion_still_holds_without_updatejson():
    """``Trace`` itself is unchanged; the model-side screen is still the truth.

    ``Section.__init__`` keeps its coercion for callers that build a section
    from data that has not been through ``updateJSON``.
    """
    from PyReconstruct.modules.datatypes.trace import Trace
    t = Trace.fromList(_row(2, True), "twopt")
    assert t.closed is True, "fromList is a decoder and does not normalize"
    assert len(t.points) == 2


# --------------------------------------------------------------------------
# end to end: through a real open and save
# --------------------------------------------------------------------------

def _sha(fp):
    with open(fp, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _stored_closed(fp, snum):
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["sections"][snum]["contours"]["twopt"][0][CLOSED]


@pytest.fixture
def jser_with_two_point_closed_trace(tmp_path):
    """A copy of the shipped fixture with one two-point ``closed: true`` row.

    No shipped fixture carries such a row, so it has to be injected; that is
    also why this change leaves ``test_jser_canonical_format.py``'s bytes alone.
    """
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    with open(FIXTURE, "r", encoding="utf-8") as f:
        data = json.load(f)
    snum = next(i for i, s in enumerate(data["sections"]) if s)
    data["sections"][snum]["contours"]["twopt"] = [_row(2, True)]
    fp = str(tmp_path / "twopt.jser")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert _stored_closed(fp, snum) is True
    return fp, snum


def _open(fp):
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    return Series.openJser(fp, progress=NullProgressReporter)


@pytest.mark.gui
def test_save_corrects_the_stored_flag_without_touching_the_section(
    tmp_path, jser_with_two_point_closed_trace
):
    """The correction reaches the file on the first save, not on a later one.

    On ``origin/main`` this assertion fails with ``True``: the unpack loop wrote
    the section data through verbatim and ``saveJser`` copied it back.
    """
    fp, snum = jser_with_two_point_closed_trace
    series = _open(fp)
    try:
        section = series.loadSection(snum)
        assert section.contours["twopt"][0].closed is False  # memory, as before
        out = str(tmp_path / "saved.jser")
        series.saveJser(save_fp=out)
    finally:
        series.close()
    assert _stored_closed(out, snum) is False


@pytest.mark.gui
def test_visiting_the_section_no_longer_changes_the_trace_row(
    tmp_path, jser_with_two_point_closed_trace
):
    """The instability that motivated the fix.

    A save that takes the section back through the model must now emit the same
    contours as one that does not. On ``origin/main`` the flag flips from
    ``true`` to ``false`` between these two saves, which is the spurious diff a
    ``.jser`` in version control picked up.

    Scoped to ``contours`` on purpose. The two files are still not byte-equal,
    for a reason this change does not touch: divergence 1 in
    ``docs/JSER_FORMAT.md``. The shipped fixture carries the legacy scalar
    ``brightness``/``contrast`` pair, ``Section.getDict`` never writes it back,
    and so it disappears the first time the section goes through the model. The
    assertion below pins that as the *only* remaining difference, so this test
    fails rather than passes quietly if the model-side writer starts changing
    something else.
    """
    fp, snum = jser_with_two_point_closed_trace

    series = _open(fp)
    try:
        untouched = str(tmp_path / "untouched.jser")
        series.saveJser(save_fp=untouched)
    finally:
        series.close()

    series = _open(untouched)
    try:
        series.loadSection(snum).save()
        touched = str(tmp_path / "touched.jser")
        series.saveJser(save_fp=touched)
    finally:
        series.close()

    with open(untouched, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(touched, "r", encoding="utf-8") as f:
        after = json.load(f)

    assert before["sections"][snum]["contours"] == \
        after["sections"][snum]["contours"]

    # and the whole section differs only by the legacy scalars
    dropped = set(before["sections"][snum]) - set(after["sections"][snum])
    assert dropped == {"brightness", "contrast"}
    assert {
        k: v for k, v in before["sections"][snum].items() if k not in dropped
    } == after["sections"][snum]


@pytest.mark.gui
def test_save_reopen_save_is_byte_identical(
    tmp_path, jser_with_two_point_closed_trace
):
    """Byte-idempotence held before this change and must still hold after it.

    Stated explicitly because it is the property the change could plausibly
    have broken: a normalization that ran on every unpack rather than settling
    after the first one would show up here.
    """
    fp, snum = jser_with_two_point_closed_trace

    series = _open(fp)
    try:
        first = str(tmp_path / "first.jser")
        series.saveJser(save_fp=first)
    finally:
        series.close()

    series = _open(first)
    try:
        second = str(tmp_path / "second.jser")
        series.saveJser(save_fp=second)
    finally:
        series.close()

    assert _sha(first) == _sha(second)
