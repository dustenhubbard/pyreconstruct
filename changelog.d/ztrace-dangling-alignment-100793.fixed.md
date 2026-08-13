- **Fixed a crash (`KeyError`) opening the z-trace list after an alignment was
  renamed or deleted.** A z-trace or object can be pinned to a named alignment,
  but renaming or deleting that alignment rewrote every section without
  updating those pins, so they kept naming an alignment that no longer existed.
  Objects shrugged that off, because their drawing path already resets a
  missing name, while the z-trace path did not: the list computes a distance
  for every row as it is built, so one pinned z-trace made the whole list
  impossible to open, and the same pin also broke smoothing that z-trace and
  adding it to a 3D scene. Renaming an alignment now carries the pins with it,
  deleting one clears them, and a pin that names something missing falls back
  to the series alignment instead of failing. A series already carrying a
  broken pin is repaired the next time its alignments are edited.
