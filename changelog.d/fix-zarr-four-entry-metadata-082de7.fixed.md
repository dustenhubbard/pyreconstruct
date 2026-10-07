- **Zarr labels import in place when the metadata has a channel entry.** When
  an `offset`, `voxel_size` or `resolution` has four entries, channel first,
  PyReconstruct now uses the last three for the images as well as the labels,
  and reads `units` for those three axes. Before, the channel entry of an
  image voxel size was read as the section thickness, and a four entry label
  offset was measured against the wrong axes, so labels were imported and
  overlaid in the wrong place.
