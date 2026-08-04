"""Stable trace identity: the frozen derivation, the base62 codec, the issuer.

Phase 1 of the columnar-sections work needs a trace to have a name that is not
"section number plus contour name plus position in a list". This module is that
name's plumbing and nothing else. **No id in this module reaches disk.** The
columnar store carries an id column in memory; `Trace.getList` is untouched, so
no `.jser` byte changes. An id that is not persisted is not yet an identity --
that is a deliberate scoping decision, recorded in the wave-B write-up, and the
id becomes an identity only when the approved keyed-row format lands.

WHY THIS IS NOT `make_unique_id()`
----------------------------------
`backend/func/utils.make_unique_id()` returns `uuid.uuid4().int` and already
means "transient Qt row id" at two call sites (`gui/table/copy_table_widget.py`
and `gui/table/object_model.py`, both setting `self.id` on a widget or a model
row that lives for one process). One helper meaning both a process-lifetime GUI
handle and a durable annotation identity is how the two get confused, so trace
identity gets its own named issuer here.

WHY TWO SCHEMES, AND WHICH APPLIES WHEN
---------------------------------------
`Flag` already ships this pair and the reason is written in first person in
`Flag.deriveID`'s docstring: a *random* id assigned by a migration is stable
only once the file is saved and only within that one copy, so two people who
each opened the same legacy file held the same flag under two ids and importing
one into the other stacked a duplicate on every flag. So:

* **traces that already exist** get a **derived** id -- a function of their own
  stored content, so two independent opens of one file agree without a save;
* **traces created from now on** get an **opaque random** id, because identity
  must survive an edit and a content hash does not.

A derived id is a **birth certificate, not a content address**. It is computed
once, when a trace first acquires an id, and never recomputed. Editing a trace
does not re-derive; if it did, "the same trace, edited" would be
indistinguishable from "a different trace", which is the one property a merge
cannot lose.

THE FROZEN DERIVATION -- `tid-v1`
---------------------------------
Written down before it was implemented, and frozen: changing any line of this
paragraph re-identifies every legacy trace in every series, silently, and there
is no migration back. A new scheme gets a new version string and both stay in
the code.

    version string   "tid-v1"  (`TRACE_ID_VERSION`), included IN the hashed
                     payload, so a future "tid-v2" cannot collide with a v1 id
                     derived from identical content.

    inputs           `[TRACE_ID_VERSION, section_number, contour_name, row]`
                     where `row` is the trace's **stored 8-field row**, exactly
                     as `Trace.getList(include_name=False)` produces it:
                     `[x, y, color, closed, negative, hidden, fill_mode, tags]`
                     with coordinates already rounded to 7 decimal places and
                     tags already sorted. The stored row is used rather than the
                     in-memory attributes precisely because it is canonical:
                     two opens of one file produce byte-identical rows, and the
                     tag set's iteration order -- which is not stable across
                     processes -- has been replaced by a sorted list. Handing
                     this function the in-memory `tags` **set** instead is the
                     mistake this paragraph exists to prevent, and since the
                     serialization below carries no `default=`, that mistake now
                     raises `TypeError` rather than hashing one process's
                     iteration order.

    salt             an integer counted up from 0, prepended to the payload as
                     `f"{salt}\\x00{payload}"`. Salting resolves a genuine
                     duplicate: two traces on one section can share a contour, a
                     colour and a point list, and they still need two ids.

    serialization    `json.dumps(inputs, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True)`. `ensure_ascii` keeps the bytes
                     independent of any locale; `separators` removes the
                     whitespace `json` would otherwise vary. There is
                     deliberately **no `default=`**: a row carrying a type
                     `json` cannot encode raises `TypeError` rather than
                     degrading to that value's `str`. `Flag.deriveID` does pass
                     `default=str`, and that divergence is the point --- a
                     stringified value is only as stable as its `__str__`, so
                     the hatch admits process-dependent bytes (a `set`'s
                     iteration order, an object's `repr` memory address) into a
                     digest declared frozen, silently. The refusal does not
                     overshoot, but the bar is NOT "what the save path
                     accepts": the real save writes `fast_dumps`
                     (`Section.save`, and every leaf of the `.jser` writer),
                     which is orjson-first with a stdlib fallback, and orjson
                     natively encodes values this recipe refuses (`datetime`,
                     `date`, `time`, `UUID`, a dataclass). The bar is that no
                     live producer emits such a value --- `Trace.getList`
                     writes only JSON-native types --- and an orjson-native
                     value does not survive a save/load round trip as itself:
                     it is read back as a JSON string, which derives fine. So
                     no row persisted in any real `.jser` can present one at
                     migration time, and no persisted trace's id moves.

    hash             `hashlib.blake2b(payload_bytes, digest_size=8)`, i.e. 64
                     bits, read big-endian as an unsigned integer.

    encoding         base62 over `TRACE_ID_ALPHABET` (A-Z, then a-z, then 0-9),
                     **least-significant digit first**, fixed width
                     `TRACE_ID_LENGTH` = 11 characters. Least-significant-first
                     is the convention `Flag.deriveID` already uses; matching it
                     means a trace id and a flag id are read the same way. 11
                     characters because 62**11 > 2**64 > 62**10.

`TRACE_ID_ALPHABET` is a frozen copy of `flag.possible_chars` rather than an
import of it, because the derivation cannot depend on a constant another module
is free to reorder -- reordering it would change every derived id. The two are
pinned equal by a test, so a change to either is reported rather than silently
absorbed.

WIDTH, SCOPE AND COLLISION POLICY
---------------------------------
**64 random bits, base62, series-global.** At the largest corpus on record
(8,676,366 traces) a 6-character flag-width id expects ~663 collisions drawn
series-globally; 64 bits expects 2.0e-6 at that scale. Uniqueness is enforced
**across the series**, not per section as flags do it, because a merge crosses
sections and files.

Collision policy, and the two halves are deliberately different:

* **at issue** -- refuse and reissue. `TraceIDIssuer.issue` draws again until
  the id is not spoken for. It owns the series' id index, so this is a set
  lookup.
* **at load and at merge** -- detect and **report by name**, never silently
  adopt and never silently reissue. `TraceIDIssuer.adopt` returns `False` and
  records the clash in `collisions`; reissuing at load is exactly the recorded
  flag failure, and adopting quietly is how a merge loses an edit.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
* It does not touch `Trace`, `Contour` or `Section`. No `Trace.copy()` change
  and no new `Trace.duplicate()`: the carry rules live in the columnar store,
  which is where a row's id is actually held.
* It decides nothing about **split-object** traces (`Series` split, renamed
  `_{n}`) or **palette** traces. Those two rows of the carry table are
  semantics the maintainer owns and they are unimplemented on purpose.
* It writes no byte to disk.
"""

