- **Per-trace geometry is about a third faster, and reports the same numbers.**
  `traceGeometry()` runs once per trace on every refresh — 323,534 times on the
  745 MB reference series — and is dominated by fixed per-call overhead rather
  than by the work of walking the points, so what it does before it starts
  computing matters more than the point count does. It closed the polygon by
  building two new arrays with `np.append`, copying every coordinate one slot
  along so the last vertex could be followed by a copy of the first, and it
  guarded that with a test for whether the trace was already closed. The closing
  edge is now written straight into the last slot of the cross-product array
  instead, which is the same n products in the same order, and the guard is
  gone: when a ring is already closed its wrap term is `x0*y0 - x0*y0`, exactly
  zero, so adding it unconditionally cannot change the sum. Segment lengths come
  from the same consecutive-vertex slices rather than from a separate `np.diff`
  pass over each coordinate.

  Measured on a ring of 107 points, the reference series' own mean: 11.64 µs per
  call before, 7.80 µs after. The 3.8 µs saved is flat in the point count,
  because it is allocation and dispatch rather than arithmetic. Length, centroid
  and radius are bit-for-bit unchanged across all 1,712 shapes checked,
  including every trace in the bundled series; area is bit-for-bit unchanged
  except on rings that already carry a duplicate closing vertex, where
  summation order shifts it by at most 8 units in the last place — some 15
  decimal digits below anything displayed, and landing closer to the exactly
  computed area more often than the old code did.
