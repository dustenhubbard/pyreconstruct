"""The trace-id issuer, the base62 codec, and the frozen `tid-v1` derivation.

These tests are the pin on a decision that cannot be taken back. The derivation
in `datatypes/trace_id.py` is declared frozen: if it moves, every trace that
already carries a derived id acquires a different identity, in every series, with
no way to tell that it happened. So the golden values below are not
housekeeping.

**Updating a golden id in this file is a deliberate act.** It is correct only
when the version string moves with it (`tid-v1` -> `tid-v2`) and the old
derivation stays in the code for the ids already issued under it. A green suite
after editing a golden and leaving the version alone means the pin has been
disabled, not satisfied.

Nothing here touches a `.jser`, a `QSettings` domain, or Qt. The whole module is
the Qt-free core.
"""
import json

import pytest

from PyReconstruct.modules.datatypes.flag import possible_chars
from PyReconstruct.modules.datatypes.trace_id import (
    DERIVATION_MAX_SALT,
    TRACE_ID_ALPHABET,
    TRACE_ID_BITS,
    TRACE_ID_LENGTH,
    TRACE_ID_VERSION,
    TraceIDIssuer,
    decodeTraceID,
    deriveTraceID,
    encodeTraceID,
)

## The 8-field stored row shape, as `Trace.getList(include_name=False)` writes
## it: [x, y, color, closed, negative, hidden, fill_mode, tags]. Eight and not
## nine deliberately -- the rows that round-trip a section file are the
## name-less ones (`Section.getDict` passes include_name=False), and the
## derivation takes the contour name as a separate input rather than from the
## row.
ROW8 = [
    [1.25, 3.0, 5.0],
    [2.5, 4.0, 6.0],
    [255, 0, 0],
    True,
    False,
    False,
    ["none", "none"],
    ["a", "b"],
]


# --- the alphabet, and the drift it is allowed to have from Flag's ------------


def test_alphabet_is_the_same_character_set_flags_use():
    """The trace alphabet is a frozen copy of `flag.possible_chars`.

    A copy, not an import, because the derivation must not move when another
    module reorders a constant. This test is the price of that copy: it fails if
    either side changes, so the duplication is reported rather than silent.
    """
    assert TRACE_ID_ALPHABET == "".join(possible_chars)
    assert len(TRACE_ID_ALPHABET) == 62
    assert len(set(TRACE_ID_ALPHABET)) == 62


def test_width_is_the_narrowest_that_holds_the_chosen_bit_count():
    """11 base62 characters, because 62**11 > 2**64 > 62**10.

    The width decision is 64 random bits. Ten characters would not hold them and
    twelve would waste one, so the arithmetic that picked eleven is pinned here
    rather than left in a docstring.
    """
    assert TRACE_ID_BITS == 64
    assert 62 ** TRACE_ID_LENGTH > 2 ** TRACE_ID_BITS
    assert 62 ** (TRACE_ID_LENGTH - 1) < 2 ** TRACE_ID_BITS


# --- the codec ---------------------------------------------------------------


def test_encoding_is_least_significant_digit_first_like_flags():
    """GOLDEN. The digit order is part of the frozen encoding.

    `Flag.deriveID` emits least-significant-first, and matching it means a trace
    id and a flag id are read the same way. Reversing this would silently
    re-identify every derived trace.
    """
    assert encodeTraceID(0) == "A" * TRACE_ID_LENGTH
    assert encodeTraceID(1) == "B" + "A" * (TRACE_ID_LENGTH - 1)
    assert encodeTraceID(61) == "9" + "A" * (TRACE_ID_LENGTH - 1)
    assert encodeTraceID(62) == "AB" + "A" * (TRACE_ID_LENGTH - 2)


def test_encoding_is_fixed_width_and_round_trips():
    for n in (0, 1, 61, 62, 3843, 2 ** 32, 2 ** 63, 2 ** 64 - 1):
        encoded = encodeTraceID(n)
        assert len(encoded) == TRACE_ID_LENGTH
        assert decodeTraceID(encoded) == n


