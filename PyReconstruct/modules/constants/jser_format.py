"""Canonical ordering for the .jser writer, plus an opt-in structural pretty printer.

Two writer behaviours live here. Neither changes the schema: every file this
module produces is the same JSON document the compact writer produced, with the
same keys and the same values. Alongside them sits one schema-level constant,
``JSER_SCHEMA_VERSION`` -- a value, not a behaviour; nothing in this module reads
it and nothing in the reader dispatches on it. Read its own docstring before
using it for anything, because what it cannot do is the interesting half.

**The normative output form is minified** -- one line, no indentation -- **with
canonical ordering always applied.** Pretty-printing is available on request and
is off by default. The two halves were introduced together but they do not cost
the same, and only one of them is free:

============================  ===================  ==========================
                              canonical ordering   pretty-printing
============================  ===================  ==========================
bytes on a 391 MB series      0 (exactly)          +0.65%
``saveJser`` wall time        within noise         +11.3%
save-path transient memory    unchanged            +27% (~1 extra copy)
fixes byte reproducibility    yes                  no
============================  ===================  ==========================

So ordering is kept unconditionally and there is deliberately no switch to turn
it off, while the whitespace is now something a caller asks for when a human is
going to read the diff.

**Canonical ordering.** Five structures are Python ``set`` objects in memory and
JSON arrays on disk (trace ``tags``, series ``editors``, the member lists of
``object_groups`` and ``ztrace_groups``, and the host lists of ``host_tree``).
Set iteration order is not the input order and is not stable across processes, so
two saves of identical content produced different bytes -- byte reproducibility
failed on any series using tags, groups or hosts. Every one of those arrays is now
sorted, and object key order is fixed by ``canon_keys`` so that a dict which was
back-filled by a migration (missing keys appended at the tail) has the same byte
layout as one derived straight from the model. Measured cost on a 391 MB series:
**0 bytes** -- sorting reorders bytes without adding or removing any, so the
minified output is byte-for-byte the same length as before ordering existed.

**Structural pretty-printing (opt in).** ``dumps_jser(doc, pretty=True)`` expands
the document's *structure* onto lines while keeping every leaf compact: one
section block, one trace, one flag, one transform per line, with coordinate
arrays staying on the trace's own line.

What it buys, and what it does not:

- **A readable diff.** A one-trace edit shows as a few hundred bytes naming the
  enclosing object, instead of ``diff`` reprinting the whole single-line file
  twice. On a 781 MB series that is 781,692,354 bytes of diff versus 669. This is
  the reason the printer exists, and it is worth asking for when you want it.
- **Convenient salvage**, not the difference between recoverable and lost. ``jq``
  refuses truncated JSON either way. Line structure makes recovery a matter of
  line-anchored patterns (a fixed column, ``sed -n Np``, the enclosing object name
  as context) rather than hand-written regexes -- but non-anchored patterns
  recover the same sections and 99.5% of the trace rows from a minified file, so
  this is ergonomics rather than data.

Set ``PYRECON_JSER_PRETTY=1`` in the environment, or pass ``pretty=True``, to get
it. The reader accepts either form; this is whitespace, so it is
backward-compatible in both directions.

**A third switch lives here and it is not whitespace.**
``PYRECON_JSER_KEYED_ROWS=1`` changes the *schema* of a trace row from a
positional array to a keyed object carrying the trace's persisted id. It is off
by default, it is the only switch in this module that changes what a file means,
and its full cost is written out at ``KEYED_ROWS_ENV_VAR`` below. Read that
before turning it on.
"""

import os

from .fast_json import fast_dumps


#: Environment variable that opts a whole process into pretty output.
PRETTY_ENV_VAR = "PYRECON_JSER_PRETTY"


