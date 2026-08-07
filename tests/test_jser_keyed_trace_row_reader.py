"""S3: the reader understands a keyed trace row AND ADOPTS ITS ID.

S3 of `specs/phase1-keyed-row-v1-slices-2026-08-06.md`. The writer is untouched:
nothing here makes this build emit a row shape it did not emit before.

WHAT THIS SLICE IS ACTUALLY ABOUT, AND IT IS NOT DECODING
---------------------------------------------------------
Decoding a keyed row was never the hard half. `Section.updateJSON` has carried a
`if type(trace) is dict:` branch since before `v1.19.0`, and the repository's own
`dev/assets/checker/files/class_series.jser` fixture is written entirely in the
keyed shape -- so "a keyed row loads" has been true for years and proves nothing
about this slice. The half that did not exist is the `id`: a keyed row may carry
the trace's persisted identity, and every reader in the tree dropped it.

Every test that matters here therefore asserts the trace's id is **the one the
file named**, not merely that the trace loaded. That distinction is the whole
slice, because S1 DERIVES an id from each row's own content: a reader that
throws the stored id away silently re-derives a plausible-looking id for every
row and looks completely healthy. The ids these tests write into their fixtures
are deliberately arbitrary strings that no derivation would ever produce, so a
build that decodes without adopting fails on the value rather than on the shape.

WHERE THE ID WAS MEASURED TO DIE
--------------------------------
Not in `Section.__init__`. `Series.openJser` runs `Section.updateJSON` over the
unpacked document and writes the RESULT into the hidden working directory; the
object model then reads that copy and never the `.jser`. The conversion to the
positional shape therefore destroyed the id one whole layer above the load path,
so no amount of adoption in `Section.__init__` could have reached it. That is
what `Section.reattachTraceIDs` exists for and what
`test_the_unpack_preserves_the_id_into_the_hidden_working_copy` pins.

THE COLLISION POLICY IS TESTED, NOT ASSUMED
-------------------------------------------
`trace_id.py` records it: at load, detect and **report by name**, never silently
adopt and never silently reissue. Two sections claiming one id is a merge losing
an edit, so the second claim is refused, recorded in `issuer.collisions`, and the
trace gets a derived id instead of the one it asked for.
"""
import itertools
import json
import os
import shutil

import pytest

from PyReconstruct.modules.constants import keyed_trace_row_to_positional
from PyReconstruct.modules.datatypes import Section, Series
from PyReconstruct.modules.datatypes.trace import normalizeObjectName
from PyReconstruct.modules.datatypes.trace_id import TRACE_ID_LENGTH

from conftest import SERIES_FIXTURE


# Ids that no derivation would produce, so a test that passes proves ADOPTION
# rather than decoding. Valid base62 and exactly TRACE_ID_LENGTH wide, because
# `TraceIDIssuer.adopt` rejects a malformed id and that is a different test.
def _tid(k : int) -> str:
    """A deterministic, obviously-hand-written id of the right width."""
    body = f"zzTEST{k:05d}"
    assert len(body) == TRACE_ID_LENGTH, body
    return body


def _idFactory(start : int = 0):
    """A source of distinct ids.

    Distinct SERIES-WIDE, not per contour or per section, which is the property
    the first draft of these tests got wrong: ids built from the row index alone
    repeat on every section, and the reader then correctly reported hundreds of
    duplicate claims. Uniqueness is a series-global rule here for the same
    reason it is one in `TraceIDIssuer`.
    """
    counter = itertools.count(start)
    return lambda: _tid(next(counter))


def _sectionKeys(doc : dict) -> dict:
    """`{section number: document key}` for an on-disk `.jser`.

    A `.jser` is a flat map keyed `"<series name>.<ext>"`, where `<ext>` is the
    section number for a section and `"ser"` for the series.
    """
    out = {}
    for key in doc:
        ext = key.rsplit(".", 1)[-1]
        if ext.isnumeric():
            out[int(ext)] = key
    return out


