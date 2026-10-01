- **A new action clears redo.** Redo used to survive a new action and replay
  the old step over it, so undoing a group change and then making another one
  let redo bring the first back and drop the second. Redo is now cleared by any
  new action, which also stops it from failing after a z-trace is deleted or
  renamed.
