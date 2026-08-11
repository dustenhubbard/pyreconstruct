- **`Ctrl+A`, `Ctrl+D` and `Ctrl+Shift+I` now act on whichever data list has
  focus instead of always acting on the field.** Pressing `Ctrl+A` (`Cmd+A` on macOS)
  with the object list focused selected every trace on the section and did
  nothing to the list, because `selectall_act` was wired straight to the field
  and, as a `QAction` on the main window, claimed the sequence for the whole
  window before the focused list's view could handle it. The three keys are now
  dispatched by focus, the rule `Ctrl+C` and backspace already followed: over a
  data list they select, clear and invert that list's rows, and over the field
  they select, deselect and invert the section's traces as before. Selecting
  rows in a list does not change the field's trace selection, matching what
  clicking rows has always done.
