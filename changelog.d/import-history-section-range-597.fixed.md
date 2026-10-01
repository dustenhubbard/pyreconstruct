- **Importing traces from a section range now trims their history to that
  range.** An edit logged on sections 2 to 7 in the other series kept the range
  2 to 7 in an import of sections 5 to 9, and one on sections 0 to 1 was
  stretched to the end of the range, so later imports treated those sections
  as modified.
