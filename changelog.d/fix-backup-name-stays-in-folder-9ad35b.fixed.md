- **A backup file always lands in the backup folder.** The file name is built
  from the series code, the series name, the user name, the date and time
  formats, the prefix, suffix and delimiter, and the comment. A `/`, `\` or
  `:` in any of them put the file in another folder, and a series code such as
  `/tmp/outside` saved the backup as `/tmp/outside.jser`. Those characters now
  become `_` in the file name. Names without them are unchanged.