def _positionalRows(rows : list) -> list:
    """Normalize a contour's rows to the 8-element positional shape.

    The shipped fixture is written in the LEGACY KEYED shape (`mode`, plus a
    `history` key), which is convenient for the reader and useless for these
    tests: a test that starts from a keyed row cannot show that keying one
    changed anything. Everything here starts from positional rows and keys the
    ones it means to key.
    """
    return [
        keyed_trace_row_to_positional(row) if isinstance(row, dict) else list(row)
        for row in rows
    ]


def _survivesScreening(row : list) -> bool:
    """Whether `Section.updateJSON` would keep this row.

    It drops any row with fewer than two points. That matters to these tests for
    a reason that has nothing to do with ids: the shipped fixture contains such
    rows, they are removed during the migration, and every row after one in the
    same contour therefore MOVES DOWN AN INDEX between the file and the working
    copy. A test that planted an id at source index 0 and looked for it at
    working index 0 would then read a different trace's id and report a bug that
    is not there. The fixtures below are screened up front so a source index and
    a working index are the same number, and index skew is tested on its own
    (`test_updateJSON_reports_indices_after_its_own_screening`) where it can be
    controlled.
    """
    return len(row[0]) >= 2


def _keyRow(row : list, trace_id=None, fill_mode_key="fill_mode") -> dict:
    """The keyed form of one positional row, optionally carrying an id."""
    keyed = {
        "x": row[0],
        "y": row[1],
        "color": row[2],
        "closed": row[3],
        "negative": row[4],
        "hidden": row[5],
        fill_mode_key: row[6],
        "tags": row[7],
    }
    if trace_id is not None:
        keyed["id"] = trace_id
    return keyed


def _buildJser(tmp_path, rewrite, name="keyed.jser", allow_duplicates=False):
    """Write a `.jser` built from the fixture, with `rewrite` applied.

        Params:
            rewrite (callable): `(section number, contour name, positional rows)
                -> rows`. Returning the rows unchanged leaves the contour
                positional; returning keyed dicts keys it.
        Returns:
            (str, dict) the path written, and
                `{(section, contour, index): id}` for every id planted
    """
    if not SERIES_FIXTURE.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"series fixture missing: {SERIES_FIXTURE}")
    with open(SERIES_FIXTURE) as f:
        doc = json.load(f)

    planted = {}
    for snum, key in sorted(_sectionKeys(doc).items()):
        sdata = doc[key]
        if not isinstance(sdata, dict) or not isinstance(sdata.get("contours"), dict):
            continue
        for cname in sorted(sdata["contours"]):
            if cname != normalizeObjectName(cname):
                # `updateJSON` renames such a contour and MERGES its rows onto
                # the tail of the normalized name's, which moves indices for the
                # same reason screening does. Excluded here and covered on its
                # own below.
                del sdata["contours"][cname]
                continue
            rows = [
                row for row in _positionalRows(sdata["contours"][cname])
                if _survivesScreening(row)
            ]
            if not rows:
                del sdata["contours"][cname]
                continue
            new_rows = rewrite(snum, cname, rows)
            sdata["contours"][cname] = new_rows
            for i, row in enumerate(new_rows):
                if isinstance(row, dict) and "id" in row:
                    assert allow_duplicates or row["id"] not in planted.values(), (
                        f"the fixture planted {row['id']!r} twice; ids must be "
                        "unique unless a test is deliberately clashing them"
                    )
                    planted[(snum, cname, i)] = row["id"]

    fp = str(tmp_path / name)
    with open(fp, "w") as f:
        json.dump(doc, f)
    return fp, planted


def _openSeries(fp):
    series = Series.openJser(fp)
    assert series is not None, "the series did not open at all"
    return series