def test_the_largest_representable_bit_pattern_round_trips():
    """GOLDEN. The top of the 64-bit range, spelled out."""
    assert encodeTraceID(2 ** TRACE_ID_BITS - 1) == "PiRKGBkRq8V"
    assert decodeTraceID("PiRKGBkRq8V") == 2 ** TRACE_ID_BITS - 1


def test_a_negative_or_oversized_value_is_refused():
    with pytest.raises(ValueError):
        encodeTraceID(-1)
    with pytest.raises(ValueError):
        encodeTraceID(62 ** TRACE_ID_LENGTH)


def test_a_malformed_id_is_refused_loudly():
    """A wrong length or a character outside the alphabet raises.

    `adopt` leans on this: an id arriving from a file is checked before it is
    entered in the index, so a garbled one is a loud failure rather than a
    permanent bad entry.
    """
    with pytest.raises(ValueError):
        decodeTraceID("tooshort")
    with pytest.raises(ValueError):
        decodeTraceID("A" * (TRACE_ID_LENGTH + 1))
    with pytest.raises(ValueError):
        decodeTraceID("A" * (TRACE_ID_LENGTH - 1) + "-")


# --- the frozen derivation ---------------------------------------------------


def test_derivation_is_frozen():
    """GOLDEN, and the most load-bearing assertion in this file.

    Read the module header before changing this value.
    """
    assert TRACE_ID_VERSION == "tid-v1"
    assert deriveTraceID(12, "dendrite01", ROW8) == "yGjaA0DdBeJ"


def test_derivation_agrees_across_calls_with_no_save_in_between():
    """The whole point of deriving: two reads of one file agree.

    A random id assigned by a migration is stable only once the file is saved
    and only within that copy -- `Flag.deriveID`'s recorded failure. A derived
    one needs no save.
    """
    first = deriveTraceID(7, "axon", ROW8)
    second = deriveTraceID(7, "axon", ROW8)
    assert first == second


def test_derivation_separates_sections_and_contours():
    a = deriveTraceID(7, "axon", ROW8)
    assert deriveTraceID(8, "axon", ROW8) != a
    assert deriveTraceID(7, "axon2", ROW8) != a


