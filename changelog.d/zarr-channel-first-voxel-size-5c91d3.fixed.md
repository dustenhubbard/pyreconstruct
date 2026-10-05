- **A label voxel size with a leading channel entry no longer breaks label
  import.** When a label array's `voxel_size` or `resolution` has four
  entries, channel first, such as `[1, 0, 0, 0]`, PyReconstruct now uses the
  last three and fills any 0 from the image grid. Before, it took the channel
  entry as the section thickness, so the import or the label overlay failed.