def _storeIDs(series) -> dict:
    """`{(section, contour, index): id}` read back through the columnar store.

    Through `SectionColumns.getID`, which is the done criterion's own endpoint:
    the id has to survive the file, the unpack, the working copy, the object
    model and the store build, and this reads it at the far end of all five.
    """
    ids = {}
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        assert section._columns is not None, f"section {snum} built with no store"
        for cname in sorted(section.contours, key=str):
            for i, row in enumerate(section._columns.rowsForContour(cname)):
                ids[(snum, cname, i)] = section._columns.getID(row)
    return ids


# ---------------------------------------------------------------------------
# the done criteria
# ---------------------------------------------------------------------------


def test_a_keyed_jser_opens_with_every_id_preserved_to_getID(tmp_path):
    """Done criterion 1, and the one that carries the slice.

    Every row keyed, every row carrying a hand-written id, read back at
    `SectionColumns.getID`. The ids are arbitrary strings, so a build that
    decodes the keyed row and drops the id passes every shape assertion here and
    still fails: it returns S1's derived id, which is not any of these.
    """
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        return [_keyRow(row, nextID()) for row in rows]

    fp, planted = _buildJser(tmp_path, rewrite)
    assert planted, "the fixture produced no rows, so this proves nothing"

    series = _openSeries(fp)
    try:
        ids = _storeIDs(series)
        assert ids, "no traces reached the store"
        missing = {key for key in ids if key not in planted}
        assert not missing, (
            f"{len(missing)} traces loaded that no planted id accounts for: "
            f"{sorted(missing)[:5]}"
        )
        wrong = {
            key: (ids[key], planted[key])
            for key in ids if ids[key] != planted[key]
        }
        assert not wrong, (
            f"{len(wrong)} of {len(ids)} traces came back with an id that is "
            f"NOT the one the file named -- got/expected: "
            f"{dict(list(wrong.items())[:5])}. An id that is 11 characters and "
            "simply wrong is the derived id: the row was decoded and its stored "
            "id thrown away."
        )
        assert series.trace_id_issuer.collisions == ()
        assert series.trace_id_issuer.malformed == ()
    finally:
        series.close()


def test_a_mixed_section_loads_every_shape_correctly(tmp_path):
    """Done criterion 2: four row shapes in one section, all four correct.

    Keyed+id, keyed without an id, positional, and -- the case the spec names
    but the obvious implementation misses -- the two spellings of the fill mode
    side by side in one contour. A row with no id must still get one (derived,
    per S1), and it must not accidentally receive a neighbour's.
    """
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        out = []
        for i, row in enumerate(rows):
            shape = i % 4
            if shape == 0:
                out.append(_keyRow(row, nextID()))
            elif shape == 1:
                out.append(_keyRow(row, None))                    # keyed, no id
            elif shape == 2:
                out.append(list(row))                             # positional
            else:
                out.append(_keyRow(                               # legacy spelling
                    row, nextID(), fill_mode_key="mode"
                ))
        return out

    fp, planted = _buildJser(tmp_path, rewrite)
    assert planted, "no ids were planted"

    series = _openSeries(fp)
    try:
        ids = _storeIDs(series)
        for key, trace_id in ids.items():
            assert trace_id is not None, f"{key} loaded with no id at all"
            assert len(trace_id) == TRACE_ID_LENGTH, (key, trace_id)
            if key in planted:
                assert trace_id == planted[key], (
                    f"{key} carried a stored id {planted[key]!r} and came back "
                    f"{trace_id!r}"
                )
            else:
                assert trace_id not in planted.values(), (
                    f"{key} carried NO stored id but came back holding "
                    f"{trace_id!r}, which belongs to another row -- the "
                    "contour/index join between the lifted ids and the traces "
                    "has skewed"
                )
        assert len(set(ids.values())) == len(ids), "two traces share an id"
        assert series.trace_id_issuer.collisions == ()
    finally:
        series.close()