import hashlib
import json
import secrets


## The version string of the derivation below. It is part of the hashed payload.
## Changing the derivation means adding a version, not editing this one.
TRACE_ID_VERSION = "tid-v1"

## Frozen. See the module docstring: a copy of `flag.possible_chars` rather than
## an import, because a derived id must not move when another module reorders a
## constant. `tests/test_trace_id_issuer.py` pins the two equal.
TRACE_ID_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
)

## 64 bits, per the width decision. 62**11 = 5.2e19 > 2**64 = 1.8e19 > 62**10.
TRACE_ID_BITS = 64
TRACE_ID_LENGTH = 11

## How many salts a derivation tries before giving up. `Flag.deriveID` falls
## back to a *random* id here; this module raises instead, because a random id
## produced by a migration is the failure `Flag.deriveID`'s own docstring
## records. Reaching the limit means blake2b collided 1000 times on one input,
## which is not a case to paper over.
DERIVATION_MAX_SALT = 1000


def encodeTraceID(n: int) -> str:
    """Render a non-negative integer as a fixed-width base62 trace id.

    Least-significant digit first, `TRACE_ID_LENGTH` characters, zero-padded
    with the alphabet's first character. Frozen; see the module docstring.

        Params:
            n (int): the value to encode, 0 <= n < 62**TRACE_ID_LENGTH
        Returns:
            (str): an 11-character id
    """
    if n < 0:
        raise ValueError(f"trace id value must be non-negative, got {n}")
    limit = len(TRACE_ID_ALPHABET) ** TRACE_ID_LENGTH
    if n >= limit:
        raise ValueError(
            f"trace id value {n} does not fit in {TRACE_ID_LENGTH} base62 digits"
        )
    out = []
    for _ in range(TRACE_ID_LENGTH):
        n, i = divmod(n, len(TRACE_ID_ALPHABET))
        out.append(TRACE_ID_ALPHABET[i])
    return "".join(out)


