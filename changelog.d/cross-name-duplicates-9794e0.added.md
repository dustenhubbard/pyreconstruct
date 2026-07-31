- **`Series ▸ Clean up ▸ Find duplicates named differently...` reports one shape
  that was traced twice under two object names.** "Remove duplicate traces..."
  never finds those, and not because it checks a name: `Trace.overlaps` is purely
  geometric and never reads one. The restriction comes from the loop, which draws
  both traces out of a single `section.contours[cname]`, and contours are keyed by
  trace name, so two differently-named traces were never handed to the comparison
  at all. That is exactly what two people tracing the same structure produce. The
  new scan compares every trace on a section against every other one, decides
  overlap by the same two tests `Trace.overlaps` always used, and lists the pairs
  it finds with both names, the measured overlap and each trace's area, with
  "Go to trace" and "Go to other trace" framing the two sides of a pair in the
  field.

  It reports and does not delete. Two traces under one name are unambiguous, so
  "Remove duplicate traces..." collapses them; when the names differ, which name
  is right does not follow from the geometry, and the answer can be to rename or
  to merge rather than to delete. Locked objects are skipped by default, matching
  the pixel-dust and empty-trace scans, and nothing in the series is modified
  either way. The same-name operation is unchanged.

  Comparing across names means comparing every trace with every other, which is
  quadratic where the old loop was not, and `Trace.getOverlapRatio` rasterizes two
  polygons per comparison. Measured on the densest section of a real
  161,767-trace autoseg series (1,291 traces, 715 objects), the plain quadratic
  comparison takes 8.6 s for that one section and 2.5 s for a section of median
  density, which is about 13 minutes for the series. The shipped scan reaches the
  same answer in 0.033 s and 0.013 s by never measuring a ratio it can rule out
  first: an x-sorted sweep stops the inner loop once no remaining trace can reach
  the current one, and a ceiling derived from the two bounding boxes and the two
  areas bounds the ratio a pair could possibly reach. That takes the densest
  section from 616,059 rasterized comparisons to 2, and the cost grows with the
  number of traces rather than with its square: 20,000 traces on one section
  scan in 0.75 s.