def test_both_fill_mode_spellings_decode_to_the_same_trace(tmp_path):
    """`mode` and `fill_mode` are both accepted, and mean the same thing.

    Read tolerance is not a preference here, it is the 2026-07-27 non-negotiable
    ("the READER must keep reading every past shape forever"): `mode` is what
    every shipped build since `v1.19.0` writes, `fill_mode` is what the model
    and `docs/JSER_FORMAT.md` call the field. This slice takes no position on
    which one a writer should emit -- that is Q1 -- it only refuses to lose
    either.
    """
    modes = {}
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        out = []
        for i, row in enumerate(rows):
            spelling = "mode" if i % 2 else "fill_mode"
            modes[(snum, cname, i)] = list(row[6])
            out.append(_keyRow(row, nextID(), fill_mode_key=spelling))
        return out

    fp, _ = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        checked = 0
        for snum in sorted(series.sections):
            section = series.loadSection(snum)
            for cname in sorted(section.contours, key=str):
                for i, trace in enumerate(section.contours[cname].getTraces()):
                    expected = modes.get((snum, cname, i))
                    if expected is None:
                        continue
                    assert list(trace.fill_mode) == expected, (
                        f"{(snum, cname, i)} decoded the fill mode as "
                        f"{trace.fill_mode!r}, expected {expected!r}"
                    )
                    checked += 1
        assert checked, "no traces were checked"
    finally:
        series.close()


def test_a_duplicate_id_across_two_sections_is_reported_by_name(tmp_path):
    """Done criterion 4: detected and reported, never silently adopted.

    One id planted on a row in two different sections. The policy
    `trace_id.py` records is refuse-and-report: the first claim wins, the second
    is recorded in `collisions` AGAINST THE OBJECT NAME so a user can be told
    which object to look at, and the losing trace falls back to a derived id
    rather than being handed an identity another trace already holds.

    Silently adopting both is how a merge loses an edit, which is the failure
    the whole id design exists to prevent.
    """
    duplicate = _tid(4242)
    victims = []

    def rewrite(snum, cname, rows):
        out = []
        for i, row in enumerate(rows):
            if i == 0 and len(victims) < 2 and rows:
                victims.append((snum, cname, i))
                out.append(_keyRow(row, duplicate))
            else:
                out.append(list(row))
        return out

    fp, _ = _buildJser(tmp_path, rewrite, allow_duplicates=True)
    assert len(victims) == 2, f"needed two sections to clash, got {victims}"
    assert victims[0][0] != victims[1][0], (
        f"both planted rows landed on one section: {victims}"
    )

    series = _openSeries(fp)
    try:
        ids = _storeIDs(series)
        holders = [key for key, value in ids.items() if value == duplicate]
        assert len(holders) == 1, (
            f"{len(holders)} traces came back holding the duplicated id "
            f"{duplicate!r}; exactly one may. Two means it was silently adopted "
            "twice, which is the failure this policy exists to prevent."
        )

        collisions = series.trace_id_issuer.collisions
        assert collisions, (
            "the clash was resolved without a word: `collisions` is empty. "
            "Detect and REPORT is the recorded policy; a silent resolution is "
            "the flag failure repeating."
        )
        clashed = [entry for entry in collisions if entry[0] == duplicate]
        assert clashed, f"{duplicate!r} is not among {collisions}"
        names = {entry[1] for entry in clashed}
        reported_on = {key[1] for key in victims}
        assert names & reported_on, (
            f"the clash was reported under {names}, none of which is one of the "
            f"objects that claimed it ({reported_on}). 'By name' is the whole "
            "point: a report nobody can act on is not a report."
        )

        # The loser still loaded, and with a real identity of its own.
        loser = next(key for key in victims if key not in holders)
        assert ids[loser] is not None and len(ids[loser]) == TRACE_ID_LENGTH, (
            f"the trace that lost the clash came back with {ids[loser]!r}; it "
            "must fall back to a derived id, not to nothing"
        )
    finally:
        series.close()


