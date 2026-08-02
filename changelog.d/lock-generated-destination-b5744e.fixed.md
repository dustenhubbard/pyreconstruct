- **"Duplicate object" and "Split into separate objects" no longer write traces
  into a locked object.** Both invent their destination rather than asking for
  one: copying gives `<obj>_copy`, splitting gives `<obj>_1` through `<obj>_N`.
  Neither looked for a free name, so a generated name that already belonged to
  an object went straight into it, and when that object was locked the operation
  added traces to the very thing the lock was protecting. Copying an object,
  locking the copy, then copying the original again was enough to do it, and any
  series that already numbers objects `<obj>_1`, `<obj>_2` could hit the same
  thing on a split. The field's own lock check did run, but it reads the objects
  you selected, which are the sources and are unlocked. The destination is
  chosen after that check has passed.

  Both now stop with the same "Cannot modify locked objects" message the field
  already shows for a refused edit, and stop before anything is written, so a
  multi-object copy or a partly numbered split cannot be left half done. The
  check reads whether the destination is locked and nothing else, which keeps it
  inside what locking means: it guards quantitative data (traces added, deleted
  or modified) and never selection, color or visibility. How the names are
  generated is unchanged, so copying twice into an unlocked `<obj>_copy` still
  merges the way it always has, and a locked object elsewhere in the series
  refuses nothing. `Series.copyObjects` and `Series.splitObject` refuse on their
  own as well as through the field, so scripts driving the series directly are
  covered too.
