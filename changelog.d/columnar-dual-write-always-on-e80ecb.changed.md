- **Every section now builds and maintains a columnar store beside its object
  model, in every session, and this costs measurable time and memory on a large
  series.** The store landed behind an environment variable whose whole premise
  was that a real launch could not reach it, which made the next step
  impossible: gated off, a section's store was `None` forever in a real session,
  so nothing outside a test had anything to read. The gate is removed rather
  than defaulted, and the repository is scanned for its name so that a
  half-removed gate — a store on one machine and not another — cannot survive.

  **Nothing reads the store yet and no byte of any `.jser` changes.** The object
  model still owns every value, `save()` still serializes it, and the store is a
  shadow copy that is written and checked against it.

  **The cost you are most likely to feel is at save.** Measured on a 745 MB
  autosegmentation series (636 sections, 323,534 traces), saving its busiest
  section goes from 90.6 ms to 131.3 ms and its median section from 60.9 ms to
  84.4 ms. A section is saved on every section change, a mouse-wheel scroll
  included, so a section change on a series that size goes from about 100 ms to
  about 160 ms. The added time is the rebuild of the store that runs once per
  save, covered by its own entry below; the first version of this change
  compared the store against the object model there instead, at 219.6 ms and
  139.6 ms, and those are the numbers for a build between the two.

  The other measured costs, on the same series: loading one section goes from
  0.0111 s to 0.0319 s (2.9x) and a whole-series pass from 11.6 s to 25.1 s
  (2.2x); opening the series cold goes from 66.6 s to 81.8 s (1.2x); changing
  magnification goes from 8.0 ms to 138.6 ms. Editing a single trace goes from
  0.0027 ms to 0.106 ms — 39x in relative terms, and still a tenth of a
  millisecond, so it is not a number you can perceive. Holding the whole series
  resident costs 488 MB more, about 11% on top of the object model it shadows;
  while you are editing, the field holds two sections at a time, so the
  interactive cost is about 1.5 MB rather than 488 MB, and the whole-series
  figure applies to passes that hold everything at once such as 3D generation
  and quantification.

  These come from a synthetic autosegmentation corpus whose busiest section
  carries 1,291 traces. A hand-traced series is smaller, so read them as close
  to a worst case rather than as typical.

  The check that compares the two representations moved from "the whole section,
  after every mutation" — which measured 81 to 127 ms per edit and would have
  made dragging a selection unusable — to a targeted per-row comparison at each
  mutation, plus the whole-section work at each save that its own entry below
  describes. Twelve places in the application edited traces or contours without
  going through `Section` and now
  rebuild the store afterwards: undo, redo, deleting an object, importing a
  segmentation, hiding objects, hiding all traces, restoring previous
  visibility, smoothing an object, deleting duplicate traces, smoothing the
  selected traces, and clicking an import-conflict flag — plus the tag merge
  the scalpel performs when cutting several traces at once. Clicking an
  import-conflict flag hid every other contour on the section in place, and
  before it was fixed it left the section unable to save for the rest of the
  session; smoothing an object failed partway through a multi-section pass and
  left the remaining sections un-smoothed.

  The whole-section work runs *after* a section is written rather than before,
  so a disagreement between the store and its object model is still reported and
  never costs you a save: the object model is what is serialized, and a stale
  shadow copy of it is not a reason to withhold your work from disk.
