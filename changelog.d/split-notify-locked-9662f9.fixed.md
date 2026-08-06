- **The scissors tool and the tracing-mode gate no longer pop an "unlock it?"
  dialog they immediately ignore.** Both called `notifyLocked`, which asks
  whether to unlock and, on "Yes", actually unlocks the object -- but
  `scissorsPress` and the tracing-mode gate in `mousePressEvent` always
  `return` right after, discarding that answer and refusing the gesture
  either way. The ask was theater: a user who answered "Yes" to keep working
  found the object unlocked but the gesture still refused. Both now use the
  same notify-and-stop wording already used everywhere else a locked object
  refuses an edit ("Cannot modify locked objects. Please unlock before
  modifying."), and no longer touch the object's lock state. `notifyLocked`
  itself is unchanged and keeps asking-then-unlocking for the trace list's
  context-menu actions (`TraceTableWidget.itemChanged`/`getSelected`), where
  unlocking and proceeding is the intended behavior.
