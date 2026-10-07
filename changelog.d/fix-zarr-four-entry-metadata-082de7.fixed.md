- **Zarr labels import in place when the metadata has a channel entry.** A
  four-entry `offset`, `voxel_size` or `resolution` is now read channel first
  on the images as well as the labels, so the channel entry no longer shifts
  the labels or passes for the section thickness.
