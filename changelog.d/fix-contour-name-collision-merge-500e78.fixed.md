- **Opening a series whose object names hold a space or a comma no longer drops
  those objects' groups, comments, curation and hosts.** An object name cannot
  hold either character, because the log is a `", "`-delimited CSV whose fourth
  field is the object name, so `Section.updateJSON` rewrites any such contour
  key on load. It only ever sees one section, though, and everything the series
  knows *about* an object is keyed by name in the series file: after the rename
  those entries pointed at a name no section held any more, and the object came
  back with none of them. Measured on `shapes1.jser`, renaming one object 'my
  star' to 'my_star' lost its comment, its curation and its group membership,
  with no name collision involved. The rename is now carried into `obj_attrs`,
  `object_groups` and `host_tree` as part of the load.

- **A series with two object names that differ only in spaces or commas now
  says so before it merges them.** 'my trace' and 'my,trace' both become
  'my_trace', and the two objects become one. Every trace survives the merge (10
  of 10 on the measured case) but only one set of groups, comments, curation and
  hosts can, and nothing said this was happening. Opening such a series now
  lists the names and asks first; declining leaves the file untouched, with no
  hidden directory written. Group and host membership is unioned rather than
  dropped, and the object whose name already obeyed the rule keeps its own
  attributes. Flag names are still left exactly as typed: a flag is never
  written as a log object name, so the constraint that motivates all of this
  does not reach it.
