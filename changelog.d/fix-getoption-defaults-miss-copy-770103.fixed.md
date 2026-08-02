- **Fixed: reading a setting that has never been saved no longer lets one
  series overwrite the shipped default for every other series.** When an option
  was absent from a series' stored settings, `getOption` returned the built-in
  default list itself rather than a copy of it. Five defaults are lists
  (`pointer`, `grid`, `flag_color`, `autoseg_color_palette`,
  `recently_opened_series`), and the recent-series list is edited in place by
  the code that maintains it, so one series could rewrite the default that a
  later series read back. The fix returns a copy for list and dict defaults.
