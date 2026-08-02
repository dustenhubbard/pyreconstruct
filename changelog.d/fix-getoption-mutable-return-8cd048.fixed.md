- **Fixed: mutating the list returned by `getOption` for a column option no
  longer corrupts the stored value.** `getOption` returned `self.options[key]`
  by reference for the six options stored in the series-internal `options` dict
  (`object_columns`, `trace_columns`, `flag_columns`, `section_columns`,
  `ztrace_columns`, `autoseg`). A caller that appended to or removed from the
  returned list silently changed what the next call saw, without going through
  `setOption`. The fix returns a shallow copy for list- and dict-typed values.