def pretty_default() -> bool:
    """Whether a ``dumps_jser`` call with no explicit ``pretty=`` pretty-prints.

    Read from the environment **on every call**, deliberately. The previous
    version of this flag was evaluated once at import, which meant it could not
    be changed in a running process -- and meant the test that claimed to cover
    it could not actually set the variable, so it monkeypatched the module global
    and the variable name itself was never exercised.

        Returns:
            (bool) True when ``PYRECON_JSER_PRETTY`` is set to ``1``
    """
    return os.environ.get(PRETTY_ENV_VAR, "") == "1"


# ---------------------------------------------------------------------------
# keyed trace rows (the v1 row shape), opt in
# ---------------------------------------------------------------------------

#: Environment variable that opts a whole process into **keyed trace rows**.
#:
#: Same spelling convention as ``PYRECON_JSER_PRETTY`` and read the same way
#: (exactly ``"1"``, on every call, never cached at import). Everything else
#: about it is different, and the difference is the point:
#:
#: **This one changes the schema.** ``Section.getDict`` stops writing the
#: 8-element positional trace row documented in ``docs/JSER_FORMAT.md`` section
#: 4.1 and writes a JSON object per trace instead, keyed by
#: ``KEYED_TRACE_ROW_KEYS``, carrying the trace's persisted id. Pretty-printing
#: adds whitespace and canonical ordering moves bytes around; this adds and
#: renames keys, and a file written with it on is a different document from the
#: one written with it off.
#:
#: **It is off by default and defaulting it on is a separate decision** (S7 of
#: `specs/phase1-keyed-row-v1-slices-2026-08-06.md`), because of what it costs
#: with an older build on the other end -- see ``KEYED_TRACE_ROW_KEYS``.
KEYED_ROWS_ENV_VAR = "PYRECON_JSER_KEYED_ROWS"


def keyed_rows_default() -> bool:
    """Whether a ``Section.getDict`` call with no explicit ``keyed_rows=`` keys.

    Read from the environment **on every call**, for the same reason
    ``pretty_default`` is: a flag evaluated once at import cannot be changed in
    a running process, and a test that cannot set the variable ends up
    monkeypatching a module global and never exercising the variable name at
    all.

        Returns:
            (bool) True when ``PYRECON_JSER_KEYED_ROWS`` is set to ``1``
    """
    return os.environ.get(KEYED_ROWS_ENV_VAR, "") == "1"


#: The keyed trace row's key order, which is also its normative key set.
#:
#: ``id`` LEADS, deliberately, and the precedent is in the file already: a flag
#: row carries its persisted id at index 0 (``docs/JSER_FORMAT.md`` section
#: 4.2), so the one other row shape in a ``.jser`` that has an identity puts it
#: first. The remaining eight are the positional row's fields in the positional
#: row's order, so the two shapes read the same left to right and a reader
#: written against one is not surprised by the other.
#:
#: The order is fixed here rather than left to dict insertion order for the
#: reason ``canon_keys`` exists: two saves of identical content must produce
#: identical bytes.
#:
#: **``fill_mode``, not ``mode``, and this is the expensive key.** The model
#: calls the field ``fill_mode``, ``docs/JSER_FORMAT.md`` section 4.1 calls it
#: ``fill_mode``, and the legacy keyed branch in ``Section.updateJSON`` calls it
#: ``mode``. Writing ``mode`` would have made a keyed row readable by every
#: shipped build back to ``v1.19.0`` for free. Writing ``fill_mode`` does not:
#: a shipped reader hits ``KeyError: 'mode'`` on the first keyed row and
#: **cannot open the file at all**. That is measured, not predicted
#: (``tests/test_jser_keyed_trace_rows.py`` runs it against a ``git archive`` of
#: the ``v1.21.0`` tag), and it is the whole reason this switch is off by
#: default and tier A. The trade was made deliberately: a schema that says what
#: it means, at the price of a hard failure in older builds instead of a silent
#: one. The reader in this build accepts BOTH spellings and always will --
#: "the reader must keep reading every past shape forever" -- so the cost is
#: paid only by builds that shipped before the tolerance did.
#:
#: ``id`` is omitted from a row whose trace has no id rather than written as
#: ``null``: absent means "no claim", the same convention ``schema_version``
#: uses. A keyed row without ``id`` is exactly the legacy keyed shape and every
#: reader that has ever existed handles it.
KEYED_TRACE_ROW_KEYS = (
    "id",
    "x",
    "y",
    "color",
    "closed",
    "negative",
    "hidden",
    "fill_mode",
    "tags",
)

