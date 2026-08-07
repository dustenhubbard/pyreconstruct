- **Offloading a series' log no longer copies a line of event text into both
  the exported CSV and the log kept behind, tearing it away from the row it
  belongs to.** Series ▸ Log ▸ Offload log history splits `existing_log.csv` by
  date, and it reads that file line by line rather than row by row: a row
  written by an older build can hold a literal newline and so occupy two
  physical lines, and the second of those is a continuation, which carries no
  date of its own and has to follow wherever its row went. The header was
  detected by asking whether `"Date"` occurred anywhere in the line — a
  substring test, not a header test — and that branch ran first, ahead of the
  row and continuation branches. A continuation is free-form event text, so
  nothing stopped it from containing that substring, and one reading `Changed
  the Date field on this trace` was given the treatment reserved for the header
  and written to both files at once. That duplicated its content into the file
  its row did not go to and severed it from the row it continues. The header is
  a single exact literal, emitted byte for byte by all three writers in the
  tree (`Series.openJser` and `Series.new` in `series.py`, and `xmlToJSON` in
  `backend/func/xml_json_conversions.py`), so it is now recorded once as
  `LOG_HEADER` beside `ROW_START` and matched exactly, against `line.strip()`
  because `readlines()` keeps the trailing newline. Branch order, `ROW_START`
  and every other path are unchanged.

  Only a log already damaged this way can hit it. `Log.__str__` replaces
  newlines in a row's fields, so nothing written from here on occupies more
  than one line, but the stored log is copied through byte for byte whenever a
  series is opened or saved and is never re-emitted from the parsed rows, so a
  row an older build split in two stays split on disk.
