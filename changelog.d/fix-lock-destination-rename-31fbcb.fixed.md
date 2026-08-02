- **Renaming a trace or an object *into* a locked object is now refused.** Every
  lock check in the field read the objects the selection is in right now, and
  none of them looked at the name being assigned, so a rename had one object
  guarded and the other not. Selecting an unlocked object's trace and giving it
  a locked object's name passed each check on the way through, since the source
  was unlocked and that was all anyone asked, and it landed a new trace inside
  the locked object. Four commands could do it: the trace attributes dialog,
  "Paste attributes" (copy is deliberately allowed on a locked object, so its
  trace can sit on the clipboard with nothing refusing it upstream), the object
  list's "Edit attributes...", and focus mode's split when an object already
  named `<obj>_split` happens to be locked. The object list's was the widest: it
  walks every section the selected object appears on, so it merged a whole
  object into the locked one rather than one trace on one section.

  All four now check the destination and stop with the same "Cannot modify
  locked objects" message the field already shows for a refused edit, rather
  than doing nothing quietly. The check reads the destination name and nothing
  else, which keeps it inside what locking means: it guards quantitative data
  (traces added, deleted or modified) and never selection, color or visibility.
  Adding traces to an object is a change to that object's data, so it belongs
  under the lock; renaming between two unlocked objects is untouched and still
  works, locked bystanders elsewhere in the series included. "Merge attributes
  only" needed no change and got none, because it renames the selection onto one
  of its own traces, so its destination was always an object the existing check
  had already cleared.