#: Every key a keyed trace row has ever spelled the fill mode with, newest
#: first. The reader tries them in order; the writer emits ``[0]``.
#:
#: Two entries and not one because the legacy keyed branch that has shipped
#: unchanged since ``v1.19.0`` writes ``mode``, and files carrying that spelling
#: exist in the wild. Tolerance on the read side is free and is required by the
#: 2026-07-27 non-negotiable.
FILL_MODE_ROW_KEYS = ("fill_mode", "mode")


def keyed_trace_row_to_positional(row : dict) -> list:
    """Convert a keyed trace row into the 8-element positional row.

    The one place the keyed shape is decoded, so the two readers that need it
    -- ``Section.updateJSON`` on the unpack path and
    ``FieldState.getContours`` on the undo-baseline path -- cannot drift on the
    key set. They did not share a decoder before this function existed, and the
    second one did not have one at all: handed a keyed row it called
    ``Trace.fromList`` on the dict, which does not raise, because ``len(dict)``
    is the key count and iterating a dict yields its keys. The result was a
    ``Trace`` named ``'x'`` with the key strings unpacked into its fields, and
    no exception anywhere.

    ``id`` is not returned. It is not part of the positional row, and the
    caller that wants it reads it off the dict before calling this.

        Params:
            row (dict): a keyed trace row, either spelling of the fill mode
        Returns:
            (list) the 8-element positional row
        Raises:
            KeyError: if the row is missing a field that has no default. The
                fill mode is the one field with a spelling to choose between,
                and a row carrying neither spelling is reported against
                ``fill_mode`` -- the name this build writes -- rather than
                against the legacy one.
    """
    for key in FILL_MODE_ROW_KEYS:
        if key in row:
            fill_mode = row[key]
            break
    else:
        raise KeyError(FILL_MODE_ROW_KEYS[0])

    return [
        row["x"],
        row["y"],
        row["color"],
        row["closed"],
        row["negative"],
        row["hidden"],
        fill_mode,
        row["tags"],
    ]


# ---------------------------------------------------------------------------
# canonical key order
# ---------------------------------------------------------------------------
#
# Both tuples are the order the *writer* emits (Section.getDict /
# Series.getDict), not the order the empty-dict templates happen to use -- the
# two disagree (the section template puts "thickness" before "tforms"; the series
# template has no "log_set" at all). Canonicalizing onto the writer's order means
# a section that passed through opaquely and a section re-derived from the model
# come out byte-identical.

SECTION_KEYS = (
    "src",
    "brightness_contrast_profiles",
    "mag",
    "align_locked",
    "tforms",
    "thickness",
    "contours",
    "flags",
    "calgrid",
)

