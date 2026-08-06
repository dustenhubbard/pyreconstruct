- **Confirming "Edit alignment..." without touching it no longer clears the
  selected objects' alignment.** The dialog's combo was built with no initial
  selection, so it opened on the blank entry that `QuickDialog` prepends for a
  field that is not required. That blank came back as a valid empty response
  rather than as "nothing chosen", and the empty response was written to every
  selected object as `None`, which `Series.setAttr` stores by deleting the key.
  The override being deleted is not a rare one: an object gets an alignment
  recorded when it is traced, and losing it silently changes which transform
  positions the object's traces, resizes them, and builds its 3D mesh. The combo
  now opens on the selection's current alignment, computed the way the 3D
  options dialog next to it computes its own: the shared value when the
  selection agrees, blank when it does not. Picking the blank entry deliberately
  still clears the override, which is what it has always meant.
