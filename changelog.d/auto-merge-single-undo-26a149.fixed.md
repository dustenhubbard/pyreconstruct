- **One undo now fully reverts an auto-merged trace.** Drawing a trace and the
  merge it triggered were recorded as separate undo states, so one Ctrl+Z
  landed on the in-between state: the original trace plus the un-merged new
  one, a composite that was never on screen. The draw and its auto-merge are
  now a single undo step, so one undo restores the section exactly as it was
  before the trace was drawn and one redo brings the merged result back.
