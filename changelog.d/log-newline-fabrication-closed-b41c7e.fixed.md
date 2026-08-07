- **A multi-line name pasted into a rename box no longer invents an editor
  nobody was.** A series' log is one row per line, but its fields are free text
  from dialogs — ztrace and alignment names, brightness/contrast profile names,
  object group names, user column names and values, the section image source,
  and the username itself — and `QLineEdit` keeps a pasted newline. One such
  paste split a row across two physical lines, and the reader, which joins a
  short line to whatever follows until it has six comma fields, then folded the
  *next* user's whole row into the fragment. When that concatenation happened to
  parse, one invented row stood in for two real ones: the row after it vanished,
  its own timestamp was reported as an editor of the series, and nothing was
  recorded or printed. Series ▸ About and the history table showed the result.

  Closed from both ends, because the two ends protect different data:

  - `Log.__str__` now replaces `\n`, `\r\n` and `\r` with `_`. It is the only
    place a log row becomes text, so no row written from here on can occupy
    more than one line. A row with no newline in any field is byte-identical to
    before.
  - `LogSet.fromList` now recognises a row by the `YY-MM-DD, HH:MM, ` stamp
    every row begins with, rather than by counting commas. A line carrying that
    stamp is a row and is no longer eaten as a continuation; a line lacking it
    is not a row and is no longer read as one. This is what protects logs that
    are *already* corrupted — the stored log is copied through byte for byte
    whenever a series is opened or saved and is never rewritten from the parsed
    rows, so a file damaged by an earlier version stays damaged.

  The trade, stated plainly: a fragment that can never be completed now reports
  a parse failure where it used to produce a row. That is the visible failure
  rather than the silent one, and it was measured before being chosen — across
  872 `.jser` files on hand (675 with a log, 1,987,237 rows) the new reader
  changes no file and reports no new failure, while on generated logs built from
  the old writer's own output it invents an editor in 0 of 200,000 cases against
  roughly 44,000 before.

  What remains is genuinely undecidable and now fails safely — but "safely" is
  worth spelling out, because it does not mean nothing gets through. A pasted
  name whose own text contains a line shaped like a whole row is byte-identical
  to two real rows. The reader keeps both rows and truncates the pasted name,
  rather than reading somebody's timestamp as a person's name. The embedded line
  is still read as a row, though, so whatever it names in the user column — text
  whoever pasted it chose — is still counted as an editor and still appears in
  Series ▸ About. What the fix prevents is the other failure, a timestamp
  reported as a person; it does not prevent a plausible name typed into a dialog
  from being admitted.

- **Series ▸ Export Log History no longer crashes on a log damaged this way.**
  It reads the log line by line and asked each line for its date, so the second
  line of a row split in two raised an uncaught error and the export failed
  outright — reproduced on a real file from 2023. Such a line is now recognised
  as the continuation it is and is archived alongside the row it belongs to,
  instead of being separated from it or ending the export.