def test_the_undo_baseline_reads_a_keyed_section_file(tmp_path):
    """Done criterion 3, and mechanism 5: the one silent trap in the read path.

    `SectionStates.initialize` `shutil.copyfile`s the section file as the undo
    baseline and `FieldState.getContours` parses that copy by calling
    `Trace.fromList` per row WITHOUT `Section.updateJSON`. Handed a keyed row
    `fromList` does not raise -- `len(dict)` is the key count and iterating a
    dict yields its keys -- so a 9-key row takes the first key string as the
    NAME and unpacks the rest into the fields. The baseline became a `Trace`
    named 'x' whose points were pairs of key names, and the first undo restored
    that over the user's real traces.

    Nothing about that failure is hypothetical any more: the section files in
    the hidden working directory really are keyed now, for any series opened
    from a keyed `.jser`, because that is what preserves the ids. So this path
    is reached by a plain open, not by a contrived fixture.
    """
    from PyReconstruct.modules.backend.func.state_manager import SectionStates

    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        return [_keyRow(row, nextID()) for row in rows]

    fp, _ = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        snum = next(
            n for n in sorted(series.sections)
            if series.loadSection(n).contours
        )
        section = series.loadSection(snum)

        # The working copy really is keyed -- otherwise this test would be
        # exercising the positional path and proving nothing.
        with open(section.filepath) as f:
            on_disk = json.load(f)
        keyed_rows = [
            row
            for rows in on_disk["contours"].values()
            for row in rows
            if isinstance(row, dict)
        ]
        assert keyed_rows, (
            "the section file the baseline is copied from is not keyed, so "
            "this test cannot see the bug it exists for"
        )

        model = {
            cname: [
                (tuple(trace.points), trace.name)
                for trace in section.contours[cname].getTraces()
            ]
            for cname in sorted(section.contours, key=str)
        }

        states = SectionStates(section, series)   # copies the keyed file as .s0
        restored = states.current_state.getContours()

        assert set(restored) == set(model), (
            f"the baseline restored contours {sorted(set(restored))[:5]} "
            f"against a model holding {sorted(set(model))[:5]}. A baseline "
            "holding a contour named 'x' is the keyed row being unpacked as "
            "its own key strings."
        )
        for cname, expected in model.items():
            got = [
                (tuple(trace.points), trace.name)
                for trace in restored[cname].getTraces()
            ]
            assert got == expected, (
                f"the undo baseline for {cname!r} does not match the object "
                f"model it was copied from"
            )
    finally:
        series.close()


# ---------------------------------------------------------------------------
# the layer the brief did not name: the unpack
# ---------------------------------------------------------------------------


def test_the_unpack_preserves_the_id_into_the_hidden_working_copy(tmp_path):
    """`Series.openJser` must not write the id out of existence.

    This is the hole that made every other done criterion unreachable, and it
    sits ABOVE the load path rather than in it. `openJser` runs
    `Section.updateJSON` over the unpacked document -- which converts a keyed
    row to the positional shape -- and writes the RESULT into the hidden working
    directory. The object model reads that copy, never the `.jser`. So before
    `Section.reattachTraceIDs`, the id was decoded and discarded one statement
    later, and `Section.__init__` had nothing to adopt no matter how carefully
    it asked.

    Asserted on the bytes in the working directory rather than through the
    store, so that a regression here is reported where it happens.
    """
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        return [_keyRow(row, nextID()) for row in rows]

    fp, planted = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        seen = 0
        for snum in sorted(series.sections):
            path = os.path.join(series.getwdir(), series.sections[snum])
            with open(path) as f:
                sdata = json.load(f)
            for cname, rows in sdata["contours"].items():
                for i, row in enumerate(rows):
                    expected = planted.get((snum, cname, i))
                    if expected is None:
                        continue
                    assert isinstance(row, dict), (
                        f"the working copy of section {snum} contour {cname!r} "
                        f"row {i} is positional, so its id is already gone"
                    )
                    assert row.get("id") == expected, (
                        f"working copy row {(snum, cname, i)} carries id "
                        f"{row.get('id')!r}, the file named {expected!r}"
                    )
                    seen += 1
        assert seen, "no id-bearing row survived the unpack at all"
    finally:
        series.close()


