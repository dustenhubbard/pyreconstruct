- **The flag and trace lists no longer hold flags and traces alive after a
  filter hides them.** Both lists map a table row to its Python object through
  a list kept beside the table (`FlagTableWidget.displayed_flags` and
  `TraceTableWidget.rows`), and rebuilding the table replaced only the entries
  for the rows it created. Any rebuild that shrank the list left the entries
  past the last row in place: any of the filters, turning `Display resolved
  flags` back off, or a section change. The lists therefore only ever grew, and
  kept objects for rows that no longer existed, including flags and traces
  since deleted. Nothing read those entries, so there was no visible defect.
  Both lists are now discarded and rebuilt with the table.
