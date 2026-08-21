- **Tagging one trace no longer tags every other trace edited alongside it.**
  Setting tags on a selection goes through `Section.editTraceAttributes`, whose
  replace branch assigned the caller's set object itself once per trace, so all
  of them ended up holding the same `set` rather than one each. Tags are added in
  place elsewhere (`Trace.addTag` is `self.tags.add(tag)`, and the import
  conflict flagger calls `trace.tags.add(...)`), so a later single-trace tag
  appeared on the whole group. Pasting attributes aliased the clipboard trace's
  own set as well, which put the stray tag back on the clipboard. Each trace now
  gets its own copy.
