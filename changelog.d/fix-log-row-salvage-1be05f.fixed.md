- **A history entry an older version split across lines now loads, even when a
  name in it holds a comma with no space after it, like `a,b`.** Older versions
  wrote a line break in a name or event as it was. The history now reads each
  entry from its date and time to the next one, so the whole entry is read back
  as written. Lists > Series history and an object's history no longer stop on
  an entry that cannot be read: they show the rest, and say how many lines they
  left out and how many entries they rebuilt. The series file keeps every line.