def test_the_version_string_is_inside_the_hashed_payload():
    """A future tid-v2 cannot collide with a tid-v1 id from identical content.

    Checked structurally rather than by faking a version: the payload the
    derivation hashes is reconstructed here from the documented recipe and must
    contain the version, and hashing the same recipe with a different version
    must give a different id.
    """
    payload = json.dumps(
        [TRACE_ID_VERSION, 7, "axon", ROW8],
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    assert TRACE_ID_VERSION in payload

    import hashlib

    def derive_with_version(version):
        text = json.dumps(
            [version, 7, "axon", ROW8],
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        digest = hashlib.blake2b(
            f"0\x00{text}".encode("utf-8"), digest_size=TRACE_ID_BITS // 8
        ).digest()
        return encodeTraceID(int.from_bytes(digest, "big"))

    assert derive_with_version(TRACE_ID_VERSION) == deriveTraceID(7, "axon", ROW8)
    assert derive_with_version("tid-v2") != deriveTraceID(7, "axon", ROW8)


def test_two_identical_rows_in_one_contour_get_two_ids():
    """Salting, and it resolves a real case rather than a theoretical one.

    Two traces on one section can share a contour, a colour and a point list.
    They are still two traces and still need two ids.
    """
    first = deriveTraceID(3, "glia", ROW8)
    second = deriveTraceID(3, "glia", ROW8, taken={first})
    assert first != second
    third = deriveTraceID(3, "glia", ROW8, taken={first, second})
    assert third not in (first, second)


# --- what `taken` may be, and what the derivation may do to it ---------------


class _MembershipSpy(set):
    """A real set that counts the membership tests and traversals it sees.

    `contains_calls` says which object answered a membership probe.
    `iter_calls` says whether anything walked the index element by element --
    the shape `set(s)`/`frozenset(s)` do NOT produce (they take CPython's
    table-merge fast path and call no Python-level hook), but `list(s)`, a
    `for` loop and any other ordinary traversal do.
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.contains_calls = 0
        self.iter_calls = 0

    def __contains__(self, item):
        self.contains_calls += 1
        return super().__contains__(item)

    def __iter__(self):
        self.iter_calls += 1
        return super().__iter__()


def test_a_set_of_taken_ids_is_tested_in_place_and_not_copied():
    """The migration must not copy the series index once per trace.

    Pinned on the MECHANISM rather than on a stopwatch, because the defect this
    guards is asymptotic and a wall-clock bound is either flaky or useless:
    `deriveForSection` hands the series-wide index to `deriveTraceID` once per
    trace, so an unconditional `set(taken)` copies n ids n times and migrating a
    series costs O(n**2) (measured: 0.888 s at 16k traces, ~91 s projected at
    the 161,767-trace dataset on record).

    A subclass of `set` cannot be copied without losing its identity, so
    counting `__contains__` calls says exactly which object was probed. Restore
    the unconditional copy and this reads 0.
    """
    spy = _MembershipSpy({encodeTraceID(1)})
    derived = deriveTraceID(12, "dendrite01", ROW8, spy)

    assert spy.contains_calls >= 1, (
        "deriveTraceID copied `taken` instead of testing the caller's set"
    )
    ## And skipping the copy did not move the id: this is the frozen golden.
    assert derived == "yGjaA0DdBeJ"


def test_derive_for_section_hands_its_own_index_to_every_derivation(monkeypatch):
    """The frame the mechanism pin above does not reach.

    The test above proves `deriveTraceID` probes the set it is *given*; it says
    nothing about which object `deriveForSection` gives it. A one-token
    refactor there -- passing `frozenset(self._taken)` per call -- passes the
    callee's `isinstance` guard, keeps every other test green, and restores the
    full O(n**2) copy-per-trace the docstring says the migration must not pay.

    THE INVARIANT IS IDENTITY WITH ONE PARTICULAR OBJECT, NOT WITH `_taken`
    ----------------------------------------------------------------------
    An earlier version of this test read `issuer._taken` *inside* the spy and
    so asserted identity against the live attribute, re-read at call time. That
    admits a second quadratic shape: a loop that rebuilds the index per trace
    and rebinds the attribute (`self._taken = set(self._taken)`) hands an object
    that IS `issuer._taken` at probe time, so the pin passed while per-trace
    cost went 12.1 -> 50.4 us across 4k -> 16k traces. Those figures are this
    PR's own re-measurement of review-wave-b F07's sabotage, not F07's record
    (F07 filed 18.7 -> 21.7 -> 53.1 us on its host); every number here is
    machine-dependent and shape-only (review-247 N07).

    So the reference is captured ONCE, before the pass, and everything is
    asserted against that one object:

      * every call received it -- no per-call copy, and no rebind, since a
        rebound attribute is a different object than the one captured;
      * it is still the attribute afterwards -- no rebind that outlives the
        pass;
      * the derived ids landed IN it -- so the pass mutated the caller's index
        in place rather than filling a copy and restoring the original.

    THE RESIDUAL CLASS IS TRAVERSAL, NOT "A COPY" -- SO TRAVERSAL IS PINNED
    ----------------------------------------------------------------------
    The shape that re-pays O(n**2) is any per-trace O(n) touch of the index,
    not only a copy of it. A bare traversal -- `for _ in self._taken: pass` in
    `deriveForSection`'s inner loop -- copies nothing and rebinds nothing, so
    it passes every identity assertion above, and it is just as quadratic
    (measured: 24.8 -> 24.9 -> 54.6 us/trace across 4k -> 8k -> 16k, against a
    flat 4.6 -> 3.6 us baseline). It is also plainly observable, because
    ordinary iteration DOES call `__iter__` on a `set` subclass. So the index
    below is a `_MembershipSpy` and `iter_calls == 0` is asserted: that pins
    the whole traversal class rather than one spelling of it (review-247 F08).

    WHAT IS OUT OF REACH -- TWO SPELLINGS, NOT A CLASS
    -------------------------------------------------
    What no assertion here can see is narrower than "a copy": the
    `set(self._taken)` and `frozenset(self._taken)` SPELLINGS specifically,
    computed per trace and discarded. Both are quadratic (measured: 22.2 ->
    53.7 us/trace across 4k -> 16k) and both are invisible, because on a `set`
    subclass they take CPython's table-merge fast path, which calls no
    Python-level hook at all -- verified on 3.11: an instrumented subclass sees
    no `__iter__`, no `__len__` and no element `__hash__`. Only the `s.copy()`
    spelling is observable, and pinning one spelling of a defect is what this
    repair exists to stop doing. Those two spellings are left to review, named
    here so the next reader knows they were considered rather than missed.
    """
    import PyReconstruct.modules.datatypes.trace_id as trace_id_module

    issuer = TraceIDIssuer()
    ## The index is a set subclass that counts traversals, so "walked the index
    ## once per trace" is a failing assertion rather than a silent regression.
    issuer._taken = _MembershipSpy()
    index = issuer._taken  # captured BEFORE the pass -- see the docstring
    handed = []
    real_derive = trace_id_module.deriveTraceID

    def spying_derive(section_number, cname, row, taken):
        handed.append(taken is index)
        return real_derive(section_number, cname, row, taken)

    monkeypatch.setattr(trace_id_module, "deriveTraceID", spying_derive)
    out = issuer.deriveForSection(3, {"axon": [ROW8], "dendrite01": [ROW8]})

    assert len(handed) == len(out) == 2
    assert all(handed), (
        "deriveForSection handed something other than the index it started "
        "with -- either a per-call copy of it or a per-trace rebind of the "
        "attribute -- and both re-pay the O(n**2) copy the F01 fix removed"
    )
    assert issuer._taken is index, (
        "deriveForSection rebound the series index instead of mutating it, so "
        "the index is rebuilt at least once per pass"
    )
    assert set(out.values()) <= index, (
        "the derived ids are not in the index the pass started with, so they "
        "were added to a copy; a later derivation could reissue them"
    )
    assert index.iter_calls == 0, (
        "deriveForSection walked the series index element by element -- not a "
        "copy and not a rebind, so the identity assertions above stay green, "
        "but a per-trace traversal is quadratic all the same"
    )


def test_the_derivation_accepts_any_iterable_of_taken_ids():
    """`taken` is documented as an iterable, and every kind must still work.

    The normalization is skipped only for a set/frozenset; a one-shot iterable
    is still copied, and that copy is load-bearing rather than defensive. `x in
    generator` *advances* the generator, so a version that dropped the copy
    entirely would exhaust it on the first probe, see nothing taken on the
    second, and hand back an id the caller already holds.
    """
    first = deriveTraceID(3, "glia", ROW8)
    for taken in (
        {first},                    # set
        frozenset([first]),         # frozenset
        [first],                    # list
        (first,),                   # tuple
        iter([first]),              # one-shot iterator
        (x for x in [first]),       # one-shot generator
        {first: "axon"}.keys(),     # dict view
        {first: "axon"},            # dict
    ):
        assert deriveTraceID(3, "glia", ROW8, taken) != first


# --- the serialization refuses what it cannot canonically encode -------------


def test_a_value_json_cannot_encode_raises_instead_of_being_stringified():
    """No `default=` in the frozen recipe, and this is why.

    `default=str` would turn a value `json` cannot encode into that value's
    `str`, which is only as stable as the `__str__` behind it. A `set` -- the
    in-memory shape of `tags`, and the mistake the module docstring warns
    against -- stringifies in the string hash seed's order, so one input derived
    three different ids across three `PYTHONHASHSEED` values. An object falling
    back to the default `repr` embeds a memory address and moves every run.
    Inside a derivation declared frozen, that is silent re-identification, so
    the recipe carries no hatch and the error surfaces.
    """
    tags_as_set = list(ROW8)
    tags_as_set[7] = {"a", "b"}
    with pytest.raises(TypeError):
        deriveTraceID(3, "axon", tags_as_set)

    class Opaque:
        """No `__str__`, so `str()` falls back to a repr with an address."""

    opaque = list(ROW8)
    opaque[7] = [Opaque()]
    with pytest.raises(TypeError):
        deriveTraceID(3, "axon", opaque)


def test_every_value_a_stored_row_can_hold_is_still_accepted():
    """The other half of the test above: the refusal must not overshoot.

    Dropping the hatch may only reject what `Trace.getList` cannot produce.
    The bar is deliberately NOT "what the save path accepts": the real save
    path is `fast_dumps` (`Section.save`, and every leaf of the `.jser`
    writer), which is orjson-first, and orjson accepts values the derive
    refuses -- a `datetime`, a `UUID`, a dataclass -- but such a value comes
    back from a save/load round trip as a JSON string, so no persisted row
    carries one at migration time. What must hold is narrower and is what this
    asserts: every value `Trace.getList` actually emits still derives.
    """
    from PyReconstruct.modules.datatypes.trace import Trace

    trace = Trace("axon", (255, 0, 0), closed=True)
    trace.points = [(1.123456789, -2.5), (0.0, 4.0)]
    trace.tags = {"beta", "alpha"}
    trace.fill_mode = ("transparent", "selected")
    row = trace.getList(include_name=False)

    ## JSON-native end to end. `json.dumps` here is the stricter of the save
    ## path's two encoders, not "the save path": a row it accepts is a row
    ## either encoder writes, and it must derive.
    json.dumps({"contours": {"axon": [row]}}, indent=2)
    assert len(deriveTraceID(5, "axon", row)) == TRACE_ID_LENGTH


def test_an_exhausted_salt_range_raises_rather_than_going_random():
    """The deliberate deviation from the flag precedent.

    `Flag.deriveID` falls back to `generateID()` -- a random id -- when salting
    is exhausted. A random id produced by a migration is precisely the failure
    that docstring records, so this raises instead. Forced by shrinking the salt
    range to zero, which is the only way to reach the branch.
    """
    import PyReconstruct.modules.datatypes.trace_id as trace_id_module

    original = trace_id_module.DERIVATION_MAX_SALT
    try:
        trace_id_module.DERIVATION_MAX_SALT = 0
        with pytest.raises(RuntimeError):
            deriveTraceID(1, "axon", ROW8)
    finally:
        trace_id_module.DERIVATION_MAX_SALT = original
    assert trace_id_module.DERIVATION_MAX_SALT == DERIVATION_MAX_SALT


def test_a_derived_id_moves_when_the_content_moves():
    """Why a derived id is a birth certificate and not a content address.

    This is the property that disqualifies derivation as an ongoing identity: a
    reshaped trace hashes differently, so "the same trace, edited" would look
    like "a different trace". The store therefore derives once and never again.
    Asserted so the reason is in the suite and not only in a docstring.
    """
    before = deriveTraceID(4, "axon", ROW8)
    reshaped = [list(ROW8[0]) + [7.0], list(ROW8[1]) + [8.0]] + list(ROW8[2:])
    assert deriveTraceID(4, "axon", reshaped) != before


# --- deterministic migration over a whole section ----------------------------


def test_migration_walks_contour_names_in_canonical_sorted_order():
    """Sorted iteration is pinned on the MECHANISM, and here is why.

    The requirement is that two opens of one file agree without a save. Checking
    that by comparing outcomes under two dict orders does not discriminate, and
    the first version of this test did not: the payload carries the contour name,
    so a salt is only ever consumed by rows that share one contour, and rows
    within a contour are always visited by index. Cross-contour order therefore
    changes the result *only* when two different contours derive the same 64-bit
    id -- a 2**-64 event nobody can construct in a test. Verified by mutation:
    replacing `sorted(contours, key=str)` with `contours` left an
    outcome-comparison version of this test green.

    So the iteration order is asserted directly. It is still worth having:
    `sorted(..., key=str)` is the order `Section.getDict` writes, and on the one
    path where order does decide an id it decides it the same way in every
    process.
    """
    import PyReconstruct.modules.datatypes.trace_id as trace_id_module

    seen = []
    real_derive = trace_id_module.deriveTraceID

    def spy(section_number, contour_name, row, taken=()):
        seen.append(contour_name)
        return real_derive(section_number, contour_name, row, taken)

    contours = {"glia": [ROW8], "axon": [ROW8, ROW8], "dendrite": [ROW8]}
    trace_id_module.deriveTraceID = spy
    try:
        issuer = TraceIDIssuer()
        result = issuer.deriveForSection(9, contours)
    finally:
        trace_id_module.deriveTraceID = real_derive

    assert seen == ["axon", "axon", "dendrite", "glia"]
    assert seen == sorted(seen, key=str)
    assert len(set(result.values())) == len(result)


def test_migration_agrees_across_two_independent_runs():
    contours = {"axon": [ROW8, ROW8], "dendrite": [ROW8], "glia": [ROW8]}
    assert (TraceIDIssuer().deriveForSection(9, contours)
            == TraceIDIssuer().deriveForSection(9, contours))


def test_migration_takes_the_series_index_not_the_sections():
    """`taken` is the series', so two sections cannot mint the same id.

    Flags enforce uniqueness per section; traces do not, because a merge crosses
    sections. Two sections whose contours are identical must still produce
    disjoint id sets when they share one issuer.

    The body used to pass section number 1 BOTH times, which pinned something
    this docstring never claimed: that re-deriving the SAME section's content
    hands out fresh ids. S1 falsified that as a desirable property --
    `Series.loadSection` builds a fresh `Section` per call with no cache, so
    salt-bumping on re-derivation would reissue every id on a section per
    scroll and leak a section's worth of taken-set per load. Re-derivation is
    now answered from the issuer's own record
    (`test_rederiving_the_same_section_returns_the_same_ids`, below), and this
    test says what it always meant: two DIFFERENT sections, disjoint ids.
    """
    contours = {"axon": [ROW8]}
    issuer = TraceIDIssuer()
    first = issuer.deriveForSection(1, contours)
    second = issuer.deriveForSection(2, contours)
    assert set(first.values()).isdisjoint(second.values())
    assert len(issuer.taken) == 2


def test_rederiving_the_same_section_returns_the_same_ids():
    """One issuer asked twice about one section's content answers the same.

    The consumer is `Section.__init__` via `Series.loadSection`, which
    constructs a fresh `Section` -- and re-derives -- on every call. Without
    the issuer's derivation record the first load's ids sit in `taken`, the
    second load salt-bumps past every one of them, and a mouse-wheel scroll
    reissues the birth certificate of every trace on the section.
    """
    contours = {"axon": [ROW8, ROW8], "dendrite": [ROW8]}
    issuer = TraceIDIssuer()
    first = issuer.deriveForSection(9, contours)
    second = issuer.deriveForSection(9, contours)
    assert first == second, "re-derivation moved ids for unchanged content"
    assert len(issuer.taken) == 3, (
        "re-derivation leaked ids into the taken-set"
    )
    ## The record answers per occurrence: two byte-identical rows in one
    ## contour are two traces and keep two distinct ids, in order.
    assert first[("axon", 0)] != first[("axon", 1)]


# --- the issuer --------------------------------------------------------------


def test_issue_returns_distinct_ids_and_records_them():
    issuer = TraceIDIssuer()
    ids = {issuer.issue() for _ in range(200)}
    assert len(ids) == 200
    assert ids <= issuer.taken


def test_issue_refuses_and_reissues_rather_than_handing_out_a_duplicate():
    """Refuse-and-reissue at issue time, forced with a repeating bit source.

    A real 64-bit source does not repeat, so the loop is unobservable in
    production. Driving it with a source that hands out 5, 5, 5, 6 proves the
    refusal is real and not decorative.
    """
    draws = iter([5, 5, 5, 6])
    issuer = TraceIDIssuer(bits_source=lambda: next(draws))
    first = issuer.issue()
    second = issuer.issue()
    assert first == encodeTraceID(5)
    assert second == encodeTraceID(6)


def test_issue_will_not_hand_out_an_id_already_adopted_from_a_file():
    existing = encodeTraceID(99)
    issuer = TraceIDIssuer(taken=[existing], bits_source=iter([99, 100]).__next__)
    assert issuer.issue() == encodeTraceID(100)


def test_a_hopeless_bit_source_raises_instead_of_looping_forever():
    issuer = TraceIDIssuer(bits_source=lambda: 1)
    assert issuer.issue() == encodeTraceID(1)
    with pytest.raises(RuntimeError):
        issuer.issue()


# --- load and merge: detect and report, never adopt silently -----------------


def test_adopt_registers_an_unseen_id():
    issuer = TraceIDIssuer()
    assert issuer.adopt(encodeTraceID(42), "axon") is True
    assert encodeTraceID(42) in issuer.taken
    assert issuer.collisions == ()


def test_adopt_reports_a_clash_by_name_and_refuses_it():
    """The third property of the acceptance bar: reported to the user by name.

    Never silently reissued -- that is the recorded flag failure -- and never
    silently adopted, which is how a merge loses an edit.
    """
    issuer = TraceIDIssuer()
    clashing = encodeTraceID(42)
    assert issuer.adopt(clashing, "axon") is True
    assert issuer.adopt(clashing, "dendrite01") is False
    assert issuer.collisions == ((clashing, "dendrite01"),)


def test_adopt_refuses_a_malformed_id_before_indexing_it():
    issuer = TraceIDIssuer()
    with pytest.raises(ValueError):
        issuer.adopt("nope", "axon")
    assert issuer.taken == frozenset()


# --- on a real series --------------------------------------------------------


def _stored_contours(series):
    """Every section's stored contour rows, as `Section.getDict` writes them.

    Yields (section number, {contour name: [8-field row, ...]}). One Section is
    held at a time, as the application holds them.
    """
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        yield snum, section.getDict()["contours"]


def test_deriving_over_a_real_series_gives_one_id_per_trace(real_series):
    """The migration, run over every trace of the checked-in series.

    Two independent issuers over the same stored rows must agree exactly --
    which is the property that makes a derived id safe to hand a file that has
    never been saved by this build -- and no id may repeat across the whole
    series, because uniqueness here is series-global rather than per section.
    """
    stored = list(_stored_contours(real_series))
    n_traces = sum(len(rows) for _, contours in stored for rows in contours.values())
    assert n_traces > 0, "the fixture series has no traces to derive ids for"

    first_issuer = TraceIDIssuer()
    second_issuer = TraceIDIssuer()
    first, second = {}, {}
    for snum, contours in stored:
        first[snum] = first_issuer.deriveForSection(snum, contours)
        second[snum] = second_issuer.deriveForSection(snum, contours)

    assert first == second
    assert len(first_issuer.taken) == n_traces


def test_the_issuer_is_exported_through_the_datatypes_package():
    """The `datatypes/__init__.py` export, taken in this PR.

    Two things ride on this one line. Identity, first: the package must hand
    out the same objects this suite tests, not a second copy of the module.
    And reach, second: `test_datatypes_import_graph_is_qt_free` proves the
    package's import graph imports cleanly with every `PySide6` import raising,
    so a module nothing in the package imports is simply outside the proof.
    `trace_id` was outside it until this line; the AST scan in that same file
    covered the source, but nothing covered the actual import.

    `deriveForSection` is a method on `TraceIDIssuer` rather than a module
    function, so the four names below are the module's whole public surface
    apart from its frozen constants, which stay module-qualified on purpose --
    `TRACE_ID_VERSION` reads as a tid-v1 fact where it is defined and as
    nothing in particular at package scope.
    """
    from PyReconstruct.modules import datatypes

    assert datatypes.TraceIDIssuer is TraceIDIssuer
    assert datatypes.deriveTraceID is deriveTraceID
    assert datatypes.encodeTraceID is encodeTraceID
    assert datatypes.decodeTraceID is decodeTraceID