def test_the_working_copy_keeps_the_spelling_the_file_used(tmp_path):
    """Re-attaching an id must not silently re-spell the fill mode.

    The working copy is what `saveJser` copies verbatim into a `.jser` for a
    section nobody touched, so a spelling chosen here becomes a spelling in the
    user's file. A reader slice is entitled to preserve what it read and not to
    pick: a row that arrived spelling `mode` is written back spelling `mode`, so
    the set of builds that can open the section is exactly what it was. Which
    spelling a WRITER emits is Q1 and is decided elsewhere.
    """
    spellings = {}
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        out = []
        for i, row in enumerate(rows):
            spelling = "mode" if i % 2 else "fill_mode"
            spellings[(snum, cname, i)] = spelling
            out.append(_keyRow(row, nextID(), fill_mode_key=spelling))
        return out

    fp, _ = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        checked = 0
        for snum in sorted(series.sections):
            path = os.path.join(series.getwdir(), series.sections[snum])
            with open(path) as f:
                sdata = json.load(f)
            for cname, rows in sdata["contours"].items():
                for i, row in enumerate(rows):
                    expected = spellings.get((snum, cname, i))
                    if expected is None or not isinstance(row, dict):
                        continue
                    assert expected in row, (
                        f"row {(snum, cname, i)} arrived spelling {expected!r} "
                        f"and was written back as {sorted(row)}"
                    )
                    other = "mode" if expected == "fill_mode" else "fill_mode"
                    assert other not in row, (
                        f"row {(snum, cname, i)} was re-spelled: it now carries "
                        f"both {expected!r} and {other!r}"
                    )
                    checked += 1
        assert checked, "nothing was checked"
    finally:
        series.close()


# ---------------------------------------------------------------------------
# the traps that only show up on the SECOND read
# ---------------------------------------------------------------------------


def test_reloading_a_section_does_not_report_it_as_clashing_with_itself(tmp_path):
    """`loadSection` builds a fresh `Section` every call. Adoption must be idempotent.

    There is no `Section` cache, so one section's rows are adopted again and
    again within a session. A naive `adopt` succeeds on the first pass, finds
    the id in `taken` on the second, and reports a collision against a trace
    that is merely being re-read -- and then hands it a DIFFERENT id, which is
    a birth certificate reissued by a scroll. `deriveForSection` documents
    exactly this trap for derivation; `adoptForSection` has to answer it too.
    """
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        return [_keyRow(row, nextID()) for row in rows]

    fp, planted = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        first = _storeIDs(series)
        assert series.trace_id_issuer.collisions == (), (
            "the first load already reported a clash"
        )
        second = _storeIDs(series)
        third = _storeIDs(series)

        assert series.trace_id_issuer.collisions == (), (
            "re-reading the same sections reported "
            f"{series.trace_id_issuer.collisions[:3]} -- each trace clashing "
            "with its own previous read"
        )
        assert first == second == third, (
            "the same rows produced different ids on a second or third load"
        )
        for key, value in first.items():
            if key in planted:
                assert value == planted[key], key
    finally:
        series.close()