def decodeTraceID(trace_id: str) -> int:
    """Recover the integer a trace id encodes.

    The inverse of `encodeTraceID`, and the reason the encoding is testable
    rather than merely plausible.

        Params:
            trace_id (str): an id produced by `encodeTraceID`
        Returns:
            (int): the encoded value
    """
    if len(trace_id) != TRACE_ID_LENGTH:
        raise ValueError(
            f"a trace id is {TRACE_ID_LENGTH} characters, got {len(trace_id)}: "
            f"{trace_id!r}"
        )
    n = 0
    for ch in reversed(trace_id):
        i = TRACE_ID_ALPHABET.find(ch)
        if i < 0:
            raise ValueError(f"{ch!r} is not a base62 trace-id character")
        n = n * len(TRACE_ID_ALPHABET) + i
    return n


def deriveTraceID(section_number: int, contour_name: str, row: list,
                  taken=()) -> str:
    """Derive a trace's id from its own stored content. Frozen as `tid-v1`.

    For traces that already exist when a series first acquires ids: the result
    is the same in every process that reads the same file, with no save
    required. Never called again after that first derivation -- an edit does not
    move a trace's id. See the module docstring for the frozen inputs.

        Params:
            section_number (int): the section the trace sits on
            contour_name (str): the contour's name (the dict key, i.e. the
                trace's own name)
            row (list): the trace's stored 8-field row, as
                `Trace.getList(include_name=False)` produces it
            taken (iterable): ids already spoken for in this SERIES, so a
                derived id never displaces one. A `set` or `frozenset` is
                membership-tested in place; any other iterable is copied into
                one first (see below).
        Returns:
            (str): the derived id, `TRACE_ID_LENGTH` base62 characters
    """
    ## Normalize only when the caller did not already hand us a hashed
    ## container. This function never mutates `taken` -- it only tests
    ## membership -- so testing the caller's own set directly is equivalent, and
    ## copying it is not: `deriveForSection` passes the SERIES-wide index once
    ## per trace, so an unconditional `set(taken)` copies n ids n times and
    ## makes migrating a series quadratic in its own trace count -- measured
    ## 0.888 s at 16k traces and projected ~91 s at the 161,767-trace corpus on
    ## record, against a flat ~3 us/trace once the copy is conditional (ledger
    ## row TID.derive.section32k). The branch cannot move an id for any `taken`
    ## that honors set semantics: `x in some_set` and `x in set(some_set)` agree
    ## whenever the container's membership test agrees with its own elements.
    ## A `set` SUBCLASS whose `__contains__` contradicts what it iterates is the
    ## one input the two arms answer differently -- it is not a container of ids
    ## under this parameter's documented contract, no producer of one exists in
    ## this codebase, and the boundary is recorded in review-247 F06 rather than
    ## guarded against here.
    ##
    ## The copy is kept for every other iterable rather than dropped, because
    ## `taken` is documented as an *iterable* and a one-shot one must not be
    ## consumed by the membership tests: `x in generator` advances it, so the
    ## salt loop's second probe would see an exhausted iterator, find nothing
    ## taken, and hand back an id the caller already holds.
    if not isinstance(taken, (set, frozenset)):
        taken = set(taken)
    payload = json.dumps(
        [TRACE_ID_VERSION, section_number, contour_name, row],
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    for salt in range(DERIVATION_MAX_SALT):
        digest = hashlib.blake2b(
            f"{salt}\x00{payload}".encode("utf-8"),
            digest_size=TRACE_ID_BITS // 8,
        ).digest()
        trace_id = encodeTraceID(int.from_bytes(digest, "big"))
        if trace_id not in taken:
            return trace_id
    raise RuntimeError(
        f"{DERIVATION_MAX_SALT} derivations of a trace id on section "
        f"{section_number}, contour {contour_name!r} all collided. Falling back "
        f"to a random id here would reintroduce the failure Flag.deriveID "
        f"documents, so this raises instead."
    )


class TraceIDIssuer():
    """The series' id index: issues new ids, adopts read ones, derives legacy.

    One issuer per series, because uniqueness is series-global. It is the only
    thing that knows which ids are spoken for, which is what makes
    refuse-and-reissue a set lookup rather than a scan.
    """

    def __init__(self, taken=(), bits_source=None):
        """Create an issuer.

            Params:
                taken (iterable): ids already in use in this series
                bits_source (callable): returns `TRACE_ID_BITS` random bits as
                    an int. Defaults to `secrets.randbits`, which is the right
                    source for an identity; tests inject a deterministic one.
        """
        self._taken = set(taken)
        self._bits_source = bits_source or (lambda: secrets.randbits(TRACE_ID_BITS))
        self._collisions = []

    @property
    def taken(self) -> frozenset:
        """The ids spoken for in this series."""
        return frozenset(self._taken)

    @property
    def collisions(self) -> tuple:
        """Every clash seen at load or merge, as (id, name) pairs.

        Reported by name rather than resolved, per the acceptance bar: anything
        that needed a rule to resolve is told to the user.
        """
        return tuple(self._collisions)

    def issue(self) -> str:
        """Issue a fresh opaque id for a trace being created now.

        Refuse-and-reissue: draws again while the drawn id is spoken for. At 64
        bits against any real series that loop does not run twice, but the index
        exists anyway and checking it is free.

            Returns:
                (str): an id no other trace in this series holds
        """
        for _ in range(DERIVATION_MAX_SALT):
            trace_id = encodeTraceID(self._bits_source())
            if trace_id not in self._taken:
                self._taken.add(trace_id)
                return trace_id
        raise RuntimeError(
            f"{DERIVATION_MAX_SALT} draws of a {TRACE_ID_BITS}-bit trace id all "
            f"landed on an id already in use; the id source is not random."
        )

    def adopt(self, trace_id: str, name: str) -> bool:
        """Register an id that arrived from a file or from another series.

        Detect and report, never silently reissue and never silently adopt: a
        second claim on one id is recorded in `collisions` and refused. The
        caller decides what to tell the user; this method's contract is only
        that the clash cannot pass unnoticed.

            Params:
                trace_id (str): the id read in
                name (str): the object name to report the clash under
            Returns:
                (bool): True if the id was free and is now registered
        """
        decodeTraceID(trace_id)  # rejects a malformed id loudly
        if trace_id in self._taken:
            self._collisions.append((trace_id, name))
            return False
        self._taken.add(trace_id)
        return True

    def deriveForSection(self, section_number: int, contours: dict) -> dict:
        """Derive ids for every trace of one section, deterministically.

        Sorted iteration over contour names -- `sorted(contours, key=str)`, the
        same canonical order `Section.getDict` writes -- so the salt a duplicate
        row receives does not depend on dict insertion order, and two opens of
        one file agree. The `taken` set is the SERIES', not the section's, so a
        derived id cannot collide with one already issued on another section.

            Params:
                section_number (int): the section these contours sit on
                contours (dict): {contour name: [stored 8-field row, ...]}, the
                    shape `Section.getDict()["contours"]` has
            Returns:
                (dict): {(contour name, index within contour): id}
        """
        out = {}
        for cname in sorted(contours, key=str):
            for i, row in enumerate(contours[cname]):
                trace_id = deriveTraceID(section_number, cname, row, self._taken)
                self._taken.add(trace_id)
                out[(cname, i)] = trace_id
        return out
