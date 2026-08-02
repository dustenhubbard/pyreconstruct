- **A saved `.jser` no longer gains an empty `log_set` key depending on what the
  user happened to do before pressing save.** `log_set` belongs to the hidden
  working directory, not to the `.jser`: the writer flattens its rows into the
  top-level `log` text and then removes the key, and the reader overwrites
  whatever it finds with `[]` on the way back in. The removal was guarded by
  `if filedata.get("log_set")`, a truthiness test standing in for an existence
  test, so a log set that was present but empty kept the key and `"log_set": []`
  was written into the file. No log content was at risk: the rows are carried
  out by a separate read of the in-memory log set, so a populated log round
  trips into `log` and comes back through the history table either way. The
  effect was on the file, whose key set tracked session activity rather than
  series content, which meant save, reopen, save was not byte-identical for any
  series that had logged an event.
