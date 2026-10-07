- **Saving in the middle of a scissors cut no longer loses the trace.** Picking
  up a trace with the scissors takes it out of the section until the cut ends,
  with no undo state. `File > Save` before the cut was finished wrote the
  section without it and marked the series saved, and closing then deleted the
  working folder, so the trace was gone. A save, close, open, reload or
  propagate now backs out of an unfinished cut first, the same as Backspace,
  and the trace goes back exactly as it was.