#: The schema this build's writer emits, stamped into the series object as
#: ``schema_version`` by ``Series.getDict``.
#:
#: **It is a hint for external consumers and it is never a reader's dispatch
#: key.** Both halves of that sentence are load-bearing, and the second one is
#: not a style preference -- the field cannot support dispatch, for two
#: independent reasons:
#:
#: 1. **It evaporates.** The series object is rebuilt from the in-memory model on
#:    every save (`docs/JSER_FORMAT.md` divergence 1: sections pass through
#:    opaquely, the series object does not), and a build older than this one has
#:    no ``schema_version`` in its ``Series.getDict``. So an older build opens a
#:    file carrying this key, ignores it, and **silently deletes it on the first
#:    save while leaving every row it wrote exactly as it found them**. That is
#:    measured, not predicted: a round trip through the shipped ``v1.21.0``
#:    reader is pinned in ``tests/test_jser_schema_version.py``. A file with no
#:    ``schema_version`` is therefore not evidence of an old document -- it is
#:    the ordinary state of any document that has been near an older build --
#:    and a reader that treated absence as "legacy shape" would be wrong about a
#:    file this build wrote ten minutes ago.
#: 2. **It cannot describe the rows anyway.** Row shape is per row: every shipped
#:    reader back to ``v1.19.0`` accepts a positional trace row and a keyed one
#:    in the same contour, so one document can legitimately hold both. A single
#:    document-level integer has nothing true to say about that mixture.
#:
#: **Per-row shape detection stays authoritative.** Anything that needs to know
#: what a row is must look at the row.
#:
#: What the field is good for is the thing that survives its own unreliability:
#: a third-party consumer -- a converter, an archive checker, a lab script
#: reading `.jser` without PyReconstruct -- gets a positive statement of which
#: schema the last writer intended, when there is one. Present means "written by
#: a build that stamps this"; absent means "no claim", not "old".
#:
#: Bump it when the document schema changes in a way an external consumer would
#: want to branch on, and record what changed in ``docs/JSER_FORMAT.md``. Version
#: ``1`` is simply "the first versioned .jser document"; it does not assert a row
#: shape, per reason 2 above.
JSER_SCHEMA_VERSION = 1

SERIES_KEYS = (
    # First deliberately: a version marker is declared before the data it
    # describes. Ordering here is what fixes its byte position; see canon_keys.
    "schema_version",
    "current_section",
    "src_dir",
    "window",
    "palette_traces",
    "palette_index",
    "ztraces",
    "alignment",
    "object_groups",
    "ztrace_groups",
    "obj_attrs",
    "ztrace_attrs",
    "current_brightness_contrast_profile",
    "options",
    "log_set",
    "editors",
    "code",
    "user_columns",
    "host_tree",
)

#: Top-level key order. The reader tolerates any order; the writer has always
#: emitted these three, and only these three.
TOP_LEVEL_KEYS = ("sections", "series", "log")


def canon_keys(d : dict, order) -> dict:
    """Return `d` rebuilt with the keys in `order` first, then the rest sorted.

    Keys this build has no concept of are **preserved**, not dropped: a section
    can legitimately carry extras (the legacy scalar ``brightness``/``contrast``
    pair survives on any section that has only ever been shuttled opaquely, which
    is why a real section object often has 11 keys where the documented shape has
    9). They are placed after the known keys, in sorted order, so that two files
    with the same content have the same bytes regardless of provenance.

        Params:
            d (dict): the mapping to reorder
            order (tuple): the canonical key order
        Returns:
            (dict) the same items, in canonical order
    """
    out = {}
    for k in order:
        if k in d:
            out[k] = d[k]
    if len(out) != len(d):
        for k in sorted(d, key=str):
            if k not in out:
                out[k] = d[k]
    return out


def canon_keys_inplace(d : dict, order) -> None:
    """Reorder `d`'s keys canonically, in place, preserving the dict's identity.

    Several callers hold a reference to the dict being canonicalized (a section
    dict is written to the hidden directory by its caller; ``series_data``'s
    sub-objects become attributes of the live ``Series``), so the reordering has
    to mutate rather than replace.
    """
    ordered = canon_keys(d, order)
    if list(ordered) != list(d):
        d.clear()
        d.update(ordered)


# ---------------------------------------------------------------------------
# structural pretty printer
# ---------------------------------------------------------------------------
#
# Every leaf is serialized by fast_dumps, so leaf bytes -- number formatting,
# ASCII escaping, orjson-vs-stdlib fallback -- are exactly what the compact
# writer produces. Only the structure is expanded. Coordinates never get a line
# of their own: they are the bulk of the file, and one point per line would be
# both enormous and less readable, not more.

_NL = b"\n"


