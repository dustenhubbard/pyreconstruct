- **A series whose log names an object with a lone surrogate opens again.** A
  lone surrogate is half of a UTF-16 pair, and an old or damaged file can hold
  one in an object name. After an edit to such an object, Save wrote the name
  into the series log, and the next open failed while it wrote the log out as
  strict UTF-8. The open now writes the log so the name round-trips, and the
  readers take it back unchanged. Other bad bytes still read as U+FFFD. Series
  > Export Log History writes the name as the text `\ud800`, so the exported
  file stays valid UTF-8.
