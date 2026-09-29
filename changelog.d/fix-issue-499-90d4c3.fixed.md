- **A new series from a Zarr made by another tool gets the right pixel size.**
  Neuroglancer stores the voxel size in nanometers, and the import used that
  number as micrometers per pixel, so a 4 nm Zarr came in 1000 times too large.
  It now converts from nanometers unless the Zarr says micrometers, and it reads
  `voxel_size` as well as `resolution`.
