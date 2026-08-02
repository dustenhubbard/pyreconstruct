- **Moving the cursor from the field up to the menu bar no longer blanks the
  status readout.** The section, alignment, brightness/contrast profile, cursor
  coordinates and closest trace stay on screen while you use the menus. The
  field posted that readout with `statusbar.showMessage()`, which is the API for
  a temporary notice, and Qt clears the temporary notice on every status-tip
  event: hovering any menu action sends one, an action with no status tip sends
  an empty string, and the bar went blank until the pointer returned to the
  field. Nothing in the tree was clearing it. The readout is now a permanent
  status-bar widget, which status-tip events do not touch.

- **Guarded a latent `IndexError` in the same readout.** `self.current_trace[-1]`
  sat under a bare `if self.is_line_tracing:`. Every path that empties
  `current_trace` today clears the flag first or runs in a mouse mode that never
  sets it, so nothing reached it, but nothing enforced that either and the
  failure would have surfaced as a traceback out of a paint event.
