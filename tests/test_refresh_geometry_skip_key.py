"""The section file is not a sound skip key for ``SeriesData.refresh()``.

``benchmarks/REPORT.md`` §5.3 carried a proposal, inherited by the backlog, to
skip geometry in ``SeriesData.refresh()`` for sections whose file is unchanged,
keyed on mtime and size. It is withdrawn, and these tests are why: the geometry
is not a function of the section file alone.

``TraceData`` maps a trace's points through ``section.tforms[alignment]``
(``series_data.py:148-159``), and *which* alignment that is comes from series
state -- ``series.alignment``, or the per-object override
``series.getAttr(name, "alignment")``. Change the alignment and every length,
area, centroid and radius changes while every section file on disk stays
byte-identical.

That is not an edge case. Three of the four production callers of ``refresh()``
fire only on an alignment change: ``state_manager.py:548-550`` (guarded by
``alignmentPreferencesChanged``, and commented "no sections modified"),
``objects.py:189`` (the per-object ``alignment`` setter), and
``field_widget_4_data.py:267-281`` (``changeAlignment``, via
``manager.py:184``). The fourth, ``series.py:204``, runs against an empty
``self.data`` at open. So a file-keyed skip is wrong on every alignment path.

``manager.py:184`` is a shared site rather than an alignment site: six call
sites reach it with ``refresh_data=True`` and only ``changeAlignment`` is an
alignment change. Series magnification (``field_widget_4_data.py:492``) rewrites
every section file, so the key would be correct on that one.

Measured on the ``rhhks276`` corpus, an alignment switch modifies **0 of 276**
section files and changes **94.6%** of trace geometry; the key would have
falsely skipped **272** sections. Those are ledger rows
``RH276.refresh.falseskip`` and ``RH276.refresh.stalerows``.

These tests pin the property rather than the numbers, so that if anyone lands a
file-keyed skip the suite says so instead of the user finding stale quantities
in the object list.
"""

import os

import pytest

from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.transform import Transform


ALT = "alt-alignment"


def _file_keys(series):
    """(mtime_ns, size) per section number -- the proposed skip key."""
    return {
        snum: (
            os.stat(os.path.join(series.hidden_dir, fname)).st_mtime_ns,
            os.stat(os.path.join(series.hidden_dir, fname)).st_size,
        )
        for snum, fname in series.sections.items()
    }


def _geometry(series):
    """(object, section, index) -> the quantities the tables show."""
    out = {}
    for name, obj_data in series.data["objects"].items():
        for snum, trace_datas in obj_data.traces.items():
            for td in trace_datas:
                out[(name, snum, td.index)] = (
                    round(td.length, 9),
                    round(td.area, 9),
                    round(td.centroid[0], 9),
                    round(td.centroid[1], 9),
                    round(td.radius, 9),
                )
    return out


def _add_alternate_alignment(series, name=ALT):
    """Give every section a second, non-identity alignment, distinct per section.

    Distinct per section is deliberate: a uniform transform could not tell a
    correct recomputation from one that applied section 3's transform to
    section 7.
    """
    for i, snum in enumerate(sorted(series.sections)):
        section = series.loadSection(snum)
        section.tforms[name] = Transform([1, 0, 2.5 + i, 0, 1, -1.25 - i])
        section.save()
    series.save()


@pytest.fixture
def series_with_two_alignments(series_jser):
    series = Series.openJser(str(series_jser))
    _add_alternate_alignment(series)
    series.data.refresh()
    yield series
    series.close()


def test_alignment_change_rewrites_no_section_file(series_with_two_alignments):
    """The premise: switching alignment touches nothing on disk."""
    series = series_with_two_alignments
    before = _file_keys(series)

    series.alignment = ALT
    series.data.refresh()

    after = _file_keys(series)
    changed = [snum for snum in before if before[snum] != after.get(snum)]

    assert changed == [], (
        "switching series.alignment rewrote section files, which this suite "
        f"does not expect: {changed}"
    )


def test_alignment_change_moves_geometry_though_no_file_moved(
    series_with_two_alignments,
):
    """The consequence: the quantities change anyway.

    This is the whole objection in one assertion. If both of these hold at once
    -- no file changed, geometry changed -- then (mtime, size) cannot gate the
    geometry rebuild.
    """
    series = series_with_two_alignments
    keys_before, geom_before = _file_keys(series), _geometry(series)

    series.alignment = ALT
    series.data.refresh()

    keys_after, geom_after = _file_keys(series), _geometry(series)

    assert keys_before == keys_after, "expected no section file to change"

    shared = set(geom_before) & set(geom_after)
    assert shared, "fixture produced no comparable trace rows"

    moved = [k for k in shared if geom_before[k] != geom_after[k]]
    assert moved, (
        "no trace geometry changed when the alignment changed. Either the "
        "fixture's alternate alignment is not distinct from the current one, "
        "or refresh() has stopped recomputing geometry -- which is exactly the "
        "regression this module exists to catch."
    )


def test_per_object_alignment_override_also_moves_geometry(
    series_with_two_alignments,
):
    """The same hole, reached through the per-object override.

    ``Objects.alignment``'s setter calls ``series.data.refresh()`` directly
    (``objects.py:189``). It changes one object's resolved transform and writes
    no file at all, so a file-keyed skip would serve that object's old numbers
    forever.
    """
    series = series_with_two_alignments
    geom_before = _geometry(series)
    keys_before = _file_keys(series)

    name = next(
        (n for n, od in series.data["objects"].items() if od.traces), None
    )
    assert name is not None, "fixture has no object with traces"

    series.setAttr(name, "alignment", ALT)
    series.data.refresh()

    assert _file_keys(series) == keys_before, "expected no section file to change"

    geom_after = _geometry(series)
    shared = {k for k in set(geom_before) & set(geom_after) if k[0] == name}
    assert shared, f"object {name!r} produced no comparable rows"

    moved = [k for k in shared if geom_before[k] != geom_after[k]]
    assert moved, (
        f"pinning object {name!r} to alignment {ALT!r} changed none of its "
        "geometry, so the per-object override is not being honored"
    )


def test_reorder_preserves_mtime_and_size_across_a_renumber():
    """The second hole, independent of alignment.

    ``Series.reorderSections`` ``os.rename``s the section files
    (``series.py:3239-3252``). Rename preserves mtime and size exactly, so a
    file that is now section N but was section M carries M's key. A skip keyed
    by section number would treat the renumbered section as unchanged and serve
    another section's geometry under its number.

    Asserted on the filesystem directly, because it is a property of rename and
    not of this codebase -- which is the point: no amount of care in
    ``refresh()`` can make the key see a renumbering.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "a"), os.path.join(d, "b")
        with open(a, "w") as fh:
            fh.write("x" * 64)
        before = os.stat(a)

        os.rename(a, b)
        after = os.stat(b)

        assert (after.st_mtime_ns, after.st_size) == (
            before.st_mtime_ns,
            before.st_size,
        ), "rename changed mtime or size, which would rescue the file-keyed skip"
