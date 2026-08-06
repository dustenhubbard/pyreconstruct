"""S1: one `TraceIDIssuer` per series, ids DERIVED at load for file rows.

Before this slice, nothing in the shipped application ever constructed a
`TraceIDIssuer`: `Section._rebuildColumnarStore` took its issuer from the
OUTGOING store, the first build has no outgoing store, and so the chain was
never seeded -- every trace in every session carried no id at all. These tests
pin the wiring that closes that gap: `Series` owns the issuer, `Section`
derives an id per stored row at load (`tid-v1`, a function of the row's own
content), and the derived ids reach the columnar store as `carried_ids`.

Every test in this module fails on the pre-slice build (`getID` comes back
`None` for every row), which is the revert-and-fail probe: stash the
`PyReconstruct/` changes and this whole file goes red.

Derived, NOT issued-at-random, and the distinction carries the whole slice:
two independent opens of one file must agree on every id with no save between
(`test_two_independent_processes_agree_on_every_id`), because a random id
minted by a load is the failure `Flag.deriveID`'s docstring records in first
person.

No byte of any `.jser` changes. That is compared rather than asserted, outside
this module, by saving the fixture series on the pre-slice and post-slice
builds and hashing every byte written (the PR carries the hashes); in here,
`test_a_full_open_save_cycle_still_saves` keeps the save path exercised.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from PyReconstruct.modules.datatypes.trace_id import TRACE_ID_LENGTH

from conftest import SERIES_FIXTURE


def _idsBySectionContour(series):
    """`{(section, contour, index within contour): id}` for a whole series.

    Read back through the store's own per-contour index, the same join
    `Section._rebuildColumnarStore` builds its row map from.
    """
    ids = {}
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        assert section._columns is not None, (
            f"section {snum} was built without a store, so there is nothing "
            "to read ids from"
        )
        for name in sorted(section.contours, key=str):
            rows = section._columns.rowsForContour(name)
            for index, row in enumerate(rows):
                ids[(snum, name, index)] = section._columns.getID(row)
    return ids


def test_every_loaded_trace_has_a_derived_id(real_series):
    """Done criterion 1: every trace of every section, non-None, 11 chars."""
    ids = _idsBySectionContour(real_series)
    assert ids, "the fixture series produced no traces, so this proves nothing"
    missing = {key for key, value in ids.items() if value is None}
    assert not missing, (
        f"{len(missing)} of {len(ids)} traces came out of a load with no id: "
        f"{sorted(missing)}"
    )
    malformed = {
        key: value for key, value in ids.items()
        if len(value) != TRACE_ID_LENGTH
    }
    assert not malformed, f"ids of the wrong width: {malformed}"


def test_ids_are_unique_across_the_whole_series(real_series):
    """Done criterion 3: series-global uniqueness, not per section.

    The issuer's `taken` set is the series', so a derived id on section 2
    cannot collide with one on section 0 -- `deriveForSection` salt-bumps past
    it instead.
    """
    ids = _idsBySectionContour(real_series)
    values = list(ids.values())
    assert len(set(values)) == len(values), (
        "two traces in the series share an id"
    )
    assert real_series.trace_id_issuer.collisions == ()


def test_the_series_owns_one_issuer_and_every_section_store_carries_it(
    real_series,
):
    """The wiring itself: `Series` grows the issuer, sections take it.

    Pre-slice, `Series` had no `trace_id_issuer` attribute and every section's
    store had `id_issuer is None` -- the never-seeded chain the spec's finding
    3 describes.
    """
    issuer = real_series.trace_id_issuer
    assert issuer is not None
    for snum in sorted(real_series.sections):
        section = real_series.loadSection(snum)
        assert section._columns.id_issuer is issuer, (
            f"section {snum}'s store carries "
            f"{section._columns.id_issuer!r}, not the series' issuer"
        )


def test_reloading_a_section_does_not_move_or_leak_ids(real_series):
    """`loadSection` builds a fresh `Section` every call; ids must not care.

    The trap this pins: the first load registers every derived id in the
    issuer's taken-set, so a NAIVE second derivation of the byte-identical
    content finds each id spoken for, salt-bumps past it, and hands every
    trace a different id -- a birth certificate reissued by a scroll -- while
    the taken-set grows by a section's worth of orphans per load. The issuer
    therefore answers a repeated derivation from its own record
    (`TraceIDIssuer.deriveForSection`), and this test is the pin on that.
    """
    first = _idsBySectionContour(real_series)
    taken_after_first = len(real_series.trace_id_issuer.taken)

    for _ in range(3):
        again = _idsBySectionContour(real_series)
        assert again == first, (
            "reloading the sections moved ids for unchanged content"
        )
    assert len(real_series.trace_id_issuer.taken) == taken_after_first, (
        "reloading the sections leaked ids into the issuer's taken-set"
    )


def test_a_session_created_trace_falls_through_to_issue(real_series):
    """A trace born in the session gets an opaque issued id, not a derived one.

    `Section.addTrace` reaches `appendRow` with no `trace_id`, which asks the
    injected issuer for a fresh one -- the same arm as before the slice, now
    with an issuer actually present to answer.
    """
    snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    existing = {
        section._columns.getID(row)
        for name in section.contours
        for row in section._columns.rowsForContour(name)
    }

    from PyReconstruct.modules.datatypes import Trace
    newcomer = Trace("newcomer", [120, 30, 40], closed=True)
    newcomer.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    section.addTrace(newcomer, log_event=False)

    row = section._column_rows[newcomer]
    issued = section._columns.getID(row)
    assert issued is not None and len(issued) == TRACE_ID_LENGTH
    assert issued not in existing, (
        "the new trace was handed an id a loaded trace already holds"
    )
    assert issued in real_series.trace_id_issuer.taken


def test_two_independent_processes_agree_on_every_id(series_jser, tmp_path):
    """Done criterion 2, measured across real process boundaries.

    Two copies of the fixture, two fresh interpreters, one open each, no save
    anywhere: every trace's id must come out identical, because `tid-v1`
    derives from the stored row's own content and nothing else. This is the
    property a random-at-load id cannot have, and it is the whole point of
    deriving.
    """
    script = tmp_path / "collect_ids.py"
    script.write_text(
        "import json, os, sys\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        "from PyReconstruct.modules.datatypes import Series\n"
        "series = Series.openJser(sys.argv[1])\n"
        "ids = {}\n"
        "for snum in sorted(series.sections):\n"
        "    section = series.loadSection(snum)\n"
        "    for name in sorted(section.contours, key=str):\n"
        "        rows = section._columns.rowsForContour(name)\n"
        "        for index, row in enumerate(rows):\n"
        "            key = f'{snum}|{name}|{index}'\n"
        "            ids[key] = section._columns.getID(row)\n"
        "with open(sys.argv[2], 'w') as f:\n"
        "    json.dump(ids, f, sort_keys=True)\n"
        "series.close()\n"
    )

    results = []
    for process in ("a", "b"):
        workdir = tmp_path / process
        workdir.mkdir()
        jser = workdir / "series.jser"
        shutil.copy(series_jser, jser)
        out = workdir / "ids.json"
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        subprocess.run(
            [sys.executable, str(script), str(jser), str(out)],
            check=True, env=env, capture_output=True,
        )
        results.append(json.loads(out.read_text()))

    assert results[0], "the subprocesses collected no traces"
    assert results[0] == results[1], (
        "two independent opens of the same file disagreed on ids -- the ids "
        "are not derived from content"
    )
    assert all(
        value is not None and len(value) == TRACE_ID_LENGTH
        for value in results[0].values()
    )


def test_the_hidden_directory_fast_path_seeds_the_issuer_too(series_jser):
    """The spec's named design residue, done criterion 6.

    `openJser` has two entry paths: the full unpack, and a fast path that
    finds an existing hidden directory and returns a `Series` WITHOUT running
    `Section.updateJSON` at the `openJser` level. Both construct the `Series`
    through `Series.__init__`, which is where the issuer now lives -- and
    `Section.__init__` runs `updateJSON` itself on whatever it reads from the
    hidden directory, so the derivation input is normalized identically on
    both paths. Asserted rather than reasoned: the ids from a fast-path open
    equal the ids from the full unpack.
    """
    from PyReconstruct.modules.datatypes import Series

    slow = Series.openJser(str(series_jser))
    slow_ids = _idsBySectionContour(slow)
    assert slow_ids and all(v is not None for v in slow_ids.values())

    # The hidden directory now exists, so a second open takes the fast path.
    fast = Series.openJser(str(series_jser))
    assert fast.leave_open, (
        "the second open did not take the hidden-directory fast path, so "
        "this test is not testing what its name says"
    )
    assert fast.trace_id_issuer is not None
    assert fast.trace_id_issuer is not slow.trace_id_issuer, (
        "the two opens shared an issuer, so agreement below would be vacuous"
    )
    fast_ids = _idsBySectionContour(fast)
    assert fast_ids == slow_ids, (
        "the fast path derived different ids than the full unpack"
    )

    fast.leave_open = False
    fast.close()


def test_a_full_open_save_cycle_still_saves(series_jser, tmp_path):
    """The load-time derivation must not disturb the save path.

    The byte-level half of this claim (a save is byte-identical to the
    pre-slice build) is compared across builds outside the suite; what a test
    on one build can hold is that the cycle completes and that saving does not
    move a single id -- `test_a_save_does_not_re_identify_the_traces_it_saves`
    pins the per-section version of the same property.
    """
    from PyReconstruct.modules.datatypes import Series

    series = Series.openJser(str(series_jser))
    before = _idsBySectionContour(series)

    # Sections were loaded transiently above; save through fresh loads, which
    # is what MainWindow.saveAllData does per section.
    for snum in sorted(series.sections):
        series.loadSection(snum).save(update_series_data=False)
    out = tmp_path / "resaved.jser"
    series.saveJser(save_fp=str(out))
    assert out.exists() and out.stat().st_size > 0

    after = _idsBySectionContour(series)
    assert after == before, "a save moved ids"
    series.close()


def test_fixture_layout_guard():
    """The module above assumes the checked-in fixture; say so if it moves."""
    if not SERIES_FIXTURE.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"series fixture missing: {SERIES_FIXTURE}")
