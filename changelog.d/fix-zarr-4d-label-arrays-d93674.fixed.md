- **A `(1, z, y, x)` Zarr label array imports and shows in the label overlay
  like a 3D one.** Its channel axis was read as the section, so label import
  failed on the first section and skipped the rest, and the overlay drew
  nothing. PyReconstruct now reads the one channel. A label array with more
  than one channel is refused with a message, and 4D images with three
  channels still draw as images.
