- **A saved `.jser` can now carry each trace's persisted id, by writing trace
  rows as keyed objects instead of positional arrays.** It is **off by default**
  and `PYRECON_JSER_KEYED_ROWS=1` turns it on for a process, the same spelling
  and the same exactly-`1` rule as `PYRECON_JSER_PRETTY`. With the switch off
  the writer is byte-identical to the one before this change: measured on three
  series, including a 50 MB 125,218-row hand-traced one, as the same sha256
  against a build of the previous commit. With it on, every row in the file is
  an object keyed `id, x, y, color, closed, negative, hidden, fill_mode, tags`
  — `id` first, matching where a flag row has always kept its id — with every
  value unchanged from the positional row it replaces. `docs/JSER_FORMAT.md`
  documents the layout normatively.

  **A build older than this one cannot open a file written with the switch on,
  and that is a deliberate trade rather than an oversight.** Every shipped build
  back to `v1.19.0` already accepts a keyed trace row, but reads the fill mode
  under the key `mode`, while the model and the format document have always
  called that field `fill_mode`. This writer emits `fill_mode`, so `v1.21.0`
  raises `KeyError: 'mode'` on the first keyed row and refuses the file — run
  against a `git archive` of the tag, not predicted. The alternative was
  measured too: spelled `mode`, the same document opens in `v1.21.0` with every
  trace correct and then **silently deletes every id in the whole file on its
  first save**. A schema that says what it means, bought with a loud failure
  instead of a quiet one. Readers from this build forward accept both
  spellings, permanently.

  Two more things worth knowing before turning it on. The file gets bigger by a
  flat 83 bytes per trace row, which is +4.1% on a densely traced series and
  +20.5% on a sparsely hand-traced one, because the cost is per row rather than
  per point. And an id is **derived from its trace's content**, not minted, so
  two opens of one file agree without a save — but the first save of a file
  written by an older, non-canonical writer changes its ids once, as the rows
  are canonicalized, and they are stable from then on.
