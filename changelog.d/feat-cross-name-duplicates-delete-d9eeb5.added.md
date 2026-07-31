- **`Series ▸ Clean up ▸ Find duplicates named differently...` can now remove the
  duplicate, one pair at a time, and it never picks which name goes.** The scan
  found pairs and stopped there, because which of two names is correct is a
  judgment about the data and the geometry cannot settle it. It still cannot, so
  the tool does not try: both name cells of a row are tickable and mutually
  exclusive, ticking one says "keep this name", and "Delete unselected" then
  deletes the trace under the other name in every row that was answered. A row
  left unticked is left completely alone, and the confirmation says how many rows
  that was. No rule fills a gap in, not "keep the name on more sections" and not
  "keep the larger trace", because a rule there would be the tool answering the
  one question it cannot answer.

  Removing a trace runs through the same path the pixel-dust and empty-trace
  clean-ups use, so a batch of answered rows is one undoable operation (Ctrl+Z
  restores every deleted trace) and each trace is re-found by its stored
  color-and-points signature after its section reloads, rather than by identity.
  Each deletion is logged against the object that lost a trace, on its section,
  naming the object kept.

  Locked objects keep their traces. The scan skips locked objects unless "check
  locked traces" is on, and a pair surfaced that way still cannot be resolved by
  deleting from the locked side: the refusal is in
  `Series.deleteDifferentlyNamedDuplicates` itself rather than in the scan, so
  the delete path cannot be reached for a locked object by any route. Deleting a
  trace changes quantitative data, which is what locking an object refuses;
  nothing about selection or visibility changed. The unlocked side of such a pair
  can still be deleted, since keeping a trace does not modify it.

  The choice is item check state rather than a radio button placed in the cell,
  for two reasons that are behavioral: check state travels with its row through a
  column sort, so re-sorting the table cannot shuffle answers onto the wrong
  pairs, and a widget filling a name cell would take that cell's click away from
  row selection, which is what "Go to trace" and "Go to other trace" run off. The
  generic "Delete selected" and "Delete all" of the other clean-up lists
  deliberately do not appear here: row selection is how a pair is inspected, not
  how it is answered, and "all" of a list of pairs would mean deleting both
  sides. The same-name operation, the columns, the sort order and the
  `include_locked` behavior are all unchanged.
