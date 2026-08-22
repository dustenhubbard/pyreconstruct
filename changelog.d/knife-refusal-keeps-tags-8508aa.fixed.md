- **A refused knife cut no longer puts deleted tags back on the trace.**
  `cutTrace` combined every selected trace's tags onto the first one, in place,
  before it had decided whether the cut could happen at all. When the cut was
  then refused (a self-intersecting outline, a knife click with no drag, a
  threshold that discards every piece), the message said the object was left
  unchanged, but the first trace had already absorbed the others' tags, so a
  tag just deleted from it reappeared. The tags are now combined on a copy that
  only the pieces of a completed cut are built from.
