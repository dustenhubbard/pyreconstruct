- **How you closed the colour picker is now recorded in the log, so "I set a
  colour and nothing happened" reports can be diagnosed instead of guessed
  at.** A Windows user reported that a trace's colour "remains blank even
  though I set a color green" in the Set Attributes dialog, and the report was
  undiagnosable, structurally: every way of closing the picker without OK --
  the Cancel button, the title-bar close, Esc -- returns the same invalid
  colour, and `ColorButton` then (correctly, for Cancel) applies nothing,
  silently. "Cancelled on purpose", "picked a colour that the dismissal
  discarded", and "OK itself misbehaved" all looked identical, in the app and
  in the log.

  `ColorButton.selectColor` now writes one line per picker interaction to the
  log Help ▸ View log file already opens: OK logs the colour it applied, the
  Cancel button is named as Cancel (read from the dialog's own button, the one
  place it differs from a window close), and a dismissal that was not Cancel
  logs the colour the picker was showing at that moment together with the fact
  that it was not applied. That showing-colour is the discriminator: `dismissed
  without OK or Cancel ... showing rgb(0,255,0)` is the reported symptom,
  witnessed. Behaviour is unchanged -- the picker looks the same and a
  dismissal still applies nothing; the dialog is only constructed explicitly
  (mirroring `QColorDialog.getColor()`'s own sequence) because the static hides
  the instance the diagnosis needs.
