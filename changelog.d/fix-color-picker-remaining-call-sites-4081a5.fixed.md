- **Cancelling the flag list's colour filter no longer filters the list to
  black.** "Filter > Color filter > Set filter..." guarded its picker with
  `if not c: return`, which never fired: `QColor` defines no `__bool__`, so a
  dismissed picker's invalid colour is still truthy. Cancel therefore fell
  through and set the filter to `(0, 0, 0)`, hiding every flag that was not
  pure black -- a flag list that emptied itself on Cancel, with a filter the
  user never chose and had to find "Remove filter" to clear. This one was not
  macOS-specific; it happened everywhere, Cancel included.

- **The autoseg import-colours editor no longer discards the colour you pick on
  macOS.** Series > Options > View > "Autoseg import colors" called
  `QColorDialog.getColor()` for Add and Edit, the same static behind the trace
  swatch bug: on macOS it opens the shared system "Colors" panel, and closing
  that panel returns an invalid colour that was then silently dropped. Both
  call sites now open Qt's own dialog, as the trace swatch does.

  Both pickers also open on the colour being edited rather than on white. A
  `QColorDialog` seeded before the native path is switched off loses its seed
  on macOS, so pressing OK without changing anything would have written white
  over the colour that was already there.
