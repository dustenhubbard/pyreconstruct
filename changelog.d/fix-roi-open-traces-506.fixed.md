- **Open traces stay open when exported as ImageJ .roi files.** Export used to
  write them as FREEHAND, which ImageJ reads as a closed shape, so a dendrite
  centerline reported an area instead of a length. Open traces now export as
  POLYLINE and one-point traces as POINT, and both come back open on import.
