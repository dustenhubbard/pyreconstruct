- **Zarrs saved with a voxel size of 0 import labels again.** Older exports
  could store 0 for the pixel size, so `Import labels` and the label overlay
  failed on them. PyReconstruct now rebuilds the size from the series the way
  the current export writes it, so these zarrs work without exporting again.