def test_an_unreadable_id_costs_that_row_its_id_and_nothing_else(tmp_path):
    """A hand-edited id must not make a series impossible to open.

    `TraceIDIssuer.adopt` calls `decodeTraceID`, which rejects a malformed id
    loudly, and letting that reach the caller would mean one bad character in
    one row of one section turns the whole file into one nobody can open. A
    `.jser` is somebody's data; a wall at open is not survivable for them.

    So the row's claim is refused and recorded in `malformed`, the trace gets a
    derived id exactly as a row carrying no id would, every other row keeps the
    id it named, and the file opens. Refused and recorded -- never believed.
    """
    bad = "not-an-id"       # wrong width, and '-' is not in the alphabet
    targets = []

    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        out = []
        for i, row in enumerate(rows):
            if i == 0 and not targets:
                targets.append((snum, cname, i))
                out.append(_keyRow(row, bad))
            else:
                out.append(_keyRow(row, nextID()))
        return out

    fp, planted = _buildJser(tmp_path, rewrite)
    assert targets, "no row was given a malformed id"
    series = _openSeries(fp)
    try:
        ids = _storeIDs(series)
        victim = targets[0]
        assert ids[victim] is not None, "the row lost its trace, not just its id"
        assert ids[victim] != bad, "a malformed id was adopted"
        assert len(ids[victim]) == TRACE_ID_LENGTH, (
            f"the fallback id is {ids[victim]!r}, which is not a derived id"
        )

        malformed = series.trace_id_issuer.malformed
        assert any(entry[0] == bad for entry in malformed), (
            f"{bad!r} was dropped without being recorded: malformed={malformed}"
        )
        assert any(entry[1] == victim[1] for entry in malformed), (
            f"the malformed id was not reported under its object name: "
            f"{malformed}"
        )

        # every OTHER row still got exactly what its file said
        for key, expected in planted.items():
            if key == victim:
                continue
            assert ids[key] == expected, (
                f"{key} lost its id because a different row was malformed"
            )
    finally:
        series.close()


def test_a_row_with_no_id_still_derives_and_the_two_never_share(tmp_path):
    """Adoption must not poison derivation, in either direction.

    A row whose id is adopted is withheld from `deriveForSection`, deliberately:
    deriving for it as well would register a second identity in the issuer's
    `taken` set that no trace holds, and every later derivation on the series
    would salt past a phantom. The visible consequence to check is the simple
    one -- ids stay unique series-wide, and an adopted id is never also handed
    out as a derived one.
    """
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        # only the even rows assert an id
        return [
            _keyRow(row, nextID()) if i % 2 == 0 else list(row)
            for i, row in enumerate(rows)
        ]

    fp, planted = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        ids = _storeIDs(series)
        assert len(set(ids.values())) == len(ids), (
            "an id is held by two traces"
        )
        derived = {key: value for key, value in ids.items() if key not in planted}
        assert derived, "no row was left to derive for"
        assert not (set(derived.values()) & set(planted.values())), (
            "a derived id collided with an adopted one"
        )
        for key, expected in planted.items():
            assert ids[key] == expected, key
    finally:
        series.close()


# ---------------------------------------------------------------------------
# nothing changes for a file that carries no id, which is every file today
# ---------------------------------------------------------------------------


def test_a_file_with_no_stored_ids_is_untouched_by_any_of_this(tmp_path):
    """The stock fixture -- keyed rows, no `id` anywhere -- is unaffected.

    This is the whole installed base: the keyed shape has shipped since before
    `v1.19.0` and no build has ever written an `id` onto a row. Such a row must
    convert to the positional form in the working copy exactly as it always did,
    derive its id per S1, and report nothing.
    """
    destination = tmp_path / "stock.jser"
    shutil.copy(SERIES_FIXTURE, destination)

    series = _openSeries(str(destination))
    try:
        for snum in sorted(series.sections):
            path = os.path.join(series.getwdir(), series.sections[snum])
            with open(path) as f:
                sdata = json.load(f)
            for cname, rows in sdata["contours"].items():
                for i, row in enumerate(rows):
                    assert not isinstance(row, dict), (
                        f"working copy row {(snum, cname, i)} stayed keyed; a "
                        "row carrying no id must convert exactly as before"
                    )
        ids = _storeIDs(series)
        assert ids, "the fixture produced no traces"
        assert all(
            value is not None and len(value) == TRACE_ID_LENGTH
            for value in ids.values()
        ), "S1's derivation stopped covering rows that carry no stored id"
        assert series.trace_id_issuer.collisions == ()
        assert series.trace_id_issuer.malformed == ()
    finally:
        series.close()


