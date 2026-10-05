- **Labels saved channel first import with the right voxel size.** A label
  array shaped `[c, z, y, x]` stores four voxel size entries, such as
  `[1, 0, 0, 0]`. PyReconstruct read the channel entry as the section
  thickness and shifted the rest by one, so `Import labels` and the label
  overlay failed or drew at the wrong scale. It now uses the last three
  entries and fills any 0 from the images, as it does for three entries.
