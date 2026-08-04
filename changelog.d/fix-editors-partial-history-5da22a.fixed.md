- **One unreadable row in a series' log no longer costs every editor their
  entry.** The editors a series lists in Series ▸ About are rebuilt from the log
  whenever the series file carries none, by folding each row's username into a
  set. That read was wrapped in a bare `except:` that printed "ERROR: corrupt
  history. Skipping editors update..." and returned nothing at all, so a single
  row that would not parse — a legacy object name holding `", "`, the pair the
  log is delimited by, is enough — discarded every *other* user's well-formed
  row along with it, and the empty result was then stored as the answer. The
  parse was already row-at-a-time, so the bad row is now dropped on its own and
  the rest are kept, with a count of what was dropped printed in place of the
  blanket error.

  Reading the log for anything else — the history table, the import comparison,
  restoring curation from the log — is unchanged, and still reports a corrupt
  file rather than showing a history it knows is incomplete.
