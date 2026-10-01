- **A comma in your username or a z-trace name no longer breaks the series
  history.** The log split each row on commas, so a name like `Smith, John`
  made crash recovery, `Lists ▸ Series history` and importing from another
  series fail with an error. Such names are now quoted in the log. A row that
  an older version already wrote with such a name still cannot be read.
