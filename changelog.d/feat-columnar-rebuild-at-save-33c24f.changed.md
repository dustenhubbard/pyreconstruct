- **Saving a section is faster again, and a place in the application that edits
  traces without going through `Section` can no longer leave a section unable to
  save.** Every section keeps a columnar store beside its object model, and
  until now `save()` compared the two and reported a mismatch by raising an
  error at you. That comparison was most of the save cost, and what it existed
  to catch was a list of places in the application that edit traces outside
  `Section` — a list that was revised four times, twice after it had been turned
  into an automated scan meant to make further revisions impossible.

  `save()` now rebuilds the store from the object model instead of comparing
  against it. The object model owns every value and is what is written to disk,
  so a store rebuilt from it cannot be stale, whatever edited the section since
  the last save. Measured on the same 745 MB autosegmentation series (636
  sections, 323,534 traces): saving its busiest section goes from 219.6 ms back
  to 131.3 ms, and its median section from 139.6 ms to 84.4 ms. Against the
  costs before the store existed at all — 90.6 ms and 60.9 ms — the remaining
  save overhead is 1.45x and 1.39x, where it was 2.42x and 2.29x. Nothing else
  measurably changed: loading a section stays at 0.031 s and a whole-series pass
  at 24.6 s.

  **A disagreement is now written to the log rather than shown as an error.**
  If something does edit a section's traces from outside `Section`, the rebuild
  absorbs it and records what differed in the log file (Help > View log file),
  naming the section and the column. Nothing is lost — the object model is what
  was saved either way — and the section stays usable, where before the same
  situation left it raising on every save for the rest of the session and could
  abort a multi-section operation, such as smoothing an object or deleting
  duplicate traces, partway through.

  That holds even when the store cannot be rebuilt at all. One kind of
  out-of-class edit — renaming a trace in place — leaves the section in a shape
  no store can be built from, and saving then keeps the store the section
  already had and writes the reason to the log instead of raising. The section
  is still saveable and still editable afterwards.
