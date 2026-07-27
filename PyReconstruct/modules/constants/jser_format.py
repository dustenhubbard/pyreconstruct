"""Canonical ordering and structural pretty-printing for the .jser writer.

Two writer guarantees live here, and nothing else. Neither changes the schema:
every file this module produces is the same JSON document the compact writer
produced, with the same keys and the same values.

**Canonical ordering.** Five structures are Python ``set`` objects in memory and
JSON arrays on disk (trace ``tags``, series ``editors``, the member lists of
``object_groups`` and ``ztrace_groups``, and the host lists of ``host_tree``).
Set iteration order is not the input order and is not stable across processes, so
two saves of identical content produced different bytes -- byte reproducibility
failed on any series using tags, groups or hosts. Every one of those arrays is now
sorted, and object key order is fixed by ``canon_keys`` so that a dict which was
back-filled by a migration (missing keys appended at the tail) has the same byte
layout as one derived straight from the model. Measured cost: 19 bytes on a
391 MB series.

**Structural pretty-printing.** ``dumps_jser`` expands the document's *structure*
onto lines while keeping every leaf compact: one section block, one trace, one
flag, one transform per line, with coordinate arrays staying on the trace's own
line. Measured cost: +0.65% of bytes on a real 391 MB series.

Why lines matter, concretely:

- A one-trace edit produces a diff of a few kilobytes naming the enclosing object,
  instead of ``diff`` reprinting the whole single-line file twice.
- A **damaged** file stays partially salvageable. ``jq`` refuses to parse
  truncated JSON, so line structure is the only thing that lets ``grep``/``sed``
  recover the intact portion. Section boundaries are therefore deliberately
  findable at a fixed column: every section block opens with ``{`` alone in
  column 0 and its first key is ``  "src":``, and every trace row begins at a
  fixed indent, so ``grep -n '^  "src":'`` enumerates sections and
  ``grep -c '^      \\['`` counts traces even in a file that no JSON parser will
  touch.

Set ``PYRECON_JSER_MINIFY=1`` (or pass ``pretty=False``) to get the old
single-line output; the reader accepts both, since this is whitespace.
"""

import os

from .fast_json import fast_dumps


#: Writer default. Pretty-printing is on unless explicitly disabled, per the
#: format decision ("pretty-print by default, with a writer flag so a minified
#: variant exists if size ever matters").
PRETTY_DEFAULT = os.environ.get("PYRECON_JSER_MINIFY", "") != "1"


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

SERIES_KEYS = (
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


def _dump_mapping_per_line(d, indent : int, out : list) -> None:
    """``{"k": <compact>, ...}`` with one key per line."""
    if not isinstance(d, dict) or not d:
        out.append(fast_dumps(d))
        return
    pad = b" " * (indent + 2)
    body = (b"," + _NL + pad).join(
        [fast_dumps(k) + b": " + fast_dumps(v) for k, v in d.items()]
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
        out.append(b" " * inner + fast_dumps(name) + b": ")
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
        out.append(b" " * inner + fast_dumps(k) + b": ")
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
        out.append(b" " * inner + fast_dumps(k) + b": ")
        if k == "palette_traces":
            # {group name: [one 9-field palette row per line]}
            if not isinstance(v, dict) or not v:
                out.append(fast_dumps(v))
            else:
                out.append(b"{" + _NL)
                gnames = list(v)
                lastg = len(gnames) - 1
                for gi, g in enumerate(gnames):
                    out.append(b" " * (inner + 2) + fast_dumps(g) + b": ")
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
                    out.append(b" " * (inner + 2) + fast_dumps(z) + b": ")
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

    Structurally pretty-printed with compact leaves by default; byte-for-byte the
    old compact single line when `pretty` is False.

        Params:
            jser_data (dict): the assembled document (sections / series / log)
            pretty (bool): override the writer default
        Returns:
            (bytes) the file contents
    """
    if pretty is None:
        pretty = PRETTY_DEFAULT
    if not pretty:
        return fast_dumps(jser_data)
    if not isinstance(jser_data, dict) or "sections" not in jser_data:
        # not a .jser document; nothing structural to expand
        return fast_dumps(jser_data)

    out = [b"{" + _NL]

    # sections: one section block per element, opening brace alone in column 0
    # so that section boundaries are findable in a file no parser will accept.
    out.append(b'"sections": [' + _NL)
    sections = jser_data["sections"]
    last = len(sections) - 1
    for i, sd in enumerate(sections):
        if sd is None:
            out.append(b"null")
        else:
            _dump_section(sd, 0, out)
        out.append((b"," if i != last else b"") + _NL)
    out.append(b"]," + _NL)

    out.append(b'"series": ')
    _dump_series(jser_data.get("series", {}), 0, out)
    out.append(b"," + _NL)

    out.append(b'"log": ' + fast_dumps(jser_data.get("log", "")))

    # any key this build does not know about is still written, so a hand-added
    # top-level key is not silently destroyed by the pretty printer
    extras = [k for k in jser_data if k not in TOP_LEVEL_KEYS]
    for k in sorted(extras, key=str):
        out.append(b"," + _NL + fast_dumps(k) + b": " + fast_dumps(jser_data[k]))

    out.append(_NL + b"}")
    return b"".join(out)