def test_updateJSON_reports_indices_after_its_own_screening(tmp_path):
    """The lifted-id map must name the rows as they end up, not as they arrived.

    `updateJSON` drops defective rows, merges contours whose names normalize
    onto one another, and sorts the contour dict -- all AFTER the row loop that
    reads the ids. A map built as the rows were read would name a different
    trace, or no trace, by the time the caller used it, and the failure mode is
    the worst kind: every id present, every id on the wrong trace.
    """
    good = [[0.0, 1.0, 1.0], [0.0, 0.0, 1.0], [0, 0, 0], True, False, False,
            ["none", "none"], []]
    # `x` shorter than 2 points: `updateJSON` pops it as defective
    defective = [[0.0], [0.0], [0, 0, 0], True, False, False,
                 ["none", "none"], []]

    section_data = {
        "src": "x.tif",
        "brightness": 0,
        "contrast": 0,
        "mag": 0.01,
        "align_locked": True,
        "thickness": 0.05,
        "tforms": {"default": [1, 0, 0, 0, 1, 0]},
        "flags": [],
        "calgrid": False,
        "contours": {
            "  spaced  name  ": [
                _keyRow(defective, _tid(11)),
                _keyRow(good, _tid(12)),
            ],
            "plain": [_keyRow(good, _tid(13))],
        },
    }

    stored = {}
    Section.updateJSON(section_data, 0, stored_ids=stored)

    # the defective row is gone, so the survivor has moved to index 0 under the
    # NORMALIZED contour name
    assert _tid(11) not in [record.trace_id for record in stored.values()], (
        "a dropped row's id is still being reported, so it will be adopted "
        "onto whichever trace inherited its index"
    )
    by_id = {record.trace_id: key for key, record in stored.items()}
    assert set(by_id) == {_tid(12), _tid(13)}, by_id

    for trace_id, (cname, index) in by_id.items():
        rows = section_data["contours"][cname]
        assert index < len(rows), (
            f"{trace_id} was reported at {(cname, index)}, which is past the "
            f"end of a {len(rows)}-row contour"
        )
    assert by_id[_tid(12)][1] == 0, (
        f"{_tid(12)} is reported at index {by_id[_tid(12)][1]}; the defective "
        "row ahead of it was removed, so it is at 0 now"
    )


def test_an_adopted_row_does_not_also_burn_a_derived_id(tmp_path):
    """A row is identified once, by exactly one of the two mechanisms.

    `deriveForSection` is told to skip every row `adoptForSection` accepted. Not
    an optimization: without it every adopted row ALSO derives an id, which is
    registered in the issuer's `taken` set and recorded in its derivation map
    even though no trace holds it. The consequences are cumulative rather than
    immediately visible, which is why this is pinned rather than left to review
    -- the adopted id still wins, so nothing looks wrong:

    * `taken` grows to twice the trace count, and every later derivation on the
      series salt-bumps past values no trace holds;
    * the derivation record retains the full canonical JSON of each row it
      answered for, which `deriveForSection` measures at ~47 MiB on the
      125,218-row corpus. Deriving for rows that did not need it doubles the
      most expensive structure in the issuer.

    So: one identity per trace, and `taken` says exactly that.
    """
    nextID = _idFactory()

    def rewrite(snum, cname, rows):
        return [_keyRow(row, nextID()) for row in rows]

    fp, planted = _buildJser(tmp_path, rewrite)
    series = _openSeries(fp)
    try:
        ids = _storeIDs(series)
        assert ids, "no traces loaded"
        assert set(ids.values()) == set(planted.values()), (
            "the ids held by the traces are not the ids the file named"
        )

        taken = series.trace_id_issuer.taken
        assert set(ids.values()) <= taken, "an id in use is not registered"
        assert len(taken) == len(ids), (
            f"the issuer has {len(taken)} ids spoken for against {len(ids)} "
            f"traces, so {len(taken) - len(ids)} identities were minted for "
            "rows that already had one and are held by nothing. Every adopted "
            "row derived a second id it did not need."
        )
    finally:
        series.close()
