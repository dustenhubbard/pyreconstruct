- **Fixed a crash (`TypeError: can only join an iterable`) when editing an
  object's attributes with the Object List open.** An attribute edit that
  renames or removes an object deletes its data before the table removes its
  row, and Qt re-queries the departing row in between, so the table was
  computing columns for an object that no longer existed: the Trace tags
  column joined the `None` that `getTags` returned for an unknown object, and
  the Flat area, Volume, and Radius columns would have failed the same way on
  rounding `None`. `getTags` now returns an empty set, and the Object List
  answers a blank row for an object whose data is already gone.
