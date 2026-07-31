- **`Restore previous visibility`, a new object right-click command, undoes
  `Hide other objects` without throwing away the hides you made yourself.**
  Isolating an object hid every other object across the whole series and had no
  inverse. `Show all objects` was offered as the way back, and it unhides
  everything, so any object you had deliberately hidden before isolating came back
  visible too, silently. The new command replays the visibility recorded at the
  moment you isolated, per trace, so an object you had hidden stays hidden and
  everything else returns. It sits directly under `Hide other objects` on all
  three menus that offer the isolate -- the field's `Object ▸` submenu, the object
  list's right-click menu, and the object list's own `Selection` menu -- is greyed
  out until an isolate has left something to restore, and a single Ctrl+Z undoes it
  like any other volume-wide visibility change.

  One level only: isolating again replaces what would be restored rather than
  stacking, so "previous" always means "before the last isolate". Nothing is
  written to the `.jser` for this, so the recorded state lasts as long as the
  series stays open. Locked objects are hidden and restored like any other, since
  locking guards edits and quantification rather than visibility.
