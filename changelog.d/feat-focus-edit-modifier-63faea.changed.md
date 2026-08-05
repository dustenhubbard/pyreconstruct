- **Focus mode's edit click is Ctrl-click, where it was Shift-click.** Editing
  which object a trace belongs to while in focus mode (splitting a trace out of the
  focused object, or incorporating another object's trace into it) was Shift-click:
  `focus_edit_p` was `event.modifiers() & Qt.ShiftModifier`. Ctrl-click did nothing
  at all in focus mode, and Ctrl's only binding anywhere in the field is Ctrl+wheel
  for zoom. The other half of a proofreading pass is **Merge traces** (`Ctrl+M`), so
  the hand had to move between two modifiers for two halves of the same job.
  Reported by Patrick Parker, who was doing exactly that, repeatedly.

  Qt swaps Ctrl and Meta on macOS, so this reads as `Cmd`-click there, which is
  also what `Ctrl+M` renders as: "the same key as merge" holds on both platforms. A
  physical Control+click on macOS is an operating-system secondary click that
  arrives as a right-button press and raises the field menu, so it cannot be this
  binding there.

  **Shift-click no longer performs this edit.** The modifier is fixed rather than
  configurable: a three-way ctrl/shift/both option was built and then cut before
  shipping, because three presets are not a remapping. A remapping that accepts
  whatever modifier combination you hold is scheduled for the next beta.
