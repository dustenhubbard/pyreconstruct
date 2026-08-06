- **A saved `.jser` now states which document schema wrote it.** `schema_version`
  leads the series object, currently the integer `1`, written by `Series.getDict`
  and tolerated-when-absent by `Series.updateJSON`. It exists for whoever reads a
  `.jser` without PyReconstruct (a converter, an archive checker, a lab script),
  and it is deliberately **a hint rather than a version gate**, because it cannot
  be one: a build older than this change opens a file carrying the key, reads
  every trace correctly, and its save deletes the key while leaving every row
  exactly as it found it. That is measured against a `git archive` of the shipped
  `v1.21.0` tag and recorded as a test expectation rather than inferred. So an
  absent `schema_version` means "no claim", never "old file", and per-row shape
  detection stays the authoritative way to read a trace row. The only change to a
  saved file is the one key: a save of the same series before and after this
  change differs by a single 19-byte insertion and by nothing else.
