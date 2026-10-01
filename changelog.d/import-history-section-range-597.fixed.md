- **Importing traces from a section range now trims their history to that
  range.** An edit logged on sections 2 to 7 in the other series kept the range
  2 to 7 in an import of sections 5 to 9. An edit on sections 0 to 1 became 0
  to 4 in an import of sections 0 to 4. Later imports then treated those
  sections as modified.
