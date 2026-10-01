- **Undo leaves the object list's columns alone.** Every series undo and redo
  put back the column choices from when the step was made, so a column turned
  on after adding an object to a group was hidden again by undoing the group
  add. Columns now change on undo only when the step created or deleted a
  categorical column.
