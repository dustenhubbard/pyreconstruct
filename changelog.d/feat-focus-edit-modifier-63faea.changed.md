- **Focus mode's edit click is Ctrl-click, and the modifier is now
  configurable.** Editing which object a trace belongs to while in focus mode
  (splitting a trace out of the focused object, or incorporating another
  object's trace into it) was Shift-click, with no setting behind it:
  `focus_edit_p` was `event.modifiers() & Qt.ShiftModifier`. Ctrl-click did
  nothing at all in focus mode, and Ctrl's only binding anywhere in the field is
  Ctrl+wheel for zoom. The other half of a proofreading pass is **Merge traces**
  (`Ctrl+M`), so the hand had to move between two modifiers for two halves of the
  same job, which is what the proofreader who reported this was doing repeatedly.

  The binding is now the `focus_edit_modifier` setting, on the **Mouse Tools**
  tab of `Series > Options`: Ctrl-click (the new default), Shift-click, or either
  one. Shift stays available because this click renames traces between objects,
  so anyone mid-series with the old habit should not discover the change by
  having a keystroke silently stop working.

  Qt swaps Ctrl and Meta on macOS, so the default reads as `Cmd`-click there,
  which is also what `Ctrl+M` renders as: "the same key as merge" holds on both
  platforms. A physical Control+click on macOS is an operating-system secondary
  click and arrives as a right-button press that raises the field menu, so it
  cannot be this binding there and is not offered as one.
