- **Fixed a crash loading any section whose contour dict contained an empty
  string key.** `Trace.fromList` discriminates 8-field rows (no embedded name)
  from 9-field rows (name first) with `if not name or len(l) == 9`. An empty
  string is falsy, so passing `name=""` sent an 8-field row down the 9-field
  path: the x-list was consumed as the name, leaving 7 fields for 8 variables,
  and Python raised `ValueError: not enough values to unpack`. Changed the
  guard to `name is None`, which is the correct sentinel for "caller did not
  supply a name".
