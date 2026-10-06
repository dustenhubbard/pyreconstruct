- **Merging a long trace with a small separate one no longer deletes the small
  one.** The merge drew every selected trace on one grid sized to the whole
  selection, so a long trace made the cells wide enough that a small trace a
  few pixels across rounded onto a single point and dropped out. Both
  originals were deleted and only the long one came back. Traces that do not
  touch are now merged separately, each on a grid sized to itself, and a merge
  that would still lose a trace leaves every trace as it was and says so.