def _dump_key(k) -> bytes:
    """Serialize `k` as a JSON *object key*, i.e. always a quoted string.

    ``fast_dumps`` passes ``orjson.OPT_NON_STR_KEYS``, so the compact writer
    coerces a non-string key to a string (``1`` -> ``"1"``) and its output is
    valid JSON. Dumping the key on its own does not: ``fast_dumps(1)`` is the
    bare token ``1``, and ``{\n  1: ...\n}`` is not JSON that any parser will
    accept -- the save would succeed and leave behind a file the app cannot
    reopen.

    The coercion is taken from the compact writer itself rather than
    reimplemented, so the two writers cannot drift.
    """
    if isinstance(k, str):
        return fast_dumps(k)
    raw = fast_dumps({k: 0})
    return raw[1:raw.rindex(b":")]


def _dump_mapping_per_line(d, indent : int, out : list) -> None:
    """``{"k": <compact>, ...}`` with one key per line."""
    if not isinstance(d, dict) or not d:
        out.append(fast_dumps(d))
        return
    pad = b" " * (indent + 2)
    body = (b"," + _NL + pad).join(
        [_dump_key(k) + b": " + fast_dumps(v) for k, v in d.items()]
    )
    out.append(b"{" + _NL + pad + body + _NL + b" " * indent + b"}")


def _dump_row_array(rows, indent : int, out : list) -> None:
    """``[<one row per line>]``.

    Written as one join rather than two appends per row: a 391 MB series has
    161,787 trace rows, and the per-row Python overhead is the whole cost of
    pretty-printing.
    """
    if not isinstance(rows, list) or not rows:
        out.append(fast_dumps(rows))
        return
    pad = b" " * (indent + 2)
    body = (b"," + _NL + pad).join([fast_dumps(row) for row in rows])
    out.append(b"[" + _NL + pad + body + _NL + b" " * indent + b"]")


def _dump_contours(contours, indent : int, out : list) -> None:
    """``{"<object name>": [<one trace per line>], ...}``."""
    if not isinstance(contours, dict) or not contours:
        out.append(fast_dumps(contours))
        return
    out.append(b"{" + _NL)
    names = list(contours)
    lastn = len(names) - 1
    inner = indent + 2
    for ni, name in enumerate(names):
        out.append(b" " * inner + _dump_key(name) + b": ")
        _dump_row_array(contours[name], inner, out)
        out.append((b"," if ni != lastn else b"") + _NL)
    out.append(b" " * indent + b"}")


def _dump_section(sd, indent : int, out : list) -> None:
    """One section block: one key per line, contours/flags/tforms expanded."""
    if not isinstance(sd, dict) or not sd:
        out.append(fast_dumps(sd))
        return
    out.append(b"{" + _NL)
    keys = list(sd)
    last = len(keys) - 1
    inner = indent + 2
    for i, k in enumerate(keys):
        out.append(b" " * inner + _dump_key(k) + b": ")
        if k == "contours":
            _dump_contours(sd[k], inner, out)
        elif k == "flags":
            _dump_row_array(sd[k], inner, out)
        elif k == "tforms":
            _dump_mapping_per_line(sd[k], inner, out)
        else:
            out.append(fast_dumps(sd[k]))
        out.append((b"," if i != last else b"") + _NL)
    out.append(b" " * indent + b"}")


#: Series keys whose value is a mapping worth one line per entry.
_SERIES_MAPPINGS = frozenset((
    "obj_attrs",
    "ztrace_attrs",
    "object_groups",
    "ztrace_groups",
    "user_columns",
    "host_tree",
    "options",
))


