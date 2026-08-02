# The .jser file format

A `.jser` file is a complete PyReconstruct series: every section, every trace, the
series settings, and the edit log, in one file. This page describes the format
**as it exists on disk today**, derived from the reader and writer code rather than
from intent, so that a collaborator can read or generate a `.jser` without running
PyReconstruct.

Two things to know before reading further:

- **There is no version field.** Nothing in a `.jser` states which revision of the
  format it is. Readers infer the shape from which keys are present. See
  [Versioning and migrations](#7-versioning-and-migrations).
- **The reader and the writer do not agree on everything.** A `.jser` written by
  PyReconstruct is not always what PyReconstruct would produce if it re-derived the
  file from its in-memory model. The known divergences are collected in
  [Reader and writer divergences](#9-reader-and-writer-divergences); they are the parts
  most likely to change in a future canonical version.
- **The writer is canonical, and minified by default.** The same series saved twice
  produces the same bytes ([one documented exception](#canonical-ordering)). The normative
  output form is a single line; **structural pretty-printing is available on request** and
  is off by default, because it costs about 11% of save time and about 27% more transient
  memory in the save path, while canonical ordering costs nothing. See
  [Canonical ordering](#canonical-ordering) and [Line structure](#line-structure). Older
  files have neither property; the reader accepts them regardless.

Every factual claim below is anchored to a source location in the
[References](#10-references) appendix. Anchors were verified against commit `5f16443`.

---

## Contents

- [1. Overview](#1-overview)
- [2. Top level](#2-top-level)
- [3. The section object](#3-the-section-object)
- [4. Positional rows](#4-positional-rows)
- [5. The series object](#5-the-series-object)
- [6. The options bag](#6-the-options-bag)
- [7. Versioning and migrations](#7-versioning-and-migrations)
- [8. A minimal valid file](#8-a-minimal-valid-file)
- [9. Reader and writer divergences](#9-reader-and-writer-divergences)
- [10. References](#10-references)

---

## 1. Overview

### One JSON document

A `.jser` is a single JSON object. There is no container, no compression, no
concatenation, and no trailing newline. The file is written in one shot as bytes and
replaced over the previous file atomically, so a crash mid-save cannot truncate an
existing series.

It is written **minified** (one line, no indentation) with
[canonical ordering](#canonical-ordering) applied. Setting `PYRECON_JSER_PRETTY=1`
switches the writer to a **structurally pretty-printed** form with compact leaves: the
document's structure is expanded onto lines, one section block / trace / flag / transform
per line, while every leaf value (coordinate arrays included) stays compact on the line
it belongs to. Both forms are the same JSON document. See
[Line structure](#line-structure).

### Canonical ordering

**The same series saved twice produces the same bytes.** Two saves of the same series, in
different processes with different hash seeds, byte-compare equal. That is the guarantee a
generator may rely on and a consumer may test against, and it is what makes byte-level
diffing of a `.jser` in version control work.

Stated precisely, because the stronger reading is not true yet: what is canonical is the
**order** of everything the writer emits (set-derived arrays, object keys, contour names),
independent of provenance. What is *not* yet canonical is the **key set** of a section
object. A section that has only ever been shuttled opaquely keeps the legacy scalar
`brightness`/`contrast` pair (divergence 2); the same section re-derived from the model
does not, because `Section.getDict` never emits it. So the same content can still differ
by those two keys depending on whether the user has touched that section, and the byte
difference cascades from there. Closing that gap means deciding whether the legacy pair is
data or debris, which is a schema question, not a writer question. See divergence 2.

Making it true required sorting the five structures that are Python `set` objects in
memory and JSON arrays on disk. Each is written in **sorted order**:

| Where | Field |
| --- | --- |
| trace row | `tags` (see [4.1](#41-trace-rows)) |
| series | `editors` |
| series | `object_groups`: group names, and each group's member list |
| series | `ztrace_groups`: group names, and each group's member list |
| series | `host_tree`: object names, and each object's host list |

Object key order is fixed as well, because a dict that a migration back-filled used to
carry its missing keys appended at the tail, so byte layout leaked a file's provenance:

- **Top level:** `sections`, `series`, `log`.
- **Section:** the nine keys in the order given in [section 3](#3-the-section-object).
  Keys this build has no concept of are **preserved**, sorted, after the nine. Most
  commonly that is the legacy scalar `brightness`/`contrast` pair, which is why a real
  section object often has 11 keys where the documented shape has 9 (divergence 2).
- **Series:** the order given in [section 5](#5-the-series-object).
- **Options bag:** the order of the writer's own template
  ([section 6](#6-the-options-bag)).
- **Contour names** within a section's `contours`: sorted.

Sorting is by Python's `sorted()` on the strings, i.e. by ASCII code point, so it is
case-sensitive and uppercase sorts before lowercase.

Because sorting reorders bytes without adding or removing any, canonical ordering is
**size-neutral**: measured at 0 bytes of difference on a 391 MB series.

### Line structure

**Opt in with `PYRECON_JSER_PRETTY=1`.** The default output is a single line; everything
in this section describes what you get when you ask for the pretty form, and applies to
files written with it. The layout is chosen so that a `.jser` can be worked with by
line-oriented tools, including on a file no JSON parser will accept.

```
{
"sections": [
null,
{
  "src": "Cropped Images/d03/001ZGBJY.tif",
  "brightness_contrast_profiles": {"default":[0,0]},
  "mag": 0.00204844,
  "align_locked": true,
  "tforms": {
    "default": [1.0,0.0,5.5738052,0.0,1.0,18.2905208]
  },
  "thickness": 0.05,
  "contours": {
    "d03": [
      [[5.000242,5.018678, ... ],[9.0165505,9.0319021, ... ],[255,0,0],true,false,false,["none","none"],["axon"]]
    ]
  },
  "flags": [],
  "calgrid": false
},
...
],
"series": {
  "current_section": 0,
  ...
},
"log": "Date, Time, User, Obj, Sections, Event\n..."
}
```

The layout rules, stated as guarantees:

| Structure | Line |
| --- | --- |
| a section object | opens with `{` alone in column 0, closes with `}` in column 0 |
| a `null` section | `null` alone on its line |
| a section key | one per line, indented 2 |
| a contour name | one per line, indented 4, as `    "<name>": [` |
| a trace row | one per line, indented 6, complete and self-contained |
| a palette trace row | one per line, **also indented 6** (see the caveat under [Line structure](#line-structure)) |
| a flag row | one per line, indented 4 |
| a transform | one per line, indented 4 |
| the series object | one key per line, indented 2; the large maps expand one entry per line |
| `log` | one line, however long |
| coordinates | **never** get a line of their own |

What that buys, in the two cases it was chosen for:

**A one-trace edit is a small diff.** `diff -U2` of a 4.3 MB series before and after one
trace moved: **8,694,122 bytes of output before, 544 bytes after**. The enclosing object
name appears as diff context, so a reviewer sees which object on which section changed
with no tooling at all. On the single-line form `diff` can only say "line 1 changed" and
reprint the whole file twice.

**A damaged file stays partially salvageable.** Recovery by reading a `.jser` directly is
a real workflow, and `jq` refuses to parse truncated or corrupt JSON. Line structure makes
that recovery a matter of line-anchored patterns instead of hand-written regexes. From a
file cut in half:

```sh
grep -c '^  "src":'     series.jser   # sections, one match per live section
grep -c '^      \['     series.jser   # trace rows -- see the caveat below
grep -n '"d01": \['     series.jser   # every section carrying object d01, with line numbers
sed -n '8068p'          series.jser   # exactly one trace row, valid JSON on its own
```

Every trace row recovered this way parses independently as JSON, because the whole row is
on one line.

Measured on a real 393 MB series (318 sections, 161,767 section traces) truncated to
exactly half its length: `jq` refuses the file, while `grep` still finds **161 sections
and 80,111 trace rows**, locates all 159 surviving sections carrying a named object, and
`sed -n Np` on any of those lines yields a row that parses on its own.

Two caveats, so the recipes above are not read as more than they are:

- **`^      \[` is not exactly "trace rows."** Palette trace rows sit at the same indent,
  so on a whole file the count is section traces **plus** the 20-or-so palette rows, and a
  palette row is a 9-field row whose first field is the trace name, a different shape
  from an 8-field section trace row. Filter on shape, not on indent alone, if the
  distinction matters.
- **`^{$` also matches the document's own opening brace.** `grep -c '^  "src":'` is the
  exact section count.

**What line structure does *not* buy.** It is worth being precise, because this is the
argument that used to justify pretty-printing every save, and it does not carry that
weight. The same cut on the **minified** form is not unrecoverable, merely less
convenient. Line-anchored patterns find nothing there, since there are no lines, but
non-anchored ones do: `grep -oa '"src":'` finds the same **161** sections, and one
`grep -oE` for the trace-row shape recovers **79,736** complete, individually-parseable
rows in about a second, 99.5% of what the pretty form yields. So line structure buys
**obvious, exact, tool-friendly salvage** (a fixed column, `sed -n Np`, the enclosing
object name as context) rather than the difference between recoverable and lost.

The readable-diff argument is the one that holds, and it is why the printer is still here:
a one-trace edit on a 781 MB series is 781,692,354 bytes of `diff` output minified against
**669 bytes** pretty. That is worth asking for when a human is going to read the diff. It
is not worth paying for on every save.

### Choosing the output form

| | default | `PYRECON_JSER_PRETTY=1` |
| --- | --- | --- |
| layout | one line | one section block / trace / flag / transform per line |
| canonical ordering | applied | applied |
| size, 391 MB series | 390,846,078 B | 393,372,829 B (+0.65%) |
| `saveJser` wall time | baseline | about +11% |
| save-path transient memory | baseline | +27% (an extra copy of the document) |

`PYRECON_JSER_PRETTY` is read **on every write**, not once at import, so it can be set,
changed or cleared in a running process and the next save honors it. `pretty=True` /
`pretty=False` passed to `dumps_jser` overrides the environment.

The reader accepts either form: this is whitespace, so it is backward-compatible in both
directions. The variable governs **whitespace only**:
[canonical ordering](#canonical-ordering) always applies, so a
minified file written by this build is *not* byte-identical to one written by a build from
before ordering was canonical. There is deliberately no switch that turns canonical
ordering off.

### Encoding and byte-level invariants

The file is **pure ASCII**. Every byte is below `0x80`. Characters outside the ASCII
range are written as JSON `\uXXXX` escapes, and code points above `U+FFFF` are written
as a UTF-16 surrogate pair, exactly as the Python standard library does with
`ensure_ascii=True`.

This is deliberate. Stock upstream PyReconstruct on Windows reads series and section
files in the platform's locale text mode (cp1252, not UTF-8). A fork-written file
carrying raw multi-byte object names or comments would decode to mojibake there.
Restricting output to ASCII keeps files readable by those locale-mode readers, because
ASCII is a subset of cp1252, latin-1 and UTF-8 alike.

Consequences for anyone generating a `.jser`:

| Invariant | Detail |
| --- | --- |
| ASCII only | Non-ASCII must be `\uXXXX`-escaped. Raw UTF-8 is readable by PyReconstruct but is not what it writes, and may corrupt on a locale-mode reader. |
| Object keys are strings | The writer is configured to accept non-string mapping keys and coerce them, so an integer key becomes the decimal string. A generator should just write strings. |
| Compact leaves | Inside a leaf value the writer emits `{"a":1}`, with no space after `:` or `,`. Only the document's *structure* carries whitespace; see [Line structure](#line-structure). |
| Canonical order | Set-derived arrays are sorted and object keys are in a fixed order, so identical content is identical bytes. See [Canonical ordering](#canonical-ordering). |
| No `NaN` or `Infinity` | Every serialized number is finite. The fast writer would silently turn a non-finite float into `null`; nothing PyReconstruct serializes can reach that path. |
| 64-bit integer range | Integers outside the signed/unsigned 64-bit range are not produced. Reading such a value coerces it to a float. |

One caveat on separators. The writer prefers `orjson` and falls back to the standard
library `json` module whenever `orjson` raises. The two produce different bytes for the
same document: `orjson` is compact, the standard library inserts a space after `:` and
`,`. Both are valid JSON and both parse identically, but a `.jser` saved on a machine
without `orjson` installed will differ from one saved with it, byte for byte, on every
line. `orjson` is a declared dependency, so this is an install-integrity concern rather
than a routine one. It is also the one exception to the byte-reproducibility guarantee
above: reproducibility holds between saves that used the same JSON backend.

### The hidden unpack directory

The `.jser` is the durable, shareable artifact. It is **not** what PyReconstruct reads
from while you work.

Opening `series.jser` in a directory `D` does the following:

1. Creates a hidden directory `D/.series/`.
2. Writes one file per non-empty section, named `series.<section_number>`, containing
   that section's JSON object.
3. Writes `D/.series/existing_log.csv`, containing the top-level `log` string verbatim.
4. Writes `D/.series/series.ser`, containing the `series` object.

The `.ser` file is written **last, on purpose**. It is the completion sentinel: both
recovery paths require it, so a canceled or crashed open can never leave a partial
hidden directory that is later mistaken for unsaved work. If the open is canceled or
raises, the whole hidden directory is removed.

Two consequences that matter:

- **The hidden directory wins.** If `D/.series/series.ser` already exists when you open
  `D/series.jser`, PyReconstruct loads the hidden directory and **never reads the
  `.jser` at all**. This is how unsaved work survives a crash. It also means that
  editing a `.jser` by hand while a stale hidden directory is present has no effect.
- **Sections are shuttled as opaque JSON.** Saving reads each `series.<n>` file back
  and drops it into the output array without interpreting it. A section that was never
  loaded and re-saved during the editing session travels from input `.jser` to output
  `.jser` byte-for-byte identically in content, including keys PyReconstruct does not
  understand. The `series` object does not work this way: it is always rebuilt from the
  in-memory model on save. See
  [Reader and writer divergences](#9-reader-and-writer-divergences).

While a series is open, the section files in the hidden directory are re-written on
every section change. They are deliberately not `fsync`ed, because that would turn a
mouse-wheel scroll into a synchronous disk flush. The `.jser` is the durable copy and
is `fsync`ed.

---

## 2. Top level

```json
{
  "sections": [ null, { ... }, { ... } ],
  "series":   { ... },
  "log":      "Date, Time, User, Obj, Sections, Event\n..."
}
```

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `sections` | array | yes | Section objects, indexed by section number. Elements may be `null`. |
| `series` | object | yes | Series-wide state and settings. See [section 5](#5-the-series-object). |
| `log` | string | no | The edit history as CSV text. Defaults to the header line alone if absent. |

The writer emits the keys in exactly this order.

A file is rejected as invalid if it is not JSON, if the root is not an object, if
`series` is not an object, if `sections` is not an array, or if `sections` contains no
non-`null` element.

### Why `sections` is an array with holes

`sections` is a **positional array, not a map**. The element at index `n` is the section
numbered `n`. Section numbers are therefore constrained to be non-negative integers, and
the array length is always `max(section_number) + 1`.

`null` appears at every index that is not a live section number. Holes occur whenever
the set of section numbers is not exactly `0..N-1`:

- **Deleting sections.** Deleting section 3 from a 10-section series leaves `null` at
  index 3. Numbering of the surviving sections is not compacted.
- **Series that do not start at 0.** A series whose lowest section number is 1 has
  `null` at index 0. Series created by PyReconstruct itself are 0-based, but imported
  and hand-built series need not be.

Both are round-trip stable: a hole in the input `.jser` is a hole in the output `.jser`.

The array carries no section-number field of its own, so **the position is the only
record of a section's number**. Reordering the array renumbers the sections.

### The `log` string

`log` is the series edit history as a single string of comma-separated text. It is not
JSON-structured. Its first line is the header

```
Date, Time, User, Obj, Sections, Event
```

and each subsequent line is one event:

```
26-07-26, 18:33, dusten, d001, 12 15-19 30, Modified trace(s)
```

| Column | Format | Meaning |
| --- | --- | --- |
| Date | `YY-MM-DD` | Two-digit year. |
| Time | `HH:MM` | 24-hour. No timezone marker. Local or UTC depending on a computer-scoped setting, so a shared series' history can interleave both. |
| User | string | Username of the editor. |
| Obj | string | Object name, or a bare `-` for events with no object. |
| Sections | string | Space-separated inclusive ranges. A single section is `12`; a run is `15-19`. A bare `-` means no sections. |
| Event | string | Free text description. |

Parsing rules that a generator must respect:

- The delimiter is the **two-character sequence `", "`**, comma followed by space. A
  comma not followed by a space never splits a field.
- **There is no quoting or escaping.** Fields beyond the sixth are re-joined into the
  Event column, so **a comma is safe in Event and only in Event**. A comma in a username
  or object name shifts every later field and makes the row unparseable. This is one
  reason contour names have their commas replaced with underscores.
- Blank lines are skipped.
- Leading and trailing whitespace in the Event column is stripped.
- A negative number cannot appear in the Sections column, because `-` is both the null
  marker and the range separator.

The string is assembled on save from two sources: the frozen history in the hidden
directory's `existing_log.csv`, and the events logged during the current session. The
session's events are appended after a newline, so a doubled newline can appear at the
join. Readers tolerate it.

---

## 3. The section object

Nine keys, **emitted in the order of the table below**. All are required by the writer; a
reader back-fills any that are missing from an empty-section template before use, and then
reorders the object canonically, so a back-filled section is byte-identical to one derived
straight from the model.

A section may legitimately carry *more* than these nine. Keys this build has no concept of
are preserved, sorted, after the nine. Most often that is the legacy scalar `brightness`
and `contrast` pair (divergence 2), which is why a real section object frequently has 11
keys.
A generator may add its own keys and they will survive, as long as the section is never
re-derived from the model.

| Key | JSON type | Units / legal values | Meaning |
| --- | --- | --- | --- |
| `src` | string | filename | The section's image, as a bare filename. Resolved against the series `src_dir`. A path is accepted on read but reduced to its basename. |
| `brightness_contrast_profiles` | object | name -> `[brightness, contrast]` | Named image adjustment profiles. Both values are integers that the UI clamps to `[-100, 100]`; nothing enforces the range on load. Must contain the key named by the series' `current_brightness_contrast_profile`. |
| `mag` | number | µm per image pixel | Magnification. Default for a new section is `0.00254`. |
| `align_locked` | boolean | | Whether the section's alignment is locked against edits. **Forced to `true` whenever a `.jser` is unpacked**, regardless of the stored value. (Resuming from an existing hidden directory does not go through the unpack path and does keep the stored value.) |
| `tforms` | object | alignment name -> 6-number array | One affine transform per alignment. See [4.4](#44-transforms). Must contain the alignment named by the series' `alignment`. The reserved name `no-alignment` is deleted on read and never written. |
| `thickness` | number | µm | Section thickness. Default for a new section is `0.05`. |
| `contours` | object | contour name -> array of trace rows | The section's traces, grouped by name. See [4.1](#41-trace-rows). |
| `flags` | array | array of flag rows | The section's flags. See [4.2](#42-flag-rows). |
| `calgrid` | boolean | | Marks the section as a calibration grid image. |

### Coordinates

Trace points, flag positions and the series `window` are all in **field coordinates,
in µm**, with the origin at the **bottom-left corner of the image** and `y` increasing
upward. The conversion to image pixels is

```
x_px = x / mag
y_px = image_height_px - (y / mag)
```

Field coordinates are stored **untransformed**. The section's `tforms` entry for the
active alignment is applied when the trace is drawn or measured, not when it is stored.
Changing an alignment therefore rewrites `tforms` and leaves every trace row untouched.

### Contour names

Contour names are written **sorted**, so an object added late in a session lands in the
same place as one that was there from the start.

A contour name is the shared name of every trace inside it, and it is also the object
name used across the whole series. Names are normalized on read: leading and trailing
whitespace is stripped, runs of internal whitespace collapse to a single `_`, and each
comma becomes `_`. If normalizing two distinct keys produces the same name, their trace
lists are concatenated.

So `"my square, big"` on disk becomes the contour `my_square__big` in memory, and that
is what the next save writes. **A contour name containing a space or a comma is not
stable across a load.** Flag names, by contrast, are not normalized and may contain
spaces and commas freely.

### Empty and defective contours

- A trace row with fewer than two points is removed on read.
- A contour whose trace list becomes empty is removed on read.
- On write, a contour with no traces is omitted.

A generator therefore cannot use a `.jser` to record a named object with no geometry on
a section.

---

## 4. Positional rows

Traces, flags, comments, transforms and ztrace points are stored as **positional
arrays**, not keyed objects. Position is meaning. This section documents each layout
normatively.

### 4.1 Trace rows

A trace row appears in two arities depending on where it is stored.

**Inside a section's `contours`: 8 elements, no name.** The name comes from the enclosing
contour key.

| Index | Field | JSON type | Legal values |
| --- | --- | --- | --- |
| 0 | `x` | array of numbers | Field x coordinates, µm. Length >= 2. |
| 1 | `y` | array of numbers | Field y coordinates, µm. Same length as `x`. |
| 2 | `color` | array of 3 integers | `[R, G, B]`, each `0..255`. |
| 3 | `closed` | boolean | `true` for an area outline, `false` for an open curve. |
| 4 | `negative` | boolean | `true` if the trace subtracts area (a hole). |
| 5 | `hidden` | boolean | `true` if the trace is not drawn. |
| 6 | `fill_mode` | array of 2 strings | `[style, condition]`. See below. |
| 7 | `tags` | array of strings | Free-form tags. Held as a set in memory, so order is not meaningful; the writer emits them **sorted**. |

**Inside `series.palette_traces`: 9 elements, name first.** Index 0 is the trace name as
a string; indices 1 through 8 are the eight fields above, shifted by one.

Notes that apply to both arities:

- **`x` and `y` are parallel arrays, not a list of pairs.** A trace with points
  `(1,2)` and `(3,4)` is `[[1,3],[2,4],...]`, not `[[1,2],[3,4],...]`.
- Coordinates are **rounded to 7 decimal places on write**. A generator supplying more
  precision will see it truncated the first time PyReconstruct re-saves that section.
- `fill_mode` is `[style, condition]`. `style` is one of `"none"`, `"transparent"`,
  `"solid"`. `condition` is one of `"none"`, `"always"`, `"selected"`, `"unselected"`,
  and says when the fill is drawn. The two are coupled: `style` of `"none"` always pairs
  with `condition` of `"none"`, and any other style pairs with one of the remaining three
  conditions. `["solid", "always"]` is the built-in scale bar's mode. Note that a
  Reconstruct XML import can never produce `"always"`, because the legacy integer mode
  encodes only selected and unselected.
- `fill_mode` must be a JSON array. Any other type (including the legacy integer mode
  from Reconstruct XML) is replaced with `["none","none"]` on read.
- A trace with exactly two points is `closed = false`, regardless of the stored flag: two
  points enclose no area. The flag is corrected on unpack as well as in memory, so a
  `.jser` written by this build never carries `closed: true` on a two-point row. See
  [section 9](#9-reader-and-writer-divergences).
- A 9-element row inside `contours` and a 10-element row inside `palette_traces` are
  legacy shapes carrying a trailing per-trace history object. The extra element is
  dropped on read.
- Row arity is how the name is located, and the two rules interact. The decoder takes
  index 0 as the name if no external name was supplied **or** if the row has 9 elements.
  A 9-element row therefore always names itself, even when a name is passed in
  alongside. Conversely, an 8-element row with no external name raises `ValueError`. In
  practice the contour key always supplies the name, so this only bites a direct caller.
- The decoder **mutates the row it is given** (it pops the name off the front), so a row
  cannot be decoded twice.
- `tags` is held in memory as a set. When a section is re-saved from the in-memory model,
  the tag order in the output is the set's iteration order and is **not the input order**.
  Two saves of the same data in different processes can emit different tag orderings.

### 4.2 Flag rows

7 elements.

| Index | Field | JSON type | Legal values |
| --- | --- | --- | --- |
| 0 | `id` | string | 6 characters drawn from `A-Za-z0-9`. Generated randomly; used to match flags across imports. |
| 1 | `name` | string | Free text. Not normalized. |
| 2 | `x` | number | Field x, µm. |
| 3 | `y` | number | Field y, µm. |
| 4 | `color` | array of 3 integers | `[R, G, B]`, each `0..255`. |
| 5 | `comments` | array | Comment rows. See [4.3](#43-comment-rows). |
| 6 | `resolved` | boolean | `true` once the flag is marked resolved. |

The flag's **section number is not stored**. It is taken from the position of the
containing section in the `sections` array.

Legacy arities are repaired on read by two consecutive checks, not a branch: a 5-element
row gains `resolved = false` at the end, and a 6-element row gains a freshly generated
`id` at the front. Because the checks run in sequence, a 5-element row picks up both
repairs in one pass and arrives at 7 elements. Note that repairing a legacy flag
**assigns a new random id on every unpack** until the section is saved, so flag identity
is not stable across opens for such files.

### 4.3 Comment rows

4 elements, used inside a flag's `comments` array.

| Index | Field | JSON type | Legal values |
| --- | --- | --- | --- |
| 0 | `user` | string | Author. |
| 1 | `text` | string | Comment body. |
| 2 | `date` | string | `YY-MM-DD`. |
| 3 | `time` | string | `HH:MM`. |

### 4.4 Transforms

A transform is an array of exactly 6 numbers describing a 2D affine map:

```
[ a, b, c,
  d, e, f ]
```

applied as

```
x' = a*x + b*y + c
y' = d*x + e*y + f
```

The identity is `[1, 0, 0, 0, 1, 0]`. Element `c` is the x translation and `f` is the y
translation, both in field µm. This is the row-major 2x3 layout used by Reconstruct, not
the column-major order of the underlying Qt matrix type; the conversion happens in the
transform constructor.

Each section's `tforms` object holds one such array per alignment name. `"default"` is
the conventional name of the base alignment. The name `no-alignment` is reserved: it
always means the identity, is never stored, and is deleted from `tforms` on read.

### 4.5 Palette entries

`series.palette_traces` is an object mapping a palette group name to an ordered array of
9-element trace rows (see [4.1](#41-trace-rows)). Each entry is a stamp shape: its
coordinates are small offsets around the origin, in field µm, and define both the shape
and the size of the stamp. Every shipped default shape has a radius of exactly 0.1 µm,
which puts its bounding extents between 0.14 and 0.20 µm depending on the shape.

`series.palette_index` is a 2-element array `[group_name, slot_index]` naming the
currently selected palette entry. `group_name` must be a key of `palette_traces`;
`slot_index` must be a valid index into that group's array. Neither is validated on
load, so an out-of-range `slot_index` opens without complaint and fails later in the UI.

The palette array is dense and ordered: slot order is button order. There is no fixed
palette size.

### 4.6 Ztrace points

A ztrace point is a 3-element array `[x, y, section_number]`, with `x` and `y` in field
µm and `section_number` an integer index into `sections`. Points are stored in path
order, not sorted by section, so a ztrace may revisit or skip sections.

---

## 5. The series object

Eighteen keys, listed here in the order the writer emits them. Unlike a section, the
series object is **always rebuilt from the in-memory model on save**, so an unrecognized
key does not survive a save.

| Key | JSON type | Meaning |
| --- | --- | --- |
| `current_section` | integer | The section number the user was last viewing. UI state only. Must be a live section number. |
| `src_dir` | string | Directory containing the section images. See [5.1](#51-src_dir). |
| `window` | array of 4 numbers | `[x, y, w, h]` of the field view in field µm. `w` and `h` are extents, not corners, and must be non-zero. Default `[0, 0, 1, 1]`. |
| `palette_traces` | object | Palette group name -> array of 9-element trace rows. See [4.5](#45-palette-entries). |
| `palette_index` | array `[string, integer]` | Selected palette group and slot. |
| `ztraces` | object | Ztrace name -> `{"color": [R,G,B], "points": [[x, y, section], ...]}`. See [5.2](#52-ztraces). |
| `alignment` | string | Name of the active alignment. Must be a key of every section's `tforms`, or the reserved `"no-alignment"`. Default `"default"`. |
| `object_groups` | object | Group name -> array of object names. Group names and members are both written **sorted**. See [5.3](#53-groups-hosts-and-attributes). |
| `ztrace_groups` | object | Group name -> array of ztrace names. Same shape, also sorted. |
| `obj_attrs` | object | Object name -> attribute object. See [5.3](#53-groups-hosts-and-attributes). |
| `ztrace_attrs` | object | Ztrace name -> attribute object. In practice only `alignment` is ever written. |
| `current_brightness_contrast_profile` | string | Name of the active image adjustment profile. Must be a key of every section's `brightness_contrast_profiles`. Default `"default"`. |
| `options` | object | Series-scoped settings. See [section 6](#6-the-options-bag). |
| `log_set` | array of strings | Optional. Pending log rows, each a complete CSV line in the format of [the log string](#the-log-string). See divergence 5 in [section 9](#9-reader-and-writer-divergences). |
| `editors` | array of strings | Usernames that have edited the series. A set in memory, so the order is not meaningful; the writer emits it **sorted**. If the stored array is empty, it is recomputed from the log history on load. |
| `code` | string | Series code: a short identifier independent of the filename. Used as the leading field of exported object tables and as the namespace for per-series computer settings. `""` means unset, and it is the only value the UI rejects. Any other string is accepted, including one containing the delimiters used by the exporters. A configurable regex (default `[0-9A-Za-z]+`) is a *detection* pattern applied to the file name to pre-fill a suggestion; it does not validate what the user enters. |
| `user_columns` | object | Column name -> array of permitted option strings. See [5.4](#54-user_columns). |
| `host_tree` | object | Object name -> array of its host names. Object names and host lists are both written **sorted**. See [5.3](#53-groups-hosts-and-attributes). |

### 5.1 `src_dir`

A plain filesystem directory path. It is joined to each section's `src` to locate the
image, with no anchoring, so:

- A writer **should** emit an absolute path.
- A reader **must not** assume the path is relative to the `.jser`. A relative value
  resolves against the process working directory, which makes it effectively unportable.
- `""` is the canonical "images unknown" value, and it is the default for a series that
  has never been pointed at images. The application prompts the user to relocate them.
  This is the right value to emit when generating a `.jser` for someone else, since the
  image directory differs between collaborators.

One sentinel is load-bearing: **if `src_dir` ends with the literal text `zarr`**, images
are read from a multiscale Zarr store and each section's `src` is looked up inside a
`scale_N/` subgroup rather than directly in the directory. The test is a suffix match on
`zarr`, not on `.zarr`, so a directory named `project-zarr` also triggers Zarr mode.

### 5.2 `ztraces`

```json
"ztraces": {
  "dendrite_path": {
    "color": [255, 0, 255],
    "points": [[3.90264, 0.82584, 0], [4.16296, 0.98186, 1]]
  }
}
```

Both `color` and `points` are **required**; a missing key raises on read. The ztrace name
is the enclosing key and is never stored inside the value.

`color` is `[R, G, B]` with each component an integer `0..255`.

`points` is an array of `[x, y, section_number]`, with `x` and `y` in field µm and
`section_number` an integer index into `sections`. Unlike trace coordinates, **ztrace
coordinates are not rounded on write**; full float precision is emitted. Points are in
path order, so a ztrace may revisit or skip sections.

Legacy form: `ztraces` may be an **array** of objects each carrying its own `"name"` key.
It is converted to the keyed form on read, with a missing `color` defaulting to yellow.
Only the keyed form is ever written. Note that the empty-series template still declares
`ztraces` as an empty array, so a freshly created series is migrated on its first load.

### 5.3 Groups, hosts, and attributes

**`object_groups` and `ztrace_groups`** map a group name to an array of member names.
The direction is group to members, not the inverse. In memory the members are a set, so
**the array order is not stable across processes**. A group is dropped on read if none of
its members is truthy, so both `[]` and `[""]` remove the group.

**`host_tree`** maps an object name to an array of its hosts, meaning its parents. An
object with no hosts is omitted entirely. The inverse index is recomputed on load and is
never stored. Two notes:

- The reader accepts a bare string where the writer only ever emits an array, so
  `{"obj": "host"}` loads as `{"obj": ["host"]}`.
- **Loading is not an identity operation.** A host that is already a transitive superhost
  of the same object is pruned on load and will not be written back.

**`obj_attrs`** maps an object name to a flat attribute object. Exactly eight attribute
keys exist:

| Attribute | JSON type | Legal values | Default when absent |
| --- | --- | --- | --- |
| `3D_mode` | string | `"surface"`, `"spheres"`, `"contours"` | `"surface"` |
| `3D_opacity` | number | `0.0` to `1.0` inclusive | `1` |
| `last_user` | string | username | `""` |
| `curation` | array of 3 | `[curated, user, date]`; `curated` boolean, `date` as `YY-MM-DD` | absent |
| `comment` | string | free text | `""` |
| `alignment` | string | an alignment name, overriding the series-wide one for this object | absent |
| `locked` | boolean | | `false` |
| `user_columns` | object | column name -> **a single option string** | `{}` |

Absent and null are not distinguishable: setting an attribute to `null` deletes the key,
and an object whose attribute set becomes empty is removed from `obj_attrs` entirely. A
writer therefore never emits a `null` attribute value or an empty per-object object.

Note that **group membership is not an object attribute**. It lives only in
`object_groups` and `ztrace_groups`.

Legacy form: a `3D_modes` key holding `[mode, opacity]` is split into `3D_mode` and
`3D_opacity` on read. Older still, the top-level series keys `object_3D_modes`,
`last_user` and `curation` were per-object maps; they are folded into `obj_attrs` on read
and never written again.

### 5.4 `user_columns`

`series.user_columns` maps a user-defined column name to an **array** of permitted option
strings. Spaces in both the column name and every option are replaced with `_` when the
column is created or edited.

Per-object selection lives elsewhere, in `obj_attrs[name]["user_columns"]`, where the
same key name maps a column name to a **single option string**. The list lives at series
level; the scalar choice lives at object level. Editing a column's option list deletes any
per-object value that is no longer a valid option.

---

## 6. The options bag

`series.options` is a small, **closed** set of series-scoped settings. It is not a
general-purpose extension point.

### The keys

| Key | JSON type | Default | Meaning |
| --- | --- | --- | --- |
| `object_columns` | array of `[string, boolean]` | see below | Which optional columns the object list shows, in display order. |
| `trace_columns` | array of `[string, boolean]` | see below | Same, for the trace list. |
| `flag_columns` | array of `[string, boolean]` | see below | Same, for the flag list. |
| `section_columns` | array of `[string, boolean]` | see below | Same, for the section list. |
| `ztrace_columns` | array of `[string, boolean]` | see below | Same, for the ztrace list. |
| `small_dist` | number | `0.01` | Finest 2D alignment nudge step, in field µm. |
| `med_dist` | number | `0.1` | Fine 2D alignment nudge step, in field µm. |
| `big_dist` | number | `1` | Coarse 2D alignment nudge step, in field µm. |
| `autoseg` | object | `{}` | Dormant. See below. |

Column defaults, in order:

- `object_columns`: `Range` on, `Count` off, `Flat area` off, `Volume` off, `Radius` off,
  `Host` on, `Superhosts` off, `Groups` on, `Trace tags` off, `Locked` on, `Last user`
  on, `Curate` off, `Alignment` off, `Comment` on, `Configuration` off.
- `trace_columns`: `Index` off, `Tags` on, `Hidden` on, `Closed` on, `Length` on,
  `Area` on, `Radius` on, `Centroid` off, `Feret` off.
- `flag_columns`: `Section` on, `Color` on, `Flag` on, `Resolved` off,
  `Last Comment` on.
- `section_columns`: `Thickness` on, `Locked` on, `Brightness` on, `Contrast` on,
  `Image Source` on.
- `ztrace_columns`: `Start` on, `End` on, `Distance` on, `Groups` on, `Alignment` on.

Columns absent from a stored list are appended from these defaults on first use, so an
old `.jser` gains new columns without losing the user's ordering.

Each `*_columns` value **must be a JSON array**. Nothing validates this at load time: the
option getter returns a series-scoped value before it reaches the type check that exists
for computer-scoped options, so a `.jser` carrying `"object_columns": {}` opens without
complaint and round-trips back to disk unchanged. It fails later, inside the table code,
with an error that says nothing about the file. Treat the array requirement as normative
and unenforced.

`autoseg` is a dormant placeholder, because the automatic segmentation feature that
populated it is disabled. A series that never had it populated carries `{}`. Historic
files may carry a flat map of job parameters (`zarr_current`, `iters`, `model_path`,
`thresholds` and similar), and because `autoseg` is a recognized top-level key, that
content is **preserved indefinitely** rather than pruned. Nothing reads it. Note that
autoseg *colors* are not here; they are computer-scoped (see below).

### Unknown keys are silently deleted

On every open, `options` is reconciled against the built-in template in two passes:
missing keys are added with their defaults, then **any key not in the template is
deleted**. There is no warning, no log entry, and no preservation. A collaborator's
`.jser` written by a newer build with an extra option loses that option the moment an
older build opens it.

The prune inspects **top-level `options` keys only**. Nested content is never examined,
which is why stale `autoseg` job parameters and unrecognized column entries survive
indefinitely.

After the two reconciliation passes the bag is reordered into the template's own key
order, so a bag whose missing keys were back-filled at the tail is byte-identical to one
that arrived complete.

The set of top-level `options` keys also cannot grow at runtime. The setter writes into
`options` only when the key is already present; an unknown option name is dropped
silently. So the nine keys above are the complete on-disk set, not merely the ones
observed in one file.

### Series scope versus computer scope

`options` is only one of three places PyReconstruct keeps settings. A setting lookup
resolves in this order:

1. **`series.options`** in the `.jser`. Travels with the file. The nine keys above.
2. **Per-series computer settings**, stored in the OS settings store under an
   application name derived from the series `code` field. Two keys: `autobackup` and
   `backup_dir`. These are series-specific but **do not travel with the `.jser`**,
   because the store is local to the machine. A collaborator opening the same file gets
   their own values.
3. **Global computer settings**, stored in the OS settings store under a single
   application name. Everything else: username, theme, keyboard shortcuts, 3D
   rendering options, mouse tool behavior, update channel, autoseg color palette and
   seed, scale bar options, and the recent-series list.

An unknown setting name resolves to `null` on read and is dropped on write, in both
cases without an error.

Reading a computer-scoped setting that has never been set has a side effect: the default
is written into the store. First read materializes the key.

This split is the result of a deliberate migration. Options that were once in the
`.jser` and are now computer-scoped include `autosave` (dropped entirely, no replacement
exists), `3D_smoothing`, `show_ztraces`, `fill_opacity`, `grid`, `pointer`, `find_zoom`,
`show_flags`, `flag_name`, `flag_color`, `flag_size`, `knife_del_threshold`,
`auto_merge`, `display_closest` and `backup_dir`. The prune described above exists
precisely to evict those keys from files that predate the move. Nothing has migrated in
the other direction.

---

## 7. Versioning and migrations

### There is no version field

A `.jser` carries no `schema_version`, no format revision, and no writer identification.
Readers detect the format by probing for keys. Every historical shape must therefore
remain readable forever, and there is no way for a file to declare that it needs a newer
reader than the one opening it.

### How migration works today

Migration is **in place, on read, unversioned, and split across two functions**. The
series object is migrated by one function and each section object by another, both of
which mutate the parsed dictionary before it is used. There is no separate migration
pass, no record that a migration ran, and no way to ask what version a file was.

Two additional migrations live in the open path itself, before the per-object functions
run.

**Top-level shape migrations (in the open path)**

| Detects | Action |
| --- | --- |
| Root has neither `sections` nor `series` | Treats every root key as a file name. A key whose extension is numeric is that-numbered section; the other key is the series. Builds the `sections` array from the numbers, filling gaps with `null`. This is the original one-key-per-file layout. |
| Root has no `log` | Inserts the bare CSV header line. |

**Series migrations**

| Detects | Action |
| --- | --- |
| Any template key missing | Adds it with its default. |
| Any `options` key missing | Adds it with its default. |
| Any `options` key not in the template | Deletes it. |
| Top-level `backup_dir` | Deletes it. Now a computer-scoped setting. |
| `ztraces` is an array | Converts to an object keyed by ztrace name, moving `name` out of each entry and defaulting a missing `color` to yellow. |
| `palette_traces` entry is an object | Converts to a 9-element positional row. |
| `palette_traces` row has 10 elements | Drops the trailing per-trace history element. |
| `palette_traces` row index 7 is not an array | Replaces the fill mode with `["none","none"]`. |
| `current_trace` present | Deletes it, wraps the flat palette array into a single group named `palette1`, and sets `palette_index` to `["palette1", 0]`. This is the single-palette to multi-palette migration. |
| `window` width is `0` | Sets it to `1`. |
| `window` height is `0` | **No-op.** The line is a comparison, not an assignment, so a zero height is not repaired. |
| `obj_attrs` missing | Adds an empty object. |
| `object_3D_modes` present | Folds each entry into `obj_attrs[name]["3D_modes"]`. |
| `last_user` present | Folds each entry into `obj_attrs[name]["last_user"]`. |
| `curation` present | Folds each entry into `obj_attrs[name]["curation"]`, without overwriting an existing value. |
| `current_brightness_contrast_profile` missing | Sets it to `"default"`. |
| `obj_attrs[name]["3D_modes"]` present | Splits it into `3D_mode` and `3D_opacity` and deletes the pair form. |
| `editors` missing | Adds an empty array. |

**Section migrations**

| Detects | Action |
| --- | --- |
| Any template key missing | Adds it with its default. |
| `brightness` and `contrast` both present | Clamps an out-of-range brightness to `0`, coerces contrast to an integer, and **replaces the whole `brightness_contrast_profiles` object** with a single `default` entry built from the two scalars. Other named profiles on that section are lost. **The scalar keys are not deleted.** |
| Trace row is an object | Converts to an 8-element positional row. |
| Trace row has 9 elements | Drops the trailing per-trace history element. |
| Trace row index 6 is not an array | Replaces the fill mode with `["none","none"]`. |
| Trace row has fewer than 2 points | Deletes the row. |
| Contour left with no rows | Deletes the contour. |
| `tforms` contains `no-alignment` | Deletes it. |
| Flag row has 5 elements | Appends `resolved = false`. Falls through to the next check, so the row ends at 7 elements. |
| Flag row has 6 elements | Inserts a freshly generated `id` at the front. |
| Contour name is not normalized | Renames it, merging into an existing contour of the normalized name if one exists. |

Several of these are unreachable in combination with each other, and none of them is
covered by a version check, so a reader cannot distinguish "this file predates the
palette split" from "this file was hand-edited and is missing `palette_index`". They are
the same code path.

### Planned direction

The modernization plan treats schema stabilization as a prerequisite workstream rather
than a byproduct. The intended shape is:

- Add a `schema_version` field at the root.
- Freeze a canonical v1, with **keyed objects in place of the positional trace and flag
  rows** documented in [section 4](#4-positional-rows).
- Put parse and migrate in exactly one owner: read any legacy `.jser`, emit canonical v1.
- Treat `options` as an explicitly versioned, prunable bag rather than one that prunes
  silently.
- Keep the Reconstruct XML import path outside the typed contract; it is a desktop-only
  importer that emits v1.

Until that lands, this page is the specification.

---

## 8. A minimal valid file

The following is a complete, openable two-section series, shown fully indented for
readability. PyReconstruct writes the same document in its own layout (structure on
lines, leaves compact; see [Line structure](#line-structure)), so saving this file back
out produces the same document with different whitespace.

Section 0 is deliberately absent, to show a hole. The image filenames are placeholders:
substitute real files in `src_dir` to see an image behind the traces.

```json
{
  "sections": [
    null,
    {
      "src": "example_0001.tif",
      "brightness_contrast_profiles": {"default": [0, 0]},
      "mag": 0.00254,
      "align_locked": true,
      "tforms": {"default": [1, 0, 0, 0, 1, 0]},
      "thickness": 0.05,
      "contours": {
        "square": [
          [
            [1.0, 2.0, 2.0, 1.0],
            [1.0, 1.0, 2.0, 2.0],
            [255, 0, 0],
            true,
            false,
            false,
            ["none", "none"],
            []
          ]
        ]
      },
      "flags": [],
      "calgrid": false
    },
    {
      "src": "example_0002.tif",
      "brightness_contrast_profiles": {"default": [0, 0]},
      "mag": 0.00254,
      "align_locked": true,
      "tforms": {"default": [1, 0, 0.05, 0, 1, -0.02]},
      "thickness": 0.05,
      "contours": {
        "square": [
          [
            [1.05, 2.05, 2.05, 1.05],
            [0.98, 0.98, 1.98, 1.98],
            [255, 0, 0],
            true,
            false,
            false,
            ["none", "none"],
            []
          ]
        ]
      },
      "flags": [
        ["Ab12Cd", "check this", 1.5, 1.5, [255, 255, 0], [["dusten", "looks thin", "26-07-26", "09:00"]], false]
      ],
      "calgrid": false
    }
  ],
  "series": {
    "current_section": 1,
    "src_dir": "",
    "window": [0.5, 0.5, 2.5, 2.0],
    "palette_traces": {
      "palette1": [
        ["circle", [-0.0948664, -0.0948664, -0.0316285, 0.0316285, 0.0948664, 0.0948664, 0.0316285, -0.0316285], [0.0316285, -0.0316285, -0.0948664, -0.0948664, -0.0316285, 0.0316285, 0.0948664, 0.0948664], [255, 128, 64], true, false, false, ["none", "none"], []],
        ["triangle", [-0.0818157, 0.0818157, 0.0], [-0.0500008, -0.0500008, 0.1], [255, 0, 128], true, false, false, ["none", "none"], []]
      ]
    },
    "palette_index": ["palette1", 0],
    "ztraces": {},
    "alignment": "default",
    "object_groups": {},
    "ztrace_groups": {},
    "obj_attrs": {},
    "ztrace_attrs": {},
    "current_brightness_contrast_profile": "default",
    "options": {
      "object_columns": [["Range", true]],
      "trace_columns": [["Tags", true]],
      "flag_columns": [["Section", true]],
      "section_columns": [["Thickness", true]],
      "ztrace_columns": [["Start", true]],
      "small_dist": 0.01,
      "med_dist": 0.1,
      "big_dist": 1,
      "autoseg": {}
    },
    "log_set": [],
    "editors": [],
    "code": "",
    "user_columns": {},
    "host_tree": {}
  },
  "log": "Date, Time, User, Obj, Sections, Event"
}
```

Notes on why this particular document round-trips unchanged:

- Key order matches the writer's emission order at every level, including inside
  `options`.
- `align_locked` is `true`, because the reader would force it to `true` anyway.
- `log_set` is present and empty, because the writer emits it in exactly that case.
- `tags` and `editors` are empty. Non-empty values are fine and are written sorted; see
  [Canonical ordering](#canonical-ordering).
- Coordinates use at most 7 decimal places, matching the writer's rounding.
- The `log` string contains no blank lines, which the log round-trip would remove. A
  trailing newline is preserved rather than stripped, so it would also be fine here; the
  example simply has none.

Trim it further if you want the smallest possible file: a single section with an empty
`contours`, empty `flags`, one palette entry, and empty collections everywhere else is
still valid. A series with **no** non-`null` section is not.

### Legacy files to test a reader against

Three `.jser` files ship with the application and are useful for exercising the migration
paths described in [section 7](#7-versioning-and-migrations):

| File | Exercises |
| --- | --- |
| `PyReconstruct/assets/checker/files/shapes1.jser` | `sections` plus `series` layout, but pre-profiles (`brightness`/`contrast` scalars), pre-flags, `current_trace` single palette, 9-element contour rows and 10-element palette rows with trailing history, and an `options` bag full of keys that no longer exist. |
| `PyReconstruct/assets/checker/files/shapes2.jser` | The same legacy shape, with non-identity section transforms rather than identities. |
| `PyReconstruct/assets/checker/files/class_series.jser` | The original **one-key-per-file** layout, with keys like `ZGBJYStudentv2.0` through `ZGBJYStudentv2.197` plus `ZGBJYStudentv2.ser`, and no `sections` or `series` key at all. |

A reader that opens all three and a writer that re-emits them in the shape described here
covers most of the format's history.

---

## 9. Reader and writer divergences

These are places where what PyReconstruct writes and what PyReconstruct would derive
from its own model differ. Each is confirmed by round-tripping a file through open and
save. They matter most for a canonical v1, because each one is a decision that has to be
made explicitly rather than inherited.

**Two of them are now fixed** and are kept here, marked, because files written by earlier
builds still exhibit them and a reader must still cope: divergence 6 (unordered sets) and
divergence 8 (provenance-dependent key order). See
[Canonical ordering](#canonical-ordering).

**1. Sections pass through opaquely; the series object does not.**
A section that is not loaded and re-saved during a session travels from input to output
with its content untouched, including keys the application has no concept of. A key
added by hand survives indefinitely. The series object, by contrast, is rebuilt from the
in-memory model on every save, so an unrecognized series-level key is silently dropped
on the first save. One file can therefore hold a mixture of section objects in different
shapes: those the current build re-derived, and those that only ever passed through.

**2. Legacy `brightness` and `contrast` keys are never removed, and they overwrite the
profiles.**
When a section carries both scalar `brightness` and `contrast`, the migration does not
merge them into `brightness_contrast_profiles`. It **replaces the entire profiles object**
with a single `default` entry built from the scalars. Any other named profile on that
section is destroyed silently. The scalars themselves are then not deleted, so because of
divergence 1 they persist in every subsequent save until that section is re-saved through
the model, and the destruction repeats on every open until then.

Two consequences worth stating plainly. A generator must never emit both forms on the
same section: the scalars win and the profiles are discarded. And a third-party reader
that prefers `brightness_contrast_profiles` over the scalars disagrees with
PyReconstruct, which is the opposite of what the key names suggest.

**3. `align_locked` is forced to `true` when a `.jser` is unpacked.**
The stored value is read and then discarded, so a `.jser` recording `false` becomes `true`
after one open-and-save cycle. The field is effectively write-only from the file's point
of view. The forcing lives in the unpack loop only, so resuming from an existing hidden
directory preserves whatever the section file holds. That is the one path on which the
stored value is honored, and it is also the path on which the `.jser` is never read.

**4. A two-point trace's `closed` flag was not corrected on disk (FIXED).**
The reader forces `closed = false` in memory for any trace with exactly two points. It
used not to write that correction back, so on-disk `closed: true` persisted on rows the
application treated as open, and two readers could legitimately disagree about such a
trace. The correction now happens on unpack, in `Section.updateJSON`, alongside the
removal of traces with fewer than two points.

The old behavior was not stable, which is why it was worth changing. A `.jser` opened and
saved without touching the section round-tripped the stale `true` byte for byte, but the
first save that took the section back through the model wrote `false`. The flag therefore
flipped at an unpredictable later save rather than never, and a byte-level diff showed a
change no edit accounts for. A generator writing `closed: true` on a two-point row should
expect it to come back as `false`.

**5. `log_set` is emitted when empty and removed when populated.**
The series writer always includes a `log_set` key. The `.jser` assembler deletes it only
when it is non-empty (its contents having been folded into the top-level `log` string).
The result is inverted from what you would expect: a saved `.jser` contains
`"log_set": []` when there is no pending log, and omits the key entirely when there was
one. Both are accepted on read, where the key is optional.

**6. Sets are serialized in unordered form (FIXED).**
Five structures are Python sets in memory and arrays on disk: trace `tags`, series
`editors`, the member lists of `object_groups` and `ztrace_groups`, and the host lists of
`host_tree`. Writing them used to produce set-iteration order, which is not the input
order and is not stable across processes, so two saves of identical data produced
different bytes and byte-level diffing in version control was defeated for any series
using tags, groups or hosts. All five are now written **sorted**; see
[Canonical ordering](#canonical-ordering). Measured: a 391 MB series re-serialized in two
separate processes differed by 9,268 bytes before, and is byte-identical now, at a cost of
0 bytes of file size.

Files written by older builds still carry the unordered form. A reader must not depend on
the order either way: the ordering is a *writer* guarantee, and the arrays remain
semantically unordered.

**7. Coordinate rounding is applied on write, not on read.**
Points are rounded to 7 decimal places when a trace is serialized from the model. A
hand-written or third-party file with more precision keeps it until that section is
re-saved, at which point precision silently drops.

**8. Section key order depends on which path the section took (FIXED).**
A section re-derived from the model emits the nine keys in the order given in
[section 3](#3-the-section-object). A section that arrived missing keys used to get them
**appended at the tail** by the migration, in template order, so a section missing
`thickness` and `tforms` came out with those two after `calgrid`: valid JSON with
identical content, but different bytes. The migration now reorders the object canonically
as its last step, and the same is done for the series object and the `options` bag. Keys
the build does not recognize are preserved, sorted, after the known ones, so the legacy
`brightness`/`contrast` pair of divergence 2 is not lost. See
[Canonical ordering](#canonical-ordering).

Older files still carry the old orders, so tooling that compares two arbitrary `.jser`
files still has to be order-insensitive; tooling that compares two files written by this
build does not.

**9. `window` height of zero is not repaired.**
The migration repairs a zero width and intends to repair a zero height, but the height
line is a comparison rather than an assignment. A `window` of `[0,0,0,0]` becomes
`[0,0,1,0]`.

**10. Legacy flags are re-identified on every open.**
A flag row lacking an `id` receives a freshly generated random one each time the file is
opened. Until the section is saved, the flag has no stable identity, so imports and
cross-references keyed on flag `id` cannot match it reliably.

**11. Contour names are normalized on read, silently.**
Whitespace and commas in a contour name are rewritten to underscores, and two names that
normalize to the same string have their traces merged. There is no warning. A generator
must pre-normalize names or accept that its object names will change.

**12. `host_tree` loses redundant edges on read.**
A host that is already a transitive superhost of the same object is pruned when the tree
is built, so a `host_tree` recorded on disk is not necessarily the `host_tree` that comes
back out. This is intentional normalization, but it means read-then-write is not an
identity for this field.

**13. Ztrace coordinates are not rounded, trace coordinates are.**
Trace points are rounded to 7 decimal places on write. Ztrace points are written at full
float precision. The two coordinate systems are the same; only the serialization
differs.

**14. The reader accepts several shapes the writer never emits.**
Beyond the ones already listed: `ztraces` as an array of named objects, `palette_traces`
as a flat array (including entries that are objects rather than rows), `host_tree` values
as bare strings, `obj_attrs` entries carrying a paired `3D_modes`, top-level
`object_3D_modes`, `last_user`, `curation` and `current_trace` maps, and a top-level
`backup_dir`. All are silently rewritten on load. A conforming reader must handle them;
a conforming writer never produces them.

---

## 10. References

Anchors verified against commit `5f16443`. If a line number no longer matches the cited
symbol, treat the corresponding claim in this page as unverified until re-checked.

### Writer and encoding

| Claim | Source |
| --- | --- |
| ASCII-only output, `\uXXXX` escaping, surrogate pairs | `PyReconstruct/modules/constants/fast_json.py:53`, `:56`, `:71` |
| Rationale for ASCII escaping (Windows locale-mode readers) | `PyReconstruct/modules/constants/fast_json.py:17-31` |
| `orjson` preferred, standard library fallback on raise | `PyReconstruct/modules/constants/fast_json.py:83-103` |
| Non-string mapping keys coerced | `PyReconstruct/modules/constants/fast_json.py:99` (`OPT_NON_STR_KEYS`) |
| Non-finite and out-of-range integer caveats | `PyReconstruct/modules/constants/fast_json.py:9-17` |
| `orjson` is a pinned dependency | `pyproject.toml:38`, `requirements.txt:9` |
| Atomic replace of the `.jser` | `PyReconstruct/modules/datatypes/series.py:88-115` |
| Structural pretty printer (opt-in); `PYRECON_JSER_PRETTY` | `PyReconstruct/modules/constants/jser_format.py` (`dumps_jser`, `pretty_default`) |
| Canonical key order and unknown-key preservation | `PyReconstruct/modules/constants/jser_format.py` (`canon_keys`, `SECTION_KEYS`, `SERIES_KEYS`) |
| Section key order and contour sort applied | `PyReconstruct/modules/datatypes/section.py` (end of `Section.updateJSON`, `Section.getDict`) |
| Series key order and options-bag order applied | `PyReconstruct/modules/datatypes/series.py` (end of `Series.updateJSON`) |
| Trace `tags` sorted | `PyReconstruct/modules/datatypes/trace.py` (`Trace.getList`) |
| `editors` sorted | `PyReconstruct/modules/datatypes/series.py` (`Series.getDict`) |
| Group names and members sorted | `PyReconstruct/modules/datatypes/obj_group_dict.py` (`ObjGroupDict.getGroupDict`) |
| `host_tree` names and hosts sorted | `PyReconstruct/modules/datatypes/host_tree.py` (`HostTree.getDict`) |
| Canonical-ordering, reproducibility and salvage tests | `tests/test_jser_canonical_format.py` |

### Open and save

| Claim | Source |
| --- | --- |
| Hidden directory path and `.ser` sentinel | `PyReconstruct/modules/datatypes/series.py:243-244`, `:334-338`, `:377-384` |
| Hidden directory short-circuits the `.jser` | `PyReconstruct/modules/datatypes/series.py:245-256` |
| Per-section files written during open | `PyReconstruct/modules/datatypes/series.py:346-366` |
| `align_locked` forced true, in the unpack loop only | `PyReconstruct/modules/datatypes/series.py:352` (the recovery path returns earlier, at `:245-256`) |
| `existing_log.csv` written during open | `PyReconstruct/modules/datatypes/series.py:368-370` |
| Empty `log_set` injected during open | `PyReconstruct/modules/datatypes/series.py:379-380` |
| Hidden directory removed on cancel or error | `PyReconstruct/modules/datatypes/series.py:360-362`, `:403-405` |
| Root structure validation | `PyReconstruct/modules/datatypes/series.py:264-276`, `:305-315` |
| Legacy one-key-per-file layout migration | `PyReconstruct/modules/datatypes/series.py:279-303` |
| Missing `log` defaulted to the header line | `PyReconstruct/modules/datatypes/series.py:318-319` |
| `sections` array length is `max(number)+1` | `PyReconstruct/modules/datatypes/series.py:431-432` |
| Sections re-read opaquely on save | `PyReconstruct/modules/datatypes/series.py:441-446` |
| `log_set` deleted only when truthy | `PyReconstruct/modules/datatypes/series.py:450` |
| Log assembled from `existing_log.csv` plus `log_set` | `PyReconstruct/modules/datatypes/series.py:451-464` |
| Top-level key emission order | `PyReconstruct/modules/datatypes/series.py:431-434` |
| Section files not `fsync`ed | `PyReconstruct/modules/datatypes/section.py:315-340` |

### Series object

| Claim | Source |
| --- | --- |
| Series read path (field by field) | `PyReconstruct/modules/datatypes/series.py:124-212` |
| Series write path and key order | `PyReconstruct/modules/datatypes/series.py:682-724` |
| Series defaults template | `PyReconstruct/modules/datatypes/series.py:726-836` |
| `log_set` optional on read | `PyReconstruct/modules/datatypes/series.py:185-188` |
| Series rebuilt from the model on save | `PyReconstruct/modules/datatypes/series.py:933-941` |
| `src_dir` joined to `src` without anchoring | `PyReconstruct/modules/datatypes/section.py:117-130` |
| `src_dir` Zarr suffix sentinel | `PyReconstruct/modules/datatypes/section.py:117-147`, `PyReconstruct/modules/backend/func/zarr_naming.py:1-30` |
| `src_dir` blanked deliberately for sharing | `PyReconstruct/assets/scripts/create_ng_zarr/utils.py:32-33` |
| `window` is field µm, extents not corners | `PyReconstruct/modules/gui/main/field_widget_7_view.py:228-258` |
| `code` used as CSV field and settings scope | `PyReconstruct/modules/datatypes/objects.py:37-41`, `PyReconstruct/modules/backend/settings_store.py:55` |
| `code` validation regex | `PyReconstruct/modules/datatypes/default_settings.py:149`, `PyReconstruct/modules/gui/main/main_window.py:3196-3213` |
| `editors` recomputed from the log when empty | `PyReconstruct/modules/datatypes/series.py:199-201`, `:3117-3128` |
| Ztrace write path, no rounding | `PyReconstruct/modules/datatypes/ztrace.py:40-49` |
| Ztrace read path, both keys required | `PyReconstruct/modules/datatypes/ztrace.py:99-106` |
| Ztrace point layout `(x, y, section)` | `PyReconstruct/modules/datatypes/ztrace.py:13`, `:120-126` |
| Ztrace color scaled from XML floats | `PyReconstruct/modules/datatypes/ztrace.py:63-65`, `:85` |
| Group dict shape and set-backed members | `PyReconstruct/modules/datatypes/obj_group_dict.py:5-26`, `:119-125` |
| Groups with no truthy member dropped on read | `PyReconstruct/modules/datatypes/obj_group_dict.py:19-21` |
| Host tree shape, hostless objects omitted | `PyReconstruct/modules/datatypes/host_tree.py:134-142` |
| Host tree accepts a bare string | `PyReconstruct/modules/datatypes/host_tree.py:28-29` |
| Redundant hosts pruned on read | `PyReconstruct/modules/datatypes/host_tree.py:45-52` |
| The eight `obj_attrs` keys and their defaults | `PyReconstruct/modules/datatypes/series.py:2677-2712` |
| Null attribute deletes the key and empties the entry | `PyReconstruct/modules/datatypes/series.py:2714-2733` |
| `3D_mode` legal values | `PyReconstruct/modules/backend/volume/generate_volumes.py:47-51`, `PyReconstruct/modules/gui/main/field_widget_3_object.py:640` |
| `3D_opacity` range | `PyReconstruct/modules/gui/main/field_widget_3_object.py:641` |
| `curation` triple shape | `PyReconstruct/modules/datatypes/series.py:2594-2597`, `PyReconstruct/modules/gui/table/object.py:373` |
| Groups are not an object attribute | `PyReconstruct/modules/datatypes/objects.py:191-193` |
| `user_columns` list at series level, scalar at object level | `PyReconstruct/modules/datatypes/series.py:3187-3205`, `:3259`, `:3278-3292` |

### The log string

| Claim | Source |
| --- | --- |
| Header line | `PyReconstruct/modules/datatypes/series.py:319`, `:901` |
| Row format and `", "` delimiter | `PyReconstruct/modules/datatypes/log.py:41-58` |
| Section range encoding, inclusive, space separated | `PyReconstruct/modules/datatypes/log.py:47-56`, `:84-94`, `:150` |
| `-` as the null marker for Obj and Sections | `PyReconstruct/modules/datatypes/log.py:42-45`, `:79-83` |
| Commas survive only in the Event column | `PyReconstruct/modules/datatypes/log.py:66-71` |
| Event whitespace stripped on read | `PyReconstruct/modules/datatypes/log.py:96` |
| Blank lines skipped | `PyReconstruct/modules/datatypes/log.py:294` |
| Date and time formats, timezone from a setting | `PyReconstruct/modules/constants/getdatetime.py:6-32` |
| `log_set` is a flat array of row strings | `PyReconstruct/modules/datatypes/log.py:276-282` |
| Session events appended only to `log_set` | `PyReconstruct/modules/datatypes/series.py:2551-2564` |
| Full history recombines both halves | `PyReconstruct/modules/datatypes/series.py:2566-2579` |

### Sections

| Claim | Source |
| --- | --- |
| Section read path | `PyReconstruct/modules/datatypes/section.py:44-90` |
| Section write path and key order | `PyReconstruct/modules/datatypes/section.py:239-271` |
| Section defaults template | `PyReconstruct/modules/datatypes/section.py:274-293` |
| Two-point trace forced open in memory | `PyReconstruct/modules/datatypes/section.py:72-76` |
| Empty contours omitted on write | `PyReconstruct/modules/datatypes/section.py:261-265` |
| `no-alignment` excluded from `tforms` on write | `PyReconstruct/modules/datatypes/section.py:253-255` |
| `no-alignment` reserved as the identity | `PyReconstruct/modules/datatypes/section.py:1180-1186` |
| Field-to-pixel conversion | `PyReconstruct/modules/calc/image.py:29-45` |
| Brightness and contrast clamped to [-100, 100] by the UI | `PyReconstruct/modules/gui/main/field_widget_4_data.py:136-160` |
| Deleting a section leaves its index unoccupied | `PyReconstruct/modules/datatypes/series.py:3331-3348` |

### Positional rows

| Claim | Source |
| --- | --- |
| Trace row layout on write, 7-decimal rounding, tags from a set | `PyReconstruct/modules/datatypes/trace.py:147-174` |
| Trace row layout on read, name-arity rule, input mutation | `PyReconstruct/modules/datatypes/trace.py:244-275` |
| Trace name normalization | `PyReconstruct/modules/datatypes/trace.py:37-51` |
| Fill mode style and condition value sets | `PyReconstruct/modules/gui/dialog/trace.py:259-284`, `PyReconstruct/modules/backend/view/trace_layer.py:308-338` |
| Fill mode values and Reconstruct mode conversion | `PyReconstruct/modules/datatypes/trace.py:610-636` |
| `negative` contributes negative area | `PyReconstruct/modules/datatypes/series_data.py:49` |
| Flag row layout on write | `PyReconstruct/modules/datatypes/flag.py:52-62` |
| Flag row layout on read, section number supplied externally | `PyReconstruct/modules/datatypes/flag.py:64-81` |
| Flag id alphabet and length | `PyReconstruct/modules/datatypes/flag.py:6-10`, `:124-127` |
| Comment row layout | `PyReconstruct/modules/datatypes/flag.py:159-166` |
| Transform 6-number layout and Qt conversion | `PyReconstruct/modules/datatypes/transform.py:7-22` |
| Transform application order | `PyReconstruct/modules/datatypes/transform.py:46-65`, and the convention restated at `:72-79` |
| Identity transform | `PyReconstruct/modules/datatypes/transform.py:172-173` |
| Default palette shapes and extents | `PyReconstruct/modules/constants/traces.py:1-112` |
| Palette group and slot indexing | `PyReconstruct/modules/gui/palette/mouse_palette.py:141-146` |

### Options and settings

| Claim | Source |
| --- | --- |
| The nine `options` keys and their defaults | `PyReconstruct/modules/datatypes/series.py:750-825` |
| Missing `options` keys back-filled | `PyReconstruct/modules/datatypes/series.py:585-587` |
| Unknown `options` keys deleted | `PyReconstruct/modules/datatypes/series.py:588-590` |
| `options` cannot gain keys at runtime | `PyReconstruct/modules/datatypes/series.py:2986-2988`, `:3002-3003` |
| Setting resolution order | `PyReconstruct/modules/datatypes/series.py:2911-2976` |
| `*_columns` must be an array | `PyReconstruct/modules/datatypes/series.py:2972-2974` |
| First read of a computer-scoped setting writes the default | `PyReconstruct/modules/datatypes/series.py:2960-2962` |
| Per-series settings scoped by series `code` | `PyReconstruct/modules/backend/settings_store.py:50-56` |
| Global and per-series computer settings | `PyReconstruct/modules/datatypes/default_settings.py:13-178` |
| Columns back-filled from defaults on use | `PyReconstruct/modules/gui/table/data_table.py:45-51` |
| Distance options are alignment nudge steps | `PyReconstruct/modules/gui/main/main_window.py:1850-1871`, `PyReconstruct/modules/gui/dialog/all_options.py:435-444` |
| `autoseg` unreferenced by live code | `PyReconstruct/modules/gui/main/main_window.py:2245`, `:2254`, `:2344`, `:2401` |

### Migrations

| Claim | Source |
| --- | --- |
| Series migration branches | `PyReconstruct/modules/datatypes/series.py:572-680` |
| Unknown `options` prune | `PyReconstruct/modules/datatypes/series.py:588-590` |
| Top-level `backup_dir` deleted | `PyReconstruct/modules/datatypes/series.py:592-594` |
| `ztraces` array to object | `PyReconstruct/modules/datatypes/series.py:596-610` |
| Palette row object to array, history drop, fill mode repair | `PyReconstruct/modules/datatypes/series.py:611-634` |
| Single palette to multi-palette | `PyReconstruct/modules/datatypes/series.py:636-640` |
| `window` width repaired, height not | `PyReconstruct/modules/datatypes/series.py:641-644` |
| `obj_attrs` consolidation | `PyReconstruct/modules/datatypes/series.py:646-665` |
| `3D_modes` split into `3D_mode` and `3D_opacity` | `PyReconstruct/modules/datatypes/series.py:672-676` |
| `editors` back-fill | `PyReconstruct/modules/datatypes/series.py:678-680` |
| Section migration branches | `PyReconstruct/modules/datatypes/section.py:150-236` |
| Brightness and contrast folded into profiles, scalars kept | `PyReconstruct/modules/datatypes/section.py:161-172` |
| Trace row object to array, history drop, fill mode repair | `PyReconstruct/modules/datatypes/section.py:175-198` |
| Short traces and empty contours removed | `PyReconstruct/modules/datatypes/section.py:199-210` |
| Legacy flag arity repair | `PyReconstruct/modules/datatypes/section.py:216-221` |
| Contour name normalization and merge | `PyReconstruct/modules/datatypes/section.py:223-236` |

### Planned v1

| Claim | Source |
| --- | --- |
| No version field, ~15 migration branches, silent options prune | `dev/REFACTOR_PLAN.md:62-68` |
| Phase 1c: `schema_version`, canonical v1, keyed rows, single migrator | `dev/REFACTOR_PLAN.md:170-180` |
| Open question on keyed objects versus positional arrays | `dev/REFACTOR_PLAN.md:289-292` |
