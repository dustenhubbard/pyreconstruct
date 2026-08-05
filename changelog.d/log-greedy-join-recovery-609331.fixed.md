- **A row in a series' log that stops partway through no longer takes the
  well-formed row after it down as well.** The log is newline-delimited but its
  fields may contain newlines, so a name holding one splits its row across
  physical lines. `LogSet.fromList` reassembles those by joining a short line to
  the lines after it until it has six comma fields, and that join is greedy: it
  takes whatever follows, including a complete row belonging to somebody else.
  When the result then failed to parse, every line the join had consumed was
  discarded as a single skipped entry — so a well-formed row was lost for no
  reason of its own, and the count of skipped rows the reader prints described
  logical rows rather than the file lines actually gone. The failure now records
  only the line that was short and resumes reading at the line after it, so the
  swallowed rows get a fresh read and the count is one entry per lost line.

  Nothing about how a log is parsed changed: the recovery lives in the handler
  for a join that has already failed, so a log that reads today reads
  identically. Series ▸ About's editors list and the history table are where the
  recovered rows show up.
