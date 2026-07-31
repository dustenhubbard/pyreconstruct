- **Duplicate detection finds duplicate open traces.** Reported by Lyndsey Kirk,
  whose lab's cfa traces are about 98% open lines: a pair measuring 0.2581 and
  0.25894 in length, 0.33% apart and an obvious duplicate by eye, was not flagged
  at a 95% overlap threshold, and the pairs the scan did report were nearly all
  closed traces. Both `Series ▸ Clean up ▸ Remove duplicate traces...` and
  `Series ▸ Clean up ▸ Find duplicates named differently...` were affected, as was
  the duplicate check that runs when one series is imported into another.

  `Trace.getOverlapRatio` measured overlap by rasterizing both traces with
  `skimage.draw.polygon` and dividing the intersection by the union. That
  function implicitly closes the point list, so for an open trace the region
  being filled is the sliver between the polyline and the straight chord from its
  last point back to its first. The shape of that sliver is governed by the
  trace's own wiggle rather than by where the curve lies, and two independent
  tracings of one structure have independent wiggle, so their slivers disagree
  even when the curves sit on top of each other. A near-straight profile is the
  worst case, because the chord runs close to the line and the sliver is almost
  entirely noise: two such profiles 0.08% apart in length measured an overlap of
  0.19. Lowering the threshold was not an available fix, since 0.19 would need a
  threshold near 15%, which would call every trace on the section a duplicate of
  its neighbors.

  Open traces are now compared curve to curve instead. Both polylines are
  resampled at even spacing along their arc length, each sample is measured
  against the other trace's line segments rather than against its points, and the
  result is the smaller of the two directions: the fraction of one trace lying
  within tolerance of the other, and the fraction of the other lying within
  tolerance of the one. Taking the smaller keeps it symmetric and conservative,
  so a short trace running along part of a long one scores about the ratio of
  their lengths and is not called a duplicate of it. Because segments are
  measured and not points, how densely each trace was clicked no longer changes
  the answer, and a trace redrawn from end to start reads as the duplicate it is.
  The tolerance is 2% of the shorter trace's length, bounded at both ends by an
  absolute distance in image pixels: never less than one pixel, never more than
  five. The fraction has the right shape, since a longer structure is clicked
  more coarsely and two tracings of it disagree by more, but on its own it goes
  wrong at both ends. On the reported series the shortest genuine duplicate pair
  is a 29 pixel line whose two tracings differ by 0.72 of a pixel, and 2% of 29
  pixels is 0.58, so the pair was missed; the longest traces run to 6,846 pixels,
  where 2% is 137 pixels and two unrelated structures ten pixels apart would have
  been called the same one. Five pixels is the distance PyReconstruct already
  treats as the same point when it compares two traces point by point.

  The result is still a ratio from 0 to 1, so the **Overlap threshold** each of
  these operations asks for keeps its scale and its direction, and a setting that
  worked before still works. What it means for an open pair has changed, though,
  and the tooltips now say so: it is no longer an area shared over an area
  covered, and a threshold of 1.0 no longer implies the two traces have identical
  points. For an open pair, 1.0 means the two lines stay within a few image
  pixels of each other from end to end.

  The curve comparison is confined to the operations that ask whether two traces
  are the same trace. Importing one series into another also asks a different
  question in two places, whether two traces overlap at all, and uses the answer
  to work out which of a colleague's traces are independent work rather than
  another version of something already there. That question keeps the measure it
  has always used, so those decisions come out exactly as they did before.

  Closed traces keep the area comparison unchanged, which is the right measure
  for them, and a pair with one open and one closed trace was never compared at
  all. The cross-name scan needed a second change to benefit: it skips pairs
  whose overlap cannot reach the threshold, using a ceiling derived from the two
  areas, and for an open trace that area is the same meaningless sliver. The
  reported pair ceilinged at 0.63 and was discarded before any overlap was
  measured, so open pairs are now exempt from that test. They cost less to
  measure than closed ones rather than more, because comparing curves is several
  times cheaper than rasterizing two polygons: on a 440-trace section of open
  profiles carrying 40 duplicate pairs, the scan found 6 of them in 0.064 s
  before and all 40 in 0.023 s after.
