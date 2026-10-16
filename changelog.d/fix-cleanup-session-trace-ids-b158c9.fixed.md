- **A clean-up list now acts on the trace you picked even when identical
  traces changed after the scan.** When two or more traces of one object on one
  section were the same in every field, a delete or paste made after the scan
  made Delete, Repair and Combine skip the row and ask you to scan again. Each
  row now remembers its trace for the rest of the session, through saves, and
  finds that exact trace. A row whose trace was undone back or replaced is
  still skipped and reported as before. Nothing in the file changes.
