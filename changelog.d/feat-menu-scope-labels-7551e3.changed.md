- **Five right-click commands that exist on both the object menu and the trace
  menu now say which one they are.** `Smooth traces`, `Edit radius...`, `Edit
  shape...`, `Unhide` and `Hide` each existed twice, once per menu, with nothing
  in either label to tell them apart. The object copies walked every section the
  object appears on and changed every trace of the contour
  (`Series.smoothObject`, `Series.editObjectRadius`, `Series.editObjectShape`,
  `Series.hideObjects`); the trace copies changed the traces you had selected, on
  the section in front of you (`Section.editTraceRadius`,
  `Section.editTraceShape`, `Trace.smooth`, `Section.hideTraces`). Picking the
  wrong one on a large series meant a series-wide change where you wanted a local
  one, and the only way to tell them apart was to run one. The object copies are
  now `Smooth object`, `Edit object radius...`, `Edit object shape...`, `Unhide
  object` and `Hide object`; the trace copies are `Smooth selected traces`, `Edit
  selected radius...`, `Edit selected shape...`, `Unhide selected traces` and
  `Hide selected traces`. The commands themselves are unchanged, so anything you
  were doing still works. Only the labels moved.

- **`Show all objects` is now `Unhide all objects`, so one verb means one
  thing.** It was the only command in the object menu's visibility group that
  said "show" for what every other row calls unhiding, and it is the exact
  complement of `Hide all objects`. `Show all traces (ignore hidden)` under
  `View` keeps its verb on purpose: that one is a display mode that overrides the
  hidden flag without clearing it, so it genuinely is not an unhide. The object
  list's own `Selection` menu offers the same command and now reads the same way.

- **The object menu's `Geometry ▸` submenu is gone and its four commands are
  top-level.** `Smooth object` is promoted because smoothing is frequent and did
  not deserve a hop, and `Split into separate objects` now sits directly under
  `Duplicate object`, being a structural command rather than a trace edit. That
  left the submenu holding two items, which is not enough to earn one, so it was
  dissolved rather than renamed: with the scope in the labels there is nothing
  left for a container to describe. `Comment...` becomes `Leave object
  comment...` and closes the object-settings section, whose order is now `Object
  attributes ▸`, `Smooth object`, `Duplicate object`, `Split into separate
  objects`, `Edit object radius...`, `Edit object shape...`, `Group ▸`, `Set
  curation ▸`, `Custom categories ▸`, `Leave object comment...`. One builder
  backs both surfaces, so the object list's menu and the field menu's `Object ▸`
  submenu change together.

- **The object menu's visibility group now reads as three pairs, one per scope
  of action.** `Hide object` / `Unhide object` act on the selected object across
  the whole series; `Hide other objects` / `Restore previous visibility` isolate
  and un-isolate; `Hide all objects` / `Unhide all objects` act on everything. It
  is still one uninterrupted section in its established order, with one row added
  and none removed or moved. `Unhide other objects` is deliberately absent: after
  isolating, unhiding everything that is not selected leaves the whole series
  visible, which `Unhide all objects` already does.
