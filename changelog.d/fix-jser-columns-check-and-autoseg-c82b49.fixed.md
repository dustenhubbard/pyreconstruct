- **A malformed column setting in a series file now says which setting is wrong
  and how to fix it, instead of crashing inside the list it feeds.** `getOption`
  carried a "must be a list" check for the five `*_columns` options, but it sat
  after the settings-store branch and all five of those options are read from
  the series-internal `options` dict, which returns earlier. Nothing reached the
  check, so a bad value round-tripped through the .jser and failed later in the
  table widgets as `dictionary update sequence element #0 has length 1; 2 is
  required`, `'dict' object has no attribute 'append'` or `'NoneType' object is
  not iterable`, none of which name the option or the file. The check now runs
  on both paths and reports the option, the expected shape, the offending value
  and the fix. It also checks the shape rather than only the type: a flat
  `["Thickness", "Locked"]` is a list and still crashed.

- **The error window keeps the line breaks in a message that has them.** The
  global exception hook renders the message as rich text and passed it through
  without converting newlines, so anything written on several lines arrived as
  one run-on paragraph. The handled save-error path already converted; this
  brings the hook into line with it.
