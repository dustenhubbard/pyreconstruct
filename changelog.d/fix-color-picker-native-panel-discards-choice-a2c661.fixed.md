- **A colour picked for a trace is no longer thrown away on macOS.** Clicking a
  colour swatch called `QColorDialog.getColor()`, which on macOS does not open a
  Qt dialog: it opens the shared system "Colors" panel, the live-apply picker
  every other Mac app uses. Picking a colour there changed nothing on screen,
  and closing the panel -- the gesture that picker invites -- returned an
  invalid colour, so the choice was discarded silently and the swatch stayed
  blank. (Qt bolts an OK button onto that panel and it does work, but the panel
  opens wherever the system last left it, nowhere near the dialog that asked for
  it.) The swatch now opens Qt's own colour dialog: modal, parented to the
  button, with OK inside its own window. This is the picker Windows and Linux
  already got. Nothing stored was ever wrong -- the colour simply never reached
  the trace -- and it affected any colour, not only the green in the report.
