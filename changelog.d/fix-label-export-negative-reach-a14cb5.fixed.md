- **Zarr label export clears an island's edge pixels under a negative trace a
  fraction of a pixel away.** Label export rounds each trace to whole pixels,
  so a negative trace that missed an island in a hole by less than a pixel
  could still round onto the island's edge. The island filled back in after
  the hole and kept those pixels, where the same traces with no hole lost
  them. A negative trace within one pixel's diagonal of an island now clears
  them again at every export scale, as one within a voxel's diagonal does in
  3D.