def _dump_series(sd, indent : int, out : list) -> None:
    """The series object: one key per line, the big mappings expanded."""
    if not isinstance(sd, dict) or not sd:
        out.append(fast_dumps(sd))
        return
    out.append(b"{" + _NL)
    keys = list(sd)
    last = len(keys) - 1
    inner = indent + 2
    for i, k in enumerate(keys):
        v = sd[k]
        out.append(b" " * inner + _dump_key(k) + b": ")
        if k == "palette_traces":
            # {group name: [one 9-field palette row per line]}
            if not isinstance(v, dict) or not v:
                out.append(fast_dumps(v))
            else:
                out.append(b"{" + _NL)
                gnames = list(v)
                lastg = len(gnames) - 1
                for gi, g in enumerate(gnames):
                    out.append(b" " * (inner + 2) + _dump_key(g) + b": ")
                    _dump_row_array(v[g], inner + 2, out)
                    out.append((b"," if gi != lastg else b"") + _NL)
                out.append(b" " * inner + b"}")
        elif k == "ztraces":
            # {ztrace name: {"color": [...], "points": [...]}}
            if not isinstance(v, dict) or not v:
                out.append(fast_dumps(v))
            else:
                out.append(b"{" + _NL)
                znames = list(v)
                lastz = len(znames) - 1
                for zi, z in enumerate(znames):
                    out.append(b" " * (inner + 2) + _dump_key(z) + b": ")
                    _dump_mapping_per_line(v[z], inner + 2, out)
                    out.append((b"," if zi != lastz else b"") + _NL)
                out.append(b" " * inner + b"}")
        elif k == "log_set":
            _dump_row_array(v, inner, out)
        elif k in _SERIES_MAPPINGS:
            _dump_mapping_per_line(v, inner, out)
        else:
            out.append(fast_dumps(v))
        out.append((b"," if i != last else b"") + _NL)
    out.append(b" " * indent + b"}")


def dumps_jser(jser_data : dict, pretty : bool = None) -> bytes:
    """Serialize a whole .jser document to ASCII JSON bytes.

    Minified by default -- a single line, with canonical ordering applied.
    Structurally pretty-printed with compact leaves when `pretty` is True, or
    when ``PYRECON_JSER_PRETTY=1`` is set in the environment.

    Both forms are the same JSON document: pretty-printing adds whitespace and
    nothing else.

        Params:
            jser_data (dict): the assembled document (sections / series / log)
            pretty (bool): force pretty on/off; None consults the environment
        Returns:
            (bytes) the file contents
    """
    if pretty is None:
        pretty = pretty_default()
    if not pretty:
        return fast_dumps(jser_data)
    if not isinstance(jser_data, dict) or "sections" not in jser_data:
        # not a .jser document; nothing structural to expand
        return fast_dumps(jser_data)

    # Each top-level member is built independently and they are joined with
    # ",\n" at the end. Emitting separators inline made the writer's correctness
    # depend on which members happened to be present, which is how it came to
    # invent a "log" key that the compact writer does not write.
    members = []

    # sections: one section block per element, opening brace alone in column 0
    # so that section boundaries are findable in a file no parser will accept.
    part = [b'"sections": [' + _NL]
    sections = jser_data["sections"]
    last = len(sections) - 1
    for i, sd in enumerate(sections):
        if sd is None:
            part.append(b"null")
        else:
            _dump_section(sd, 0, part)
        part.append((b"," if i != last else b"") + _NL)
    part.append(b"]")
    members.append(b"".join(part))

    # "series" and "log" are emitted only when the document actually has them:
    # defaulting them in would *add* keys the compact writer does not write, and
    # the promise at the top of this module is that both writers produce the same
    # document. saveJser always populates all three, so a missing one only arises
    # for a caller assembling a document by hand.
    if "series" in jser_data:
        part = [b'"series": ']
        _dump_series(jser_data["series"], 0, part)
        members.append(b"".join(part))

    if "log" in jser_data:
        members.append(b'"log": ' + fast_dumps(jser_data["log"]))

    # any key this build does not know about is still written, so a hand-added
    # top-level key is not silently destroyed by the pretty printer
    for k in sorted((k for k in jser_data if k not in TOP_LEVEL_KEYS), key=str):
        members.append(_dump_key(k) + b": " + fast_dumps(jser_data[k]))

    return b"{" + _NL + (b"," + _NL).join(members) + _NL + b"}"
