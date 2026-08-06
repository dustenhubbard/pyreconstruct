- **An id-stability harness now drives a real series through the application's
  own mutation entry points and records what moves a trace's id.** Test-only:
  no application code changes and no `.jser` byte changes. Twenty tests drive
  add, delete, attribute edit, rename, duplicate-object, copy-traces-to-sections,
  rebuild, save, whole-series save and reopen, reload, undo and redo, and assert
  the id outcome of each against the carry table `columnar_store.py` documents.

  Two of the table's rows do not hold, and both are pinned as the code actually
  behaves rather than as the table describes. `copyRow`, the operation the table
  says implements an attribute edit and a rename, has no caller outside the
  tests, so both operations re-identify the trace they edit, in memory, with no
  save involved. An undo re-identifies every trace on the section, and a redo
  every trace in the contours it restores, because both replace the `Trace`
  objects the rebuild correlates ids through.

  Two further movements are pinned as intended for this phase, so that they turn
  red when persisted ids arrive: an edit followed by a save and a reload moves
  the edited trace's id and no neighbour's, and an id issued during a session
  does not survive a save and a reload. The carry table travels in the module as
  a manifest with a test on it, so every row is either exercised or listed as
  unexercised with its reason; the two rows reserved to the maintainer
  (split-object `_{n}` traces, palette traces) are reported as unexercised
  rather than answered by accident.
