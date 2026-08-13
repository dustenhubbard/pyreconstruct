- **Fixed a crash (`AttributeError`) using undo or redo after an earlier
  undo.** When a series-wide undo and a section-only undo are both available
  and are not part of the same operation, the app compares the two to work out
  which one Ctrl+Z should take. That comparison reads a timestamp off each
  saved state, and section states were only being stamped on one of the three
  paths that put them on an undo stack, so undoing and then pressing Ctrl+Z
  again could hit a state with no timestamp at all and fail instead of undoing
  anything. Every state is now stamped when it is created and re-stamped
  whenever it moves onto a stack.
