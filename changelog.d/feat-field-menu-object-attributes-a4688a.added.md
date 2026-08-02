- **"Edit object attributes..." now sits in the top strip of the field's
  right-click menu**, directly under the row that reads "Edit trace
  attributes..." whenever traces are selected. It was reachable only through
  `Object >`, one hop further in than the trace equivalent, which is what a
  beta-5 tester reported. The object list has carried it as its first row all
  along; this brings the field into line. Both rows run the same
  handler, so the field copy edits the objects owning the selected traces and
  grays out when no traces are selected. `Object >` keeps its own copy, exactly
  as `Trace >` keeps "Edit trace attributes...", and no keyboard shortcut moved.
